"""Curriculum App configuration loaded from curriculum_app/.env."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
load_dotenv(APP_DIR / ".env")


def _project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("CURRICULUM_APP_NAME", "Curriculum Book Assistant")
    db_path: Path = _project_path(
        os.getenv("CURRICULUM_DB_PATH", "work/lab8b_run/AIT/curriculum.db")
    )
    ollama_url: str = os.getenv("CURRICULUM_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CURRICULUM_OLLAMA_MODEL", "qwen3:4b")
    request_timeout: int = int(os.getenv("CURRICULUM_REQUEST_TIMEOUT", "180"))
    max_rows: int = int(os.getenv("CURRICULUM_MAX_ROWS", "100"))


settings = Settings()

