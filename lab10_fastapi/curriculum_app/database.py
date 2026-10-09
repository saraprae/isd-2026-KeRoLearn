"""SQLite adapter และ context ของ request: deadline, เวลาแต่ละขั้นและ counters."""

from pathlib import Path
from types import ModuleType
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import RLock
from collections import OrderedDict
from copy import deepcopy
import re
import sqlite3
import json
import time
import unicodedata


_request_deadline = ContextVar("curriculum_request_deadline", default=None)
# ใช้ context เดียวกันทั้ง planner และ SQLite โดยไม่ import กลับไป model_service.
STAGES = ("cache", "lock_wait", "planning", "qwen", "compile", "query", "citations", "render")
_trace = ContextVar("curriculum_performance", default=None)


class RequestTrace:
    """เก็บเวลาที่ไม่ซ้อนกันและ counters ของคำขอเดียว; ไม่มีข้อมูลคำตอบใน trace."""
    def __init__(self):
        self.started = time.perf_counter()
        self.stages = dict.fromkeys(STAGES, 0.0)
        self.stack = []
        self.plan_source = "unknown"
        self.intent = None
        self.answer_cache_hit = False
        self.answer_cache_checked = False
        self.plan_cache_hit = False
        self.qwen_calls = self.query_calls = self.citation_query_calls = 0
        self.ollama_ms = {}
        self.outcome = "success"
        self.error_type = None
        self.planning_diagnostics = {}

    def snapshot(self):
        total = max(0.0, (time.perf_counter() - self.started) * 1000)
        stages = {**self.stages, "other": max(0.0, total - sum(self.stages.values()))}
        return dict(total_ms=round(total, 3), stages_ms={k:round(v, 3) for k,v in stages.items()},
                    plan_source=self.plan_source, intent=self.intent,
                    answer_cache_hit=self.answer_cache_hit, answer_cache_checked=self.answer_cache_checked,
                    plan_cache_hit=self.plan_cache_hit,
                    qwen_calls=self.qwen_calls, query_calls=self.query_calls,
                    citation_query_calls=self.citation_query_calls,
                    ollama_ms={k:round(v, 3) for k,v in self.ollama_ms.items()},
                    outcome=self.outcome, error_type=self.error_type,
                    planning_diagnostics=deepcopy(self.planning_diagnostics))



def current_trace():
    return _trace.get()


def inside_citations():
    trace = current_trace()
    return trace is not None and any(frame[0] == "citations" for frame in trace.stack)


@contextmanager
def measure_stage(name):
    """เก็บเวลาใน finally; หักเวลาขั้นลูกออกจากขั้นแม่และแยก context ต่อ request."""
    trace = current_trace()
    if trace is None:
        yield
        return
    frame = [name, time.perf_counter(), 0.0]
    trace.stack.append(frame)
    try:
        yield
    finally:
        elapsed = max(0.0, time.perf_counter() - frame[1])
        trace.stack.pop()
        trace.stages[name] += max(0.0, elapsed - frame[2]) * 1000
        if trace.stack:
            trace.stack[-1][2] += elapsed


