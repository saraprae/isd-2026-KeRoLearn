import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


CODE_RE = re.compile(r"^(?:\d{8}|\d{5}x{3}|\d{4}x{4}|x{4,8})$", re.IGNORECASE)
CREDITS_RE = re.compile(r"\d+\s*\(\s*\d+\s*-\s*\d+\s*-\s*\d+\s*\)")
TOTAL_RE = re.compile(r"^(?:รวม|เธฃเธงเธก|total)$", re.IGNORECASE)


def extract_curriculum_from_file(
    ocr_path: str | Path,
    template_path: str | Path | None = None,
    program: str = "DSBA",
    plan: str = "no_coop",
) -> dict[str, Any]:
    payload = _load_ocr_payload(ocr_path)
    parsed = extract_curriculum(payload, program=program, plan=plan)

    # Disable GT/template merge while measuring OCR extraction quality.
    # if template_path:
    #     with Path(template_path).open("r", encoding="utf-8") as f:
    #         template = json.load(f)
    #     return merge_with_template(parsed, template)

    return parsed


def extract_curriculum(payload: dict[str, Any], program: str = "DSBA", plan: str = "no_coop") -> dict[str, Any]:
    courses = []
    for page_index, page in enumerate(payload.get("pages", []), start=1):
        year, semester = _year_semester_for_page(page_index)
        courses.extend(_extract_page_courses(page, year=year, semester=semester))

    return {
        "source": "OCR curriculum extraction",
        "description": f"Extracted academic plan from OCR for {program} ({plan})",
        "program": program,
        "plan": plan,
        "courses": courses,
    }


