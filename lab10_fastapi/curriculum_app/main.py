"""Application 1: curriculum database question answering."""

import json
import logging
import mimetypes
import os
import sqlite3
import sys
import time
from pathlib import Path
from contextlib import asynccontextmanager, contextmanager
from logging.handlers import RotatingFileHandler

import requests
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, Settings, settings

# เชื่อม Lab 10 -> Lab 8B: ใช้ open_db และ guard_sql; model_service เรียก Ollama /api/chat.
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ["LAB8_OLLAMA_URL"] = settings.ollama_url
os.environ["LAB8_MODEL_TEXT"] = settings.ollama_model
from ocr_system import lab8b_curriculum_db as lab8b  # noqa: E402

from .database import CurriculumDatabase, resolve_database  # noqa: E402
from .model_service import (  # noqa: E402
    InferenceResponseError, InferenceUnavailable, QueryExecutionError, QwenTextToSQL,
)
from .schemas import (  # noqa: E402
    AskRequest, AskResponse, CourseCreate, CourseResponse, HealthResponse,
)


@contextmanager
def configure_logging(config: Settings | None = None):
    """เปิด JSONL ตาม Settings เฉพาะช่วงแอปทำงาน แล้วคืน logger/ปิดไฟล์เมื่อจบ.

    ไม่แก้ handlers ของ Uvicorn; ซ้อน context เดิมได้โดยไม่เพิ่ม file handler ซ้ำ.
    Paths อิง PROJECT_ROOT จึงไม่ขึ้นกับ working directory ของผู้เริ่ม server.
    """
    config = config if config is not None else settings
    if not config.log_enabled:
        yield
        return

    log_dir = Path(config.log_dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = PROJECT_ROOT / log_dir
    log_dir = log_dir.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    registrations = []
    try:
        for suffix, filename in (
            ("observations", "lab10_planner.jsonl"),
            ("performance", "lab10_performance.jsonl"),
        ):
            logger = logging.getLogger(f"{__package__}.model_service.{suffix}")
            if any(getattr(handler, "_curriculum_file_log", False) for handler in logger.handlers):
                continue
            handler = RotatingFileHandler(
                log_dir / filename, maxBytes=1048576, backupCount=2,
                encoding="utf-8", delay=True,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler._curriculum_file_log = True
            registrations.append((logger, handler, logger.level, logger.propagate))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        yield
    finally:
        # คืนเฉพาะ resources ที่ context นี้สร้าง; ไม่ปิด handler ของผู้เรียกอื่น.
        for logger, handler, previous_level, previous_propagate in reversed(registrations):
            logger.removeHandler(handler)
            try:
                handler.close()
            finally:
                logger.setLevel(previous_level)
                logger.propagate = previous_propagate


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup เปิด logging; shutdown/exception ปิด handlers ผ่าน finally ของ context."""
    with configure_logging():
        yield


STATIC_DIR = PROJECT_ROOT / "lab11(frontend)" / "static"
app = FastAPI(
    title=f"{settings.app_name} — Curriculum",
    description="Qwen text-to-SQL + SQLite curriculum application",
    version="1.0.0",
    lifespan=lifespan,
)
# Ensure JavaScript is served correctly even with Windows MIME registry overrides.
mimetypes.init()
mimetypes.add_type("text/javascript", ".js")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
database = CurriculumDatabase(lab8b, settings.db_path, settings.max_rows)
model = QwenTextToSQL(settings, lab8b)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", response_model=HealthResponse)
def health() -> dict:
    db_ready = settings.db_path.exists()
    ollama_ready = model.available()
    return {
        "status": "ok" if db_ready and ollama_ready else "degraded",
        "database": str(settings.db_path),
        "database_ready": db_ready,
        "model": settings.ollama_model,
        "ollama_ready": ollama_ready,
        "lab8b_module": str(Path(lab8b.__file__).resolve()),
    }


def select_database(program: str | None, track: str | None) -> CurriculumDatabase:
    if program is None:
        if track is not None:
            raise HTTPException(status_code=422, detail="program is required with track")
        return database
    try:
        return resolve_database(lab8b, settings, program, track)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/curricula")
def curricula() -> dict:
    return {"programs": model.catalog.programs()}


@app.get("/api/study-plan")
def study_plan(
    program: str, year: int = Query(ge=1), semester: int = Query(ge=1, le=3),
    track: str | None = None,
) -> list[dict]:
    selected_database = select_database(program, track)
    try:
        return selected_database.study_plan(year, semester)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/course-description")
def course_description(courseid: str) -> dict:
    try:
        course = database.course_description(courseid, settings.db_paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@app.get("/api/program")
def get_program(program: str | None = None, track: str | None = None) -> dict:
    selected_database = select_database(program, track)
    try:
        program = selected_database.program()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if program is None:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลหลักสูตร")
    return program


@app.get("/api/courses", response_model=list[CourseResponse])
def get_courses(
    program: str | None = None,
    track: str | None = None,
    search: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    try:
        return select_database(program, track).courses(search, limit, offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/courses", response_model=CourseResponse,
          status_code=status.HTTP_201_CREATED)
def post_course(
    course: CourseCreate, program: str | None = None, track: str | None = None,
) -> dict:
    try:
        return select_database(program, track).create_course(course.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="รหัสวิชานี้มีอยู่แล้ว") from exc


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest) -> dict:
    started = time.perf_counter()
    try:
        answer = model.ask(
            # การเทียบใช้ targets ในข้อความ; ฟอร์มไม่บังคับให้เปิด DB ที่ไม่ได้ใช้ตอบ.
            None if model.is_program_comparison(request.question) else select_database(request.program, request.track), request.question,
            program=request.program, track=request.track,
        )
        # จับเวลาหลัง ask() จบทุกครั้ง รวมคำตอบจาก cache; ไม่เก็บเวลาเก่าใน cache.
        return {**answer, "processing_ms": round((time.perf_counter() - started) * 1000, 3)}
    # Planner/query ใช้ deadline ร่วมกัน และแยกความผิดพลาดของบริการจากคำถามผู้ใช้.
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="คำถามนี้ใช้เวลาเกินกำหนด กรุณาลองใหม่หรือแบ่งคำถาม") from exc
    except InferenceResponseError as exc:
        raise HTTPException(status_code=502, detail="โมเดลส่งคำตอบผิดรูปแบบ กรุณาลองใหม่") from exc
    except InferenceUnavailable as exc:
        raise HTTPException(status_code=503, detail="ติดต่อ Ollama ไม่ได้") from exc
    except QueryExecutionError as exc:
        raise HTTPException(status_code=500, detail="ค้นข้อมูลหลักสูตรไม่สำเร็จ") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="ติดต่อ Ollama ไม่ได้") from exc
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
