"""Curriculum DB adapter that reuses Lab 8B database functions."""

from pathlib import Path
from types import ModuleType
import sqlite3

class UnsupportedGenedMetadata(ValueError):
    pass

class CurriculumDatabase:
    def __init__(self, lab8b: ModuleType, path: Path, max_rows: int = 100):
        self.lab8b = lab8b
        self.path = path.resolve()
        self.max_rows = max_rows

    def _require_db(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"ไม่พบฐานข้อมูล: {self.path}")

    def program(self) -> dict | None:
        self._require_db()
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            row = conn.execute("SELECT * FROM program LIMIT 1").fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def courses(self, search: str = "", limit: int = 20, offset: int = 0) -> list[dict]:
        self._require_db()
        limit = min(max(limit, 1), self.max_rows)
        offset = max(offset, 0)
        sql = "SELECT * FROM course"
        params: list[object] = []
        if search.strip():
            sql += " WHERE code LIKE ? OR name_th LIKE ? OR name_en LIKE ?"
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY code LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    # เพิ่มเมธอดแผนเรียน main.py มี route /api/study-plan ที่เรียก selected_database.study_plan(...) อยู่แล้ว แต่ adapter ยังไม่มีเมธอดนี้ เพิ่มในคลาส CurriculumDatabase
    def study_plan(self, year: int, semester: int) -> list[dict]:
        self._require_db()
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            rows = conn.execute(
                """
                SELECT year, semester, code, name_th, name_en, credits, alt_group, note
                FROM v_plan
                WHERE year = ? AND semester = ?
                ORDER BY code
                """,
                (year, semester),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def course_description(
        self,
        courseid: str,
        db_paths: dict[str, dict[str, Path]],
    ) -> dict | None:
        paths = dict.fromkeys(
            path
            for tracks in db_paths.values()
            for path in tracks.values()
        )

        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"ไม่พบฐานข้อมูล: {path}")

            conn = self.lab8b.open_db(path, readonly=True)
            try:
                row = conn.execute(
                    """
                    SELECT code, name_th, name_en, description_th
                    FROM course
                    WHERE code = ?
                    """,
                    (courseid,),
                ).fetchone()
                if row is not None:
                    return dict(row)
            finally:
                conn.close()

        return None

    def create_course(self, course: dict) -> dict:
        self._require_db()
        columns = (
            "code", "name_th", "name_en", "credits", "lecture_h", "lab_h",
            "self_h", "description_th",
        )
        conn = self.lab8b.open_db(self.path)
        try:
            conn.execute(
                """
                INSERT INTO course (
                    code, name_th, name_en, credits,
                    lecture_h, lab_h, self_h, description_th
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(course.get(column) for column in columns),
            )
            conn.commit()
            return course
        finally:
            conn.close()

    def query_from_model(
        self,
        sql: str,
        *,
        is_gened: bool = False,
    ) -> tuple[str, list[dict]]:
        self._require_db()
        safe_sql = self.lab8b.guard_sql(sql)
        conn = self.lab8b.open_db(self.path, readonly=True)

        blocked_metadata = False

        def authorize(action, table, column, database_name, source):
            nonlocal blocked_metadata

            if (
                is_gened
                and action == sqlite3.SQLITE_READ
                and (table or "").lower() == "program"
                and (column or "").lower() in {"years", "total_credits"}
            ):
                blocked_metadata = True
                return sqlite3.SQLITE_DENY

            return sqlite3.SQLITE_OK

        try:
            conn.set_authorizer(authorize)

            try:
                rows = [
                    dict(row)
                    for row in conn.execute(safe_sql).fetchall()
                ]
            except sqlite3.DatabaseError as exc:
                if blocked_metadata:
                    raise UnsupportedGenedMetadata(
                        "GENED ไม่มีระยะเวลาหลักสูตรของตัวเอง "
                        "ส่วนหน่วยกิตศึกษาทั่วไปที่ต้องเรียน "
                        "ให้ตรวจจากเกณฑ์ของหลักสูตรหลักและปีหลักสูตร "
                        "ค่า years/total_credits ใน DB นี้"
                        "ไม่ควรใช้เป็นเกณฑ์การเรียน"
                    ) from exc
                raise

            return safe_sql, rows[:self.max_rows]
        finally:
            conn.close()


SQL_SCHEMA_CONTEXT = """
program(program_id, name_th, name_en, degree, total_credits, years)
course(code, name_th, name_en, credits, lecture_h, lab_h, self_h, description_th)
plan_item(id, program_id, year, semester, code, credits, alt_group, note)
prerequisite(code, requires, kind)
v_plan(id, year, semester, code, name_th, name_en, credits, alt_group, note)
v_semester_credits(year, semester, credits, n_courses)
""".strip()

