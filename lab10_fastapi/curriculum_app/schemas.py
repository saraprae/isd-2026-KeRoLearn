"""Curriculum App HTTP request and response schemas."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 
class StudentTerm(BaseModel):
    """รายวิชาที่ผู้ใช้วางไว้ในหนึ่งเทอม; ไม่ถือว่าเรียนผ่านแล้ว."""
    model_config = ConfigDict(extra="forbid")
    year: Annotated[int, Field(strict=True, ge=1, le=8)]
    semester: Annotated[int, Field(strict=True, ge=1, le=3)]
    course_codes: list[Annotated[str, Field(pattern=r"^[0-9]{8}$")]] = Field(min_length=1, max_length=100)


class StudentContext(BaseModel):
    """ข้อมูลผู้ใช้สำหรับตรวจ/ร่างแผน; เพดานเป็นข้อสมมติ ไม่ใช่ระเบียบทางการ."""
    model_config = ConfigDict(extra="forbid")
    student_plan: list[StudentTerm] | None = Field(default=None, max_length=24)
    completed_courses: list[Annotated[str, Field(pattern=r"^[0-9]{8}$")]] = Field(default_factory=list, max_length=500)
    max_credits_per_term: Annotated[int, Field(strict=True, ge=1, le=60)] = 30
    completed_grades: dict[Annotated[str, Field(pattern=r"^[0-9]{8}$")], Annotated[float, Field(ge=0, le=4)]] = Field(default_factory=dict)
    approved_equivalences: list[Annotated[str, Field(pattern=r"^[0-9]{8}$")]] = Field(default_factory=list, max_length=500)
    category_allocations: dict[Annotated[str, Field(pattern=r"^[0-9]{8}$")], Literal["specialized", "general_education", "free_elective"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_terms(self):
        terms = [(t.year, t.semester) for t in self.student_plan or []]
        if len(terms) != len(set(terms)):
            raise ValueError("กรุณารวมรายวิชาของปี/เทอมเดียวกันไว้ในรายการเดียว")
        return self


class AskRequest(StudentContext):
    page: int | None = Field(default=None, ge=1)
    page_size: int | None = Field(default=None, ge=1, le=1000)
    question: str = Field(min_length=2, max_length=500)
    program: str = Field(min_length=2)
    track: str | None = None
    edition: str | None = Field(default=None, min_length=1, max_length=40)


class CitationPage(BaseModel):
    """Keep the stored page, PDF index and printed label distinct, including unknowns."""
    stored_page: Annotated[int, Field(strict=True, gt=0)]
    page_basis: Literal["pdf", "printed", "unknown"] = "unknown"
    pdf_page: Annotated[int, Field(strict=True, gt=0)] | None = None
    printed_page: str | None = None
    section_name: str | None = None
    pdf_url: str | None = None
    verification_status: Literal["metadata_only", "content_verified", "unknown"] = "unknown"


class Citation(BaseModel):
    """Legacy pages plus explicit provenance; no automatic printed-page offsets."""
    source: Literal["course", "study_plan", "program", "prerequisite", "elective_slot"]
    pages: list[Annotated[int, Field(strict=True, gt=0)]] = Field(min_length=1)
    program: str | None = None
    track: str | None = None
    edition: str | None = None
    edition_label: str | None = None
    course_code: str | None = None
    year: int | None = None
    semester: int | None = None
    citation_id: str | None = None
    document_id: str | None = None
    document_title: str | None = None
    page_basis: Literal["pdf", "printed", "unknown"] = "unknown"
    evidence_source: Literal["course", "plan_item", "program", "prerequisite", "elective_slot", "unknown"] = "unknown"
    evidence_scope: Literal["page_set", "chunk", "unknown"] = "unknown"
    section_name: str | None = None
    supports: list[str] = Field(default_factory=list)
    verification_status: Literal["metadata_only", "content_verified", "unknown"] = "unknown"
    page_references: list[CitationPage] = Field(default_factory=list)


class AskPerformance(BaseModel):
    """เวลาของ request ปัจจุบัน; stages เป็นเวลาที่ไม่ซ้อนกัน หน่วยมิลลิวินาที."""
    total_ms: float = Field(ge=0)
    stages_ms: dict[str, Annotated[float, Field(ge=0)]]
    plan_source: Literal["unknown", "preflight", "rules", "qwen", "qwen_sql", "classifier", "plan_cache",
                         "short_plan_cache", "answer_cache"]
    intent: str | None = None
    answer_cache_hit: bool = False
    answer_cache_checked: bool = False
    plan_cache_hit: bool = False
    qwen_calls: int = Field(default=0, ge=0)
    qwen_retries: int = Field(default=0, ge=0)
    qwen_retry_reasons: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    ollama_tokens: dict[str, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    query_calls: int = Field(default=0, ge=0)
    citation_query_calls: int = Field(default=0, ge=0)
    ollama_ms: dict[str, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    outcome: Literal["success", "error"] = "success"
    error_type: str | None = None
    planning_diagnostics: dict[str, Any] = Field(default_factory=dict)


class TrackDiffSummary(BaseModel):
    """ขอบเขตและจำนวนจากชุดเต็ม ใช้แสดงผลได้แม้ส่วนต่างว่างหรือ rows ถูกจำกัด."""
    program: str
    edition: str | None = None
    tracks: list[Literal["coop", "nocoop"]] = Field(min_length=2, max_length=2)
    direction: Literal["coop_only", "nocoop_only", "both"]
    counts: dict[str, Annotated[int, Field(strict=True, ge=0)]]
    placeholder_slots: dict[str, Annotated[int, Field(strict=True, ge=0)]]
    invalid_code_slots: dict[str, Annotated[int, Field(strict=True, ge=0)]]
    total: int = Field(ge=0)
    displayed: int = Field(ge=0)


class AskResponse(BaseModel):
    total_count: int | None = Field(default=None, ge=0)
    returned_count: int | None = Field(default=None, ge=0)
    page: int | None = None
    page_size: int | None = None
    has_more: bool | None = None
    question: str
    sql: str
    rows: list[dict[str, Any]]
    answer: str
    edition: str | None = None
    edition_label: str | None = None
    scope: dict[str, Any] | None = None
    # ค่าเริ่มต้นทำให้คำตอบเดิมที่มีเพียงสี่ฟิลด์ยังผ่าน validation.
    citations: list[Citation] = Field(default_factory=list)
    processing_ms: float | None = Field(default=None, ge=0)
    performance: AskPerformance | None = None
    comparison: TrackDiffSummary | None = None
    # กราฟ/ผลตรวจ/ร่างแผนระบุข้อสมมติและข้อมูลที่ขาด แยกจากคำตอบเดิม.
    analysis: dict[str, Any] | None = None

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
