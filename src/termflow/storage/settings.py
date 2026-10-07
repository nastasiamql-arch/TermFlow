import os
from pathlib import Path

from pydantic import BaseModel, Field

from termflow.storage.paths import APPDATA


class Settings(BaseModel):
    provider: str = "openai"
    credential_name: str = "openai"
    base_url: str = ""
    model: str = ""
    selected_search_prompt: str = "builtin-search"
    selected_polish_prompt: str = "builtin-polish"
    timeout: int = Field(default=900, ge=30, le=1800)
    retries: int = Field(default=0, ge=0, le=10)
    search_chunks: int = Field(default=1, ge=1, le=20)
    search_model: str = ""
    polish_model: str = ""
    reuse_results: bool = True
    font_size: int = 12
    check_updates_on_startup: bool = True
    show_welcome: bool = True
    theme: str = "System"
    debug: bool = False


def settings_path() -> Path:
    return APPDATA / "settings.json"


def load_settings() -> Settings:
    try:
        settings = Settings.model_validate_json(settings_path().read_text("utf-8"))
        # 11 pt was the previous default and rendered too small on common displays.
        if settings.font_size == 11:
            settings.font_size = 12
        return settings
    except (OSError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
