"""Curriculum App HTTP request and response schemas."""

from typing import Any

from pydantic import BaseModel, Field

# 
class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    program: str = Field(min_length=2)
    track: str | None = None


class AskResponse(BaseModel):
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str

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

