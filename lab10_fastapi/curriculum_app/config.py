"""Curriculum App configuration loaded from curriculum_app/.env."""

import json
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


def _env_bool(name: str, default: bool = False) -> bool:
    """อ่าน flag แบบชัดเจน; ไม่ตีความข้อความ 'false' เป็น True แบบ bool(str)."""
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false, 1/0, yes/no or on/off")

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


# ชื่อเรียกอยู่จุดเดียว; รหัสและชื่อเต็มของหลักสูตรยังมาจาก db_paths และ metadata ใน DB.
PROGRAM_ALIASES = {
    "IT": ("ไอที",),
    "DSBA": ("ดีเอสบีเอ",),
    "BIT": ("บีไอที",),
    "AIT": ("เอไอที",),
    "GENED": ("เจนเอ็ด", "ศึกษาทั่วไป", "หมวดศึกษาทั่วไป"),
}


def _program_aliases() -> dict[str, tuple[str, ...]]:
    """เพิ่ม/แทนชื่อเรียกผ่าน JSON ใน .env โดยไม่กระจาย regex ไปตาม planner."""
    aliases = dict(PROGRAM_ALIASES)
    raw = os.getenv("CURRICULUM_PROGRAM_ALIASES")
    if raw:
        configured = json.loads(raw)
        if not isinstance(configured, dict):
            raise ValueError("CURRICULUM_PROGRAM_ALIASES must be a JSON object")
        aliases.update(configured)
    return aliases


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
    program_aliases: dict[str, tuple[str, ...]] = field(default_factory=_program_aliases)
    ollama_url: str = os.getenv("CURRICULUM_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CURRICULUM_OLLAMA_MODEL", "qwen3:4b")
    request_timeout: int = int(os.getenv("CURRICULUM_REQUEST_TIMEOUT", "180"))
    max_rows: int = int(os.getenv("CURRICULUM_MAX_ROWS", "100"))
    # Metrics ใน API ทำงานเสมอ; flag นี้ควบคุมเฉพาะการเขียน JSONL ข้าม restart.
    log_enabled: bool = field(default_factory=lambda: _env_bool("CURRICULUM_LOG_ENABLED"))
    log_dir: Path = field(
        default_factory=lambda: _project_path(os.getenv("CURRICULUM_LOG_DIR", "work"))
    )

    def __post_init__(self):
        # เก็บเฉพาะรหัสที่ระบบมีจริง; alias ที่ชนกันให้ catalog คืนความกำกวมแทนการเดา.
        programs = {str(code).strip().upper() for code in self.db_paths}
        aliases = {}
        for code, values in self.program_aliases.items():
            code = str(code).strip().upper()
            if code not in programs:
                continue
            if not isinstance(values, (list, tuple)) or any(not isinstance(value, str) for value in values):
                raise ValueError("Program aliases must be arrays of strings")
            aliases[code] = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
        object.__setattr__(self, "program_aliases", aliases)

settings = Settings()