def timed_stage(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            # SQL/compile ที่หาเลขหน้าอยู่ใน citations ทั้งหมด ไม่บวกซ้ำใน query/compile.
            if name in {"query", "compile"} and inside_citations():
                return function(*args, **kwargs)
            with measure_stage(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def count_query():
    trace = current_trace()
    if trace is not None:
        if inside_citations():
            trace.citation_query_calls += 1
        else:
            trace.query_calls += 1


def record_qwen_call():
    trace = current_trace()
    if trace is not None:
        trace.qwen_calls += 1  # นับ HTTP requests จริง รวม retry เมื่อ output ถูกตัด.


def record_ollama_durations(body):
    trace = current_trace()
    if trace is None:
        return
    for field, label in (("total_duration", "total"), ("load_duration", "load"),
                         ("prompt_eval_duration", "prompt"), ("eval_duration", "generate")):
        value = body.get(field)
        if type(value) is int and value >= 0:
            trace.ollama_ms[label] = trace.ollama_ms.get(label, 0.0) + value / 1_000_000


def profile_request(function):
    """ครอบ ask(): เริ่ม trace ใหม่ บันทึกแม้เกิด error แล้วแนบ metrics หลัง cache."""
    @wraps(function)
    def wrapped(self, database, question, *, program=None, track=None):
        trace = RequestTrace()
        token = _trace.set(trace)
        try:
            response = function(self, database, question, program=program, track=track)
        except Exception as exc:
            trace.outcome, trace.error_type = "error", type(exc).__name__
            raise
        finally:
            report = trace.snapshot()
            _trace.reset(token)
            self._record_performance(report, program, track)
        # เพิ่มหลัง cache จบ จึงไม่ cache เวลา/counters ของ request ก่อนหน้า.
        return {**response, "performance": report}
    return wrapped


def remaining_seconds() -> float:
    """คืนเวลาที่ request ยังใช้ได้ เพื่อให้ inference และ SQL ใช้งบเดียวกัน."""
    deadline = _request_deadline.get()
    if deadline is None:
        return float("inf")
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        raise TimeoutError("หมดเวลาสำหรับคำถามนี้")
    return remaining


@contextmanager
def request_budget(seconds: float):
    """แยก deadline ของแต่ละ request/thread และคืน context เมื่อทำงานเสร็จ."""
    if seconds <= 0:
        raise ValueError("request timeout ต้องมากกว่าศูนย์")
    deadline = time.perf_counter() + seconds
    current = _request_deadline.get()
    token = _request_deadline.set(min(deadline, current) if current is not None else deadline)
    try:
        yield
        remaining_seconds()
    finally:
        _request_deadline.reset(token)


def _canonical(value) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def whole_word(text, term) -> int:
    """ค้นคำเต็มภาษาอังกฤษ: DATA ไม่ตรง DATABASE; ค่าค้นยังส่งเป็น parameter."""
    needle = _canonical(term)
    return int(bool(needle) and re.search(
        r"(?<![A-Za-z0-9_])" + re.escape(needle) + r"(?![A-Za-z0-9_])",
        _canonical(text),
    ) is not None)


def ocr_contains(text, term) -> int:
    """ค้นโดยข้ามช่องว่าง OCR แต่ไม่แก้ข้อความต้นฉบับในฐานข้อมูล."""
    haystack = re.sub(r"\s+", "", _canonical(text))
    needle = re.sub(r"\s+", "", _canonical(term))
    return int(bool(needle) and needle in haystack)

class UnsupportedGenedMetadata(ValueError):
    pass


def database_revision(path: Path) -> tuple:
    """ใช้ทั้งไฟล์ DB และ WAL เป็นรุ่นข้อมูลร่วมสำหรับ catalog และ answer cache."""
    path = Path(path)

    def revision(file: Path):
        info = file.stat()
        return (info.st_mtime_ns, info.st_size, info.st_ctime_ns)

    try:
        wal = revision(path.with_name(path.name + "-wal"))
    except FileNotFoundError:
        wal = None
    return revision(path), wal


def resolve_database(lab8b: ModuleType, config, program: str | None = None,
                     track: str | None = None) -> "CurriculumDatabase":
    """เลือกฐานด้วย mapping กลาง; API แปลง ValueError เป็น 422 โดยไม่มี circular import."""
    if program is None:
        if track is not None:
            raise ValueError("program is required with track")
        return CurriculumDatabase(lab8b, config.db_path, config.max_rows)
    program = program.strip().upper()
    tracks = config.db_paths.get(program)
    if tracks is None:
        raise ValueError("Unknown program")
    if track is None:
        if len(tracks) != 1:
            raise ValueError("Select a track for this program")
        track = next(iter(tracks))
    track = track.strip().lower()
    if track not in tracks:
        raise ValueError("Unknown track for this program")
    return CurriculumDatabase(lab8b, tracks[track], config.max_rows)


class ProgramCatalog:
    """รายชื่อหลักสูตรชุดเดียวกับ curricula พร้อม alias และชื่อจาก DB แบบ read-only.

    โหลด metadata เมื่อเริ่มจับชื่อครั้งแรกและเมื่อ DB/WAL เปลี่ยนเท่านั้น; การถามซ้ำ
    ตรวจ stat ของไฟล์แล้วใช้ snapshot เดิม จึงไม่เพิ่ม SQL query ของคำตอบแต่ละ request.
    """
    def __init__(self, config, lab8b: ModuleType):
        self.config, self.lab8b = config, lab8b
        self._lock = RLock()
        self._metadata = {}
        self._snapshot_revision = None
        self._patterns = ()
        self._path_configuration = None
        self._raw_paths = None
        self._relative_paths = False
        self._normalized_paths = ()
        self._paths_by_program = {}

    def programs(self) -> list[dict]:
        """คง response shape ของ /api/curricula และไม่อ่าน DB เพื่อแสดงตัวเลือก."""
        return [{"program": program, "tracks": list(tracks)}
                for program, tracks in self.config.db_paths.items()]

    def resolve(self, program: str | None, track: str | None = None) -> "CurriculumDatabase":
        return resolve_database(self.lab8b, self.config, program, track)

    @contextmanager
    def _locked(self):
        """รอ catalog lock ภายใน deadline เดียวกับ request; เวลานี้อยู่ใน planning."""
        remaining = remaining_seconds()
        acquired = (self._lock.acquire() if remaining == float("inf")
                    else self._lock.acquire(timeout=remaining))
        if not acquired:
            raise TimeoutError("หมดเวลารอตรวจชื่อหลักสูตร")
        try:
            remaining_seconds()
            yield
        finally:
            self._lock.release()

    @staticmethod
    def _path_revision(path):
        try:
            return database_revision(path)
        except OSError as exc:
            # ชื่อรหัสยังใช้ได้แม้ไฟล์หาย; query หลักจะแจ้งข้อผิดพลาดฐานข้อมูลตามเดิม.
            return ("unavailable", type(exc).__name__)

    def _signature(self):
        raw_paths = tuple((str(program), str(track), str(path))
                          for program, tracks in self.config.db_paths.items()
                          for track, path in tracks.items())
        aliases = tuple(sorted((str(program), tuple(values))
                               for program, values in getattr(self.config, "program_aliases", {}).items()))
        if raw_paths != self._raw_paths:
            self._relative_paths = any(not Path(path).is_absolute() for _, _, path in raw_paths)
            self._raw_paths = raw_paths
        # resolve บน Windows แตะ filesystem หลายครั้ง จึงทำเฉพาะเมื่อ mapping/alias เปลี่ยน.
        # relative paths ยังผูกกับ cwd เพื่อให้การเปลี่ยนโฟลเดอร์ไม่ใช้ path เก่าผิดฐาน.
        configuration = raw_paths, aliases, str(Path.cwd()) if self._relative_paths else None
        if configuration != self._path_configuration:
            normalized, paths_by_program, resolved = [], {}, {}
            for program, track, raw in raw_paths:
                if raw not in resolved:
                    resolved[raw] = Path(raw).resolve()
                path = resolved[raw]
                normalized.append((program, track, str(path), path))
                paths_by_program.setdefault(program, []).append(path)
            self._normalized_paths = tuple(normalized)
            self._paths_by_program = {program: tuple(dict.fromkeys(paths))
                                      for program, paths in paths_by_program.items()}
            self._path_configuration = configuration
        # คง stat ของ DB และ WAL ทุก request; cache เฉพาะการ normalize path ไม่ cache รุ่นข้อมูล.
        paths = tuple((program, track, path_text, self._path_revision(path))
                      for program, track, path_text, path in self._normalized_paths)
        return paths, aliases

    def _metadata_names(self, path: Path, revision) -> tuple[str, ...]:
        cached = self._metadata.get(path)
        if cached is not None and cached[0] == revision:
            return cached[1]
        names = ()
        if path.is_file():
            conn = None
            try:
                # อ่านเฉพาะชื่อเพื่อสร้าง catalog; ไม่ใช้ query_from_model และไม่นับเป็น query คำตอบ.
                remaining = remaining_seconds()
                conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                       timeout=min(2.0, remaining))
                deadline = time.perf_counter() + min(2.0, remaining)
                conn.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)
                row = conn.execute("SELECT name_th, name_en FROM program LIMIT 1").fetchone()
                names = tuple(value.strip() for value in (row or ())
                              if isinstance(value, str) and value.strip())
                remaining_seconds()
            except TimeoutError:
                raise
            except (OSError, sqlite3.Error):
                # DB รุ่นเก่า/GENED อาจไม่มีชื่อ; ยังจับด้วยรหัสและ alias จาก configuration ได้.
                names = ()
            finally:
                if conn is not None:
                    conn.close()
        self._metadata[path] = (revision, names)
        return names

    def _refresh(self):
        signature = self._signature()
        if signature == self._snapshot_revision:
            return
        for attempt in range(2):
            mapping = {}

            def add(alias, program):
                normalized = re.sub(r"\s+", " ", _canonical(alias)).strip()
                if normalized:
                    mapping.setdefault(normalized, set()).add(program)

            for program, tracks in self.config.db_paths.items():
                code = str(program).strip().upper()
                add(code, code)
                for alias in getattr(self.config, "program_aliases", {}).get(code, ()):
                    add(alias, code)
                for path in self._paths_by_program.get(str(program), ()):
                    for name in self._metadata_names(path, self._path_revision(path)):
                        add(name, code)
            patterns = []
            for alias, programs in mapping.items():
                # ASCII boundary ทำให้ IT ไม่ตรง BIT/AIT แต่ยังใช้ได้ในข้อความภาษาไทยติดกัน.
                expression = r"\s+".join(re.escape(part) for part in alias.split(" "))
                if re.match(r"[A-Za-z0-9_]", alias[0]):
                    expression = r"(?<![A-Za-z0-9_])" + expression
                if re.match(r"[A-Za-z0-9_]", alias[-1]):
                    expression += r"(?![A-Za-z0-9_])"
                patterns.append((alias, tuple(sorted(programs)), re.compile(expression, re.IGNORECASE)))
            current = self._signature()
            if current == signature:
                self._patterns = tuple(sorted(patterns, key=lambda item: (-len(item[0]), item[0])))
                self._snapshot_revision = signature
                return
            signature = current
        raise RuntimeError("ข้อมูลชื่อหลักสูตรเปลี่ยนระหว่างอ่าน กรุณาถามใหม่")

    def aliases_revision(self) -> tuple:
        """คืนรุ่น snapshot ของชื่อหลักสูตร; answer cache ใช้ targets/DB revisions หลัง parse ใหม่."""
        with self._locked():
            self._refresh()
            return self._snapshot_revision

    def match_mentions(self, text: str) -> list[dict]:
        """คืนทุกตำแหน่งที่พบ รวมชื่อซ้ำและชื่อกำกวม เพื่อให้ planner ตรวจ grammar ต่อ."""
        with self._locked():
            self._refresh()
            candidates = []
            for alias, programs, pattern in self._patterns:
                for match in pattern.finditer(text):
                    candidates.append({"program": programs[0] if len(programs) == 1 else None,
                                       "programs": programs, "alias": alias,
                                       "start": match.start(), "end": match.end()})
            selected = []
            # เลือกชื่อยาวก่อนทั่วข้อความ เพื่อไม่แยกชื่อเต็มออกเป็นหลายหลักสูตรโดยผิดพลาด.
            for candidate in sorted(candidates, key=lambda hit: (-(hit["end"] - hit["start"]), hit["start"])):
                if not any(candidate["start"] < previous["end"] and candidate["end"] > previous["start"]
                           for previous in selected):
                    selected.append(candidate)
            return sorted(selected, key=lambda hit: hit["start"])


