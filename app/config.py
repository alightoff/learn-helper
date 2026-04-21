from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_DATABASE_URL = f"sqlite:///{(DEFAULT_DATA_DIR / 'app.db').as_posix()}"


class Settings(BaseSettings):
    app_name: str = "Learn Helper"
    app_env: str = "development"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True
    database_url: str = DEFAULT_DATABASE_URL
    data_dir: Path = Field(default=DEFAULT_DATA_DIR)

    model_config = SettingsConfigDict(
        env_prefix="LEARN_HELPER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def project_root(self) -> Path:
        return BASE_DIR

    @property
    def templates_dir(self) -> Path:
        return APP_DIR / "templates"

    @property
    def static_dir(self) -> Path:
        return APP_DIR / "static"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def course_uploads_dir(self) -> Path:
        return self.uploads_dir / "courses"

    @property
    def previews_dir(self) -> Path:
        return self.data_dir / "previews"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_storage(self) -> None:
        for path in (
            self.data_dir,
            self.uploads_dir,
            self.course_uploads_dir,
            self.previews_dir,
            self.exports_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
