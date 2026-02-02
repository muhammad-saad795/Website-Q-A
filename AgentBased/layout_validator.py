#!/usr/bin/env python3
"""
Layout Validator - Analyzes layout snapshots for common issues
Validates both mobile and desktop layouts from result.json
"""

import json
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    """Issue severity levels"""
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class LayoutIssue:
    """Represents a layout validation issue"""
    severity: Severity
    category: str
    message: str
    element: Dict[str, Any]
    viewport_type: str  # 'desktop' or 'mobile'
    details: Dict[str, Any] = None


class LayoutValidator:
    """Validates layout snapshots for common issues"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize validator with optional configuration
        
        Args:
            config: Configuration dict with thresholds and tolerances
        """
        self.config = config or {}
        
        # Default thresholds
        self.overflow_tolerance = self.config.get('overflow_tolerance_px', 5)
        self.offscreen_tolerance = self.config.get('offscreen_tolerance_px', 10)
        self.min_interactive_size = self.config.get('min_interactive_size_px', 44)
        self.overlap_threshold = self.config.get('overlap_threshold', 0.1)
        
        self.issues: List[LayoutIssue] = []
    
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
        
        print(f"\n{'='*60}")
        print(f"Validating {viewport_type.upper()} layout ({viewport_width}x{viewport_height})")
        print(f"Analyzing {len(elements)} elements...")
        print(f"{'='*60}\n")
        
        # Run all validation checks
        self._check_viewport_overflow(elements, viewport_width, viewport_height, viewport_type)
        self._check_offscreen_elements(elements, viewport_width, viewport_height, viewport_type)
        self._check_viewport_consistency(elements, viewport_width, viewport_height, viewport_type)
        self._check_zero_size_elements(elements, viewport_type)
        self._check_text_overflow(elements, viewport_type)
        self._check_interactive_element_size(elements, viewport_type)
        self._check_element_overlaps(elements, viewport_type)
        self._check_negative_positioning(elements, viewport_type)
        
        return self.issues
    
    def _check_viewport_overflow(self, elements: List[Dict], vp_width: int, vp_height: int, viewport_type: str):
        """Check for elements extending beyond viewport boundaries"""
        for elem in elements:
            rect = elem.get('rect', {})
            x = rect.get('x', 0)
            width = rect.get('width', 0)
            
            # Check horizontal overflow
            right_edge = x + width
            if right_edge > vp_width + self.overflow_tolerance:
                overflow_amount = right_edge - vp_width
                self.issues.append(LayoutIssue(
                    severity=Severity.CRITICAL if overflow_amount > 50 else Severity.WARNING,
                    category="VIEWPORT_OVERFLOW",
                    message=f"Element extends {overflow_amount:.1f}px beyond right edge of viewport",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'element_right': right_edge,
                        'viewport_width': vp_width,
                        'overflow_px': overflow_amount
                    }
                ))
            
            # Check if element starts before left edge
            if x < -self.overflow_tolerance:
                self.issues.append(LayoutIssue(
                    severity=Severity.WARNING,
                    category="VIEWPORT_OVERFLOW",
                    message=f"Element starts {abs(x):.1f}px before left edge of viewport",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={'element_x': x}
                ))
    
    def _check_offscreen_elements(self, elements: List[Dict], vp_width: int, vp_height: int, viewport_type: str):
        """Check for visible elements that are completely offscreen (horizontally or above viewport)"""
        for elem in elements:
            flags = elem.get('flags', {})
            rect = elem.get('rect', {})
            
            # Skip if element is marked as not visible
            if not flags.get('isVisible', False):
                continue
            
            x = rect.get('x', 0)
            y = rect.get('y', 0)
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # ONLY check for horizontal offscreen and above viewport
            # Below-the-fold content is NORMAL and should NOT be flagged
            is_offscreen_left = x + width < -self.offscreen_tolerance
            is_offscreen_right = x > vp_width + self.offscreen_tolerance
            is_offscreen_above = y + height < -self.offscreen_tolerance
            
            # Determine if actually offscreen (excluding below-fold)
            if is_offscreen_left or is_offscreen_right or is_offscreen_above:
                # Determine direction
                if is_offscreen_left:
                    direction = "left"
                elif is_offscreen_right:
                    direction = "right"
                else:
                    direction = "above"
                
                # Only flag interactive elements as critical
                is_interactive = flags.get('isInteractive', False)
                severity = Severity.CRITICAL if is_interactive else Severity.WARNING
                
                self.issues.append(LayoutIssue(
                    severity=severity,
                    category="OFFSCREEN_ELEMENT",
                    message=f"Visible element is completely {direction} the viewport",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'position': {'x': x, 'y': y},
                        'size': {'width': width, 'height': height},
                        'direction': direction
                    }
                ))
    
    def _check_viewport_consistency(self, elements: List[Dict], vp_width: int, vp_height: int, viewport_type: str):
        """Check for elements marked as in-viewport but positioned outside (layout bug)"""
        for elem in elements:
            flags = elem.get('flags', {})
            rect = elem.get('rect', {})
            
            # Skip if not marked as in viewport
            if not flags.get('isInViewport', False):
                continue
            
            x = rect.get('x', 0)
            y = rect.get('y', 0)
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # Check if element is actually outside viewport bounds
            # Allow small tolerance for rounding
            tolerance = 5
            is_outside = (
                x + width < -tolerance or  # Completely left
                x > vp_width + tolerance or  # Completely right
                y + height < -tolerance or  # Completely above
                y > vp_height + tolerance  # Completely below
            )
            
            if is_outside:
                self.issues.append(LayoutIssue(
                    severity=Severity.WARNING,
                    category="VIEWPORT_INCONSISTENCY",
                    message=f"Element marked as in-viewport but positioned outside viewport bounds",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={
                        'position': {'x': x, 'y': y},
                        'size': {'width': width, 'height': height},
                        'viewport': {'width': vp_width, 'height': vp_height}
                    }
                ))
    
    def _check_zero_size_elements(self, elements: List[Dict], viewport_type: str):
        """Check for elements with zero or negative dimensions"""
        for elem in elements:
            rect = elem.get('rect', {})
            flags = elem.get('flags', {})
            
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # Skip invisible elements
            if not flags.get('isVisible', False):
                continue
            
            if width <= 0 or height <= 0:
                # Critical if it's an interactive element
                is_interactive = flags.get('isInteractive', False)
                severity = Severity.CRITICAL if is_interactive else Severity.INFO
                
                self.issues.append(LayoutIssue(
                    severity=severity,
                    category="ZERO_SIZE",
                    message=f"Visible element has zero/negative dimensions (w:{width}, h:{height})",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={'width': width, 'height': height}
                ))
    
    def _check_text_overflow(self, elements: List[Dict], viewport_type: str):
        """Check for text elements that might be clipped"""
        text_tags = ['p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'button', 'label', 'div']
        
        for elem in elements:
            tag = elem.get('tag', '').lower()
            if tag not in text_tags:
                continue
            
            text = elem.get('text')
            if not text or len(text.strip()) < 3:
                continue
            
            computed = elem.get('computed', {})
            overflow_x = computed.get('overflow', 'visible')
            overflow_y = computed.get('overflow', 'visible')
            
            # Check if overflow is hidden or clip
            if overflow_x in ['hidden', 'clip'] or overflow_y in ['hidden', 'clip']:
                rect = elem.get('rect', {})
                
                # If element has text but small dimensions, might be clipped
                if rect.get('width', 0) < 50 or rect.get('height', 0) < 20:
                    self.issues.append(LayoutIssue(
                        severity=Severity.WARNING,
                        category="TEXT_OVERFLOW",
                        message=f"Text element with overflow:{overflow_x} has small dimensions, text may be clipped",
                        element=self._simplify_element(elem),
                        viewport_type=viewport_type,
                        details={
                            'text_length': len(text),
                            'text_preview': text[:50] + '...' if len(text) > 50 else text,
                            'dimensions': {'width': rect.get('width'), 'height': rect.get('height')}
                        }
                    ))
    
    def _check_interactive_element_size(self, elements: List[Dict], viewport_type: str):
        """Check if interactive elements are large enough (especially on mobile)"""
        # Only strict on mobile
        if viewport_type != 'mobile':
            return
        
        interactive_tags = ['button', 'a', 'input', 'select', 'textarea']
        
        for elem in elements:
            tag = elem.get('tag', '').lower()
            flags = elem.get('flags', {})
            
            if tag not in interactive_tags and not flags.get('isClickable', False):
                continue
            
            rect = elem.get('rect', {})
            width = rect.get('width', 0)
            height = rect.get('height', 0)
            
            # Check minimum touch target size (44x44 is recommended)
            if width < self.min_interactive_size and height < self.min_interactive_size:
                self.issues.append(LayoutIssue(
                    severity=Severity.WARNING,
                    category="SMALL_INTERACTIVE",
                    message=f"Interactive element too small for touch ({width:.0f}x{height:.0f}px, recommended: {self.min_interactive_size}x{self.min_interactive_size}px)",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={'width': width, 'height': height}
                ))
    
    def _check_element_overlaps(self, elements: List[Dict], viewport_type: str):
        """Check for significant element overlaps (basic check)"""
        # Only check visible, in-viewport elements
        visible_elements = [
            e for e in elements 
            if e.get('flags', {}).get('isVisible', False) and 
               e.get('flags', {}).get('isInViewport', False)
        ]
        
        # Limit to prevent performance issues
        if len(visible_elements) > 100:
            visible_elements = visible_elements[:100]
        
        checked_pairs = set()
        
        for i, elem_a in enumerate(visible_elements):
            for elem_b in visible_elements[i+1:]:
                # Create unique pair identifier
                pair_id = (id(elem_a), id(elem_b))
                if pair_id in checked_pairs:
                    continue
                checked_pairs.add(pair_id)
                
                overlap_area = self._calculate_overlap(
                    elem_a.get('rect', {}),
                    elem_b.get('rect', {})
                )
                
                if overlap_area > 0:
                    # Calculate overlap ratio
                    area_a = self._calculate_area(elem_a.get('rect', {}))
                    area_b = self._calculate_area(elem_b.get('rect', {}))
                    
                    if area_a > 0 and area_b > 0:
                        overlap_ratio = overlap_area / min(area_a, area_b)
                        
                        if overlap_ratio > self.overlap_threshold:
                            self.issues.append(LayoutIssue(
                                severity=Severity.WARNING,
                                category="ELEMENT_OVERLAP",
                                message=f"Elements overlap by {overlap_ratio*100:.1f}% of smaller element",
                                element=self._simplify_element(elem_a),
                                viewport_type=viewport_type,
                                details={
                                    'element_a': self._simplify_element(elem_a),
                                    'element_b': self._simplify_element(elem_b),
                                    'overlap_area': overlap_area,
                                    'overlap_ratio': overlap_ratio
                                }
                            ))
    
    def _check_negative_positioning(self, elements: List[Dict], viewport_type: str):
        """Check for elements with suspicious negative positioning"""
        for elem in elements:
            rect = elem.get('rect', {})
            computed = elem.get('computed', {})
            flags = elem.get('flags', {})
            
            x = rect.get('x', 0)
            y = rect.get('y', 0)
            
            # Skip if not visible
            if not flags.get('isVisible', False):
                continue
            
            # Check for large negative positions (likely unintentional)
            if x < -100 or y < -100:
                position = computed.get('position', 'static')
                
                self.issues.append(LayoutIssue(
                    severity=Severity.WARNING,
                    category="NEGATIVE_POSITION",
                    message=f"Element has large negative position (x:{x:.0f}, y:{y:.0f}) with position:{position}",
                    element=self._simplify_element(elem),
                    viewport_type=viewport_type,
                    details={'x': x, 'y': y, 'position': position}
                ))
    
    def _calculate_overlap(self, rect_a: Dict, rect_b: Dict) -> float:
        """Calculate overlap area between two rectangles"""
        x1 = max(rect_a.get('x', 0), rect_b.get('x', 0))
        y1 = max(rect_a.get('y', 0), rect_b.get('y', 0))
        x2 = min(
            rect_a.get('x', 0) + rect_a.get('width', 0),
            rect_b.get('x', 0) + rect_b.get('width', 0)
        )
        y2 = min(
            rect_a.get('y', 0) + rect_a.get('height', 0),
            rect_b.get('y', 0) + rect_b.get('height', 0)
        )
        
        if x2 > x1 and y2 > y1:
            return (x2 - x1) * (y2 - y1)
        return 0
    
    def _calculate_area(self, rect: Dict) -> float:
        """Calculate area of a rectangle"""
        return rect.get('width', 0) * rect.get('height', 0)
    
    def _simplify_element(self, elem: Dict) -> Dict:
        """Create a simplified element representation for reporting"""
        return {
            'tag': elem.get('tag'),
            'id': elem.get('id'),
            'classes': elem.get('classes', [])[:3],  # Limit classes
            'text': (elem.get('text', '') or '')[:50],  # Truncate text
            'rect': elem.get('rect', {})
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
        elif warning_count > 5:
            status = "WARNING"
        else:
            status = "PASS"
        
        return {
            'status': status,
            'summary': {
                'total_issues': total_issues,
                'critical': critical_count,
                'warnings': warning_count,
                'info': info_count
            },
            'by_severity': {
                k: [self._issue_to_dict(i) for i in v]
                for k, v in by_severity.items()
            },
            'by_category': {
                k: len(v) for k, v in by_category.items()
            },
            'by_viewport': {
                'desktop': len(by_viewport['desktop']),
                'mobile': len(by_viewport['mobile'])
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
            'details': issue.details
        }
    
    def print_summary(self):
        """Print a human-readable summary of issues"""
        report = self.generate_report()
        
        print("\n" + "="*80)
        print("LAYOUT VALIDATION REPORT")
        print("="*80)
        
        print(f"\nOverall Status: {report['status']}")
        print(f"\nTotal Issues Found: {report['summary']['total_issues']}")
        print(f"  - Critical: {report['summary']['critical']}")
        print(f"  - Warnings: {report['summary']['warnings']}")
        print(f"  - Info: {report['summary']['info']}")
        
        print(f"\nIssues by Viewport:")
        print(f"  - Desktop: {report['by_viewport']['desktop']}")
        print(f"  - Mobile: {report['by_viewport']['mobile']}")
        
        print(f"\nIssues by Category:")
        for category, count in sorted(report['by_category'].items(), key=lambda x: -x[1]):
            print(f"  - {category}: {count}")
        
        # Print critical issues
        if report['summary']['critical'] > 0:
            print(f"\n{'='*80}")
            print("CRITICAL ISSUES:")
            print("="*80)
            for issue in report['by_severity']['CRITICAL'][:10]:  # Limit to first 10
                print(f"\n[{issue['viewport'].upper()}] {issue['category']}")
                print(f"  {issue['message']}")
                elem = issue['element']
                print(f"  Element: <{elem['tag']}> {elem.get('id', '')} {elem.get('classes', [])}")
                if elem.get('text'):
                    print(f"  Text: {elem['text']}")
        
        print("\n" + "="*80 + "\n")


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
    
    # Print summary
    validator.print_summary()
    
    # Save report if output file specified
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        print(f"Detailed report saved to: {output_file}")
    
    return report


if __name__ == "__main__":
    validate_layout_file('result.json')

