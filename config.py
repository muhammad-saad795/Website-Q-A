import os
from pathlib import Path
from typing import Dict, Optional, Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

class GeminiSettings(BaseModel):
    api_key: Optional[str] = Field(None, alias="api_key")
    model: str = "gemini-2.0-flash"
    max_steps: int = 15

class ViewportSettings(BaseModel):
    width: int
    height: int

class BrowserSettings(BaseSettings):
    headless: bool = True
    max_load_seconds: int = 60
    nav_timeout_ms: int = 30000
    settle_time_ms: int = 1000
    retries: int = 3
    viewports: Dict[str, ViewportSettings] = {
        "desktop": ViewportSettings(width=1920, height=1080),
        "mobile": ViewportSettings(width=375, height=812)
    }

class CrawlerSettings(BaseModel):
    max_pages: int = 50
    max_depth: int = 3
    output_dir: str = "crawl_results"

class Settings(BaseSettings):
    """
    Main Settings class.
    Priority: 
    1. Environment Variables (e.g., GEMINI_API_KEY)
    2. config.yaml
    3. Defaults defined in code
    """
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    crawler: CrawlerSettings = Field(default_factory=CrawlerSettings)
    logging_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_nested_delimiter='__',
        env_prefix='',
        extra='ignore'
    )

    @classmethod
    def load_prod_config(cls) -> "Settings":
        config_path = Path("config.yaml")
        yaml_data = {}
        
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    yaml_data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"⚠️ Warning: Could not read config.yaml: {e}. using defaults.")
        
        # Priority mapping for common env vars that might not follow nested naming
        obj = cls(**yaml_data)
        
        # Override with standard env vars if set
        primary_key = os.getenv("GEMINI_API_KEY")
        if primary_key:
            obj.gemini.api_key = primary_key
            
        return obj

# Global settings instance
try:
    settings = Settings.load_prod_config()
except Exception as e:
    print(f"\n❌ Configuration Error: {e}")
    print("Please check your config.yaml or environment variables.\n")
    raise SystemExit(1)

