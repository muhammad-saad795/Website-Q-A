# Layout Validator - Technical Documentation

## Overview
Production-grade Python module that validates web page layouts from snapshot data, detecting genuine layout bugs while ignoring intentional design patterns.

## Key Features

### 🎯 Smart Detection
- **Distinguishes between bugs and design choices**
  - Ignores off-canvas sidebars/menus (common mobile pattern)
  - Doesn't flag below-the-fold content (vertical scrolling is normal!)
  - Recognizes icon buttons vs. text buttons for touch target validation

### 🔍 Validation Checks

#### 1. Horizontal Overflow
Detects elements extending beyond viewport width (horizontal scrolling is almost always a bug).
```
✅ Ignores: Off-canvas sidebars, drawers, hidden menus
❌ Flags: Content boxes, images, containers overflowing right edge
```

#### 2. Broken Interactive Elements
Finds buttons/links that are completely inaccessible to users.
```
❌ Zero-size interactive elements
❌ Interactive elements with collapsed layouts
✅ Ignores: Hidden menu items in off-canvas drawers
```

#### 3. Text Rendering Issues
Detects text that may be clipped or not rendering properly.
```
❌ Long text in tiny containers with overflow:hidden
❌ Text elements with suspicious dimensions
```

#### 4. Fixed Position Issues
Checks for fixed/sticky elements that overflow viewport.
```
❌ Fixed headers/footers that extend beyond screen
✅ Ignores: Off-canvas navigation panels
```

#### 5. Touch Target Validation (Mobile Only)
Ensures interactive elements are large enough for touch input.
```
Critical: < 20x20px (way too small)
Info: 20-44px (below recommended but usable)
Different thresholds for icon buttons vs. text buttons
```

## Usage

### Command Line
```bash
# Basic usage
python3 layout_validator.py result.json

# Save detailed report
python3 layout_validator.py result.json validation_report.json
```

### Programmatic Usage
```python
from layout_validator import validate_layout_file, LayoutValidator

# Validate file and get report
report = validate_layout_file('result.json', 'output_report.json')

# Custom configuration
validator = LayoutValidator(config={
    'overflow_tolerance_px': 10,
    'min_interactive_size_px': 44,
    'min_icon_size_px': 20
})

# Validate specific snapshot
validator.validate_snapshot(snapshot_data, 'mobile')
report = validator.generate_report()
validator.print_detailed_report()
```

## Output Format

### Console Report
```
📋 LAYOUT VALIDATION REPORT
================================================================================

❌ Overall Status: FAIL

📊 Summary:
   Total Issues: 1
   🔴 Critical: 1
   ⚠️  Warnings: 0
   ℹ️  Info: 0

🔴 CRITICAL ISSUES (Must Fix)
================================================================================

1. [MOBILE] SMALL_TOUCH_TARGET
   Touch target too small: icon button is 16x16px (recommended: 44x44px minimum)
   Element: <button>.absolute.right-3.top-1/2
   Position: x=280, y=632
   Size: 16 x 16 px
   💡 Fix: Add padding or increase button size to meet WCAG touch target guidelines (44x44px).
```

### JSON Report
```json
{
  "status": "FAIL",
  "summary": {
    "total_issues": 1,
    "critical": 1,
    "warnings": 0,
    "info": 0
  },
  "by_category": {
    "SMALL_TOUCH_TARGET": 1
  },
  "issues": [
    {
      "severity": "CRITICAL",
      "category": "SMALL_TOUCH_TARGET",
      "message": "Touch target too small: icon button is 16x16px",
      "viewport": "mobile",
      "element": {
        "descriptor": "<button>.absolute.right-3.top-1/2",
        "tag": "button",
        "classes": ["absolute", "right-3", "top-1/2"],
        "rect": {"x": 280, "y": 632.5, "width": 16, "height": 16}
      },
      "details": {
        "width": 16,
        "height": 16,
        "is_icon": true
      },
      "recommendation": "Add padding or increase button size..."
    }
  ]
}
```

## Issue Categories

| Category | Severity | Description |
|----------|----------|-------------|
| `HORIZONTAL_OVERFLOW` | CRITICAL/WARNING | Elements extending beyond right viewport edge |
| `BROKEN_INTERACTIVE` | CRITICAL | Interactive elements with zero dimensions |
| `TEXT_CLIPPING` | WARNING | Text that may be cut off or hidden |
| `FIXED_OVERFLOW` | CRITICAL | Fixed/sticky elements overflowing viewport |
| `SMALL_TOUCH_TARGET` | CRITICAL/INFO | Touch targets below recommended size |

## Status Levels

- **PASS**: No critical issues, < 3 warnings
- **WARNING**: No critical issues, ≥ 3 warnings
- **FAIL**: Any critical issues found

## What Makes This Validator Smart

### Traditional validators flag:
- ❌ Off-canvas sidebars (-360px offset) → FALSE POSITIVE
- ❌ Below-the-fold content → FALSE POSITIVE  
- ❌ All small buttons equally → NOISY
- ❌ Negative positioning → FALSE POSITIVE

### This validator understands:
- ✅ Off-canvas panels are intentional design (position:fixed + negative x with sidebar ID/class)
- ✅ Vertical scrolling is normal (only checks horizontal overflow)
- ✅ Icon buttons can be smaller than text buttons (different thresholds)
- ✅ Negative positioning in off-canvas elements is expected

## Configuration Options

```python
config = {
    # Allow small positioning errors (px)
    'overflow_tolerance_px': 5,
    
    # Minimum touch target for text buttons (px)
    'min_interactive_size_px': 44,
    
    # Minimum size for icon buttons (px)
    'min_icon_size_px': 20
}
```

## Integration with Existing Workflow

Can be integrated into `controller.py`:
```python
from layout_validator import validate_layout_file

# After generating snapshots
result = loader.load_page(url)

# Validate layout
report = validate_layout_file('result.json')

# Check status
if report['status'] == 'FAIL':
    print(f"❌ Layout validation failed with {report['summary']['critical']} critical issues")
```

## Real-World Example

**Input**: Website with mobile hamburger menu (sidebar at x=-360)

**Old Validator Output**:
```
❌ 23 Issues Found
- 6 viewport overflow
- 6 negative positioning  
- 5 offscreen elements
- 6 small touch targets
```

**New Validator Output**:
```
❌ 1 Issue Found
- 1 critical: 16x16px button (too small for touch)

✅ Correctly ignored:
- Off-canvas sidebar (#page-sidebar at x=-360)
- Below-fold content (y > 812px)
- Icon buttons 20-44px (informational only)
```

## Recommendations Format

Each issue includes specific, actionable recommendations:
- "Add max-width: 100% to prevent horizontal overflow"
- "Increase button padding to meet 44x44px touch target"
- "Use text-overflow: ellipsis for clipped text"
- "Check CSS for missing width/height on collapsed element"

## License & Credits

Created for Website QA automation system.
Part of the AgentBased testing framework.
