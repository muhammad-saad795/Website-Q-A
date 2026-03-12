from src.url_verifier import URLVerifier


def _make_verifier():
    return URLVerifier()


class TestURLVerifier:
    def test_healthy_200(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", final_url="https://example.com",
                      http_status=200, status="success")
        assert r.is_ok is True
        assert r.status_label == "Healthy"
        assert r.redirected is False

    def test_redirect_detected(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", final_url="https://example.com/home",
                      http_status=301, status="success")
        assert r.redirected is True
        assert "Redirected to" in r.issues[0]

    def test_client_error_4xx(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com/missing", http_status=404, status="failed")
        assert r.is_ok is False
        assert r.status_label == "Client Error"

    def test_server_error_5xx(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com/crash", http_status=500, status="failed")
        assert r.is_ok is False
        assert r.status_label == "Server Error"

    def test_loader_failure(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", status="failed")
        assert r.is_ok is False
        assert r.status_label == "Failed"

    def test_runtime_error(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", status="success", error="Timeout")
        assert r.is_ok is False
        assert r.status_label == "Execution Error"

    def test_console_errors_counted(self):
        v = _make_verifier()
        console = [
            {"type": "error", "text": "ReferenceError"},
            {"type": "warning", "text": "Deprecation"},
            {"type": "error", "text": "TypeError"},
        ]
        r = v.verify(url="https://example.com", http_status=200,
                      status="success", console_errors=console)
        assert r.console_summary["errors"] == 2
        assert r.console_summary["warnings"] == 1

    def test_slow_navigation_flagged(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", http_status=200,
                      status="success", navigation_time=6.0)
        slow_issues = [i for i in r.issues if "Slow navigation" in i]
        assert len(slow_issues) == 1

    def test_slow_load_flagged(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", http_status=200,
                      status="success", load_time=20.0)
        slow_issues = [i for i in r.issues if "Slow full load" in i]
        assert len(slow_issues) == 1

    def test_performance_recorded(self):
        v = _make_verifier()
        r = v.verify(url="https://example.com", http_status=200,
                      status="success", navigation_time=1.23, load_time=4.56)
        assert r.performance["navigation_seconds"] == 1.23
        assert r.performance["total_load_seconds"] == 4.56
