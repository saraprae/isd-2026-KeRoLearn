"""Curriculum DB adapter that reuses Lab 8B database functions."""

from pathlib import Path
from types import ModuleType


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

    def create_course(self, course: dict) -> dict:
        self._require_db()
        columns = (
            "code", "name_th", "name_en", "credits", "lecture_h", "lab_h",
            "self_h", "description_th",
        )
        conn = self.lab8b.open_db(self.path)
        try:
            conn.execute(
                "INSERT INTO course VALUES (?,?,?,?,?,?,?,?)",
                tuple(course.get(column) for column in columns),
            )
            conn.commit()
            return course
        finally:
            conn.close()

    def query_from_model(self, sql: str) -> tuple[str, list[dict]]:
        """Use Lab 8B's SQL guard and read-only connection directly."""
        self._require_db()
        safe_sql = self.lab8b.guard_sql(sql)
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            rows = [dict(row) for row in conn.execute(safe_sql).fetchall()]
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

