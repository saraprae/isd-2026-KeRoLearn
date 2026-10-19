"""SQLite adapter และ context ของ request: deadline, เวลาแต่ละขั้นและ counters."""

from pathlib import Path
from types import ModuleType
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps, lru_cache
from threading import RLock
from collections import OrderedDict
from copy import deepcopy
import re
import sqlite3
import json
import time
import unicodedata
import hashlib

from .config import PROJECT_ROOT


_request_deadline = ContextVar("curriculum_request_deadline", default=None)
# ใช้ context เดียวกันทั้ง planner และ SQLite โดยไม่ import กลับไป model_service.
STAGES = ("cache", "lock_wait", "planning", "classifier", "qwen", "compile", "query", "reasoning", "citations", "render")
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
        self.qwen_retries = 0
        self.qwen_retry_reasons = {}
        self.ollama_tokens = {}
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
                    qwen_retries=self.qwen_retries, qwen_retry_reasons=dict(self.qwen_retry_reasons),
                    ollama_tokens=dict(self.ollama_tokens),
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
    for field in ("prompt_eval_count", "prompt_eval_cached_count", "eval_count"):
        value = body.get(field)
        if type(value) is int and value >= 0:
            trace.ollama_tokens[field] = trace.ollama_tokens.get(field, 0) + value


def record_qwen_retry(reason):
    trace = current_trace()
    if trace is not None:
        trace.qwen_retries += 1
        trace.qwen_retry_reasons[reason] = trace.qwen_retry_reasons.get(reason, 0) + 1


def profile_request(function):
    """ครอบ ask(): เริ่ม trace ใหม่ บันทึกแม้เกิด error แล้วแนบ metrics หลัง cache."""
    @wraps(function)
    def wrapped(self, database, question, *, program=None, track=None, **kwargs):
        trace = RequestTrace()
        token = _trace.set(trace)
        try:
            response = function(self, database, question, program=program, track=track, **kwargs)
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


def edition_paths(config, edition: str | None = None) -> dict:
    """เลือก mapping ฉบับอย่างชัดเจน; ไม่มีการแทนฉบับที่ขาดด้วยฐาน default."""
    selected = (getattr(config, "active_edition", "default") if edition is None else edition).strip()
    if not selected:
        raise ValueError("Select a curriculum edition")
    if selected == getattr(config, "active_edition", "default"):
        return config.db_paths
    if selected == "default":
        raise ValueError("Default edition is not available in this scoped catalog")
    paths = getattr(config, "edition_db_paths", {}).get(selected)
    if paths is None:
        raise ValueError(f"Unknown curriculum edition: {selected}")
    return paths


def edition_metadata(config, edition: str | None = None, program: str | None = None) -> dict:
    """อ่านป้ายกลางแล้วทับด้วยป้ายเฉพาะหลักสูตร; ไม่เดาปีจากระยะเวลาเรียน."""
    selected = edition or getattr(config, "active_edition", "default")
    metadata = dict(getattr(config, "edition_metadata", {}).get(selected, {
        "label": "ไม่ระบุปี" if selected == "default" else selected,
        "year": None, "year_source": None,
    }))
    overrides = metadata.pop("programs", {})
    if program:
        metadata.update(overrides.get(program.strip().upper(), {}))
    return metadata


class AmbiguousEditionError(ValueError):
    reason_code = "ambiguous_edition"


def resolve_edition(config, program, edition=None, *, from_year=False):
    """Map a program-specific human year to an edition ID; never guess revisions."""
    active = getattr(config, "active_edition", "default")
    value = str(active if edition is None else edition).strip()
    mappings = {active: config.db_paths, **getattr(config, "edition_db_paths", {})}
    program = program.strip().upper() if program else None
    if not from_year and value in mappings:
        return value
    candidates = [key for key, paths in mappings.items()
                  if (not program or program in paths)
                  and str(edition_metadata(config, key, program).get("year")) == value]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise AmbiguousEditionError(f"ปีหลักสูตร {value} มีหลายฉบับ กรุณาเลือกฉบับให้ชัดเจน: {', '.join(candidates)}")
    if value in mappings and (not program or program in mappings[value]):
        return value
    raise ValueError(f"ไม่มีฐานข้อมูลฉบับ {value} สำหรับ {program or 'หลักสูตรที่เลือก'} ใน catalog")