def merge_with_template(parsed: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    parsed_by_code: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for course in parsed.get("courses", []):
        parsed_by_code[str(course.get("code"))].append(course)

    output = {
        "source": template.get("source"),
        "description": template.get("description"),
        "program": template.get("program", parsed.get("program")),
        "plan": template.get("plan", parsed.get("plan")),
        "courses": [],
    }

    for template_course in template.get("courses", []):
        course = dict(template_course)
        code = str(course.get("code"))
        if parsed_by_code[code]:
            parsed_course = parsed_by_code[code].popleft()
            for key in ("name_th", "name_en", "credits", "year", "semester"):
                if course.get(key) in (None, "") and parsed_course.get(key) not in (None, ""):
                    course[key] = parsed_course[key]
        output["courses"].append(course)

    return output


def _load_ocr_payload(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    text = path.read_text(encoding="utf-8")
    pages = []
    for page_no, chunk in _split_text_pages(text):
        lines = [{"text": line.strip(), "box": [[0, index], [0, index]]} for index, line in enumerate(chunk.splitlines()) if line.strip()]
        pages.append({"page": page_no, "text": chunk, "lines": lines})
    return {"source_path": str(path), "engine": "text", "text": text, "pages": pages}


def _split_text_pages(text: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"--- Page (\d+) ---", text))
    if not matches:
        return [(1, text)]
    pages = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append((int(match.group(1)), text[start:end]))
    return pages


def _year_semester_for_page(page_index: int) -> tuple[int | None, int | None]:
    sequence = {
        1: (1, 1),
        2: (1, 2),
        3: (2, 1),
        4: (2, 2),
        5: (3, 1),
        6: (3, 2),
        7: (4, 1),
    }
    return sequence.get(page_index, (None, None))


def _extract_page_courses(page: dict[str, Any], year: int | None, semester: int | None) -> list[dict[str, Any]]:
    words = [_line_word(line) for line in page.get("lines", []) if str(line.get("text", "")).strip()]
    words.sort(key=lambda item: (item["y"], item["x"]))
    code_indexes = [index for index, word in enumerate(words) if CODE_RE.match(_clean_code(word["text"]))]
    courses = []

    for position, index in enumerate(code_indexes):
        code = _clean_code(words[index]["text"])
        next_index = code_indexes[position + 1] if position + 1 < len(code_indexes) else len(words)
        block = words[index + 1 : next_index]
        block = _trim_block(block)
        if not block:
            continue
        courses.append(_course_from_block(code, block, year=year, semester=semester))

    return courses


def _line_word(line: dict[str, Any]) -> dict[str, Any]:
    text = str(line.get("text", "")).strip()
    box = line.get("box") or [[0, 0]]
    xs = [point[0] for point in box if len(point) >= 2]
    ys = [point[1] for point in box if len(point) >= 2]
    return {
        "text": text,
        "x": min(xs) if xs else 0,
        "y": min(ys) if ys else 0,
    }


def _trim_block(block: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trimmed = []
    for word in block:
        text = word["text"].strip()
        if TOTAL_RE.match(text) or "รวมตลอด" in text or "เธฃเธงเธกเธ•เธฅเธญเธ”" in text:
            break
        if _is_footer(text):
            break
        trimmed.append(word)
    return trimmed


def _course_from_block(code: str, block: list[dict[str, Any]], year: int | None, semester: int | None) -> dict[str, Any]:
    texts = [word["text"].strip() for word in block if word["text"].strip()]
    credit_index = _first_credit_index(texts)
    credits = _normalize_credits(texts[credit_index]) if credit_index is not None else None

    before_credit = texts[: credit_index if credit_index is not None else len(texts)]
    after_credit = texts[credit_index + 1 :] if credit_index is not None else []

    name_th = _join_name(_remove_noise(before_credit))
    name_en = _join_english_name(after_credit)

    return {
        "code": code,
        "name_th": name_th,
        "name_en": name_en,
        "credits": credits,
        "year": year,
        "semester": semester,
        "category": None,
        "type": None,
        "prerequisite": None,
        "flexible_year_semester": None,
        "note": None,
    }


def _first_credit_index(texts: list[str]) -> int | None:
    for index, text in enumerate(texts):
        if CREDITS_RE.search(_compact_credit_text(text)):
            return index
    return None


def _compact_credit_text(text: str) -> str:
    return re.sub(r"\s+", "", text).replace("))", ")")


def _normalize_credits(text: str) -> str | None:
    compact = _compact_credit_text(text)
    match = re.search(r"(\d+\(\d+-\d+-\d+\))", compact)
    return match.group(1) if match else None


def _remove_noise(texts: list[str]) -> list[str]:
    cleaned = []
    for text in texts:
        value = text.strip()
        if not value:
            continue
        if re.fullmatch(r"\d+", value):
            continue
        if value in {"|", ".", "a"}:
            continue
        cleaned.append(value)
    return cleaned


def _join_name(parts: list[str]) -> str | None:
    value = " ".join(parts).strip()
    return value or None


def _join_english_name(parts: list[str]) -> str | None:
    english_parts = []
    for text in parts:
        if TOTAL_RE.match(text) or _is_footer(text):
            break
        if CREDITS_RE.search(_compact_credit_text(text)):
            continue
        if _looks_english(text):
            english_parts.append(text.strip())
    value = " ".join(english_parts).strip()
    value = re.sub(r"\s+", " ", value)
    return value.upper() if value else None


def _looks_english(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text)
    return bool(letters) and len(letters) >= max(2, len(text.strip()) // 3)


def _is_footer(text: str) -> bool:
    footer_tokens = [
        "เธงเธ—",
        "เธเธ“เธฐ",
        "เธชเธเธฅ",
        "มคอ",
    ]
    return any(token in text for token in footer_tokens)


def _clean_code(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()

if __name__ == '__main__':
    # 1. ระบุไฟล์ Input ที่คุณต้องการใช้งาน (.json หรือ .txt)
    input_file = "output_easyocr/sample_ocr.json" 
    
    # 2. เรียกใช้ฟังก์ชันสกัดข้อมูลหลัก
    result = extract_curriculum_from_file(ocr_path=input_file)
    
    # 3. กำหนดโฟลเดอร์ปลายทาง และสร้างโฟลเดอร์อัตโนมัติ (ถ้ายังไม่มี)
    output_dir = Path("output_easyocr")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 4. ตั้งชื่อไฟล์ Output (เช่น extracted_result.json)
    output_file_path = output_dir / "extracted_result.json"
    
    # 5. เขียนผลลัพธ์ลงไฟล์ในโฟลเดอร์นั้น
    with open(output_file_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)
        
    print(f"สกัดข้อมูลเสร็จเรียบร้อย! ผลลัพธ์ถูกบันทึกไว้ที่: {output_file_path}")