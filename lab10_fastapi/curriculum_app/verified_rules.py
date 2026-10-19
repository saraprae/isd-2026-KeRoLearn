"""Reviewed curriculum facts, bound to exact PDF bytes. No Lab 8 writes."""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("curriculum_rules.json")

@lru_cache(maxsize=8)
def _manifest(stamp):
    return json.loads(MANIFEST.read_text(encoding="utf-8"))

@lru_cache(maxsize=32)
def _sha(path, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rules_revision():
    stat = MANIFEST.stat()
    data = _manifest((stat.st_mtime_ns, stat.st_size))
    files = []
    for key, item in sorted(data["documents"].items()):
        path = ROOT / item["pdf_path"]
        try:
            st = path.stat()
            files.append((key, st.st_mtime_ns, st.st_size))
        except OSError:
            files.append((key, None, None))
    return (stat.st_mtime_ns, stat.st_size, tuple(files))

def document_rules(program, edition="default"):
    stat = MANIFEST.stat()
    data = _manifest((stat.st_mtime_ns, stat.st_size))
    item = data["documents"].get(f"{program}:{edition}")
    if not item:
        return None
    path = ROOT / item["pdf_path"]
    try:
        st = path.stat()
        if _sha(str(path), (st.st_mtime_ns, st.st_size)) != item["sha256"]:
            return None
    except OSError:
        return None
    return deepcopy(item)

def rule_citation(program, track, edition, pages, supports, *, course_code=None):
    return {"source": "prerequisite" if course_code else "program", "program": program,
            "track": track, "edition": edition, "pages": pages,
            "evidence_source": "prerequisite" if course_code else "program",
            "evidence_scope": "page_set", "page_basis": "pdf",
            "verification_status": "content_verified", "supports": supports,
            "verified_rule_sha256": (document_rules(program, edition or "default") or {}).get("sha256"),
            **({"course_code": course_code} if course_code else {})}

def evaluate_requirement(expression, completed, *, equivalents=(), grades=None):
    """Three-valued AND/OR. Missing grade/approval never means a failed branch."""
    grades = grades or {}
    if "all_of" in expression or "any_of" in expression:
        key = "all_of" if "all_of" in expression else "any_of"
        values = [evaluate_requirement(x, completed, equivalents=equivalents, grades=grades)
                  for x in expression[key]]
        if not values:return None
        if key == "all_of":
            return False if False in values else True if all(v is True for v in values) else None
        return True if True in values else False if all(v is False for v in values) else None
    if "approved_equivalent_of" in expression:
        return True if expression["approved_equivalent_of"] in equivalents else None
    code = expression.get("course")
    if code not in completed:
        return False
    if expression.get("min_grade") is not None:
        value = grades.get(code)
        return None if value is None else value >= expression["min_grade"]
    return True

def requirement_result(ctx):
    spec, target = ctx.spec, ctx.target
    record = document_rules(target.program, target.edition or "default")
    requirements = [] if not record else [r for r in record.get("requirements", [])
        if r["category"] == spec.category and r.get("course_type") == spec.course_type]
    if not requirements:
        return {"status": "unknown", "requirements": [],
                "limitations": ["ยังไม่มีเกณฑ์ของหมวด/ฉบับนี้ที่ตรวจจากเล่มแล้ว ไม่ใช้ยอดช่องตามแผนแทน"]}
    for r in requirements:
        citation = rule_citation(target.program, target.track, target.edition, r["pages"],
                                 [r["label"], "เกณฑ์หน่วยกิตจากเอกสารหลักสูตร"])
        ctx.evidence[("verified_requirement", r["category"], r.get("course_type"))] = citation
    return {"status": "verified_document_requirement", "requirements": [
        {"category": r["category"], "name_th": r["label"], "minimum_credits": r["credits"],
         "pages": r["pages"], "basis": "curriculum_document"} for r in requirements],
        "limitations": ["เป็นเกณฑ์หมวด ไม่ใช่ยอดช่องตามแผนหรือคำรับรองจบ"]}

def eligibility_result(contexts):
    home = contexts[0]
    record = document_rules(home.target.program, home.target.edition or "default")
    req = next((r for r in (record or {}).get("requirements", []) if r["category"] == "free_elective"), None)
    courses = []
    for code in home.spec.codes:
        candidates = [ctx for ctx in contexts if code in ctx.courses]
        if candidates:
            item = candidates[-1].brief(code)
            item["source_program"] = candidates[-1].target.program
            courses.append(item)
        else:
            courses.append({"code": code, "status": "unknown", "reason": "ไม่พบรายละเอียดในฐานที่ระบุ"})
    if req:
        home.evidence[("verified_free_rule",)] = rule_citation(home.target.program, home.target.track,
            home.target.edition, req["pages"], ["เกณฑ์หมวดเลือกเสรี"])
    return {"status": "unknown", "courses": courses,
            "minimum_credits": req["credits"] if req else None,
            "selection_scope": (record or {}).get("free_elective_scope"),
            "recognition_verified": False,
            "limitations": ["มีเพียงเกณฑ์ทั่วไปและข้อมูลรายวิชา ยังไม่ยืนยันการนับวิชานี้เป็นเสรี",
                            "ต้องตรวจการนับหมวด/นับซ้ำ ข้อกำหนดที่ใช้จริง และการเปิดสอนหรือผลอนุมัติที่จำเป็น"]}
