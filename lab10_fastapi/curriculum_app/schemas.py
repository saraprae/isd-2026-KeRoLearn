"""Curriculum App HTTP request and response schemas."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# 
class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    program: str = Field(min_length=2)
    track: str | None = None


class Citation(BaseModel):
    """เลขหน้าที่เก็บกับข้อมูลต้นทาง; ยังไม่ใช่เลขหน้า PDF หรือ URL ของเอกสาร."""
    source: Literal["course", "study_plan", "program", "prerequisite"]
    pages: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1)
    program: str | None = None
    track: str | None = None
    course_code: str | None = None
    year: int | None = None
    semester: int | None = None


class AskPerformance(BaseModel):
    """เวลาของ request ปัจจุบัน; stages เป็นเวลาที่ไม่ซ้อนกัน หน่วยมิลลิวินาที."""
    total_ms: float = Field(ge=0)
    stages_ms: dict[str, Annotated[float, Field(ge=0)]]
    plan_source: Literal["unknown", "preflight", "rules", "qwen", "plan_cache",
                         "short_plan_cache", "answer_cache"]
    intent: str | None = None
    answer_cache_hit: bool = False
    answer_cache_checked: bool = False
    plan_cache_hit: bool = False
    qwen_calls: int = Field(default=0, ge=0)
    query_calls: int = Field(default=0, ge=0)
    citation_query_calls: int = Field(default=0, ge=0)
    ollama_ms: dict[str, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    outcome: Literal["success", "error"] = "success"
    error_type: str | None = None
    planning_diagnostics: dict[str, Any] = Field(default_factory=dict)


class AskResponse(BaseModel):
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    # ค่าเริ่มต้นทำให้คำตอบเดิมที่มีเพียงสี่ฟิลด์ยังผ่าน validation.
    citations: list[Citation] = Field(default_factory=list)
    processing_ms: float | None = Field(default=None, ge=0)
    performance: AskPerformance | None = None

# ข้อมูลจริงบางแถวมี credits = NULL และ AIT มีรหัส PLACEHOLDER_060464XX จึงไม่ผ่านเงื่อนไขของ CourseCreate และทำให้ GET รายวิชาเกิด response validation error
class CourseCreate(BaseModel):
    code: str = Field(pattern=r"^\d{8}$")
    name_th: str = Field(min_length=1, max_length=300)
    name_en: str | None = Field(default=None, max_length=300)
    credits: int = Field(ge=0, le=12)
    lecture_h: int | None = Field(default=None, ge=0, le=60)
    lab_h: int | None = Field(default=None, ge=0, le=60)
    self_h: int | None = Field(default=None, ge=0, le=60)
    description_th: str | None = None

# แยก schema สำหรับอ่านรายวิชาออกจาก schema สำหรับเพิ่มรายวิชา
# คง CourseCreate เดิมเพื่อให้การเพิ่มข้อมูลใหม่ยังตรวจเข้มเหมือนเดิม การแก้นี้ช่วยให้ API อ่านข้อมูลที่มีอยู่ได้ ส่วนข้อมูล placeholder ควรตรวจแก้ที่ต้นทางแยกต่างหาก
class CourseResponse(BaseModel):
        code: str
        name_th: str | None = None
        name_en: str | None = None
        credits: int | None = None
        lecture_h: int | None = None
        lab_h: int | None = None
        self_h: int | None = None
        description_th: str | None = None


class HealthResponse(BaseModel):
    status: str
    database: str
    database_ready: bool
    model: str
    ollama_ready: bool
    lab8b_module: str
