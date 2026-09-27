"""Application 1: curriculum database question answering."""

import json
import os
import sqlite3
import sys
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import PROJECT_ROOT, settings

# เชื่อม Lab 10 -> Lab 8B โดยตรง: ใช้ open_db, guard_sql และ ollama_generate เดิม
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ["LAB8_OLLAMA_URL"] = settings.ollama_url
os.environ["LAB8_MODEL_TEXT"] = settings.ollama_model
from ocr_system import lab8b_curriculum_db as lab8b  # noqa: E402

from .database import CurriculumDatabase  # noqa: E402
from .model_service import QwenTextToSQL  # noqa: E402
from .schemas import (  # noqa: E402
    AskRequest, AskResponse, CourseCreate, CourseResponse, HealthResponse,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
app = FastAPI(
    title=f"{settings.app_name} — Curriculum",
    description="Qwen text-to-SQL + SQLite curriculum application",
    version="1.0.0",
)
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


@app.get("/api/program")
def get_program() -> list[dict]:
    try:
        programs = database.programs(settings.db_paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not programs:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลหลักสูตร")
    return programs


def select_database(program: str | None, track: str | None) -> CurriculumDatabase:
    selected_database = database
    if program is None and track is not None:
        raise HTTPException(status_code=422, detail="กรุณาระบุ program เมื่อเลือก track")
    if program is not None:
        program = program.strip().upper()
        tracks = settings.db_paths.get(program)
        if tracks is None:
            raise HTTPException(status_code=422, detail="หลักสูตรต้องเป็น IT, DSBA, BIT, AIT หรือ GENED")
        selected_track = track.strip().lower() if track is not None else (
            "nocoop" if "nocoop" in tracks else "default"
        )
        if selected_track not in tracks:
            raise HTTPException(
                status_code=422,
                detail=f"แผนของ {program} ต้องเป็น: {', '.join(tracks)}",
            )
        selected_database = CurriculumDatabase(lab8b, tracks[selected_track], settings.max_rows)
    return selected_database


@app.get("/api/courses", response_model=list[CourseResponse])
def get_courses(
    program: str | None = Query(default=None, description="IT, DSBA, BIT, AIT or GENED"),
    track: str | None = Query(default=None, description="coop, nocoop or default (AIT and GENED)"),
    search: str = Query(default="", max_length=100),
) -> list[dict]:
    selected_database = select_database(program, track)
    try:
        return selected_database.courses(search, limit=settings.max_rows)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/descriptions")
def get_description(
    courseid: str = Query(..., pattern=r"^[0-9]{8}$", description="รหัสวิชา 8 หลัก"),
) -> dict:
    try:
        result = database.course_description(courseid, settings.db_paths)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="ไม่พบรหัสวิชานี้")
    return result


@app.get("/api/study-plan")
def get_study_plan(
    program: str = Query(..., description="IT, DSBA, BIT, AIT or GENED"),
    track: str = Query(..., description="coop, nocoop or default (AIT and GENED)"),
    year: int = Query(..., ge=1, le=4, description="ปีการศึกษา 1–4"),
    semester: int = Query(..., ge=1, le=3, description="1, 2 หรือ 3 (ภาคฤดูร้อน)"),
) -> list[dict]:
    selected_database = select_database(program, track)
    try:
        return selected_database.study_plan(year, semester)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/courses", response_model=CourseResponse,
          status_code=status.HTTP_201_CREATED)
def post_course(course: CourseCreate) -> dict:
    try:
        return database.create_course(course.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="รหัสวิชานี้มีอยู่แล้ว") from exc


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest) -> dict:
    try:
        return model.ask(database, request.question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="ติดต่อ Ollama ไม่ได้") from exc
    except (ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
