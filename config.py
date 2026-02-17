import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class GeminiSettings(BaseModel):
    api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model: str = "gemini-2.5-flash"
    ## REMOVED the max step limit for the agent , but it needs proper testing and trust
    # max_steps: int = 15

class Viewport(BaseModel):
    width: int
    height: int

class BrowserSettings(BaseModel):
    headless: bool = True
    max_load_seconds: int = 60
    nav_timeout_ms: int = 30000
    settle_time_ms: int = 1000
    retries: int = 3
    deep_analysis: bool = False
    viewports: Dict[str, Viewport] = {
        "desktop": Viewport(width=1920, height=1080),
        "mobile": Viewport(width=375, height=812)
    }

class CrawlerSettings(BaseModel):
    max_pages: Optional[int] = None
    max_depth: Optional[int] = None
    output_dir: str = "crawl_results"

class Settings(BaseSettings):
    gemini: GeminiSettings = GeminiSettings()
    browser: BrowserSettings = BrowserSettings()
    crawler: CrawlerSettings = CrawlerSettings()
    logging_level: str = "INFO"

    @classmethod
    def load(cls):
        path = Path("config.yaml")
        data = {}
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        return cls(**data)

settings = Settings.load()
