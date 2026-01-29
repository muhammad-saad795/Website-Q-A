import json
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - [LAYOUT_VALIDATOR] - %(message)s'
)
logger = logging.getLogger(__name__)

class Severity(Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"

class LayoutValidator:
    """
    Robust layout validator that analyzes webpage snapshots for layout integrity issues.
    Focuses on actual layout problems, not design patterns or styling choices.
    """
    
    def __init__(self, snapshot: Dict[str, Any]):
        self.viewport = snapshot.get("viewport", {"width": 1920, "height": 1080})
        self.elements = snapshot.get("elements", [])
        self.timestamp = snapshot.get("timestamp")
        self.issues = []
        
        # Build element lookup for parent relationships
        self.element_map = {}
        self.element_by_position = {}  # Key: (x, y, width, height) -> element
        for el in self.elements:
            key = self._get_element_key(el)
            self.element_map[key] = el
            
            # Build position-based index for parent matching
            rect = el.get("rect", {})
            if rect:
                pos_key = (
                    round(rect.get("x", 0), 1),
                    round(rect.get("y", 0), 1),
                    round(rect.get("width", 0), 1),
                    round(rect.get("height", 0), 1)
                )
                self.element_by_position[pos_key] = el
        
        # Cache for expensive calculations
        self.interactive_elements_cache = None
        
    def _get_element_key(self, element: Dict[str, Any]) -> str:
        """Create a unique key for an element based on its properties."""
        tag = element.get("tag", "unknown")
        el_id = element.get("id", "")
        classes = ".".join(sorted(element.get("classes", [])))
        rect = element.get("rect", {})
        position = f"{rect.get('x', 0):.1f},{rect.get('y', 0):.1f},{rect.get('width', 0):.1f},{rect.get('height', 0):.1f}"
        
        return f"{tag}:{el_id}:{classes}:{position}"
    
    def _get_element_identifier(self, element: Dict[str, Any]) -> str:
        """Get a human-readable identifier for an element."""
        tag = element.get("tag", "unknown")
        el_id = element.get("id")
        classes = element.get("classes", [])
        text = element.get("text", "")
        
        if el_id:
            return f"{tag}#{el_id}"
        elif classes:
            # Take first 2 classes for readability
            short_classes = ".".join(classes[:2])
            if len(classes) > 2:
                short_classes += "..."
            return f"{tag}.{short_classes}"
        elif text and len(text) < 30:
            # Include text snippet for identification
            return f"{tag}['{text[:20]}...']"
        else:
            return tag
    
    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float, handling various formats."""
        if value is None:
            return default
        
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Remove 'px', '%', etc.
            cleaned = ''.join(c for c in value if c.isdigit() or c == '.' or c == '-')
            if cleaned and cleaned.replace('.', '').replace('-', '').isdigit():
                try:
                    return float(cleaned)
                except (ValueError, TypeError):
                    return default
        
        return default
    
    def _safe_int(self, value: Any, default: int = 0) -> int:
        """Safely convert a value to int."""
        try:
            if isinstance(value, str):
                if value == "auto":
                    return default
                # Try to parse
                cleaned = ''.join(c for c in value if c.isdigit() or c == '-')
                if cleaned:
                    return int(cleaned)
            elif isinstance(value, (int, float)):
                return int(value)
        except (ValueError, TypeError):
            pass
        return default
    
    def _add_issue(self, severity: Severity, category: str, 
                   message: str, element: Dict[str, Any], 
                   confidence: float = 1.0, data: Dict = None):
        """Record an issue with confidence scoring."""
        if confidence < 0.3:  # Skip low-confidence issues
            return
            
        identifier = self._get_element_identifier(element)
        
        issue = {
            "severity": severity.value,
            "category": category,
            "message": message,
            "element": identifier,
            "tag": element.get("tag"),
            "rect": element.get("rect"),
            "confidence": confidence,
            "data": data or {}
        }
        self.issues.append(issue)
    
    # ------------------------------------------------------------------
    # Core Layout Health Checks - FIXED VERSIONS
    # ------------------------------------------------------------------
    
    def _get_interactive_elements(self) -> List[Dict[str, Any]]:
        """Get all interactive elements with caching."""
        if self.interactive_elements_cache is None:
            self.interactive_elements_cache = []
            for el in self.elements:
                flags = el.get("flags", {})
                computed = el.get("computed", {})
                
                # Check if element is interactive
                is_interactive = flags.get("isInteractive", False)
                
                # Check visibility
                display = computed.get("display", "inline")
                visibility = computed.get("visibility", "visible")
                opacity = self._safe_float(computed.get("opacity", 1))
                
                if (is_interactive and 
                    display != "none" and 
                    visibility != "hidden" and 
                    opacity > 0.1):
                    self.interactive_elements_cache.append(el)
                    
        return self.interactive_elements_cache
    
    def check_critical_overlaps(self):
        """Detect overlapping interactive elements that impede usability."""
        interactives = self._get_interactive_elements()
        
        for i in range(len(interactives)):
            el1 = interactives[i]
            r1 = el1.get("rect", {})
            if not r1 or r1.get("width", 0) < 1 or r1.get("height", 0) < 1:
                continue
            
            for j in range(i + 1, len(interactives)):
                el2 = interactives[j]
                r2 = el2.get("rect", {})
                if not r2 or r2.get("width", 0) < 1 or r2.get("height", 0) < 1:
                    continue
                
                # Skip if elements are too far apart (optimization)
                if (abs(r1["x"] - r2["x"]) > max(r1["width"], r2["width"]) * 2 or
                    abs(r1["y"] - r2["y"]) > max(r1["height"], r2["height"]) * 2):
                    continue
                
                # Calculate intersection
                x_overlap = max(0, min(r1["x"] + r1["width"], r2["x"] + r2["width"]) - max(r1["x"], r2["x"]))
                y_overlap = max(0, min(r1["y"] + r1["height"], r2["y"] + r2["height"]) - max(r1["y"], r2["y"]))
                
                if x_overlap > 0 and y_overlap > 0:
                    overlap_area = x_overlap * y_overlap
                    area1 = r1["width"] * r1["height"]
                    area2 = r2["width"] * r2["height"]
                    
                    # Skip very small overlaps (< 5px²)
                    if overlap_area < 5:
                        continue
                    
                    # Only flag if overlap is significant (>15% of smaller element)
                    min_area = min(area1, area2)
                    if min_area > 0 and overlap_area / min_area > 0.15:
                        # Check if this might be intentional (e.g., dropdowns, tooltips)
                        # by looking at z-index
                        z1 = self._safe_int(el1.get("computed", {}).get("zIndex", 0))
                        z2 = self._safe_int(el2.get("computed", {}).get("zIndex", 0))
                        
                        # If z-index differs significantly, might be intentional layering
                        if abs(z1 - z2) < 10:  # Similar z-index suggests unintentional overlap
                            overlap_percent = int((overlap_area / min_area) * 100)
                            confidence = min(0.9, overlap_area / min_area)
                            
                            # Check if either element is clearly on top (higher z-index)
                            # If one has much higher z-index, it might be intentional
                            if abs(z1 - z2) > 100:
                                confidence *= 0.5  # Reduce confidence for large z-index difference
                            
                            self._add_issue(
                                Severity.CRITICAL,
                                "InteractiveOverlap",
                                f"Overlaps with {self._get_element_identifier(el2)} "
                                f"({overlap_percent}% of smaller element)",
                                el1,
                                confidence,
                                {"overlap_with": self._get_element_identifier(el2)}
                            )
    
    def check_viewport_visibility(self):
        """Check if important elements are visible within the viewport."""
        viewport_height = self.viewport["height"]
        viewport_width = self.viewport["width"]
        
        # Primary CTAs and navigation should be in viewport
        primary_selectors = ["button", "a.btn", "nav", "header", "navbar"]
        
        for el in self.elements:
            rect = el.get("rect", {})
            if not rect:
                continue
                
            # Check if element is completely outside viewport but marked as in viewport
            flags = el.get("flags", {})
            computed = el.get("computed", {})
            
            # Element position relative to viewport
            # Element is in viewport if any part of it is visible
            intersects_viewport = (
                rect["x"] < viewport_width and
                rect["x"] + rect["width"] > 0 and
                rect["y"] < viewport_height and
                rect["y"] + rect["height"] > 0
            )
            
            # Check for contradiction between flags and actual position
            if flags.get("isInViewport", True) and not intersects_viewport:
                # Only warn if element is large or interactive and not just below fold
                element_area = rect["width"] * rect["height"]
                is_interactive = flags.get("isInteractive", False)
                
                # Check if it's just below the fold (normal scrolling)
                is_just_below_fold = (rect["y"] > viewport_height and 
                                     rect["y"] < viewport_height * 3)  # Within 3 viewports
                is_just_above_fold = rect["y"] + rect["height"] < 0
                
                # Reduce confidence for normal below/above-fold content
                if is_just_below_fold or is_just_above_fold:
                    confidence = 0.2
                else:
                    confidence = 0.7
                
                # Only report if significant
                if (element_area > 10000 or is_interactive) and confidence > 0.5:
                    position_desc = "above" if rect["y"] + rect["height"] < 0 else "below"
                    self._add_issue(
                        Severity.WARNING,
                        "ViewportMismatch",
                        f"Element marked as in viewport but is {position_desc} the visible area",
                        el,
                        confidence
                    )
    
    def check_layout_containment(self):
        """
        Check for serious layout containment issues, ignoring normal CSS patterns.
        """
        for el in self.elements:
            parent_info = el.get("parent")
            if not parent_info or not parent_info.get("rect"):
                continue
            
            child_rect = el.get("rect", {})
            parent_rect = parent_info["rect"]
            
            # Skip absolutely/fixed positioned elements - they're meant to break out
            position = el.get("computed", {}).get("position", "static")
            if position in ["absolute", "fixed"]:
                continue
                
            # Skip elements with overflow visible (parent might allow bleeding)
            overflow = el.get("computed", {}).get("overflow", "visible")
            if overflow == "visible":
                continue
            
            # Calculate how much child extends beyond parent (with tolerance for rounding)
            tolerance = 2  # 2px tolerance for rounding errors
            bleed_left = max(0, parent_rect["x"] - child_rect["x"] - tolerance)
            bleed_right = max(0, (child_rect["x"] + child_rect["width"]) - 
                            (parent_rect["x"] + parent_rect["width"]) - tolerance)
            bleed_top = max(0, parent_rect["y"] - child_rect["y"] - tolerance)
            bleed_bottom = max(0, (child_rect["y"] + child_rect["height"]) - 
                             (parent_rect["y"] + parent_rect["height"]) - tolerance)
            
            total_bleed = bleed_left + bleed_right + bleed_top + bleed_bottom
            
            # Only flag significant bleeding (>20px total or >10px in any direction)
            if total_bleed > 20 or max(bleed_left, bleed_right, bleed_top, bleed_bottom) > 10:
                # Check if parent might have padding/margin that accounts for this
                parent_has_padding = False
                parent_computed = self._find_element_by_rect(parent_rect)
                if parent_computed:
                    for side in ["Top", "Bottom", "Left", "Right"]:
                        padding = parent_computed.get(f"padding{side}", "0px")
                        margin = parent_computed.get(f"margin{side}", "0px")
                        if padding != "0px" or margin != "0px":
                            parent_has_padding = True
                            break
                
                confidence = 0.8 if not parent_has_padding else 0.3
                
                # Only flag if element is visible and not decorative
                opacity = self._safe_float(el.get("computed", {}).get("opacity", 1))
                if opacity > 0.1 and child_rect.get("width", 0) * child_rect.get("height", 0) > 100:
                    bleed_dirs = []
                    if bleed_left > 0: bleed_dirs.append(f"left:{int(bleed_left)}px")
                    if bleed_right > 0: bleed_dirs.append(f"right:{int(bleed_right)}px")
                    if bleed_top > 0: bleed_dirs.append(f"top:{int(bleed_top)}px")
                    if bleed_bottom > 0: bleed_dirs.append(f"bottom:{int(bleed_bottom)}px")
                    
                    self._add_issue(
                        Severity.WARNING,
                        "LayoutContainment",
                        f"Extends beyond parent ({', '.join(bleed_dirs)})",
                        el,
                        confidence
                    )
    
    def _find_element_by_rect(self, rect: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Find an element by its rectangle with tolerance."""
        if not rect:
            return None
            
        target_key = (
            round(rect.get("x", 0), 1),
            round(rect.get("y", 0), 1),
            round(rect.get("width", 0), 1),
            round(rect.get("height", 0), 1)
        )
        
        # Exact match
        if target_key in self.element_by_position:
            return self.element_by_position[target_key]
        
        # Fuzzy match with tolerance
        tolerance = 2.0
        for pos_key, element in self.element_by_position.items():
            if (abs(pos_key[0] - target_key[0]) < tolerance and
                abs(pos_key[1] - target_key[1]) < tolerance and
                abs(pos_key[2] - target_key[2]) < tolerance and
                abs(pos_key[3] - target_key[3]) < tolerance):
                return element
        
        return None
    
    def check_visibility_contradictions(self):
        """
        Check for contradictions between computed styles and actual rendering.
        """
        for el in self.elements:
            computed = el.get("computed", {})
            flags = el.get("flags", {})
            rect = el.get("rect", {})
            
            if not rect:
                continue
                
            # Check for invisible but large elements that might be blocking
            opacity = self._safe_float(computed.get("opacity", 1))
            visibility = computed.get("visibility", "visible")
            display = computed.get("display", "inline")
            
            area = rect.get("width", 0) * rect.get("height", 0)
            
            if (opacity == 0 or visibility == "hidden" or display == "none") and area > 10000:
                # Large invisible element - might be a hidden modal or overlay
                self._add_issue(
                    Severity.INFO,
                    "LargeInvisibleElement",
                    f"Large invisible element ({int(area)}px²) could affect layout",
                    el,
                    0.6
                )
            
            # Check for zero-sized but visible elements
            if (area == 0 and 
                opacity > 0 and 
                visibility == "visible" and 
                display not in ["none", "hidden"] and
                flags.get("isInteractive", False)):
                
                self._add_issue(
                    Severity.WARNING,
                    "ZeroSizedInteractive",
                    "Interactive element has zero size but is visible",
                    el,
                    0.9
                )
    
    def check_content_clipping(self):
        """
        Check for content that's being clipped in problematic ways.
        FIXED VERSION: Proper parent-child matching with position verification.
        """
        # Build a map of element by their computed rectangle for parent lookup
        rect_to_element = {}
        for el in self.elements:
            rect = el.get("rect", {})
            if rect:
                rect_key = (
                    round(rect.get("x", 0), 1),
                    round(rect.get("y", 0), 1),
                    round(rect.get("width", 0), 1),
                    round(rect.get("height", 0), 1)
                )
                rect_to_element[rect_key] = el
        
        # Track elements we've already flagged to avoid duplicates
        flagged_elements = set()
        
        for el in self.elements:
            computed = el.get("computed", {})
            overflow = computed.get("overflow", "visible")
            
            # Only check elements that could clip their children
            if overflow not in ["hidden", "clip"]:
                continue
            
            el_rect = el.get("rect", {})
            if not el_rect:
                continue
            
            el_key = self._get_element_key(el)
            
            # Find children that actually belong to this element
            for child in self.elements:
                child_key = self._get_element_key(child)
                if child_key in flagged_elements:
                    continue
                
                # Skip if not interactive
                if not child.get("flags", {}).get("isInteractive", False):
                    continue
                
                child_parent = child.get("parent")
                if not child_parent:
                    continue
                
                child_parent_rect = child_parent.get("rect", {})
                if not child_parent_rect:
                    continue
                
                # FIX: Proper parent matching with tolerance for floating point errors
                tolerance = 1.0  # 1px tolerance for rounding errors
                parent_matches = (
                    abs(el_rect.get("x", 0) - child_parent_rect.get("x", 0)) <= tolerance and
                    abs(el_rect.get("y", 0) - child_parent_rect.get("y", 0)) <= tolerance and
                    abs(el_rect.get("width", 0) - child_parent_rect.get("width", 0)) <= tolerance and
                    abs(el_rect.get("height", 0) - child_parent_rect.get("height", 0)) <= tolerance
                )
                
                if not parent_matches:
                    continue  # Not the actual parent
                
                # Now check for actual clipping
                child_rect = child.get("rect", {})
                if not child_rect:
                    continue
                
                # Calculate clipping with tolerance for subpixel rendering
                clip_tolerance = 2.0  # 2px tolerance
                is_clipped = (
                    (child_rect.get("x", 0) < el_rect.get("x", 0) - clip_tolerance) or
                    (child_rect.get("y", 0) < el_rect.get("y", 0) - clip_tolerance) or
                    (child_rect.get("x", 0) + child_rect.get("width", 0) > 
                     el_rect.get("x", 0) + el_rect.get("width", 0) + clip_tolerance) or
                    (child_rect.get("y", 0) + child_rect.get("height", 0) > 
                     el_rect.get("y", 0) + el_rect.get("height", 0) + clip_tolerance)
                )
                
                if is_clipped:
                    # Calculate how much is clipped
                    clip_left = max(0, el_rect.get("x", 0) - child_rect.get("x", 0))
                    clip_top = max(0, el_rect.get("y", 0) - child_rect.get("y", 0))
                    clip_right = max(0, (child_rect.get("x", 0) + child_rect.get("width", 0)) - 
                                    (el_rect.get("x", 0) + el_rect.get("width", 0)))
                    clip_bottom = max(0, (child_rect.get("y", 0) + child_rect.get("height", 0)) - 
                                     (el_rect.get("y", 0) + el_rect.get("height", 0)))
                    
                    total_clip = clip_left + clip_right + clip_top + clip_bottom
                    child_area = child_rect.get("width", 0) * child_rect.get("height", 0)
                    
                    if child_area > 0 and total_clip / child_area > 0.05:  # At least 5% clipped
                        flagged_elements.add(child_key)
                        
                        # Calculate confidence based on clipping severity
                        clip_ratio = total_clip / child_area
                        confidence = min(0.9, clip_ratio * 5)  # Scale to 0-0.9
                        
                        self._add_issue(
                            Severity.WARNING,
                            "ClippedInteractive",
                            f"Interactive element clipped by parent (extends {int(total_clip)}px beyond bounds)",
                            child,
                            confidence
                        )
    
    def check_touch_targets(self):
        """
        Check for interactive elements that are too small for reliable interaction.
        Uses context-aware thresholds.
        """
        interactives = self._get_interactive_elements()
        
        for el in interactives:
            rect = el.get("rect", {})
            width, height = rect.get("width", 0), rect.get("height", 0)
            
            # Skip elements that are clearly decorative or secondary
            tag = el.get("tag", "")
            classes = el.get("classes", [])
            text = el.get("text", "")
            
            # Context-aware thresholds
            min_size = 24  # Default minimum for primary CTAs
            
            # Adjust thresholds based on context
            is_footer_link = any(cls in ["footer", "small", "text-muted"] for cls in classes)
            is_map_attribution = "map" in str(classes).lower() or "attribution" in str(text).lower()
            is_icon_button = any(cls in ["btn-sm", "icon", "rounded-circle"] for cls in classes)
            is_text_link = (tag == "a" and not any(cls.startswith("btn") for cls in classes))
            
            if is_footer_link or is_map_attribution:
                min_size = 10  # Footer links can be smaller
            elif is_icon_button:
                min_size = 20  # Icon buttons can be slightly smaller
            elif is_text_link:
                min_size = 16  # Text links can be smaller
            
            # Check if element is too small
            if width < min_size or height < min_size:
                # Calculate confidence based on how small it is
                size_ratio = min(width, height) / min_size if min_size > 0 else 0
                confidence = max(0.3, 1 - size_ratio)
                
                # Adjust severity based on context
                if min(width, height) < 10:
                    severity = Severity.WARNING
                elif min(width, height) < 16:
                    severity = Severity.WARNING if is_icon_button else Severity.INFO
                else:
                    severity = Severity.INFO
                
                self._add_issue(
                    severity,
                    "SmallTouchTarget",
                    f"Interactive element is small ({int(width)}x{int(height)}px)",
                    el,
                    confidence
                )
    
    def check_stacking_context(self):
        """
        Check for potential stacking context issues (z-index conflicts).
        """
        elements_with_zindex = []
        
        for el in self.elements:
            z_index_str = el.get("computed", {}).get("zIndex", "auto")
            if z_index_str != "auto":
                try:
                    z_val = self._safe_int(z_index_str)
                    elements_with_zindex.append((el, z_val))
                except (ValueError, TypeError):
                    # Skip if we can't parse the z-index
                    pass
        
        # Check for extremely high z-index values that might cause issues
        for el, z_val in elements_with_zindex:
            if abs(z_val) > 10000:  # Very high z-index might indicate issues
                self._add_issue(
                    Severity.WARNING,
                    "ExtremeZIndex",
                    f"Extreme z-index value ({z_val}) might cause stacking issues",
                    el,
                    0.6
                )
    
    def check_layout_stability(self):
        """
        Check for potential layout instability issues (like elements with position: static
        that have unexpected negative margins).
        """
        for el in self.elements:
            computed = el.get("computed", {})
            position = computed.get("position", "static")
            rect = el.get("rect", {})
            
            # Check for static elements with negative coordinates (could be pulled out of flow)
            if position == "static" and rect.get("x", 0) < -100:
                self._add_issue(
                    Severity.WARNING,
                    "NegativePosition",
                    f"Static element at negative x position ({rect['x']})",
                    el,
                    0.7
                )
            
            # Check for extremely large negative margins
            for side in ["Top", "Bottom", "Left", "Right"]:
                margin = computed.get(f"margin{side}", "0px")
                margin_val = self._safe_float(margin)
                if margin_val < -100:  # Very large negative margin
                    self._add_issue(
                        Severity.WARNING,
                        "LargeNegativeMargin",
                        f"Large negative margin-{side.lower()}: {margin}",
                        el,
                        0.8
                    )
    
    def check_scrollable_overflow(self):
        """
        Check for elements that might cause unintended scrolling.
        """
        viewport_width = self.viewport["width"]
        viewport_height = self.viewport["height"]
        
        for el in self.elements:
            rect = el.get("rect", {})
            if not rect:
                continue
            
            # Check if element extends far beyond viewport width (horizontal overflow)
            element_right = rect.get("x", 0) + rect.get("width", 0)
            if element_right > viewport_width * 1.5:
                # Check if this is intentional (like a wide table or horizontal scroll area)
                computed = el.get("computed", {})
                overflow_x = computed.get("overflowX", "visible")
                
                if overflow_x in ["visible", "auto", "scroll"]:
                    confidence = 0.3  # Might be intentional
                else:
                    confidence = 0.8
                
                self._add_issue(
                    Severity.WARNING,
                    "HorizontalOverflow",
                    f"Element extends {int(element_right - viewport_width)}px beyond viewport width",
                    el,
                    confidence
                )
            
            # Check for elements far below viewport that might indicate excessive page height
            element_bottom = rect.get("y", 0) + rect.get("height", 0)
            if element_bottom > viewport_height * 10:  # More than 10 viewports down
                # Skip footer elements and long content sections
                tag = el.get("tag", "")
                classes = el.get("classes", [])
                
                if tag not in ["footer", "section"] and not any(c in ["footer", "long-content"] for c in classes):
                    self._add_issue(
                        Severity.INFO,
                        "ExcessivePageLength",
                        f"Content extends {int(element_bottom / viewport_height)} viewports down",
                        el,
                        0.5
                    )
    
    def check_accessibility_issues(self):
        """
        NEW: Check for common accessibility issues related to layout.
        """
        for el in self.elements:
            computed = el.get("computed", {})
            flags = el.get("flags", {})
            rect = el.get("rect", {})
            
            if not flags.get("isInteractive", False):
                continue
            
            # Check for low contrast (if color info is available)
            color = computed.get("color", "")
            bg_color = computed.get("backgroundColor", "")
            
            # Simple contrast check for common issues
            if "rgba(0,0,0,0)" in bg_color or "transparent" in bg_color:
                # Check if text might be hard to read
                if rect.get("width", 0) * rect.get("height", 0) > 100:
                    self._add_issue(
                        Severity.INFO,
                        "LowContrast",
                        "Interactive element may have low contrast with transparent background",
                        el,
                        0.4
                    )
            
            # Check for focus indicators
            outline = computed.get("outline", "none")
            border_widths = [
                self._safe_float(computed.get("borderTopWidth", "0px")),
                self._safe_float(computed.get("borderBottomWidth", "0px")),
                self._safe_float(computed.get("borderLeftWidth", "0px")),
                self._safe_float(computed.get("borderRightWidth", "0px"))
            ]
            
            if outline == "none" and max(border_widths) < 2:
                self._add_issue(
                    Severity.INFO,
                    "MissingFocusIndicator",
                    "Interactive element may lack visible focus indicator",
                    el,
                    0.5
                )
    
    def check_performance_issues(self):
        """
        NEW: Check for potential performance issues in layout.
        """
        # Check for too many interactive elements (could affect performance)
        interactives = self._get_interactive_elements()
        if len(interactives) > 100:
            self._add_issue(
                Severity.INFO,
                "ManyInteractiveElements",
                f"Page has {len(interactives)} interactive elements (may affect performance)",
                {"tag": "page", "rect": {}},
                0.6
            )
        
        # Check for elements with complex transforms that might affect performance
        for el in self.elements:
            computed = el.get("computed", {})
            transform = computed.get("transform", "none")
            
            if transform != "none" and "matrix" in transform.lower():
                # Complex matrix transform
                area = el.get("rect", {}).get("width", 0) * el.get("rect", {}).get("height", 0)
                if area > 10000:  # Large element with complex transform
                    self._add_issue(
                        Severity.INFO,
                        "ComplexTransform",
                        "Large element uses complex transform (may affect performance)",
                        el,
                        0.4
                    )
    
    # ------------------------------------------------------------------
    # Evaluation Orchestration
    # ------------------------------------------------------------------
    
    def evaluate(self) -> Dict[str, Any]:
        """
        Run all layout checks and generate a comprehensive report.
        """
        logger.info(f"Validating layout for {len(self.elements)} elements")
        
        # Reset issues and cache
        self.issues = []
        self.interactive_elements_cache = None
        
        # Run checks in order of importance
        try:
            self.check_critical_overlaps()           # Most critical
            self.check_viewport_visibility()
            self.check_layout_containment()
            self.check_visibility_contradictions()
            self.check_content_clipping()           # FIXED VERSION
            self.check_touch_targets()              # Lower priority
            self.check_stacking_context()
            self.check_layout_stability()
            self.check_scrollable_overflow()
            self.check_accessibility_issues()       # NEW
            self.check_performance_issues()         # NEW
        except Exception as e:
            logger.error(f"Error during layout validation: {e}")
            # Add an issue about the validation error
            self._add_issue(
                Severity.WARNING,
                "ValidationError",
                f"Layout validation encountered an error: {str(e)[:50]}...",
                {"tag": "system", "rect": {}},
                1.0
            )
        
        return self._generate_report()
    
    def _generate_report(self) -> Dict[str, Any]:
        """Generate a structured report of all issues found."""
        # Filter out duplicate issues (same element, same category)
        unique_issues = []
        seen_keys = set()
        
        for issue in self.issues:
            # Skip system issues for unique check
            if issue["element"] == "system":
                unique_issues.append(issue)
                continue
                
            key = f"{issue['element']}:{issue['category']}:{issue.get('data', {}).get('overlap_with', '')}"
            if key not in seen_keys:
                seen_keys.add(key)
                unique_issues.append(issue)
        
        # Sort by severity and confidence
        severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        unique_issues.sort(key=lambda x: (severity_order.get(x["severity"], 3), -x.get("confidence", 0)))
        
        # Calculate health score - improved formula
        critical_count = sum(1 for i in unique_issues if i["severity"] == "CRITICAL")
        warning_count = sum(1 for i in unique_issues if i["severity"] == "WARNING")
        info_count = sum(1 for i in unique_issues if i["severity"] == "INFO")
        
        # Weighted scoring - focus on critical issues, be forgiving of info issues
        health_score = 100
        health_score -= critical_count * 30  # Heavy penalty for critical
        health_score -= warning_count * 5    # Moderate penalty for warnings
        health_score -= info_count * 0.5     # Light penalty for info
        health_score = max(0, min(100, health_score))
        
        # Adjust score based on element count (more elements = more potential issues)
        element_count = len(self.elements)
        if element_count > 200:
            # Normalize for large pages
            health_score = min(health_score + 10, 100)
        
        return {
            "health_score": int(health_score),
            "summary": {
                "critical": critical_count,
                "warning": warning_count,
                "info": info_count,
                "total_elements": len(self.elements),
                "interactive_elements": len(self._get_interactive_elements()),
                "unique_issues": len(unique_issues)
            },
            "issues": unique_issues,
            "timestamp": self.timestamp,
            "viewport": self.viewport
        }
    
    def print_report(self):
        """Print a human-readable report."""
        report = self.evaluate()
        
        print("\n" + "="*60)
        print(" LAYOUT INTEGRITY VALIDATION REPORT")
        print("="*60)
        
        score = report["health_score"]
        if score >= 80:
            color = "🟢"
            status = "Good"
        elif score >= 60:
            color = "🟡"
            status = "Fair"
        else:
            color = "🔴"
            status = "Poor"
        
        print(f"{color} Health Score: {score}/100 ({status})")
        
        summary = report["summary"]
        print(f"   Issues: {summary['critical']} Critical, "
              f"{summary['warning']} Warnings, "
              f"{summary['info']} Info")
        print(f"   Elements: {summary['total_elements']} total, "
              f"{summary['interactive_elements']} interactive")
        print("-" * 60)
        
        if not report["issues"] or (len(report["issues"]) == 1 and report["issues"][0]["element"] == "system"):
            print("✓ No layout issues detected.")
        else:
            issue_count = 0
            for issue in report["issues"]:
                # Skip system error if no other issues
                if issue["element"] == "system" and len(report["issues"]) > 1:
                    continue
                    
                issue_count += 1
                # Select appropriate emoji
                if issue["severity"] == "CRITICAL":
                    icon = "🔴"
                elif issue["severity"] == "WARNING":
                    icon = "🟡"
                else:
                    icon = "🔵"
                
                confidence = issue.get("confidence", 1.0)
                confidence_str = f"[{int(confidence*100)}%] " if confidence < 0.95 else ""
                
                print(f"{icon} [{issue['severity']}] {confidence_str}{issue['category']}")
                print(f"   {issue['message']}")
                print(f"   Element: {issue['element']}")
                if issue.get("data"):
                    for k, v in issue["data"].items():
                        if k != "_debug":
                            print(f"   {k}: {v}")
                print()
            
            if issue_count == 0:
                print("✓ No layout issues detected.")
        
        print("="*60)
        
        # Provide interpretation
        if score >= 80:
            print("✓ Layout appears stable and well-structured.")
        elif score >= 60:
            print("⚠ Layout has some issues but is generally functional.")
        else:
            print("✗ Layout has significant issues that may affect usability.")
        
        print("="*60)