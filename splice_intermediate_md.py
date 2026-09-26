#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
splice_intermediate_md.py — patch specific pages of an existing intermediate_vlm.md
using a smaller re-OCR run, without re-OCR-ing pages that already came out fine.

ที่มา: BIT run — หน้า 27/28/32/33 ถูก OCR ตัดกลางตาราง (LAB7B_OCR_NUM_PREDICT ไม่พอ)
วิธีนี้ให้ OCR ใหม่แค่ 4 หน้าที่พังลงโฟลเดอร์แยก แล้ว "ปะ" กลับเข้า intermediate_vlm.md
เดิม แทนที่จะ OCR ใหม่ทั้ง 30 หน้า

ใช้:
    python splice_intermediate_md.py <base.md> <patch.md> <output.md>

- <base.md>   คือ intermediate_vlm.md เดิม (มีหน้าที่ดีอยู่แล้ว + หน้าที่พัง)
- <patch.md>  คือ intermediate_vlm.md จากรอบ OCR เฉพาะหน้าที่พัง (เช่น --pages "27,28,32,33")
- <output.md> ไฟล์ผลลัพธ์ — ทุกหน้าเหมือน base.md ทุกประการ ยกเว้นหน้าที่มีอยู่ใน
              patch.md จะถูกแทนที่ด้วยเนื้อหาจาก patch.md

หน้าไหนใน patch.md ที่ไม่มีใน base.md จะถูกเพิ่มเข้าไปด้วย (เผื่อ base.md เดิมไม่มี
หน้านั้นอยู่แล้วเลยเพราะ <table> ไม่ปิดเลยไม่ถูกนับเป็นหน้าแยกจาก marker เดิม —
ในทางปฏิบัติ marker <!-- PDF_PAGE N --> จะยังอยู่เสมอไม่ว่าตารางข้างในจะพังแค่ไหน
เพราะ marker ไม่ได้มาจากผลของ OCR ตาราง แต่เขียนจากโค้ดตอนแบ่ง chunk)

สคริปต์นี้ไม่รู้จักโครงสร้างตาราง/OCR เลย ทำงานแค่ระดับ "หน้า" (marker
<!-- PDF_PAGE N -->) เท่านั้น — ถ้าอยากตรวจว่าหน้าที่ปะเข้าไปแล้วสมบูรณ์จริง
(ไม่มี <table> ที่เปิดไม่ปิด) ให้รัน lab7b_curriculum.py -p markdown ต่อจากไฟล์
ผลลัพธ์นี้แล้วดู log — ตัวสคริปต์หลักมี diagnostic เตือนเรื่องนี้อยู่แล้ว
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER_RE = re.compile(r"<!--\s*PDF_PAGE\s+(\d+)\s*-->")


def split_by_page(text: str) -> dict[int, str]:
    """แยกไฟล์ markdown เป็น {เลขหน้า: เนื้อหาทั้งก้อนรวม marker ของหน้านั้น}"""
    matches = list(MARKER_RE.finditer(text))
    if not matches:
        raise ValueError("ไม่เจอ marker <!-- PDF_PAGE N --> เลยในไฟล์นี้")
    pages: dict[int, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pages[int(m.group(1))] = text[start:end]
    return pages


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(f"ใช้: python {Path(sys.argv[0]).name} <base.md> <patch.md> <output.md>")

    base_path, patch_path, out_path = (Path(a) for a in sys.argv[1:4])
    base_pages = split_by_page(base_path.read_text(encoding="utf-8"))
    patch_pages = split_by_page(patch_path.read_text(encoding="utf-8"))

    replaced, added = [], []
    for pg, content in patch_pages.items():
        if pg in base_pages:
            replaced.append(pg)
        else:
            added.append(pg)
        base_pages[pg] = content

    merged = "".join(base_pages[pg] for pg in sorted(base_pages))
    out_path.write_text(merged, encoding="utf-8")

    print(f"แทนที่ {len(replaced)} หน้า: {', '.join(map(str, sorted(replaced))) or '-'}")
    if added:
        print(f"เพิ่มหน้าใหม่ {len(added)} หน้า (ไม่มีใน base.md เดิม): "
              f"{', '.join(map(str, sorted(added)))}")
    print(f"รวม {len(base_pages)} หน้า -> เขียน {out_path}")


if __name__ == "__main__":
    main()
