"""Curriculum App configuration loaded from curriculum_app/.env."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
# curriculum_app -> lab10_fastapi -> project root
PROJECT_ROOT = APP_DIR.parents[1]
load_dotenv(APP_DIR / ".env")

# โค้ดนี้ใช้ตั้งค่าให้แอปรู้ว่า ฐานข้อมูลของแต่ละหลักสูตรและแผนเรียนอยู่ที่ไฟล์ไหน
# - DB_ROOT กำหนดโฟลเดอร์หลักที่เก็บฐานข้อมูล โดยอ่านจาก CURRICULUM_DB_ROOT ใน .env
# - DB_PATHS จับคู่หลักสูตรกับไฟล์ฐานข้อมูล เช่น IT + coop จะเลือก IT/coop/curriculum.db; AIT ใช้แผน default
# - Settings.db_paths เก็บ mapping นี้ไว้ให้ main.py ใช้เลือกฐานข้อมูลตามหลักสูตรและแผนที่ผู้ใช้ส่งมา

def _project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path

DB_ROOT = Path(os.getenv("CURRICULUM_DB_ROOT", "work/lab8b_run")).expanduser()
if not DB_ROOT.is_absolute():
    DB_ROOT = (PROJECT_ROOT / DB_ROOT).resolve()


DB_PATHS = {
    "IT": {
        "coop": DB_ROOT / "IT/coop/curriculum.db",
        "nocoop": DB_ROOT / "IT/nocoop/curriculum.db",
    },
    "DSBA": {
        "coop": DB_ROOT / "DSBA/coop/curriculum.db",
        "nocoop": DB_ROOT / "DSBA/nocoop/curriculum.db",
    },
    "BIT": {
        "coop": DB_ROOT / "BIT/coop/curriculum.db",
        "nocoop": DB_ROOT / "BIT/nocoop/curriculum.db",
    },
    "AIT": {
        "default": DB_ROOT / "AIT/curriculum.db",
    },
    "GENED": {
        "default": DB_ROOT / "GENED/curriculum.db",
    },
}


@dataclass(frozen=True)
class Settings:
    db_path: Path = field(
        default_factory=lambda: _project_path(
            os.getenv(
                "CURRICULUM_DB_PATH",
                str(DB_PATHS["DSBA"]["nocoop"]),
            )
        )
    )
    app_name: str = os.getenv("CURRICULUM_APP_NAME", "Curriculum Book Assistant")
    db_paths: dict[str, dict[str, Path]] = field(
        default_factory=lambda: DB_PATHS
    )
    ollama_url: str = os.getenv("CURRICULUM_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CURRICULUM_OLLAMA_MODEL", "qwen3:4b")
    request_timeout: int = int(os.getenv("CURRICULUM_REQUEST_TIMEOUT", "180"))
    max_rows: int = int(os.getenv("CURRICULUM_MAX_ROWS", "100"))

settings = Settings()

