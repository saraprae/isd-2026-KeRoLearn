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

# edition คือฉบับหลักสูตร ไม่ใช่ชั้นปีเรียน; default เป็น ID เดิมสำหรับ client เก่า.
# ปี/ป้ายของฐาน default แยกตามหลักสูตรตามข้อมูลที่ผู้ใช้ระบุ ไม่เดาจากชื่อโฟลเดอร์.
# ปีของชุดเพิ่มเติมยืนยันได้จาก ID ใน manifest ของ Lab 8B; ยังไม่รับรองจาก PDF.
# เพิ่มฉบับ/ฉบับแก้ไขของปีเดียวกันได้ด้วย ID ใหม่ เช่น "2560-r2" และ label ที่ชัดเจน.
EDITION_DB_PATHS = {
    "2560": {
        program: {track: DB_ROOT / f"{program}_2560/{track}/curriculum.db"
                  for track in ("coop", "nocoop")}
        for program in ("IT", "DSBA", "BIT")
    },
    "2559": {"GENED": {"default": DB_ROOT / "GENED_2559/curriculum.db"}},
    "2564": {"GENED": {"default": DB_ROOT / "GENED_2564/curriculum.db"}},
}
EDITION_METADATA = {
    "default": {
        "label": "ไม่ระบุปี", "year": None, "year_source": None,
        "programs": {
            **{program: {"label": "พ.ศ. 2565", "year": 2565, "year_source": "user_provided"}
               for program in ("IT", "DSBA", "BIT")},
            "AIT": {"label": "พ.ศ. 2566", "year": 2566, "year_source": "user_provided"},
            # data/input/GENED.pdf เป็นฉบับ 2566; hash ตรง GE66_Th_Ed240501 และ export 98 หน้า.
            "GENED": {"label": "พ.ศ. 2566", "year": 2566, "year_source": "user_provided"},
        },
    },
    **{str(year): {"label": f"พ.ศ. {year}",
                   "year": year, "year_source": "source_dataset_id"}
       for year in (2559, 2560, 2564)},
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


def _document_sources() -> dict:
    """Optional, reviewed document/page mappings keyed by program:edition[:track]."""
    sources = json.loads(os.getenv("CURRICULUM_DOCUMENT_SOURCES", "{}"))
    if not isinstance(sources, dict) or any(
        not isinstance(key, str) or len(key.split(":")) not in {2, 3} or
        not isinstance(value, dict) for key, value in sources.items()
    ):
        raise ValueError("CURRICULUM_DOCUMENT_SOURCES must map program:edition[:track] to objects")
    return sources


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
    # ใช้ร่วมกันทั้ง API/catalog/UI; โหลด lexicon เฉพาะฐานที่ถูกเลือก.
    edition_db_paths: dict[str, dict[str, dict[str, Path]]] = field(
        default_factory=lambda: EDITION_DB_PATHS
    )
    edition_metadata: dict[str, dict] = field(default_factory=lambda: EDITION_METADATA)
    active_edition: str = "default"
    program_aliases: dict[str, tuple[str, ...]] = field(default_factory=_program_aliases)
    ollama_url: str = os.getenv("CURRICULUM_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.getenv("CURRICULUM_OLLAMA_MODEL", "qwen3:4b")
    ollama_keep_alive: str = field(default_factory=lambda: os.getenv("CURRICULUM_OLLAMA_KEEP_ALIVE", "10m"))
    ollama_output_tokens: int = field(default_factory=lambda: int(os.getenv("CURRICULUM_OLLAMA_OUTPUT_TOKENS", "128")))
    ollama_output_retry_tokens: int = field(default_factory=lambda: int(os.getenv("CURRICULUM_OLLAMA_OUTPUT_RETRY_TOKENS", "256")))
    ollama_warmup: bool = field(default_factory=lambda: _env_bool("CURRICULUM_OLLAMA_WARMUP"))
    planner_example_limit: int = field(default_factory=lambda: int(os.getenv("CURRICULUM_PLANNER_EXAMPLE_LIMIT", "6")))
    planner_reuse_verified_search: bool = field(default_factory=lambda: _env_bool("CURRICULUM_PLANNER_REUSE_VERIFIED_SEARCH", True))
    classifier_mode: str = field(default_factory=lambda: os.getenv("CURRICULUM_CLASSIFIER_MODE", "shadow").strip().lower())
    classifier_path: Path = field(default_factory=lambda: _project_path(os.getenv(
        "CURRICULUM_CLASSIFIER_PATH", "lab10_fastapi/curriculum_app/intent_classifier.json")))
    document_sources: dict = field(default_factory=_document_sources)
    source_export_root: Path = field(default_factory=lambda: _project_path(
        os.getenv("CURRICULUM_SOURCE_EXPORT_ROOT", "work/lab7b_run")))
    request_timeout: int = int(os.getenv("CURRICULUM_REQUEST_TIMEOUT", "180"))
    max_rows: int = int(os.getenv("CURRICULUM_MAX_ROWS", "100"))
    # Metrics ใน API ทำงานเสมอ; flag นี้ควบคุมเฉพาะการเขียน JSONL ข้าม restart.
    log_enabled: bool = field(default_factory=lambda: _env_bool("CURRICULUM_LOG_ENABLED"))
    log_dir: Path = field(
        default_factory=lambda: _project_path(os.getenv("CURRICULUM_LOG_DIR", "work"))
    )

    def __post_init__(self):
        for key, entry in self.document_sources.items():
            if not isinstance(key, str) or len(key.split(":")) not in {2, 3} or not isinstance(entry, dict):
                raise ValueError("Document sources must use program:edition[:track] keys")
            if entry.get("page_basis", "unknown") not in {"pdf", "printed", "unknown"}:
                raise ValueError("Document page_basis must be pdf, printed or unknown")
            for field_name in ("title", "pdf_path", "sha256", "pred_path", "markdown_path"):
                if field_name in entry and not isinstance(entry[field_name], str):
                    raise ValueError(f"Document {field_name} must be a string")
            mappings = entry.get("page_mapping", {})
            if not isinstance(mappings, dict):
                raise ValueError("Document page_mapping must be an object")
            for stored_page, mapping in mappings.items():
                if not str(stored_page).isdigit() or int(stored_page) < 1 or not isinstance(mapping, dict):
                    raise ValueError("Document page_mapping keys must be positive stored pages")
                if "pdf_page" in mapping and (type(mapping["pdf_page"]) is not int or mapping["pdf_page"] < 1):
                    raise ValueError("Mapped PDF pages must be positive integers")
                for field_name in ("printed_page", "section_name"):
                    if field_name in mapping and not isinstance(mapping[field_name], str):
                        raise ValueError(f"Mapped {field_name} must be a string")
                if "content_verified" in mapping and type(mapping["content_verified"]) is not bool:
                    raise ValueError("content_verified must be a reviewed boolean")
        if self.classifier_mode not in {"off", "shadow", "active"}:
            raise ValueError("CURRICULUM_CLASSIFIER_MODE must be off, shadow or active")
        if not 2 <= self.planner_example_limit <= 6:
            raise ValueError("CURRICULUM_PLANNER_EXAMPLE_LIMIT must be between 2 and 6")
        if not 64 <= self.ollama_output_tokens <= self.ollama_output_retry_tokens <= 1024:
            raise ValueError("Ollama output budgets must satisfy 64 <= initial <= retry <= 1024")
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
