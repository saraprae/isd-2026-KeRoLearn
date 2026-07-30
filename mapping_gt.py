import sys
import csv
import json
import re
import pdfplumber
from pathlib import Path


def load_ground_truth(json_path: str) -> dict:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return data


def extract_page_texts(pdf_path: str) -> dict:
    """คืนค่า dict: {page_number (1-indexed): text}"""
    page_texts = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_texts[i + 1] = page.extract_text() or ""
    return page_texts


def find_pages_by_code(code: str, page_texts: dict) -> list:
    return [p for p, text in page_texts.items() if code in text]


def find_pages_by_name_en(name_en: str, page_texts: dict) -> list:
    """Fallback: ค้นหาด้วยชื่อวิชาภาษาอังกฤษแบบ case-insensitive
    (ตัดช่องว่างซ้ำ/ทำ normalize เล็กน้อยกันเคสตัด line-break กลางคำ)"""
    if not name_en:
        return []
    target = re.sub(r"\s+", " ", name_en.strip().upper())
    pages = []
    for p, text in page_texts.items():
        norm_text = re.sub(r"\s+", " ", text.upper())
        if target in norm_text:
            pages.append(p)
    return pages


def is_valid_course_row(course: dict) -> bool:
    """คัดแถวขยะ (เช่น note ที่หลุดเข้ามาเป็น row โดยไม่มีชื่อวิชาจริง) ออก"""
    return bool(course.get("name_th") or course.get("name_en"))


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 map_curriculum_to_ground_truth.py <curriculum.pdf> <ground_truth.json> <output.csv>")
        sys.exit(1)

    pdf_path, json_path, out_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    pdf_filename = Path(pdf_path).name

    print(f"[1/3] อ่าน ground truth: {json_path}")
    gt = load_ground_truth(json_path)
    program = gt.get("program", "")
    plan = gt.get("plan", "")
    gt_source = gt.get("source", "")
    all_courses = gt.get("courses", [])

    valid_courses = [c for c in all_courses if is_valid_course_row(c)]
    skipped = len(all_courses) - len(valid_courses)
    if skipped:
        print(f"    ! พบ {skipped} แถวที่ข้อมูลไม่สมบูรณ์ (ไม่มีชื่อวิชา) -> ข้ามไป ไม่นับเป็นรายวิชา")

    print(f"[2/3] อ่าน PDF และแตกข้อความทีละหน้า: {pdf_path}")
    page_texts = extract_page_texts(pdf_path)
    print(f"    รวมทั้งหมด {len(page_texts)} หน้า")

    print("[3/3] จับคู่รายวิชากับหน้าที่พบใน PDF ...")
    rows = []
    found_count = 0
    for course in valid_courses:
        code = (course.get("code") or "").strip()
        name_th = re.sub(r"\s+", " ", (course.get("name_th") or "").strip())
        name_en = re.sub(r"\s+", " ", (course.get("name_en") or "").strip())

        pages = find_pages_by_code(code, page_texts) if code else []
        match_type = "code"

        if not pages:
            # fallback: ลองค้นด้วยชื่ออังกฤษ
            pages = find_pages_by_name_en(name_en, page_texts)
            match_type = "name_en_fallback" if pages else "not_found"

        if pages:
            found_count += 1

        rows.append({
            "ground_truth_source": gt_source,
            "program": program,
            "plan": plan,
            "course_code": code,
            "name_th": name_th,
            "name_en": name_en,
            "year": course.get("year"),
            "semester": course.get("semester"),
            "category": course.get("category"),
            "type": course.get("type"),
            "curriculum_book_file": pdf_filename,
            "found_in_pages": ", ".join(str(p) for p in pages),
            "page_count": len(pages),
            "match_type": match_type,
        })

    fieldnames = [
        "ground_truth_source", "program", "plan",
        "course_code", "name_th", "name_en", "year", "semester",
        "category", "type",
        "curriculum_book_file", "found_in_pages", "page_count", "match_type",
    ]

    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nเสร็จสิ้น: จับคู่ได้ {found_count}/{len(valid_courses)} รายวิชา")
    print(f"บันทึกผลลัพธ์ที่: {out_csv}")


if __name__ == "__main__":
    main()