def curriculum_category(value: str | None) -> str | None:
    """ค่ากลางของหมวดจริง ไม่ใช้ประเภท 'เลือก' แทนหมวดเลือกเสรี."""
    text = str(value or "").strip()
    if "เสรี" in text:
        return "free_elective"
    if "ศึกษาทั่วไป" in text:
        return "general_education"
    if "เฉพาะ" in text:
        return "specialized"
    return None


class CurriculumLexicon:
    """Snapshot ชื่อ/หมวด/capabilities ของ DB ที่เลือก เก็บ LRU ผูก DB และ WAL revision.

    อ่านแบบ read-only ภายใต้ deadline; ไม่ส่งรายชื่อทั้งฐานไป Qwen และไม่ใช้ข้อมูล
    ต่าง revision ใน plan cache. ผลคืนเป็นสำเนาเพื่อไม่ให้ผู้เรียกแก้ snapshot กลาง.
    """
    def __init__(self):
        self._lock = RLock()
        self._cache = OrderedDict()

    def snapshot(self, database):
        database._require_db()
        acquired = self._lock.acquire(timeout=min(60.0, remaining_seconds()))
        if not acquired:
            raise TimeoutError("หมดเวลารอข้อมูลคำศัพท์หลักสูตร")
        try:
            for _ in range(2):
                revision = database_revision(database.path)
                key = (str(database.path), revision)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return deepcopy(self._cache[key])
                conn = database.lab8b.open_db(database.path, readonly=True)
                try:
                    deadline = time.perf_counter() + min(5.0, remaining_seconds())
                    conn.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)
                    columns = {table: {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                               for table in ("course", "v_plan", "plan_item", "prerequisite")}
                    names = {}
                    for row in conn.execute("SELECT code,name_th,name_en FROM course"):
                        remaining_seconds()
                        for field in ("name_th", "name_en"):
                            name = str(row[field] or "").strip()
                            if len(name) >= 3:
                                names.setdefault(name, []).append(row["code"])
                    category_column = "category" if "category" in columns["plan_item"] else "NULL AS category"
                    type_column = "type" if "type" in columns["plan_item"] else "NULL AS type"
                    plans = ([dict(r) for r in conn.execute(
                        f"SELECT year,semester,code,{category_column},{type_column} FROM plan_item")]
                        if columns["plan_item"] else [])
                    categories, types = {}, {}
                    for row in plans:
                        category = curriculum_category(row["category"])
                        if category:
                            categories.setdefault(category, set()).add(row["category"])
                        value = str(row["type"] or "").strip()
                        kind = "required" if value == "บังคับ" else "elective" if value == "เลือก" else None
                        if kind:
                            types.setdefault(kind, set()).add(row["type"])
                    # Compile ชื่อเพียงครั้งต่อ revision; GENED มีชื่อจำนวนมากเกิน regex cache กลาง.
                    name_patterns = []
                    for name,codes in names.items():
                        expression = re.escape(name)
                        if re.search(r"[A-Za-z]",name):
                            expression = r"(?<![A-Za-z0-9_])" + expression + r"(?![A-Za-z0-9_])"
                        name_patterns.append((re.compile(expression,re.I),codes))
                    snapshot = {"revision": revision, "names": names, "name_patterns": name_patterns,"plans": plans,
                                "columns": {t: sorted(c) for t,c in columns.items()},
                                "categories": {k: sorted(v) for k,v in categories.items()},
                                "types": {k: sorted(v) for k,v in types.items()}}
                    remaining_seconds()
                except sqlite3.OperationalError as exc:
                    if time.perf_counter() >= deadline:
                        raise TimeoutError("อ่านข้อมูลคำศัพท์หลักสูตรเกินกำหนด") from exc
                    raise
                finally:
                    conn.close()
                if database_revision(database.path) == revision:
                    # ล้างรุ่นเก่าของฐานนี้พร้อมจำกัดจำนวนฐาน ไม่สะสม snapshots หลังแก้ DB.
                    for old in list(self._cache):
                        if old[0] == key[0]:
                            self._cache.pop(old)
                    self._cache[key] = snapshot
                    while len(self._cache) > 16:
                        self._cache.popitem(last=False)
                    return deepcopy(snapshot)
            raise RuntimeError("ฐานข้อมูลเปลี่ยนระหว่างอ่านคำศัพท์ กรุณาถามใหม่")
        finally:
            self._lock.release()


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

    @timed_stage("query")
    def query_from_model(
        self,
        sql: str,
        *,
        params: tuple = (),
        is_gened: bool = False,
    ) -> tuple[str, list[dict]]:
        # Compiler ส่ง SQL และค่าค้นแยกกัน; คง guard/read-only/GENED authorizer เดิม.
        count_query()
        remaining_seconds()
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
            conn.create_function("whole_word", 2, whole_word, deterministic=True)
            conn.create_function("ocr_contains", 2, ocr_contains, deterministic=True)
            conn.set_authorizer(authorize)
            deadline = time.perf_counter() + min(5.0, remaining_seconds())
            conn.set_progress_handler(lambda: int(time.perf_counter() >= deadline), 1000)

            try:
                rows = [
                    dict(row)
                    for row in conn.execute(safe_sql, params).fetchmany(self.max_rows)
                ]
                remaining_seconds()
            except sqlite3.DatabaseError as exc:
                if time.perf_counter() >= deadline:
                    raise TimeoutError("การค้นฐานข้อมูลใช้เวลาเกินกำหนด") from exc
                if blocked_metadata:
                    raise UnsupportedGenedMetadata(
                        "GENED ไม่มีระยะเวลาหลักสูตรของตัวเอง "
                        "ส่วนหน่วยกิตศึกษาทั่วไปที่ต้องเรียน "
                        "ให้ตรวจจากเกณฑ์ของหลักสูตรหลักและปีหลักสูตร "
                        "ค่า years/total_credits ใน DB นี้"
                        "ไม่ควรใช้เป็นเกณฑ์การเรียน"
                    ) from exc
                raise

            return safe_sql, rows
        finally:
            conn.close()


    def query_citations(
        self, sql: str, *, params: tuple = (), source: str,
        row_limit: int | None = None, is_gened: bool = False,
    ) -> list[dict]:
        """อ่าน pages แยกจากยอดรวม โดยใช้เงื่อนไข/ลำดับเดียวกับ query จริง.

        รวม evidence เป็นหนึ่งแถวเพื่อให้ LIMIT ของ guard ไม่ตัดแหล่งอ้างอิง
        ของ COUNT/SUM; รายการรายวิชาจำกัดตามจำนวนแถวที่แสดงจริงเท่านั้น.
        DB รุ่นที่ไม่มี pages และค่า JSON ผิดรูปแบบคืนรายการอ้างอิงว่างได้.
        """
        table = {"course": "course", "study_plan": "v_plan", "program": "program",
                 "prerequisite": "prerequisite"}.get(source)
        if table is None:
            raise ValueError("Unknown citation source")
        remaining_seconds()
        self._require_db()
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            count_query()  # PRAGMA ตรวจคอลัมน์เป็นงานของ citations เมื่ออยู่ใน stage นี้.
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        finally:
            conn.close()
        if "pages" not in columns:
            return []
        if row_limit is not None:
            if type(row_limit) is not int or row_limit < 1:
                raise ValueError("Citation row limit must be positive")
            sql += " LIMIT ?"
            params = (*params, row_limit)
        packed_sql = (
            "SELECT json_group_array(json_object('course_code',e.code,'year',e.year,"
            "'semester',e.semester,'pages',e.pages)) AS evidence FROM (" + sql + ") e"
        )
        _, packed = self.query_from_model(packed_sql, params=params, is_gened=is_gened)
        evidence = json.loads(packed[0]["evidence"]) if packed else []
        result = []
        for item in evidence:
            remaining_seconds()
            raw_pages = item.pop("pages")
            try:
                pages = json.loads(raw_pages) if isinstance(raw_pages, str) else raw_pages
            except (ValueError, TypeError):
                continue
            if not isinstance(pages, list):
                continue
            pages = sorted({page for page in pages if type(page) is int and page > 0})
            if pages:
                result.append({**item, "pages": pages})
        return result


SQL_SCHEMA_CONTEXT = """
program(program_id, name_th, name_en, degree, total_credits, years)
course(code, name_th, name_en, credits, lecture_h, lab_h, self_h, description_th)
plan_item(id, program_id, year, semester, code, credits, alt_group, category, type, note, pages)
prerequisite(code, requires, kind)
v_plan(id, year, semester, code, name_th, name_en, credits, alt_group, category, type, note, pages)
v_semester_credits(year, semester, credits, n_courses)
""".strip()
