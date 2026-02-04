#!/usr/bin/env python3
"""
Layout Validator - Production-Grade Layout Analysis Tool
Validates both mobile and desktop layouts from result.json
Reports detailed, actionable issues with element context
"""

import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    """Issue severity levels"""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class LayoutIssue:
    """Represents a layout validation issue with full context"""
    severity: Severity
    category: str
    message: str
    element: Dict[str, Any]
    viewport_type: str  # 'desktop' or 'mobile'
    details: Dict[str, Any] = None
    recommendation: str = ""


class LayoutValidator:
    """
    Production-grade layout validator
    
    Detects genuine layout issues while ignoring intentional design patterns:
    - Off-canvas sidebars/menus
    - Below-the-fold content
    - Hidden/collapsed elements
    - Decorative elements
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize validator with optional configuration
        
        Args:
            config: Configuration dict with thresholds and tolerances
        """
        self.config = config or {}
        
        # Default thresholds
        self.overflow_tolerance = self.config.get('overflow_tolerance_px', 5)
        self.min_interactive_size = self.config.get('min_interactive_size_px', 44)
        
        # Allowable padding for small icon buttons
        self.min_icon_size = self.config.get('min_icon_size_px', 20)
        
        self.issues: List[LayoutIssue] = []
        
        # Track known design patterns to avoid false positives
        self.off_canvas_selectors = ['sidebar', 'drawer', 'menu', 'nav']
    
    def validate_snapshot(self, snapshot_data: Dict[str, Any], viewport_type: str) -> List[LayoutIssue]:
        """
        Validate a single layout snapshot
        
        Args:
            snapshot_data: Layout snapshot data with viewport and elements
            viewport_type: 'desktop' or 'mobile'
            
        Returns:
            List of detected layout issues
        """
        viewport = snapshot_data.get('viewport', {})
        elements = snapshot_data.get('elements', [])
        
        viewport_width = viewport.get('width', 0)
        viewport_height = viewport.get('height', 0)
        
        print(f"\n{'='*80}")
        print(f"🔍 Analyzing {viewport_type.upper()} Layout ({viewport_width}x{viewport_height})")
        print(f"{'='*80}")
        print(f"📊 Processing {len(elements)} elements...")
        
        # Run all validation checks
        self._check_horizontal_overflow(elements, viewport_width, viewport_type)
        self._check_broken_interactive_elements(elements, viewport_type)
        self._check_text_rendering_issues(elements, viewport_type)
        self._check_fixed_position_issues(elements, viewport_width, viewport_height, viewport_type)
        
        # Only check touch targets on mobile
        if viewport_type == 'mobile':
            self._check_touch_targets(elements, viewport_type)
        
        return self.issues
    
    def _is_off_canvas_element(self, elem: Dict) -> bool:
        """
        Detect if element is an intentional off-canvas design (sidebar/drawer)
        These are NOT layout bugs - they're supposed to be hidden until triggered
        """
        elem_id = (elem.get('id') or '').lower()
        computed = elem.get('computed', {})
        position = computed.get('position', 'static')
        
        # Fixed/absolute positioned sidebars/menus are intentional
        if position in ['fixed', 'absolute']:
            for selector in self.off_canvas_selectors:
                if selector in elem_id:
                    return True
                for cls in elem.get('classes', []):
                    if selector in cls.lower():
                        return True
        
        return False
    
    def _check_horizontal_overflow(self, elements: List[Dict], vp_width: int, viewport_type: str):
        """
        Check for elements overflowing viewport horizontally
        ONLY flags actual layout bugs, not intentional off-canvas elements
        """
        for elem in elements:
            # Skip off-canvas elements (sidebars, drawers, etc.)
            if self._is_off_canvas_element(elem):
                continue
            
            flags = elem.get('flags', {})
            
            # Only check visible elements
            if not flags.get('isVisible', False):
                continue
            
            rect = elem.get('rect', {})
            x = rect.get('x', 0)
            width = rect.get('width', 0)
            computed = elem.get('computed', {})
            # Skip fixed/sticky elements - they are handled by _check_fixed_position_issues
            if computed.get('position') in ['fixed', 'sticky']:
                continue
                
            # Check if element overflows right edge
            right_edge = x + width
            if right_edge > vp_width + self.overflow_tolerance:
                # CHECK PARENT: If parent fits in viewport, assume child is clipped/scrolled
                # This handles carousels, sliders, and hidden overflow containers
                parent = elem.get('parent', {})
                parent_rect = parent.get('rect', {})
                parent_tag = parent.get('tag', '').lower()
                
                if parent_rect and parent_tag not in ['body', 'html', 'main']:
                    parent_right = parent_rect.get('x', 0) + parent_rect.get('width', 0)
                    # If parent ends within viewport (with tolerance), ignore child overflow
                    if parent_right <= vp_width + self.overflow_tolerance:
                        # ENSURE parent actually handles overflow
                        # Don't just assume; check if overflow is hidden/scroll/auto
                        p_computed = parent.get('computed', {})
                        p_overflow = p_computed.get('overflow', 'visible')
                        p_overflow_x = p_computed.get('overflowX', 'visible')
                        
                        # If parent explicitly clips or scrolls content, this overflow is intentional
                        if any(v in ['hidden', 'scroll', 'auto', 'clip'] for v in [p_overflow, p_overflow_x]):
                            continue

                overflow_amount = right_edge - vp_width
                
                # More serious if it's interactive
                is_interactive = flags.get('isInteractive', False)
                severity = Severity.CRITICAL if is_interactive else Severity.WARNING
                
                self.issues.append(LayoutIssue(
                    severity=severity,
                    category="HORIZONTAL_OVERFLOW",
                    message=f"Element overflows viewport by {overflow_amount:.0f}px on the right",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'element_right_edge': right_edge,
                        'viewport_width': vp_width,
                        'overflow_px': overflow_amount,
                        'is_interactive': is_interactive
                    },
                    recommendation=f"Add responsive width or max-width: 100%. Element extends to {right_edge:.0f}px but viewport is only {vp_width}px wide."
                ))
    
    def _check_broken_interactive_elements(self, elements: List[Dict], viewport_type: str):
        """
        Check for interactive elements that are completely inaccessible
        These are ACTUAL bugs - buttons/links users can't reach
        """
        for elem in elements:
            flags = elem.get('flags', {})
            
            # Only check interactive elements
            if not flags.get('isInteractive', False):
                continue
            
            # Skip off-canvas elements
            if self._is_off_canvas_element(elem):
                continue
            
            # Element is visible but not in viewport
            is_visible = flags.get('isVisible', False)
            is_in_viewport = flags.get('isInViewport', False)
            
            rect = elem.get('rect', {})
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # Check for zero-size interactive elements
            if is_visible and (width <= 0 or height <= 0):
                self.issues.append(LayoutIssue(
                    severity=Severity.CRITICAL,
                    category="BROKEN_INTERACTIVE",
                    message=f"Interactive element has zero dimensions ({width:.0f}x{height:.0f}px) - completely broken",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={'width': width, 'height': height},
                    recommendation="Element has collapsed. Check CSS for missing width/height or hidden content."
                ))
    
    def _check_text_rendering_issues(self, elements: List[Dict], viewport_type: str):
        """
        Check for text that may be clipped or not rendering properly
        """
        text_tags = ['p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'button', 'label', 'li', 'td', 'th']
        
        for elem in elements:
            tag = elem.get('tag', '').lower()
            if tag not in text_tags:
                continue
            
            text = (elem.get('text') or '').strip()
            if not text or len(text) < 3:
                continue
            
            flags = elem.get('flags', {})
            if not flags.get('isVisible', False):
                continue
            
            computed = elem.get('computed', {})
            rect = elem.get('rect', {})
            
            # Check for text with overflow:hidden and suspiciously small container
            overflow = computed.get('overflow', 'visible')
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # Text longer than 20 chars in a tiny container with overflow:hidden
            if overflow in ['hidden', 'clip'] and len(text) > 20:
                if width < 30 or height < 15:
                    self.issues.append(LayoutIssue(
                        severity=Severity.WARNING,
                        category="TEXT_CLIPPING",
                        message=f"Text may be clipped: {len(text)} characters in {width:.0f}x{height:.0f}px container with overflow:{overflow}",
                        element=self._simplify_element(elem),
                        viewport_type=viewport_type,
                        details={
                            'text_length': len(text),
                            'text_preview': text[:40] + '...' if len(text) > 40 else text,
                            'container_size': {'width': width, 'height': height},
                            'overflow': overflow
                        },
                        recommendation="Container too small for text content. Use text-overflow: ellipsis or increase container size."
                    ))
    
    def _check_fixed_position_issues(self, elements: List[Dict], vp_width: int, vp_height: int, viewport_type: str):
        """
        Check for fixed/sticky positioned elements that are broken
        (Not including intentional off-canvas elements)
        """
        for elem in elements:
            computed = elem.get('computed', {})
            position = computed.get('position', 'static')
            
            if position not in ['fixed', 'sticky']:
                continue
            
            # Skip off-canvas elements
            if self._is_off_canvas_element(elem):
                continue
            
            flags = elem.get('flags', {})
            if not flags.get('isVisible', False):
                continue
            
            rect = elem.get('rect', {})
            x = rect.get('x', 0)
            y = rect.get('y', 0)
            width = rect.get('width', 0)
            
            # Fixed element overflowing viewport is usually a bug
            right_edge = x + width
            if right_edge > vp_width + self.overflow_tolerance:
                overflow = right_edge - vp_width
                self.issues.append(LayoutIssue(
                    severity=Severity.CRITICAL,
                    category="FIXED_OVERFLOW",
                    message=f"Fixed/sticky element overflows viewport by {overflow:.0f}px",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'position': position,
                        'overflow_px': overflow,
                        'element_rect': rect
                    },
                    recommendation=f"Fixed position element should fit viewport. Add max-width or reduce width."
                ))
    
    def _check_touch_targets(self, elements: List[Dict], viewport_type: str):
        """
        Check for touch targets that are too small (mobile only)
        Uses more lenient rules for icon buttons vs. text buttons
        """
        interactive_tags = ['button', 'a', 'input', 'select', 'textarea']
        
        for elem in elements:
            tag = elem.get('tag', '').lower()
            flags = elem.get('flags', {})
            
            if tag not in interactive_tags and not flags.get('isClickable', False):
                continue
            
            # Skip if not visible or not in viewport
            if not flags.get('isVisible', False):
                continue
            
            rect = elem.get('rect', {})
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            text = (elem.get('text') or '').strip()
            
            # Determine if this is likely an icon button (no text, small size)
            is_icon_button = len(text) == 0 and width < 40 and height < 40
            
            # Different thresholds for icons vs. text buttons
            min_size = self.min_icon_size if is_icon_button else self.min_interactive_size
            
            if width < min_size and height < min_size:
                # Only report if it's way too small
                if width < 20 or height < 20:
                    severity = Severity.CRITICAL
                    msg_type = "icon button" if is_icon_button else "interactive element"
                else:
                    severity = Severity.INFO
                    msg_type = "icon button" if is_icon_button else "button"
                
                self.issues.append(LayoutIssue(
                    severity=severity,
                    category="SMALL_TOUCH_TARGET",
                    message=f"Touch target too small: {msg_type} is {width:.0f}x{height:.0f}px (recommended: 44x44px minimum)",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'width': width,
                        'height': height,
                        'is_icon': is_icon_button,
                        'recommended_size': '44x44px'
                    },
                    recommendation="Add padding or increase button size to meet WCAG touch target guidelines (44x44px)."
                ))
    
    def _simplify_element(self, elem: Dict) -> Dict:
        """Create a simplified element representation for reporting"""
        tag = elem.get('tag', '')
        elem_id = elem.get('id', '')
        classes = elem.get('classes', [])[:3]  # Limit classes
        text = (elem.get('text', '') or '')[:60]  # Truncate text
        rect = elem.get('rect', {})
        
        # Create readable descriptor
        descriptor = f"<{tag}>"
        if elem_id:
            descriptor += f"#{elem_id}"
        if classes:
            descriptor += f".{'.'.join(classes)}"
        
        return {
            'descriptor': descriptor,
            'tag': tag,
            'id': elem_id,
            'classes': classes,
            'text': text,
            'rect': rect
        }
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate a comprehensive validation report"""
        # Group issues by severity and category
        by_severity = {
            'CRITICAL': [],
            'WARNING': [],
            'INFO': []
        }
        
        by_category = {}
        by_viewport = {'desktop': [], 'mobile': []}
        
        for issue in self.issues:
            by_severity[issue.severity.value].append(issue)
            
            if issue.category not in by_category:
                by_category[issue.category] = []
            by_category[issue.category].append(issue)
            
            by_viewport[issue.viewport_type].append(issue)
        
        # Calculate summary statistics
        total_issues = len(self.issues)
        critical_count = len(by_severity['CRITICAL'])
        warning_count = len(by_severity['WARNING'])
        info_count = len(by_severity['INFO'])
        
        # Determine overall status
        if critical_count > 0:
            status = "FAIL"
        elif warning_count > 3:
            status = "WARNING"
        else:
            status = "PASS"
        
        return {
            'status': status,
            'summary': {
                'total_issues': total_issues,
                'critical': critical_count,
                'warnings': warning_count,
                'info': info_count,
                'by_viewport': {
                    'desktop': len(by_viewport['desktop']),
                    'mobile': len(by_viewport['mobile'])
                },
                'by_category': {
                    k: len(v) for k, v in by_category.items()
                }
            },
            'issues': [self._issue_to_dict(i) for i in self.issues]
        }
    
    def _issue_to_dict(self, issue: LayoutIssue) -> Dict:
        """Convert LayoutIssue to dictionary"""
        return {
            'severity': issue.severity.value,
            'category': issue.category,
            'message': issue.message,
            'viewport': issue.viewport_type,
            'element': issue.element,
            'details': issue.details,
            'recommendation': issue.recommendation
        }
    
    def print_detailed_report(self):
        """Print a detailed, actionable report of all issues"""
        report = self.generate_report()
        
        print("\n" + "="*80)
        print("📋 LAYOUT VALIDATION REPORT")
        print("="*80)
        
        # Overall status
        status_emoji = "✅" if report['status'] == "PASS" else "⚠️" if report['status'] == "WARNING" else "❌"
        print(f"\n{status_emoji} Overall Status: {report['status']}")
        
        # Summary
        print(f"\n📊 Summary:")
        print(f"   Total Issues: {report['summary']['total_issues']}")
        print(f"   🔴 Critical: {report['summary']['critical']}")
        print(f"   ⚠️  Warnings: {report['summary']['warnings']}")
        print(f"   ℹ️  Info: {report['summary']['info']}")
        
        # By viewport
        print(f"\n🖥️  Issues by Viewport:")
        print(f"   Desktop: {report['summary']['by_viewport']['desktop']}")
        print(f"   Mobile: {report['summary']['by_viewport']['mobile']}")
        
        # By category
        if report['summary']['by_category']:
            print(f"\n📑 Issues by Category:")
            for category, count in sorted(report['summary']['by_category'].items(), key=lambda x: -x[1]):
                print(f"   {category}: {count}")
        
        # Group issues for detail sections
        by_severity_detail = {'CRITICAL': [], 'WARNING': [], 'INFO': []}
        for issue in report['issues']:
            by_severity_detail[issue['severity']].append(issue)
        
        # Critical issues detail
        if report['summary']['critical'] > 0:
            print(f"\n{'='*80}")
            print("🔴 CRITICAL ISSUES (Must Fix)")
            print("="*80)
            for i, issue in enumerate(by_severity_detail['CRITICAL'], 1):
                self._print_issue_detail(i, issue)
        
        # Warning issues detail
        if report['summary']['warnings'] > 0 and report['summary']['warnings'] <= 10:
            print(f"\n{'='*80}")
            print("⚠️  WARNINGS")
            print("="*80)
            for i, issue in enumerate(by_severity_detail['WARNING'], 1):
                self._print_issue_detail(i, issue)
        elif report['summary']['warnings'] > 10:
            print(f"\n⚠️  {report['summary']['warnings']} warnings found (showing first 5)")
            for i, issue in enumerate(by_severity_detail['WARNING'][:5], 1):
                self._print_issue_detail(i, issue)
        
        # Info issues summary
        if report['summary']['info'] > 0:
            print(f"\nℹ️  {report['summary']['info']} informational items (minor improvements)")
        
        print("\n" + "="*80)
        
        # Final verdict
        if report['summary']['total_issues'] == 0:
            print("✅ Layout looks good! No issues found.")
        elif report['summary']['critical'] == 0:
            print("💡 Layout is functional but has some minor issues to improve.")
        else:
            print(f"❌ Found {report['summary']['critical']} critical layout bugs that need fixing.")
        
        print("="*80 + "\n")
    
    def _print_issue_detail(self, index: int, issue: Dict):
        """Print detailed information about a single issue"""
        print(f"\n{index}. [{issue['viewport'].upper()}] {issue['category']}")
        print(f"   {issue['message']}")
        
        elem = issue['element']
        print(f"   Element: {elem['descriptor']}")
        
        if elem.get('text'):
            print(f"   Text: \"{elem['text']}\"")
        
        rect = elem['rect']
        print(f"   Position: x={rect['x']:.0f}, y={rect['y']:.0f}")
        print(f"   Size: {rect['width']:.0f} x {rect['height']:.0f} px")
        
        if issue.get('recommendation'):
            print(f"   💡 Fix: {issue['recommendation']}")


def validate_layout_file(json_file_path: str, output_file: str = None) -> Dict:
    """
    Validate layout from a JSON file containing snapshots
    
    Args:
        json_file_path: Path to result.json file
        output_file: Optional path to save validation report
        
    Returns:
        Validation report dictionary
    """
    # Load the JSON file
    print(f"📂 Loading {json_file_path}...")
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Create validator
    validator = LayoutValidator()
    
    # Validate desktop snapshot
    if 'layout_snapshot_desktop' in data:
        validator.validate_snapshot(data['layout_snapshot_desktop'], 'desktop')
    
    # Validate mobile snapshot
    if 'layout_snapshot_mobile' in data:
        validator.validate_snapshot(data['layout_snapshot_mobile'], 'mobile')
    
    # Generate report
    report = validator.generate_report()
    
    # Print detailed summary
    validator.print_detailed_report()
    
    # Save report if output file specified
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"💾 Detailed report saved to: {output_file}")
    
    return report


if __name__ == "__main__":
    import sys
    
    # Get file path from command line or use default
    json_file = sys.argv[1] if len(sys.argv) > 1 else 'result.json'
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'validation_report.json'
    
    validate_layout_file(json_file, output_file)