def resolve_database(lab8b: ModuleType, config, program: str | None = None,
                     track: str | None = None, edition: str | None = None) -> "CurriculumDatabase":
    """เลือกฐานด้วย mapping กลาง; API แปลง ValueError เป็น 422 โดยไม่มี circular import."""
    if program is None:
        if track is not None or edition is not None:
            raise ValueError("program is required with track/edition")
        return CurriculumDatabase(lab8b, config.db_path, config.max_rows)
    program = program.strip().upper()
    tracks = edition_paths(config, resolve_edition(config, program, edition)).get(program)
    if tracks is None:
        raise ValueError(f"Unknown program or unavailable edition: {program}")
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
        """เมนูสามขั้นจาก catalog เดียว; ตรวจไฟล์ด้วย stat ไม่เปิด/query DB.

        tracks เดิมยังอยู่สำหรับ API client เก่า ส่วน editions มีเฉพาะฐานที่มีจริง.
        """
        active = getattr(self.config, "active_edition", "default")
        mappings = {active: self.config.db_paths,
                    **getattr(self.config, "edition_db_paths", {})}
        codes = dict.fromkeys(program for paths in mappings.values() for program in paths)
        result = []
        for program in codes:
            editions = []
            for edition, paths in mappings.items():
                tracks = [track for track, path in paths.get(program, {}).items()
                          if Path(path).is_file()]
                if tracks:
                    editions.append({"edition": edition, **edition_metadata(self.config, edition, program),
                                     "tracks": tracks})
            if editions:
                preferred = next((item for item in editions if item["edition"] == active), editions[0])
                result.append({"program": program, "tracks": preferred["tracks"],
                               "default_edition": preferred["edition"], "editions": editions})
        return result

    def resolve(self, program: str | None, track: str | None = None,
                edition: str | None = None) -> "CurriculumDatabase":
        return resolve_database(self.lab8b, self.config, program, track, edition)

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


