"""Curriculum App configuration loaded from curriculum_app/.env."""

import os
from dataclasses import dataclass, field
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
        os.getenv("CURRICULUM_DB_PATH", "work/lab8b_run/DSBA/nocoop/curriculum.db")
    )
    # Group databases by curriculum and track. AIT has one unsplit plan.
    # Keep db_path above for endpoints that still use a single database.
    db_paths: dict[str, dict[str, Path]] = field(default_factory=lambda: {
        program: {
            track: _project_path(os.getenv(
                f"CURRICULUM_DB_PATH_{program}_{track.upper()}",
                os.getenv(f"CURRICULUM_DB_PATH_{program}", path)
                if track in ("nocoop", "default") else path,
            ))
            for track, path in tracks.items()
        }
        for program, tracks in {
            "IT": {
                "coop": "work/lab8b_run/IT/coop/curriculum.db",
                "nocoop": "work/lab8b_run/IT/nocoop/curriculum.db",
            },
            "DSBA": {
                "coop": "work/lab8b_run/DSBA/coop/curriculum.db",
                "nocoop": "work/lab8b_run/DSBA/nocoop/curriculum.db",
            },
            "BIT": {
                "coop": "work/lab8b_run/BIT/coop/curriculum.db",
                "nocoop": "work/lab8b_run/BIT/nocoop/curriculum.db",
            },
            "AIT": {"default": "work/lab8b_run/AIT/curriculum.db"},
            "GENED": {"default": "work/lab8b_run/GENED/curriculum.db"}
        }.items()
    })
    ollama_url: str = os.getenv("CURRICULUM_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CURRICULUM_OLLAMA_MODEL", "qwen3:4b")
    request_timeout: int = int(os.getenv("CURRICULUM_REQUEST_TIMEOUT", "180"))
    max_rows: int = int(os.getenv("CURRICULUM_MAX_ROWS", "100"))


settings = Settings()

