import os
from config import Settings


class TestConfig:
    def test_defaults_load(self):
        s = Settings.load()
        assert s.gemini.model == "gemini-2.5-flash"
        assert s.gemini.max_steps == 25
        assert s.openai.model == "gpt-4o"
        assert s.browser.headless is True
        assert s.browser.nav_timeout_ms == 30000
        assert s.api.port == 8000
        assert s.logging_level == "INFO"

    def test_browser_viewports(self):
        s = Settings.load()
        assert "desktop" in s.browser.viewports
        assert "mobile" in s.browser.viewports
        assert s.browser.viewports["desktop"].width == 1920
        assert s.browser.viewports["mobile"].width == 375

    def test_env_override_logging(self, monkeypatch):
        monkeypatch.setenv("LOGGING_LEVEL", "DEBUG")
        s = Settings.load()
        assert s.logging_level == "DEBUG"
