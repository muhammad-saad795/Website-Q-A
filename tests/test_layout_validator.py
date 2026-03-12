from src.layout_validator import LayoutValidator


def _make_element(tag="div", x=0, y=0, width=100, height=50,
                  is_visible=True, is_interactive=False, position="static",
                  overflow="visible", classes=None, elem_id="", text=""):
    return {
        "tag": tag,
        "id": elem_id,
        "classes": classes or [],
        "text": text,
        "rect": {"x": x, "y": y, "width": width, "height": height},
        "computed": {
            "position": position,
            "overflow": overflow,
            "overflowX": overflow,
        },
        "flags": {
            "isVisible": is_visible,
            "isInteractive": is_interactive,
            "isInViewport": True,
            "isClickable": is_interactive,
        },
        "parent": {
            "tag": "body",
            "rect": {"x": 0, "y": 0, "width": 1920, "height": 5000},
            "computed": {"overflow": "visible", "overflowX": "visible"},
        },
    }


def _snapshot(vp_width, vp_height, elements):
    return {
        "viewport": {"width": vp_width, "height": vp_height},
        "elements": elements,
    }


class TestLayoutValidator:
    def test_no_issues_clean_page(self):
        v = LayoutValidator()
        snap = _snapshot(1920, 1080, [_make_element()])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        assert report["status"] == "PASS"
        assert report["summary"]["total_issues"] == 0

    def test_horizontal_overflow_detected(self):
        v = LayoutValidator()
        elem = _make_element(x=1800, width=200)
        snap = _snapshot(1920, 1080, [elem])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        overflow_issues = [i for i in report["issues"] if i["category"] == "HORIZONTAL_OVERFLOW"]
        assert len(overflow_issues) == 1

    def test_offcanvas_sidebar_not_flagged(self):
        v = LayoutValidator()
        elem = _make_element(x=-300, width=280, position="fixed",
                             classes=["sidebar"], elem_id="sidebar")
        snap = _snapshot(1920, 1080, [elem])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        assert report["summary"]["total_issues"] == 0

    def test_zero_size_interactive_critical(self):
        v = LayoutValidator()
        elem = _make_element(tag="button", width=0, height=0, is_interactive=True)
        snap = _snapshot(1920, 1080, [elem])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        broken = [i for i in report["issues"] if i["category"] == "BROKEN_INTERACTIVE"]
        assert len(broken) == 1
        assert broken[0]["severity"] == "CRITICAL"

    def test_small_touch_target_on_mobile(self):
        v = LayoutValidator()
        elem = _make_element(tag="button", width=15, height=15,
                             is_interactive=True, text="OK")
        snap = _snapshot(375, 812, [elem])
        v.validate_snapshot(snap, "mobile")
        report = v.generate_report()
        touch = [i for i in report["issues"] if i["category"] == "SMALL_TOUCH_TARGET"]
        assert len(touch) >= 1

    def test_text_clipping_warned(self):
        v = LayoutValidator()
        elem = _make_element(tag="p", width=20, height=10,
                             overflow="hidden", text="This is a very long piece of text that surely clips")
        snap = _snapshot(1920, 1080, [elem])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        clip = [i for i in report["issues"] if i["category"] == "TEXT_CLIPPING"]
        assert len(clip) == 1

    def test_fixed_overflow_detected(self):
        v = LayoutValidator()
        elem = _make_element(x=1800, width=200, position="fixed")
        snap = _snapshot(1920, 1080, [elem])
        v.validate_snapshot(snap, "desktop")
        report = v.generate_report()
        fixed = [i for i in report["issues"] if i["category"] == "FIXED_OVERFLOW"]
        assert len(fixed) == 1