@lru_cache(maxsize=16)
def _verified_pdf(path: str, digest: str, revision: tuple):
    """Only expose an explicitly registered, hash-matched PDF with readable page bounds."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", digest) or revision[1] > 256 * 1024 * 1024:
        return None
    try:
        checksum = hashlib.sha256()
        with Path(path).open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                return None
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != digest.lower():
            return None
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz  # Older optional OCR dependency; missing parser leaves metadata usable without links.
        with fitz.open(path) as document:
            if document.is_encrypted or document.page_count < 1:
                return None
            return {"path": Path(path), "page_count": document.page_count}
    except (ImportError, OSError, RuntimeError, ValueError):
        return None


class CitationDocumentCatalog:
    """Lazy, revision-cached provenance from existing exports and reviewed configuration.

    No extraction, page offset guesses, network access or per-citation DB reads.
    PDF indices are confirmed by PDF_PAGE markers, not the printed page labels.
    """
    def __init__(self, config):
        self.config = config
        self.sources = deepcopy(getattr(config, "document_sources", {}))
        self.export_root = Path(getattr(config, "source_export_root", PROJECT_ROOT / "work/lab7b_run"))
        self._cache, self._served = OrderedDict(), {}
        self._lock = RLock()

    @staticmethod
    def _path(value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    @staticmethod
    def _revision(path):
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _descriptor(self, program, edition, track):
        key = f"{program}:{edition}"
        scoped_key = f"{key}:{track}"
        configured_key = scoped_key if scoped_key in self.sources else key
        entry = self.sources.get(configured_key, {})
        paths = edition_paths(self.config, edition).get(program, {})
        db_path = paths.get(track) or next(iter(paths.values()), None)
        dataset = Path(db_path).parent if db_path else None
        if dataset is not None and dataset.name in {"coop", "nocoop"}:
            dataset = dataset.parent
        dataset_name = dataset.name if dataset is not None else program
        pred = self._path(entry["pred_path"]) if entry.get("pred_path") else self.export_root / dataset_name / "pred_vlm.json"
        markdown = self._path(entry["markdown_path"]) if entry.get("markdown_path") else pred.with_name("intermediate_vlm.md")
        manifest = dataset / "manifest.json" if dataset is not None else None
        pdf_path = self._path(entry["pdf_path"]) if entry.get("pdf_path") else None
        fingerprint = (configured_key, str(pred), self._revision(pred), self._revision(markdown),
                       self._revision(manifest) if manifest else None,
                       self._revision(pdf_path) if pdf_path else None)
        with self._lock:
            if fingerprint in self._cache:
                return self._cache[fingerprint]
            metadata, markers = {}, set()
            try:
                # Export must be linked by the DB manifest or an explicit reviewed mapping.
                linked = bool(entry.get("pred_path"))
                if manifest is not None and manifest.is_file():
                    lineage = json.loads(manifest.read_text(encoding="utf-8-sig"))
                    source = str(lineage.get("source", "")).replace("\\", "/")
                    linked = linked or (lineage.get("program") in {program, dataset_name} and
                                         source.endswith(f"/{dataset_name}/pred_vlm.json"))
                if linked and pred.is_file() and pred.stat().st_size <= 8 * 1024 * 1024:
                    metadata = json.loads(pred.read_text(encoding="utf-8-sig")).get("_meta", {})
                    if markdown.is_file() and markdown.stat().st_size <= 20 * 1024 * 1024:
                        markers = {int(value) for value in re.findall(
                            r"<!--\s*PDF_PAGE\s+(\d+)\s*-->", markdown.read_text(encoding="utf-8-sig"))}
            except (OSError, ValueError, TypeError, AttributeError):
                metadata, markers = {}, set()
            document_id = "doc-" + hashlib.sha256(configured_key.encode()).hexdigest()[:16]
            pdf = (_verified_pdf(str(pdf_path), str(entry.get("sha256", "")), self._revision(pdf_path))
                   if pdf_path and self._revision(pdf_path) is not None else None)
            descriptor = {"document_id": document_id,
                "document_title": entry.get("title") or f"ชุดข้อมูลต้นทาง {program} · {edition_metadata(self.config, edition, program)['label']}",
                "page_basis": entry.get("page_basis", "unknown"), "markers": markers,
                "evidence_scope": "page_set" if metadata.get("pages_per_chunk") == 1 else
                                  "chunk" if isinstance(metadata.get("pages_per_chunk"), int) and metadata["pages_per_chunk"] > 1 else "unknown",
                "page_mapping": entry.get("page_mapping", {}), "pdf": pdf}
            if descriptor["page_basis"] not in {"pdf", "printed", "unknown"}:
                descriptor["page_basis"] = "unknown"
            self._cache[fingerprint] = descriptor
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            if pdf:
                self._served[document_id] = (program, edition, track)
            return descriptor

    def enrich(self, citation):
        result = dict(citation)
        program, edition, track = citation.get("program"), citation.get("edition") or "default", citation.get("track")
        pages = sorted({page for page in citation.get("pages", []) if type(page) is int and page > 0})
        descriptor = self._descriptor(program, edition, track) if program else {}
        basis = descriptor.get("page_basis", "unknown")
        if basis == "unknown" and pages and set(pages) <= descriptor.get("markers", set()):
            basis = "pdf"
        actual = citation.get("evidence_source", "unknown")
        support = {"course": "ข้อมูลรายวิชาที่บันทึกไว้", "plan_item": "ตำแหน่งปี/เทอมและข้อมูลในแผนการเรียน",
                   "prerequisite": "ข้อมูลความสัมพันธ์วิชาก่อน/วิชาควบที่บันทึกไว้",
                   "program": "ข้อมูลหลักสูตรที่บันทึกไว้", "elective_slot": "รายการในบัญชีวิชาเลือก"}
        reviewed = False
        if citation.get("verified_rule_sha256") and descriptor.get("pdf"):
            from .verified_rules import document_rules, ROOT
            record = document_rules(program, edition)
            reviewed = bool(record and record["sha256"] == citation["verified_rule_sha256"]
                            and Path(descriptor["pdf"]["path"]).resolve() == (ROOT / record["pdf_path"]).resolve())
        references = []
        for page in pages:
            mapping = descriptor.get("page_mapping", {}).get(str(page), {})
            page_basis = "pdf" if basis == "unknown" and page in descriptor.get("markers", set()) else basis
            pdf_page = mapping.get("pdf_page", page if page_basis == "pdf" else None)
            if type(pdf_page) is not int or pdf_page < 1:
                pdf_page = None
            pdf = descriptor.get("pdf")
            if pdf and pdf_page and pdf_page > pdf["page_count"]:
                pdf_page = None
            printed = mapping.get("printed_page", str(page) if page_basis == "printed" else None)
            references.append({"stored_page": page, "page_basis": page_basis, "pdf_page": pdf_page,
                "printed_page": str(printed) if printed is not None else None,
                "section_name": mapping.get("section_name"),
                "pdf_url": f"/api/documents/{descriptor['document_id']}#page={pdf_page}" if pdf and pdf_page else None,
                "verification_status": "content_verified" if pdf and pdf_page and (mapping.get("content_verified") is True or reviewed) else "metadata_only"})
        identity = [descriptor.get("document_id"), citation.get("source"), actual, program, edition, track,
                    citation.get("course_code"), citation.get("year"), citation.get("semester"), pages]
        sections = {reference["section_name"] for reference in references}
        result.update(citation_id="ref-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:16],
            document_id=descriptor.get("document_id"), document_title=descriptor.get("document_title"),
            page_basis=basis, evidence_source=actual, evidence_scope=descriptor.get("evidence_scope", "unknown"),
            section_name=next(iter(sections)) if len(sections) == 1 else None,
            supports=citation.get("supports", []) if reviewed else [support[actual]] if actual in support else ["บริบทของข้อมูลที่ใช้ตอบ ยังไม่ยืนยันแหล่งหน้าระดับฟิลด์"],
            verification_status="content_verified" if references and all(r["verification_status"] == "content_verified" for r in references) else "metadata_only",
            page_references=references)
        result.pop("verified_rule_sha256", None)
        return result

    def document_file(self, document_id):
        with self._lock:
            scope = self._served.get(document_id)
        if scope is None:
            for key in self.sources:
                parts = key.split(":")
                if len(parts) in {2, 3} and document_id == "doc-" + hashlib.sha256(key.encode()).hexdigest()[:16]:
                    scope = (parts[0], parts[1], parts[2] if len(parts) == 3 else None)
                    break
        if scope is None:
            return None
        descriptor = self._descriptor(*scope)
        return descriptor["pdf"]["path"] if descriptor.get("pdf") else None


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
                               for table in ("course", "v_plan", "plan_item", "prerequisite", "program", "elective_slot")}
                    names, course_codes = {}, set()
                    for row in conn.execute("SELECT code,name_th,name_en FROM course"):
                        remaining_seconds()
                        course_codes.add(row["code"])
                        for field in ("name_th", "name_en"):
                            name = str(row[field] or "").strip()
                            if len(name) >= 3:
                                names.setdefault(name, []).append(row["code"])
                    category_column = "category" if "category" in columns["plan_item"] else "NULL AS category"
                    type_column = "type" if "type" in columns["plan_item"] else "NULL AS type"
                    # ส่งกลุ่มตัวเลือกให้ planner รู้ว่าจำนวนรหัสอาจไม่ใช่จำนวนช่อง
                    # ใช้ SELECT/cache revision เดิม ไม่ query เพิ่มหรือแก้ schema DB.
                    alternative_column = "alt_group" if "alt_group" in columns["plan_item"] else "NULL AS alt_group"
                    plans = ([dict(r) for r in conn.execute(
                        f"SELECT year,semester,code,{category_column},{type_column},{alternative_column} FROM plan_item")]
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
                    # สร้างชื่อสั้นจากชื่อจริง ตัดเฉพาะคำนำ/ท้ายทั่วไปและรักษาเลขรุ่นวิชา.
                    # รวมทุก candidate เพื่อไม่เลือกวิชาแรกเมื่อชื่อกำกวม.
                    aliases = {}
                    for name, codes in names.items():
                        variants = {name}
                        for _ in range(2):
                            for value in list(variants):
                                shorter = re.sub(r"^(?:หลักการ|พื้นฐาน|เบื้องต้นเกี่ยวกับ|ความรู้เบื้องต้นเกี่ยวกับ)\s*", "", value)
                                shorter = re.sub(r"\s*(?:เบื้องต้น|ขั้นพื้นฐาน)$", "", shorter).strip()
                                if len(shorter) >= 6 and shorter != value:
                                    variants.add(shorter)
                        for value in variants - {name}:
                            aliases.setdefault(value, set()).update(codes)
                    alias_patterns = []
                    for alias, codes in aliases.items():
                        codes.update(names.get(alias, []))
                        expression = re.escape(alias)
                        if re.search(r"[A-Za-z]", alias):
                            expression = r"(?<![A-Za-z0-9_])" + expression + r"(?![A-Za-z0-9_])"
                        alias_patterns.append((re.compile(expression, re.I), sorted(codes)))
                    snapshot = {"revision": revision, "names": names, "codes": course_codes,
                                "alias_patterns": alias_patterns,
                                "name_patterns": name_patterns,"plans": plans,
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

    @staticmethod
    def flexible_sources(columns: dict, *, is_gened: bool = False) -> dict:
        """Read-only code-owned projections, derived only from existing DB columns.

        qa_plan includes course descriptions by a code-owned join; the model need
        not invent joins. Pages retain their real owner; nothing is written to DB.
        Schema data comes from the revision-aware lexicon cache.
        """
        sources = {}
        course = set(columns.get("course", []))
        plan = set(columns.get("plan_item", []))
        fields = [f for f in ("code", "name_th", "name_en", "credits", "lecture_h",
                             "lab_h", "self_h", "description_th") if f in course]
        real = "length(c.code)=8 AND c.code NOT GLOB '*[^0-9]*'"
        if "code" in course:
            projection = [f'c."{f}" AS "{f}"' for f in fields]
            if "pages" in course:
                projection.append('c.pages AS course_pages')
            sources["qa_course"] = {"columns": fields + (["course_pages"] if "pages" in course else []),
                "sql": "SELECT " + ",".join(projection) + " FROM course c WHERE " + real,
                "definition": "one row per real 8-digit course code; NULL is unknown"}
        if {"code", "year", "semester"} <= plan and "code" in course:
            projection = ['p.code AS code', 'p.year AS year', 'p.semester AS semester']
            names = ["code", "year", "semester"]
            for f in fields:
                if f == "code":
                    continue
                expression = "COALESCE(p.credits,c.credits)" if f == "credits" and f in plan else f'c."{f}"'
                projection.append(expression + f' AS "{f}"')
                names.append(f)
            for f in ("category", "type", "alt_group"):
                if f in plan:
                    projection.append(f'p."{f}" AS "{f}"')
                    names.append(f)
            for owner, schema, alias in (("c", course, "course_pages"), ("p", plan, "plan_pages")):
                if "pages" in schema:
                    projection.append(f'{owner}.pages AS {alias}')
                    names.append(alias)
            sources["qa_plan"] = {"columns": names,
                "sql": "SELECT DISTINCT " + ",".join(projection) +
                       " FROM plan_item p LEFT JOIN course c ON c.code=p.code"
                       " WHERE length(p.code)=8 AND p.code NOT GLOB '*[^0-9]*'",
                "definition": "real codes in recorded study plan, with year/term/category/type and course descriptions; alternatives are not slot-credit requirements"}
        program = set(columns.get("program", []))
        if not is_gened and {"total_credits", "years"} <= program:
            names = [f for f in ("program_id", "name_th", "name_en", "degree", "total_credits", "years") if f in program]
            sources["qa_program"] = {"columns": names, "sql": "SELECT " + ",".join(names) + " FROM program",
                "definition": "recorded program metadata only, not personal graduation certification"}
        return sources

    @timed_stage("query")
    def query_flexible_records(self, sql: str, params: tuple, source: dict,
                               source_name: str, output_fields: tuple,
                               *, is_gened: bool = False) -> tuple[str, list[dict]]:
        """Execute an AST-verified SELECT with complete JSON-packed results.

        The outer query has one row so max_rows does not truncate courses/evidence.
        Only code-owned source SQL is injected, never a user-provided path/table.
        guard_sql, readonly connection, authorizer and deadline still apply.
        """
        if not re.fullmatch(r"qa_(?:course|plan|program)", source_name):
            raise ValueError("Unknown flexible source")
        if not output_fields or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", f) for f in output_fields):
            raise ValueError("Invalid flexible result fields")
        pairs = ",".join(f"'{f}',r.\"{f}\"" for f in output_fields)
        wrapped = (f"WITH {source_name} AS ({source['sql']}) "
                   f"SELECT json_group_array(json_object({pairs})) AS records FROM ({sql}) r")
        executed, packed = self.query_from_model(wrapped, params=params, is_gened=is_gened)
        return executed, json.loads(packed[0]["records"]) if packed else []

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
    def query_compiled_records(self, sql: str, *, params=(), is_gened=False):
        """Read the complete compiler-owned course projection as one JSON row.

        guard_sql/read-only/deadline/GENED authorization still apply to the outer
        SELECT. No request can supply column names or bypass the public row guard.
        """
        projection=sql.split(" FROM ",1)[0].removeprefix("SELECT ").removeprefix("DISTINCT ")
        allowed={"code","name_th","name_en","credits","year","semester","alt_group","note","category","type","lecture_h","lab_h","self_h","description_th"}
        fields=[]
        for part in projection.split(","):
            if part.strip()=="requested.value AS code":
                fields.append("code");continue
            match=re.fullmatch(r"[a-z]+[.]([a-z_]+)",part.strip())
            if not match or match[1] not in allowed:raise ValueError("Not a compiled course projection")
            fields.append(match[1])
        pairs=", ".join("'"+field+"', compiled."+field for field in fields)
        wrapped="SELECT json_group_array(json_object("+pairs+")) AS records FROM ("+sql+") AS compiled"
        executed,rows=self.query_from_model(wrapped,params=params,is_gened=is_gened)
        return executed,json.loads(rows[0]["records"]) if rows else []

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


    @staticmethod
    def planning_snapshot_sql(*, include_metadata: bool = True, include_classification: bool = False) -> str:
        """อ่าน course/plan/prerequisite ครบในหนึ่งแถว ก่อนจำกัดแถวคำตอบ.

        ใช้ SELECT ที่กำหนดเองและอ่านอย่างเดียว; guard LIMIT และ max_rows จึงไม่ตัดกราฟ.
        เก็บทั้งแถวเป็น JSON เพื่อรองรับฐานเดิมที่ไม่มี category/type/pages ได้ด้วย.
        """
        classification = ", 'category',category,'type',type" if include_classification else ""
        return (
            "SELECT (SELECT json_group_array(json_object('code',code,'name_th',name_th,'credits',credits)) FROM course) AS courses, "
            "(SELECT json_group_array(json_object('code',code,'requires',requires,'kind',kind)) FROM prerequisite) AS edges, "
            "(SELECT json_group_array(json_object('id',id,'code',code,'year',year,'semester',semester,'credits',credits,'alt_group',alt_group" + classification + ")) FROM plan_item) AS plan, "
            + ("(SELECT total_credits FROM program LIMIT 1) AS total_credits" if include_metadata else "NULL AS total_credits")
        )

    @staticmethod
    def data_snapshot_sql(columns: dict, *, include_metadata: bool = True) -> str:
        """อ่านข้อมูลครบใน SELECT เดียว; LIMIT ของคำตอบไม่ตัดชุดรหัสหรือกราฟ.

        ชื่อตารางเป็นรายการปิด ส่วนชื่อคอลัมน์มาจาก PRAGMA ของ lexicon เท่านั้น
        ไม่รับ SQL/paths/identifiers จากคำถามหรือ Qwen และไม่เปลี่ยน schema DB.
        ฐานเก่าที่ไม่มี elective_slot/pages ยังค้นส่วนที่มีได้ตามจริง.
        """
        expressions = []
        for table, key in (("course", "courses"), ("plan_item", "plan"),
                           ("prerequisite", "edges"), ("elective_slot", "electives"),
                           ("program", "program")):
            fields = sorted(columns.get(table, [])) if table != "program" or include_metadata else []
            if not fields:
                expressions.append(f"'[]' AS {key}")
                continue
            if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None for name in fields):
                raise ValueError("Invalid database column name")
            pairs = ",".join(f"'{name}',\"{name}\"" for name in fields)
            expressions.append(f"(SELECT json_group_array(json_object({pairs})) FROM {table}) AS {key}")
        return "SELECT " + ", ".join(expressions)

    def data_snapshot(self, columns: dict, *, is_gened: bool = False) -> tuple[str, dict]:
        """คืน snapshot atomic สำหรับ query แบบประกอบ: lookup → filter → compute.

        อ่านหนึ่งแถว JSON จากทั้งชุด ภายใต้ guard/read-only/deadline เดิม; GENED
        ไม่อ่าน metadata ยอด/จำนวนปีที่ใช้แทนเกณฑ์หลักสูตรไม่ได้.
        """
        sql = self.data_snapshot_sql(columns, include_metadata=not is_gened)
        executed, rows = self.query_from_model(sql, is_gened=is_gened)
        if len(rows) != 1:
            raise ValueError("Incomplete curriculum snapshot")
        return executed, {key: json.loads(rows[0][key] or "[]")
                          for key in ("courses", "plan", "edges", "electives", "program")} | {
                              "columns": columns}

    def planning_snapshot(self, *, include_metadata: bool = True, include_classification: bool = False) -> tuple[str, dict]:
        """ส่งข้อมูลครบให้โค้ดเดินกราฟ/ตรวจแผน โดยไม่ให้ AI คำนวณหรือแก้ฐาน."""
        sql, rows = self.query_from_model(self.planning_snapshot_sql(include_metadata=include_metadata, include_classification=include_classification))
        if len(rows) != 1:
            raise ValueError("อ่านข้อมูลสำหรับวางแผนไม่ครบ")
        data = rows[0]
        return sql, {key: json.loads(data[key] or "[]") for key in ("courses", "edges", "plan")} | {
            "total_credits": data["total_credits"]}

    @staticmethod
    def plan_course_codes_sql() -> str:
        """รวมชุดรหัสเป็นหนึ่งแถว เพื่ออ่านครบก่อนใช้ max_rows จำกัดคำตอบ.

        นับช่อง placeholder/รหัสผิดรูปแบบแยกกัน ไม่ตีความเป็นรายวิชาจริง
        และไม่ใช้ course catalog ซึ่งอาจเหมือนกันทั้งสองแผน.
        """
        valid = "length(code)=8 AND code NOT GLOB '*[^0-9]*'"
        return (
            "SELECT json_group_array(DISTINCT CASE WHEN " + valid +
            " THEN code END) AS codes, COUNT(*) AS plan_rows, "
            "COALESCE(SUM(CASE WHEN code GLOB 'PLACEHOLDER_*' THEN 1 ELSE 0 END),0) AS placeholder_slots, "
            "COALESCE(SUM(CASE WHEN (" + valid + ") OR code GLOB 'PLACEHOLDER_*' "
            "THEN 0 ELSE 1 END),0) AS invalid_code_slots FROM plan_item"
        )

    def plan_course_codes(self) -> tuple[str, dict]:
        """อ่านรหัส plan_item ทั้งชุดด้วย query เดียว ภายใต้ guard/deadline เดิม.

        ผลรวม JSON ไม่ถูก fetchmany(max_rows) ตัดรหัสปลายชุด; NULL ที่เกิดจาก
        CASE ถูกตัดเฉพาะตอนแปลงเป็น set ไม่ตัดข้อมูลจริงหรือเลขศูนย์นำหน้า.
        """
        sql, rows = self.query_from_model(self.plan_course_codes_sql())
        if len(rows) != 1:
            raise ValueError("ไม่สามารถอ่านชุดรหัสจากแผนการเรียนได้ครบ")
        data = rows[0]
        data["codes"] = {code for code in json.loads(data["codes"]) if code is not None}
        return sql, data

    def query_citations(
        self, sql: str, *, params: tuple = (), source: str,
        row_limit: int | None = None, is_gened: bool = False, plan_items: bool = False,
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
        if plan_items:
            if source != "study_plan":
                raise ValueError("Plan item evidence requires source=study_plan")
            table = "plan_item"  # ส่วนต่างห้ามใช้ COALESCE กับ course.pages แทนหน้าแผน.
        remaining_seconds()
        self._require_db()
        conn = self.lab8b.open_db(self.path, readonly=True)
        try:
            count_query()  # PRAGMA ตรวจคอลัมน์เป็นงานของ citations เมื่ออยู่ใน stage นี้.
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            origin = "'" + {"course": "course", "program": "program", "prerequisite": "prerequisite",
                             "study_plan": "plan_item" if plan_items else "unknown"}[source] + "'"
            if source == "study_plan" and not plan_items and "pages" in columns:
                probes = []
                for owner in ("plan_item", "course"):
                    count_query()
                    owner_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({owner})")}
                    if "pages" not in owner_columns:
                        continue
                    match = "o.code=e.code AND o.pages=e.pages"
                    if owner == "plan_item":
                        match += " AND o.year IS e.year AND o.semester IS e.semester"
                    probes.append(f"WHEN EXISTS(SELECT 1 FROM {owner} o WHERE {match}) THEN '{owner}'")
                if probes:
                    origin = "CASE " + " ".join(probes) + " ELSE 'unknown' END"
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
            "'semester',e.semester,'pages',e.pages,'evidence_source'," + origin + ")) AS evidence FROM (" + sql + ") e"
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
