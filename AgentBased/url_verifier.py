import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

# ──────────────────────────────────────────────
# Config / Thresholds
# ──────────────────────────────────────────────
SLOW_NAV_THRESHOLD = 5.0  # seconds
SLOW_LOAD_THRESHOLD = 15.0  # seconds

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger(__name__)

@dataclass
class VerificationReport:
    url: str
    is_ok: bool = True
    redirected: bool = False
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    status_label: str = "Healthy"
    issues: List[str] = field(default_factory=list)
    performance: Dict[str, Any] = field(default_factory=dict)
    console_summary: Dict[str, Any] = field(default_factory=dict)
    console_logs: List[Dict[str, str]] = field(default_factory=list)

class URLVerifier:
    """ analyses page load data and generates rule-based quality reports. """

    def verify(
        self, 
        url: str, 
        final_url: Optional[str] = None, 
        http_status: Optional[int] = None, 
        status: str = "pending", 
        error: Optional[str] = None, 
        console_errors: List[Dict[str, Any]] = None,
        navigation_time: Optional[float] = None,
        load_time: Optional[float] = None
    ) -> VerificationReport:
        """ 
        Verifies page load health based on explicitly provided arguments.
        """
        console_errors = console_errors or []
        report = VerificationReport(url=url, final_url=final_url, http_status=http_status)

        # 1. Check Redirection
        if final_url and url.rstrip('/') != final_url.rstrip('/'):
            report.redirected = True
            report.issues.append(f"Redirected to: {final_url}")

        # 2. Check HTTP Status
        if http_status:
            if not (200 <= http_status < 400):
                report.is_ok = False
                report.status_label = "Unhealthy"
                report.issues.append(f"HTTP Status: {http_status}")
            elif http_status >= 400:
                report.is_ok = False
                report.status_label = "Error Status"
                report.issues.append(f"HTTP Error: {http_status}")
        elif status == "failed":
            report.is_ok = False
            report.status_label = "Failed"
            report.issues.append(f"Loader failed to fetch page")

        # 3. Check Execution Errors
        if error:
            report.is_ok = False
            report.status_label = "Execution Error"
            report.issues.append(f"Runtime Error: {error}")

        # 4. Analyze Console Errors
        report.console_logs = [{"type": ce.get("type"), "text": ce.get("text")} for ce in console_errors]
        err_count = sum(1 for ce in report.console_logs if ce["type"] == "error")
        warn_count = sum(1 for ce in report.console_logs if ce["type"] == "warning")
        
        report.console_summary = {"errors": err_count, "warnings": warn_count}
        if err_count > 0:
            report.issues.append(f"Found {err_count} console errors")
        if warn_count > 0:
            report.issues.append(f"Found {warn_count} console warnings")

        # 5. Performance Checks
        perf = {}
        if navigation_time is not None:
            perf["navigation_seconds"] = round(navigation_time, 2)
            if navigation_time > SLOW_NAV_THRESHOLD:
                report.issues.append(f"Slow navigation: {navigation_time:.2f}s")
        
        if load_time is not None:
            perf["total_load_seconds"] = round(load_time, 2)
            if load_time > SLOW_LOAD_THRESHOLD:
                report.issues.append(f"Slow full load: {load_time:.2f}s")
        
        report.performance = perf

        return report

    def print_report(self, report: VerificationReport):
        """ Prints a formatted summary for a report. """
        print(f"\n{'='*70}")
        print(f"VERIFICATION REPORT: {report.url}")
        print(f"{'='*70}")
        
        status_text = "PASSED" if report.is_ok else "FAILED"
        print(f"Overall Result: {status_text} | Label: {report.status_label}")
        print(f"Final URL:      {report.final_url}")
        print(f"HTTP Status:    {report.http_status}")
        
        if report.performance:
            perf_vals = " | ".join([f"{k}: {v}s" for k, v in report.performance.items()])
            print(f"Performance:    {perf_vals}")
            
        print(f"Console Logs:   Errors: {report.console_summary.get('errors')}, Warnings: {report.console_summary.get('warnings')}")
        
        if report.console_logs:
            print("\nDetailed Console Logs:")
            for log in report.console_logs:
                label = "[ERROR]" if log["type"] == "error" else "[WARN]"
                print(f"  {label} {log['text']}")

        if report.issues:
            print("\nIssues/Notes:")
            for issue in report.issues:
                print(f"  [!] {issue}")
        else:
            print("\nResult: No critical issues detected.")
            
        print(f"{'='*70}\n")

if __name__ == "__main__":
    # Internal test with dummy arguments
    verifier = URLVerifier()
    test_report = verifier.verify(
        url="https://example.com",
        final_url="https://example.com/welcome",
        http_status=200,
        status="success",
        navigation_time=2.5,
        load_time=6.1,
        console_errors=[{"type": "error", "text": "Failed to load resource"}]
    )
    verifier.print_report(test_report)
