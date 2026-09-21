#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 lab7b_curriculum.py
 Lab 7B — สกัดแผนการศึกษาจากเล่มหลักสูตร ด้วย LLM ที่รันบนเครื่องตัวเอง
================================================================================

 วิชา 06026240 การพัฒนาระบบอัจฉริยะ  |  เทคโนโลยีสารสนเทศ สจล.
 --------------------------------------------------------------------------
 ⚠️  ข้อบังคับ: รันแบบออฟไลน์ 100% ไม่มีค่าใช้จ่าย
 --------------------------------------------------------------------------
 แม้เล่มหลักสูตรจะเป็นเอกสารสาธารณะ (ไม่เข้าข่าย PDPA) แต่แล็บนี้กำหนดให้
 ทุกกลุ่มใช้โมเดลที่รันบนเครื่องเท่านั้น ด้วยเหตุผล 3 ข้อ:
   1. นักศึกษาต้องไม่มีค่าใช้จ่าย
   2. ผลลัพธ์ต้องทำซ้ำได้ (API ภายนอกเปลี่ยนโมเดลเงียบ ๆ เมื่อไรก็ได้)
   3. เป็นทักษะที่ใช้ได้จริงเมื่อไปทำงานกับข้อมูลที่ห้ามออกนอกองค์กร

 --------------------------------------------------------------------------
 โหมดสกัด Markdown -> JSON (ตั้งด้วย env)
 --------------------------------------------------------------------------
   LAB7_EXTRACT=rules   (ค่าเริ่มต้น) ใช้กฎอ่านตาราง "แผนการศึกษา" และหน้า "คำอธิบายรายวิชา"
                        ตรวจยอดรวมหน่วยกิตของทุกตารางกับแถว "รวม" ในเล่มให้เอง
                        ถ้าเอกสารไม่ใช่ HTML table จะถอยไปใช้ LLM เอง
   LAB7_EXTRACT=llm     ใช้ qwen3 สกัดทั้งหมดแบบเดิม
   LAB7_ALT_MODE=split  (ค่าเริ่มต้น) สหกิจ "A หรือ B" แยกสองแถว / single = แถวเดียว

 --------------------------------------------------------------------------
 การแก้ไขจากผล eval_gt.json (แผน IT ไม่สหกิจ) — ทุกข้อเป็นกฎทั่วไป ไม่ hard-code รหัส/ชื่อวิชา
 --------------------------------------------------------------------------
   1. repair_plan_rows(): ซ่อมตารางที่ OCR ยุบ rowspan — ชื่อ/หน่วยกิตยึดหน้า "คำอธิบายรายวิชา"
      (รหัสอยู่หน้าชื่อเสมอ) แล้วให้ตารางทุกแผนช่วยลงคะแนน; กู้วิชาที่รหัสหายจากตารางด้วยชื่อ;
      หารหัสของแถวที่ไม่มีรหัสด้วยชื่อ; แยก "9064xxxxx" ที่ครอบสองวิชาเป็น 9064xxxx + xxxxxxxx
   2. แถว "รหัส+ชื่อ" อยู่ช่องเดียว (90644042) ไม่ถูกทิ้งอีก
   3. คำอธิบายรายวิชา: แยกเลขท้ายชื่อ ("หัวข้อพิเศษ ... 1") ออกจากหน่วยกิต, "(3-0-6)" ที่ไม่มีเลขนำหน้า
      คำนวณเป็น N(l-p-s), "(3-2-5)" ที่หารสามไม่ลงตัวถูกทิ้ง, ชื่ออังกฤษในวงเล็บ, หน่วยกิตที่ลอยเดี่ยว ๆ
   4. บั๊ก _DOC_NOISE_RE ที่ตัด "มคอ" ออกจากคำว่า "โปรแกรมคอมพิวเตอร์"
   5. แถวที่ OCR อ่านไม่ได้เลย (เช่น "วิชาเลือก... 1") สร้างคืนได้เฉพาะเมื่อ เลขลำดับขาด + ยอด "รวม" ของภาค
      ขาดพอดี + มีภาคเดียวที่เข้าเงื่อนไข (ติดหมายเหตุใน note เสมอ)
   6. เล่มสองแผน: วิชาที่มีแต่ในแผนสหกิจ ได้แถว year=0 เพิ่มสำหรับแผนไม่สหกิจ (แถวสหกิจยังอยู่)
   7. หมวด "เลือกเสรี": AIT = "หมวดวิชาเสรี", โปรแกรมอื่น = "หมวดวิชาเลือกเสรี" (บังคับด้วย LAB7_CATEGORY_FREE)
   ⚠ รหัสตัวแทนคงรูปตามเล่ม (060164xx, 9064xxxx, xxxxxxxx) — สคริปต์นี้ไม่สร้าง "PLACEHOLDER_" ที่ใดเลย

 --------------------------------------------------------------------------
 วิธีใช้
 --------------------------------------------------------------------------
   python3 lab7b_curriculum.py --check

   python3 lab7b_curriculum.py \
       --input data/DSBA_plan.pdf \
       --gt    gt/DSBA_academic_plan_coop.json \
       --pipeline all --out output/

   # เล่มหลักสูตรยาวมาก ให้ระบุเฉพาะหน้าที่เป็นตารางแผนการศึกษา
   python3 lab7b_curriculum.py -i data/DSBA.pdf --pages 42-58 -g gt/x.json

================================================================================
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import Lab3_ocr_system.ocr_system.src.lab7_metrics as M  # noqa: E402


# ==============================================================================
#  ส่วนที่ 0 — ค่าตั้งต้น
# ==============================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL_OCR = os.getenv("LAB7_MODEL_OCR", "scb10x/typhoon-ocr1.5-3b")
MODEL_TEXT = os.getenv("LAB7_MODEL_TEXT", "qwen3:4b")
DPI = int(os.getenv("LAB7_DPI", "150"))
# ด้านยาวสุดของภาพที่ส่งเข้า OCR (px) — หน้าใหญ่กว่า A4 ที่ 150 DPI จะถูกย่อลง
# (Typhoon-OCR แนะนำ ~1800) ใส่ 0 เพื่อปิด
MAX_SIDE_PX = int(os.getenv("LAB7_MAX_SIDE", "1800"))
REQUEST_TIMEOUT = 900
NUM_CTX = int(os.getenv("LAB7B_NUM_CTX", "8192"))
NUM_PREDICT = int(os.getenv("LAB7B_NUM_PREDICT", "4096"))
OCR_NUM_CTX = int(os.getenv("LAB7B_OCR_NUM_CTX", "4096"))
OCR_NUM_PREDICT = int(os.getenv("LAB7B_OCR_NUM_PREDICT", "1200"))

# ⭐ ค่าเฉพาะของกลุ่ม B
# เล่มหลักสูตรมี 50-150 หน้า ส่งเข้าโมเดลทีเดียวไม่ได้แน่นอน
# เราจึง "แบ่งเป็นก้อน" (chunk) ทีละไม่กี่หน้า แล้วรวมผลทีหลัง
PAGES_PER_CHUNK = int(os.getenv("LAB7_CHUNK", "1"))

# ข้าม pipeline baseline (Tesseract) ทั้งหมด
#     export LAB7_SKIP_BASELINE=1
# ⚠️ ผลที่ตามมา: จะไม่มีเส้นฐานไว้เปรียบเทียบ ทำให้ตอบคำถามท้ายบท
#    ชุดที่ 2 (เปรียบเทียบ pipeline) ไม่ได้ และเสียคะแนนส่วนที่ 3
SKIP_BASELINE = os.getenv("LAB7_SKIP_BASELINE", "").strip() in ("1", "true", "yes")


# ==============================================================================
#  ส่วนที่ 0.5 — รีจิสทรีของ "รอบรัน" (program × section -> ไฟล์ PDF + ช่วงหน้า)
# ==============================================================================
#
#  หนึ่งรอบ = หนึ่งไฟล์ PDF (5 ไฟล์ -> 5 รอบ: IT, DSBA, BIT, AIT, GENED)
#
#  IT/DSBA/BIT มีแผนการศึกษาสองแบบ (ไม่สหกิจ/สหกิจ) อยู่ติดกันในเล่มเดียว
#  รอบเดียวจึงอ่านช่วงหน้าที่ครอบคลุมทั้งสองแผน (เช่น IT = 31-44) + หน้าคำอธิบายรายวิชา
#  แต่ schema มี field "plan" แค่ระดับเอกสาร ไม่ใช่ระดับรายวิชา โมเดลจึงบอกไม่ได้ว่า
#  วิชาไหนอยู่แผนไหน  วิธีแก้ที่นี่ไม่พึ่งโมเดลเลย:
#      ทุกวิชาที่สกัดได้ถูกแนบ "pages" = เลขหน้า PDF จริงที่เจอวิชานั้น
#      (ใส่จากโค้ดตอนแบ่ง chunk ไม่ใช่ให้ OCR/LLM อ่านเลขหน้าเอง)
#  แล้ว Lab 8B (import-lab7b) ใช้ PROGRAM_PAGE_RANGES แยกเป็น nocoop/coop ทีหลัง
#
#  ⚠️ ช่วงหน้าที่นี่ต้องเท่ากับผลรวมของทุก section ใน PROGRAM_PAGE_RANGES
#     ของ lab8b_curriculum_db.py — run_lab8b.py ตรวจให้ทุกครั้งที่เริ่มรัน

@dataclass(frozen=True)
class RunSpec:
    program: str                          # ชื่อไฟล์ PDF (ไม่รวมนามสกุล) เช่น "IT"
    section: str | None                   # เก็บไว้เพื่อความเข้ากันได้ — ตอนนี้เป็น None ทุกรอบ
    page_ranges: list[tuple[int, int]]    # หน้าที่ต้องใช้ (1-indexed, inclusive)

    @property
    def run_id(self) -> str:
        """ชื่อโฟลเดอร์ output ของรอบรันนี้ เช่น 'IT' (section=None ทุกรอบหลังรวมแล้ว)"""
        return self.program if self.section is None else f"{self.program}_{self.section}"

    @property
    def pages_spec(self) -> str:
        """แปลง page_ranges เป็น spec ของ --pages เช่น '31-44,324-360'"""
        return ",".join(f"{a}-{b}" for a, b in self.page_ranges)


RUN_REGISTRY: list[RunSpec] = [
    RunSpec("IT",    None, [(31, 44), (324, 360)]),   # nocoop 31-37 + coop 38-44
    RunSpec("DSBA",  None, [(23, 36), (314, 341)]),   # nocoop 23-29 + coop 30-36
    RunSpec("BIT",   None, [(26, 35), (238, 257)]),   # nocoop 26-30 + coop 31-35
    RunSpec("AIT",   None, [(23, 26), (287, 304)]),
    RunSpec("GENED", None, [(39, 117)]),
]
RUNS_BY_ID: dict[str, RunSpec] = {r.run_id: r for r in RUN_REGISTRY}
PROGRAMS: list[str] = sorted({r.program for r in RUN_REGISTRY})


def resolve_input_pdf(program: str, input_dir: Path) -> Path:
    """หา <input_dir>/<PROGRAM>.pdf โดยไม่สนตัวพิมพ์เล็ก-ใหญ่ของชื่อไฟล์"""
    candidate = input_dir / f"{program}.pdf"
    if candidate.exists():
        return candidate
    for f in input_dir.glob("*.pdf"):
        if f.stem.lower() == program.lower():
            return f
    raise SystemExit(f"❌ ไม่พบไฟล์ {program}.pdf ใน {input_dir}")


# ==============================================================================
#  ส่วนที่ 1 — ตรวจความพร้อม / ยืนยันออฟไลน์
# ==============================================================================


def _need(mod: str, pipname: str = "") -> Any:
    try:
        return __import__(mod)
    except ImportError:
        raise SystemExit(f"\n❌ ไม่พบไลบรารี '{mod}'\n   ติดตั้ง: pip install {pipname or mod}\n")


def assert_offline() -> None:
    """ตรวจว่า Ollama ชี้ไปที่เครื่องตัวเอง — fail closed ถ้าไม่แน่ใจ"""
    allowed = ("127.0.0.1", "localhost", "0.0.0.0", "::1")
    host = OLLAMA_HOST.replace("http://", "").replace("https://", "").split(":")[0]
    if host not in allowed:
        raise SystemExit(
            f"\n❌ OLLAMA_HOST = {OLLAMA_HOST} ไม่ใช่เครื่องภายใน\n"
            f"   แล็บนี้กำหนดให้รันออฟไลน์เท่านั้น  แก้โดย: unset OLLAMA_HOST\n")
    print(f"✓ ยืนยันโหมดออฟไลน์: {OLLAMA_HOST}")


def check_environment() -> bool:
    ok = True
    print("\n" + "=" * 70)
    print("  ตรวจความพร้อมของเครื่อง")
    print("=" * 70)

    if shutil.which("ollama"):
        try:
            v = subprocess.run(["ollama", "--version"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
            print(f"  ✓ พบ Ollama: {v}")
        except Exception:
            print("  ✓ พบ Ollama")
    else:
        print("  ✗ ไม่พบคำสั่ง ollama --> ดูเอกสารแล็บ ส่วนที่ 2")
        ok = False

    try:
        requests = _need("requests")
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        installed = [m["name"] for m in r.json().get("models", [])]
        print(f"  ✓ Ollama service ทำงานที่ {OLLAMA_HOST}")
        for tag, role in [(MODEL_OCR, "อ่านภาพ"), (MODEL_TEXT, "จัด JSON")]:
            hit = any(i == tag or i.split(":")[0] == tag for i in installed)
            print(f"  {'✓' if hit else '✗'} [{role}] {tag}"
                  + ("" if hit else f"   --> ollama pull {tag}"))
            if not hit:
                ok = False
    except Exception as e:
        print(f"  ✗ ต่อ Ollama ไม่ได้: {e}\n    --> สั่ง: ollama serve")
        ok = False

    for mod, pip in [("fitz", "pymupdf"), ("PIL", "pillow"),
                     ("requests", "requests"), ("pdfplumber", "pdfplumber"),
                     ("pythainlp", "pythainlp")]:
        try:
            __import__(mod)
            print(f"  ✓ python: {mod}")
        except ImportError:
            print(f"  ✗ python: {mod} --> pip install {pip}")
            ok = False

    # --- ของที่ไม่จำเป็น — ขาดได้ ไม่ทำให้ --check ตก ---
    #
    # ⚠️ สังเกตว่าส่วนนี้ "ไม่มี ok = False" เลย
    #    สิ่งที่ทำให้ผลตรวจ "ไม่พร้อม" ต้องเป็นสิ่งที่ขาดแล้วรันไม่ได้จริงเท่านั้น
    print("\n  ส่วนเสริม (ขาดได้ ไม่ทำให้ --check ตก):")

    if SKIP_BASELINE:
        print("  ○ tesseract — ข้ามตามค่า LAB7_SKIP_BASELINE=1")
    else:
        has_exe = shutil.which("tesseract") is not None
        try:
            __import__("pytesseract")
            has_lib = True
        except ImportError:
            has_lib = False

        if has_exe and has_lib:
            print("  ✓ tesseract (จาก Lab 5-6) — ใช้กับ pipeline baseline")
        else:
            miss = []
            if not has_lib:
                miss.append("pip install pytesseract")
            if not has_exe:
                miss.append("ติดตั้งตัว engine (ดูเอกสาร Lab 5)")
            print(f"  ✗ tesseract — {' + '.join(miss)}")
            print("      pipeline baseline จะถูกข้ามไป (text และ vlm ยังใช้ได้ตามปกติ)")
            print("      ถ้าไม่ต้องการใช้ baseline เลย:  export LAB7_SKIP_BASELINE=1")

    print("=" * 70)
    print("  พร้อมใช้งาน ✓" if ok else "  ยังไม่พร้อม ✗")
    print("=" * 70 + "\n")
    return ok


# ==============================================================================
#  ส่วนที่ 2 — เตรียม input
# ==============================================================================


def parse_page_range(spec: str, total: int) -> list[int]:
    """
    แปลงข้อความอย่าง "42-58" หรือ "3,7,10-12" เป็น list ของ index (เริ่มที่ 0)

    ทำไมต้องมี? เพราะเล่มหลักสูตรมี 150 หน้า แต่ตารางแผนการศึกษาอยู่แค่ 10-20 หน้า
    การส่งทั้งเล่มเข้าโมเดลคือการเผาเวลาไปกับหน้าที่ไม่เกี่ยวข้อง
    (ในระบบที่จ่ายเงินตาม token นี่คือการเผาเงินด้วย)
    """
    idx: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            idx.update(range(int(a) - 1, int(b)))    # ผู้ใช้พิมพ์เลขหน้าเริ่มที่ 1
        elif part:
            idx.add(int(part) - 1)
    return sorted(i for i in idx if 0 <= i < total)


def load_pages(path: str, page_spec: str | None = None) -> list[bytes]:
    """แปลง PDF เป็นภาพ PNG รายหน้า (เวอร์ชันเดิม — คืนเฉพาะภาพ)"""
    return load_pages_with_numbers(path, page_spec)[0]


def load_pages_with_numbers(path: str, page_spec: str | None = None
                            ) -> tuple[list[bytes], list[int]]:
    """
    แปลง PDF เป็นภาพ PNG รายหน้า พร้อมเลขหน้า PDF จริง (เริ่มที่ 1) ของแต่ละภาพ

    เลขหน้ามาจาก index ของหน้าใน PDF ที่ PyMuPDF เปิด ไม่ได้มาจากการอ่านตัวเลขบนหน้ากระดาษ
    (เล่มหลักสูตรมีเลขหน้าพิมพ์ไม่ตรงกับหน้า PDF และ OCR อ่านเลขผิดได้)
    """
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"❌ ไม่พบไฟล์: {path}")

    if p.is_dir():
        image_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        files = sorted(x for x in p.iterdir() if x.suffix.lower() in image_exts)
        if not files:
            raise SystemExit(f"❌ ไม่พบไฟล์ภาพในโฟลเดอร์: {path}")
        print(f"  อ่านภาพจากโฟลเดอร์ {len(files)} หน้า: "
              + ", ".join(x.name for x in files))
        return [x.read_bytes() for x in files], list(range(1, len(files) + 1))

    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return [p.read_bytes()], [1]

    fitz = _need("fitz", "pymupdf")
    doc = fitz.open(str(p))
    wanted = parse_page_range(page_spec, len(doc)) if page_spec else range(len(doc))

    if page_spec:
        print(f"  เล่มมี {len(doc)} หน้า — เลือกใช้ {len(list(wanted))} หน้า")

    pages, nums = [], []
    for i in wanted:
        # หน้าที่ใหญ่/ยาวผิดปกติ ที่ 150 DPI จะได้ภาพหลายพัน px -> โมเดล vision ใช้ token/หน่วยความจำ
        # เกินจน Ollama ตอบ 500 (หน้าอื่นในเล่มเดียวกันยังผ่านได้) จึงจำกัดด้านยาวสุด
        rect = doc[i].rect
        zoom = DPI / 72
        if MAX_SIDE_PX and max(rect.width, rect.height) * zoom > MAX_SIDE_PX:
            zoom = MAX_SIDE_PX / max(rect.width, rect.height)
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pages.append(pix.tobytes("png"))
        nums.append(i + 1)
    doc.close()
    print(f"  แปลงเป็นภาพแล้ว {len(pages)} หน้า @ {DPI} DPI")
    return pages, nums


def extract_pdf_text(path: str, page_spec: str | None = None) -> str:
    """
    ดึงข้อความจาก PDF โดยตรง (ถ้าเป็น PDF ที่ฝังข้อความไว้ ไม่ใช่ภาพสแกน)

    ⚠️ ประเด็นสำคัญของกลุ่ม B:
       เล่มหลักสูตรจำนวนมากเป็น "digital PDF" ที่มีข้อความอยู่แล้ว
       ถ้าเป็นแบบนั้น การเอาไปทำ OCR คือการทำงานซ้ำซ้อนโดยไม่จำเป็น
       และยังทำให้ผลแย่ลง เพราะ OCR มีโอกาสอ่านผิด แต่ข้อความที่ฝังมาไม่ผิด

       --> ตรวจก่อนเสมอ ว่าดึงข้อความตรง ๆ ได้ไหม
       เกณฑ์ที่ใช้: ถ้าดึงได้เกิน 500 ตัวอักษรต่อหน้า ถือว่าเป็น digital PDF

    ⚠️ แต่มีข้อควรระวัง: extract_text() ธรรมดา "ทำตารางพัง"
       คอลัมน์จะปนกันมั่ว --> ต้องใช้ layout=True เพื่อรักษาตำแหน่ง
       นี่คือเหตุผลที่ตาราง "แผนการศึกษา" มักอ่านผิดแม้เป็น digital PDF
    """
    pdfplumber = _need("pdfplumber")
    out = []
    with pdfplumber.open(path) as pdf:
        wanted = parse_page_range(page_spec, len(pdf.pages)) if page_spec \
            else range(len(pdf.pages))
        for i in wanted:
            # layout=True รักษาระยะห่างแนวนอน ทำให้คอลัมน์ยังเรียงกันอยู่
            t = pdf.pages[i].extract_text(layout=True) or ""
            out.append(f"\n=== หน้า {i + 1} ===\n{t}")
    return "\n".join(out)


# ==============================================================================
#  ส่วนที่ 3 — JSON SCHEMA
# ==============================================================================
#
#  Schema ต้องตรงกับ ground truth (DSBA_academic_plan_coop.json) เป๊ะ ๆ
#
#  ⚠️ ข้อสังเกตจาก ground truth จริง ที่ต้องสะท้อนใน schema:
#
#   1. `year` และ `semester` เป็น "0" ได้ ซึ่งไม่ได้แปลว่าปี 0
#      แต่แปลว่า "วิชาเลือก ที่ยังไม่กำหนดว่าจะลงปีไหน/ภาคไหน"
#      กรณีนี้ต้องกรอก flexible_year_semester แทน เช่น "3/1, 3/2, 4/1"
#
#   2. `prerequisite` เป็น string ไม่ใช่ list  ถ้าไม่มีให้ใส่คำว่า "ไม่มี"
#      (ไม่ใช่ null, ไม่ใช่ [] — ต้องตรงกับ GT)
#
#   3. `credits` เป็น string รูปแบบ "3(3-0-6)"
#      แปลว่า 3 หน่วยกิต = บรรยาย 3 ชม. - ปฏิบัติ 0 ชม. - ศึกษาเอง 6 ชม.
#      บางวิชาเป็น "3(3-0-6) หรือ 3(2-2-5)" ได้ด้วย
#
#   4. `name_en` ใน GT มีอักขระขึ้นบรรทัดใหม่ (\n) ฝังอยู่
#      เพราะชื่อยาวเกินความกว้างคอลัมน์ใน PDF แล้วถูกตัดบรรทัด
#      --> เราจะจัดการด้วย normalization ไม่ใช่บังคับให้โมเดลเดาว่าตัดตรงไหน
# ==============================================================================

_S = {"type": "string"}
_SN = {"type": ["string", "null"]}

# ⭐ ลำดับ/ชุดฟิลด์ "มาตรฐาน" ของหนึ่งวิชา — ใช้ยึดเป็นฟอร์แมตกลางให้ทุก
# pipeline (vlm / markdown / text) ออกมาหน้าตาเหมือนกันเป๊ะเสมอ
#
# ⚠️ เหตุผลที่ต้องมีค่าคงที่นี้: COURSE_SCHEMA ด้านล่างกำหนด "required" ไว้แค่
#    code/name_th/name_en/credits/year/semester ฟิลด์ที่เหลือ (category, type,
#    prerequisite, flexible_year_semester, note) เป็น "ไม่บังคับ" ตามความหมาย
#    ของ JSON Schema จริง ๆ  --> โมเดลมีสิทธิ์ "ไม่ใส่ key นั้นเลย" ในแต่ละก้อน
#    ไม่ใช่แค่ใส่เป็น null  ผลคือคนละก้อนได้ชุด key ไม่เท่ากัน (เจอจริง:
#    pred_markdown.json ก้อนหนึ่งมี category/type แต่อีกก้อนกลับมี
#    flexible_year_semester/note แทน — สลับกันไปตามแต่ก้อนไหนโมเดลเลือกใส่)
#    เอา normalize_course() ไปครอบทุกแถวหลัง parse_json() ให้ได้ key ครบชุด
#    เท่ากันเสมอ ก่อนจะเข้าสู่ merge_chunks()
COURSE_FIELDS: tuple[str, ...] = (
    "code", "name_th", "name_en", "credits", "year", "semester",
    "category", "type", "prerequisite", "flexible_year_semester", "note",
)


def normalize_course(c: dict) -> dict:
    """เติม key ที่ขาดของแถววิชาหนึ่งให้ครบตาม COURSE_FIELDS (ไม่แตะ key อื่น เช่น pages)"""
    out = dict(c)
    for field in COURSE_FIELDS:
        if field not in out:
            out[field] = "ไม่มี" if field == "prerequisite" else None
    return out


# ==============================================================================
#  ส่วนที่ 3.5 — ทำความสะอาดข้อความ (post-extraction text cleaning)
# ==============================================================================
#
#  ⚠️ ที่มา: วิเคราะห์ eval_gt.json (ดู intermediate_vlm.md หัวข้อ 1) พบ 3
#  รูปแบบข้อผิดพลาดซ้ำ ๆ ที่สั่งผ่าน prompt อย่างเดียวป้องกันไม่ได้ 100%
#  (กฎ [7.5] ในพรอมป์ห้ามไว้แล้ว แต่โมเดลบางครั้งยัง "หลุด") จึงต้องมี
#  ตาข่ายชั้นสองเป็นโค้ด ทำงานหลังผลออกจากโมเดลเสมอ ไม่ว่าจะมาจาก
#  pipeline ไหน (rules-based หรือ LLM):
#
#    1. Text bleeding: วงเล็บค้าง / เลขหน่วยกิต "(3-2-5)" หลุดเข้า name_en
#    2. Noise/watermark: ข้อความหัว-ท้ายกระดาษ เช่น "มคอ. 2" หลุดเข้ามา
#    3. ภาษาอังกฤษยาวปนใน name_th (กฎ [7.5] หลุดบางครั้ง)
#
#  หลักการ: "ตัดเฉพาะสิ่งที่มั่นใจว่าเป็นขยะ" เท่านั้น ถ้าตัดแล้วข้อความว่าง
#  ให้คืนค่าดิบเดิมไว้เสมอ (กันลบเนื้อหาจริงทิ้งเกินจำเป็น)
# ==============================================================================

# เลขหน่วยกิตรูปแบบ "N(N-N-N)" หรือ "(N-N-N)" ที่หลุดเข้ามาปนในชื่อวิชา
_CREDIT_PATTERN_RE = re.compile(r"\(?\s*\d+\s*[-–]\s*\d+\s*[-–]\s*\d+\s*\)?")

# ข้อความ metadata ของเอกสาร (หัว/ท้ายกระดาษ) ที่ไม่ใช่ส่วนหนึ่งของชื่อวิชาจริง
# ⚠️ เจอ noise แบบอื่นจากเล่มอื่นเพิ่มได้เรื่อย ๆ โดยเติมใน pattern นี้
_DOC_NOISE_RE = re.compile(
    # ⚠️ "มคอ" ต้องมีจุด (มคอ.) หรือมีเลขตามหลังเท่านั้น และห้ามอยู่กลางคำไทย —
    #    รูปแบบเดิม "มคอ\.?" ไปกินตัวอักษรกลางคำ "โปรแกรม[มคอ]พิวเตอร์" (เจอจริง: 06066303)
    r"(มคอ\.\s*\d*|(?<![\u0E00-\u0E7F])มคอ\s*\d+|หน้า\s*\d+|เอกสารแนบ\s*\d*|หลักสูตรปรับปรุง\s*\S*|page\s*\d+)",
    re.IGNORECASE,
)

# คำอังกฤษ "ยาว" (>=4 ตัวติดกัน) ที่ไม่ควรอยู่ใน name_th
# (ตัวย่อสั้น ๆ ในวงเล็บ เช่น "(IoT)" ที่ตั้งใจให้อยู่คู่ชื่อไทยจริง ๆ ไม่โดนตัด)
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _strip_unmatched_parens(text: str) -> str:
    """ตัดวงเล็บเปิด/ปิดที่ไม่มีคู่ทิ้ง (วงเล็บค้างที่ปลายข้อความ)"""
    if text.count("(") != text.count(")"):
        text = re.sub(r"\(\s*$", "", text)   # วงเล็บเปิดค้างท้ายข้อความ
        text = re.sub(r"^\s*\)", "", text)   # วงเล็บปิดค้างต้นข้อความ
        if text.count("(") > text.count(")"):
            text = text[::-1].replace("(", "", 1)[::-1]
        elif text.count(")") > text.count("("):
            text = text.replace(")", "", 1)
    return text.strip()


# ตัวอักษรไทย — ใช้ตรวจ "ช่องว่างหลุดกลางวลีไทย" (ดู _join_th_parts ด้านบนสำหรับ
# ที่มาของปัญหานี้ในเส้นทาง rules_extract; เพิ่มไว้ที่นี่ด้วยเป็นตาข่ายรองรับ
# เส้นทาง LLM/baseline ที่อาจเกิดปัญหาเดียวกันจากคนละสาเหตุ)
_THAI_CHAR_RE = re.compile(r"[\u0E00-\u0E7F]")
# ช่องว่างที่อยู่ "กลางวลีไทย" (ทั้งสองฝั่งเป็นอักษรไทย ไม่ใช่ตัวเลข) — ไม่ควรมีอยู่จริง
# (ตรวจกับ ground truth แล้ว: ช่องว่างที่ถูกต้องใน name_th มีแค่หน้าตัวเลขลำดับท้ายชื่อ)
_MID_THAI_SPACE_RE = re.compile(
    r"(?<=[\u0E00-\u0E7F])[ \t]+(?=[\u0E00-\u0E7F])")


def clean_name_th(raw: str | None) -> str | None:
    """ทำความสะอาด name_th: ตัดคำอังกฤษยาว / เลขหน่วยกิต / noise เอกสารที่หลุดเข้ามา"""
    if not raw:
        return raw
    text = _DOC_NOISE_RE.sub("", raw)
    # คำอังกฤษ "เดี่ยว ๆ ท้ายชื่อไทย" ที่สั้นแบบตัวย่อ (เช่น "...สำหรับ SDGs") เป็นส่วนของชื่อจริง
    # ไม่ใช่ชื่ออังกฤษที่หลุดเข้ามา — ชื่ออังกฤษที่หลุดเข้ามามักเป็นวลีหลายคำหรือคำยาวกว่านี้
    # (ตัวย่อ <=3 ตัวอักษร เช่น "IPO" ไม่เข้าเงื่อนไข _LATIN_WORD_RE อยู่แล้ว)
    runs = _LATIN_WORD_RE.findall(text)
    keep_tail = (len(runs) == 1 and len(runs[0]) <= 5
                 and _THAI_RE.search(text)
                 and re.search(r"[A-Za-z][A-Za-z.&-]*\s*$", text))
    stripped = text if keep_tail else _LATIN_WORD_RE.sub("", text)
    if stripped.strip():          # กันลบจนว่างเปล่า (เผื่อบางวิชาชื่อเป็นคำอังกฤษล้วนจริง ๆ)
        text = stripped
    text = _MID_THAI_SPACE_RE.sub("", text)   # ช่องว่างหลุดกลางวลีไทย (บรรทัดตัดคำ)
    text = _strip_unmatched_parens(re.sub(r"\s{2,}", " ", text).strip())
    return text or raw


def clean_name_en(raw: str | None) -> str | None:
    """ทำความสะอาด name_en: ตัดเลขหน่วยกิต / noise เอกสารที่หลุดเข้ามา"""
    if not raw:
        return raw
    text = _DOC_NOISE_RE.sub("", raw)
    stripped = _CREDIT_PATTERN_RE.sub("", text)
    if stripped.strip():
        text = stripped
    text = _strip_unmatched_parens(re.sub(r"\s{2,}", " ", text).strip())
    return text or raw


# --- คำทับศัพท์ไทยที่สะกดต่างกันได้บ่อย (ปิดอยู่โดย default) -----------------------
# ⚠️ นี่คือ "normalize เพื่อให้คะแนน Eval สูงขึ้น" ตามที่ intermediate_vlm.md
#    เสนอในข้อ 1 (ปัญหาคำทับศัพท์ เช่น โรบอต vs โรบอท) ไม่ใช่การแก้ความถูกต้อง
#    ของข้อมูล เพราะสะกดไหน "ถูก" ขึ้นกับเล่มต้นฉบับจริง ไม่ใช่กฎภาษาตายตัว
#    จึงเปิดเป็น opt-in เท่านั้น (LAB7_NORMALIZE_SPELLING=1) ไม่เปิดโดย default
#    เพื่อไม่ให้การ "แก้ข้อมูลให้ตรง GT" กลายเป็นการเพิ่มคะแนนลับ ๆ โดยไม่รู้ตัว
_SPELLING_VARIANTS: dict[str, str] = {
    "โรบอท": "โรบอต",
    "คอมพิวเตอร์กราฟฟิค": "คอมพิวเตอร์กราฟิก",
    "ซอฟท์แวร์": "ซอฟต์แวร์",
}
NORMALIZE_SPELLING = os.getenv("LAB7_NORMALIZE_SPELLING", "").strip() in ("1", "true", "yes")

# ความผิดของ OCR ที่ "ไม่ใช่คำไทยที่สะกดได้" (ไม่ใช่ทางเลือกการสะกด) — แก้เสมอ ไม่ต้องเปิด flag
# เพิ่มได้เรื่อย ๆ เมื่อเจอจาก eval: รูปผิด -> รูปถูก  (ห้ามใส่คำที่มีทั้งสองแบบใช้จริง)
_THAI_OCR_FIXES: dict[str, str] = {
    "ออใจล์": "อไจล์",      # AGILE: OCR อ่าน "อไ" เป็น "ออใ"
}


def _normalize_spelling(text: str | None) -> str | None:
    if not text or not NORMALIZE_SPELLING:
        return text
    for variant, canon in _SPELLING_VARIANTS.items():
        text = text.replace(variant, canon)
    return text


def clean_course_row(c: dict) -> dict:
    """ครอบความสะอาดทั้งหมดของหนึ่งแถววิชา (เรียกหลัง normalize_course() เสมอ)"""
    out = dict(c)
    out["name_th"] = _normalize_spelling(clean_name_th(out.get("name_th")))
    out["name_en"] = clean_name_en(out.get("name_en"))
    return out


def clean_courses_output(data: dict) -> dict:
    """ครอบ clean_course_row() ให้ทุกแถวใน courses ของผลลัพธ์ทั้งชุด (ทุก pipeline)"""
    if not isinstance(data, dict):
        return data
    courses = data.get("courses")
    if courses:
        data = dict(data)
        data["courses"] = [clean_course_row(c) for c in courses]
    return data


COURSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "program": _SN,          # เช่น "DSBA"
        "plan": _SN,             # เช่น "coop" หรือ "normal"
        "courses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": _S,           # รหัสวิชา 8 หลัก
                    "name_th": _SN,
                    "name_en": _SN,
                    "credits": _SN,       # "3(3-0-6)"
                    # ⭐ เดิม type รับ "string" ด้วย ทำให้โมเดลตอบ year/semester
                    #    เป็นข้อความอิสระได้ (เช่น "ปี 2") ซึ่งกำกวมและเทียบกับ
                    #    GT (ตัวเลขล้วน) ไม่ตรง — บังคับเป็นตัวเลขจริงหรือ null เท่านั้น
                    #    0 ยังคงถูกต้อง (สงวนไว้เฉพาะวิชาเลือกที่ตารางระบุว่าลงได้
                    #    หลายภาค คู่กับ flexible_year_semester — ดูกติกา [2] ในพรอมป์
                    #    และการตรวจย้อนหลังใน verify_internal() กฎ 4)
                    "year": {"type": ["integer", "null"], "enum": [0, 1, 2, 3, 4, 5, None]},
                    "semester": {"type": ["integer", "null"], "enum": [0, 1, 2, 3, None]},
                    "category": _SN,      # หมวดวิชาศึกษาทั่วไป / เฉพาะ / เลือกเสรี
                    "type": _SN,          # บังคับ / เลือก
                    "prerequisite": _SN,  # รหัสวิชา หรือคำว่า "ไม่มี"
                    "flexible_year_semester": _SN,
                    "note": _SN,
                },
                "required": ["code", "name_th", "name_en", "credits", "year", "semester"],
            },
        },
    },
    "required": ["courses"],
}


# ==============================================================================
#  ส่วนที่ 4 — PROMPT
# ==============================================================================

SYSTEM_PROMPT = """You are a precise document extraction system for Thai university curriculum documents.
You transcribe exactly what is printed. You never invent courses that are not in the document.
You never stop early. When a field is absent you output null."""

EXTRACT_PROMPT = """ต่อไปนี้คือข้อความจากเล่มหลักสูตรของสถาบันในประเทศไทย
จงสกัดรายวิชาทั้งหมดออกมาเป็น JSON ตาม schema ที่กำหนด

=== กติกา ===

[1] สกัดทุกวิชาที่ปรากฏ ห้ามข้าม ห้ามหยุดกลางทาง
    ดูให้ครบทุกหมวด:
      - หมวดวิชาศึกษาทั่วไป
      - หมวดวิชาเฉพาะ (กลุ่มวิชาแกน / กลุ่มวิชาเฉพาะด้าน / กลุ่มวิชาบังคับ / กลุ่มวิชาเลือก)
      - หมวดวิชาเลือกเสรี
      - รายวิชาสหกิจศึกษา (ถ้ามี)

[1.5] ⭐ สกัดแบบ "ทีละแถว ตามลำดับที่ตารางพิมพ์จริง" (row-by-row) โดยยึด
      รหัสวิชาของแต่ละแถวเป็นหลัก (anchor) ห้ามเอาชื่อวิชา/หน่วยกิต/ปี-ภาค
      ของแถวหนึ่งไปประกอบกับรหัสวิชาของอีกแถวหนึ่งเด็ดขาด แม้ตารางจะมีเส้น
      แบ่งไม่ชัดหรือแถวชิดกัน ให้เทียบตำแหน่งบรรทัดของรหัสวิชากับชื่อวิชา/
      หน่วยกิตในบรรทัดเดียวกัน (หรือบรรทัดที่ตัดคำต่อกันของแถวเดียวกัน)
      ก่อนประกอบเป็นหนึ่งรายการเสมอ

[2] ปี/ภาคการศึกษา — อ่านให้ดี ตรงนี้ผิดกันบ่อย
    - วิชาบังคับที่ตารางแผนการศึกษาระบุปี/ภาคชัดเจน
        --> ใส่ year = 1..4 และ semester = 1..3 ตามที่ระบุ
        --> flexible_year_semester = null
    - วิชาเลือก ที่ตารางบอกว่าลงได้หลายภาค
        --> ใส่ year = 0 และ semester = 0
        --> แล้วระบุตัวเลือกใน flexible_year_semester เช่น "3/1, 3/2, 4/1"
    ห้ามเดาปี/ภาคให้วิชาเลือกที่เอกสารไม่ได้ระบุ
    ⭐ year=0/semester=0 คือค่าพิเศษเฉพาะกรณี "วิชาเลือกยืดหยุ่น" เท่านั้น
       ห้ามใช้ 0 เป็นค่า default เวลาไม่แน่ใจ หรืออ่านคอลัมน์ปี/ภาคไม่ทัน
       ถ้าตารางระบุปี/ภาคของแถวนั้นไว้ชัดเจน ต้องใส่ตัวเลขจริงตามตารางเสมอ
       ทุกครั้งที่ตอบ year=0 และ semester=0 ต้องมี flexible_year_semester
       ที่ไม่ใช่ null กำกับด้วยเสมอ ไม่เช่นนั้นถือว่าอ่านตารางผิด

[3] prerequisite (วิชาบังคับก่อน)
    - ถ้ามี ให้ใส่ "รหัสวิชา" ของวิชาบังคับก่อน เช่น "06026200"
    - ถ้าไม่มี ให้ใส่คำว่า "ไม่มี"  (ห้ามใส่ null ห้ามใส่ [])
    - ⚠️ ข้อความที่ป้อนให้ตรงนี้คือตาราง "แผนการศึกษา" ซึ่งปกติไม่มีคอลัมน์นี้จริง
      อย่าเดาโดยอาศัยความรู้ทั่วไปว่าวิชาไหน "น่าจะ" ต้องเรียนก่อน — ถ้าไม่เห็น
      ข้อความระบุชัดเจนในเอกสารตรงหน้า ให้ใส่ "ไม่มี" เสมอ (ค่านี้จะถูกแทนที่ทีหลัง
      ด้วยค่าที่ดึงจากหน้า "คำอธิบายรายวิชา" อยู่แล้ว ซึ่งเป็นแหล่งข้อมูลที่ถูกต้องจริง)

[4] credits ให้คัดลอกตามที่พิมพ์ เช่น "3(3-0-6)" หรือ "3(2-2-5)"
    ห้ามแปลงเป็นตัวเลขเดี่ยว  ถ้าเอกสารเขียนสองแบบ ให้คงไว้ทั้งสอง
    เช่น "3(3-0-6) หรือ 3(2-2-5)"

[5] category ต้องเป็นหนึ่งใน 3 ค่านี้เท่านั้น:
    "หมวดวิชาศึกษาทั่วไป" | "หมวดวิชาเฉพาะ" | "หมวดวิชาเลือกเสรี"

[6] type ต้องเป็น "บังคับ" หรือ "เลือก" เท่านั้น

[7] ชื่อวิชาภาษาอังกฤษ ให้คัดลอกตามที่พิมพ์ รวมทั้งตัวพิมพ์ใหญ่
    ถ้าชื่อถูกตัดขึ้นบรรทัดใหม่ในเอกสาร ให้ต่อเป็นบรรทัดเดียวโดยเว้นวรรค 1 ครั้ง

[7.5] ⭐ ห้ามเอาชื่ออังกฤษไปปนในฟิลด์ name_th เด็ดขาด แม้ในต้นฉบับชื่อไทยกับ
      อังกฤษจะอยู่ติดกัน (เช่น ชื่อไทยแล้วขึ้นบรรทัดใหม่เป็นชื่ออังกฤษตัวพิมพ์ใหญ่ทันที)
      ให้แยกเก็บเสมอ: name_th = เฉพาะข้อความภาษาไทยล้วน ๆ,
      name_en = เฉพาะข้อความภาษาอังกฤษล้วน ๆ ห้ามมีคำอังกฤษหลงเหลือใน name_th
      ห้ามเอาตัวเลขหน่วยกิต เช่น "(3-2-5)" ไปปนในฟิลด์ name_en เด็ดขาด ตัวเลข
      แบบนี้อยู่ในฟิลด์ credits เท่านั้น ถ้าเห็นมันติดอยู่หน้า/หลังชื่ออังกฤษ
      ให้ตัดออกจาก name_en ก่อนตอบเสมอ

[7.6] ⭐ ห้ามเอาข้อความ metadata ของเอกสาร (เช่น "มคอ.", "มคอ. 2", เลขหน้า
      กระดาษ "หน้า X", "เอกสารแนบ") ไปปนในฟิลด์ name_th หรือ name_en เด็ดขาด
      แม้ข้อความเหล่านี้จะอยู่ใกล้ชื่อวิชาในตำแหน่งเดียวกับหัว/ท้ายกระดาษก็ตาม
      มันไม่ใช่ส่วนหนึ่งของชื่อวิชา

[7.7] ⭐ ถ้าชื่อวิชา (ทั้ง name_th และ name_en) มีตัวเลขลำดับกำกับท้ายชื่อ
      (เช่น "หัวข้อพิเศษทางด้านเทคโนโลยีสารสนเทศ 1", "ELECTIVE COURSE 2")
      ต้องเก็บตัวเลขลำดับนั้นไว้เสมอ ห้ามตัดออกเด็ดขาด แม้ตัวเลขจะดูเหมือน
      ไม่มีความหมาย — มันคือส่วนหนึ่งของชื่อวิชาที่ใช้แยกวิชาคนละรายการออกจากกัน
      (เช่น "หัวข้อพิเศษ... 1" กับ "หัวข้อพิเศษ... 2" คือคนละวิชา ห้ามรวมเป็นชื่อเดียว)

[8] ⭐ แถว "ช่องวิชาเลือก" ที่ยังไม่ระบุวิชาเจาะจง
    ในตารางแผนการศึกษา บางแถวไม่ได้ระบุรหัสวิชาจริง แต่เขียนว่า
    "วิชาเลือกกลุ่ม..." หรือ "วิชาเลือกเสรี" พร้อมรหัสที่มี x เช่น
        06026xxx  9064xxxx  xxxxxxxx
    แถวเหล่านี้ "เป็นข้อมูลจริง" ต้องสกัดออกมาด้วย ห้ามข้าม
    ให้คัดลอกรหัสตามที่พิมพ์ (เก็บตัว x ไว้) และคัดลอกชื่อตามที่พิมพ์
    ถ้ามีหลายแถวชื่อคล้ายกัน ให้แยกเป็นคนละรายการ เช่น
        "วิชาเลือกกลุ่มวิทยาการข้อมูล 1" และ "วิชาเลือกกลุ่มวิทยาการข้อมูล 2"

[9] ห้ามสร้างวิชาที่ไม่มีในเอกสาร ห้ามเติมวิชาที่ "น่าจะมี"
    ถ้าไม่แน่ใจว่าแถวนั้นเป็นวิชาหรือไม่ ให้ข้าม ดีกว่าใส่ข้อมูลผิด
    (แต่แถวช่องวิชาเลือกตามข้อ [8] ถือเป็นวิชา ต้องเก็บ)

=== ข้อความจากเอกสาร ===
{document_text}

=== สิ้นสุดข้อความ ===
ตอบเป็น JSON เท่านั้น"""

TYPHOON_PROMPT = """Extract all text from the image.

Instructions:
- Only return the clean Markdown.
- Do not include any explanation or extra text.
- You must include all information on the page.

Formatting Rules:
- Tables: Render tables using <table>...</table> in clean HTML format.
- Equations: Render equations using LaTeX syntax with inline ($...$) and block ($$...$$).
- Watermarks, background seals, stamps, or faint institutional logos printed across the page (e.g. a translucent circular emblem behind the text) are page decoration, not content. Ignore them completely: do not wrap them in <figure> tags, do not describe them, do not mention them at all.
- Images/Charts/Diagrams: Wrap only clearly defined, intentional visual content (e.g. charts, diagrams, photos placed inline with the text — NOT background watermarks/seals) in:

<figure>
Describe the image's main elements (people, objects, text), note any contextual clues (place, event, culture), mention visible text and its meaning, provide deeper analysis when relevant (especially for financial charts, graphs, or documents), comment on style or architecture if relevant, then give a concise overall summary. Describe in Thai.
</figure>

- Page Numbers: Wrap page numbers in <page_number>...</page_number> (e.g., <page_number>14</page_number>).
- Checkboxes: Use ☐ for unchecked and ☑ for checked boxes."""


# ==============================================================================
#  ส่วนที่ 5 — เรียก Ollama
# ==============================================================================


def ollama_chat(model: str, messages: list[dict], *, fmt: dict | None = None,
                images: list[bytes] | None = None, temperature: float = 0.0,
                retries: int = 2, think: bool | None = None,
                num_ctx: int | None = None,
                num_predict: int | None = None) -> str:
    """เหมือนกับของกลุ่ม A — ดูคำอธิบายละเอียดในเอกสารแล็บ ส่วนที่ 4"""
    requests = _need("requests")

    if images:
        messages = [dict(m) for m in messages]
        messages[-1]["images"] = [base64.b64encode(im).decode() for im in images]

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx or NUM_CTX,
            "num_predict": num_predict or NUM_PREDICT,
        },
    }
    if fmt is not None:
        payload["format"] = fmt
    if think is not None:
        payload["think"] = think

    last: Exception | None = None
    repeat_hits = 0
    for attempt in range(retries + 1):
        try:
            if repeat_hits:
                # โมเดลวนซ้ำ (loop) จน Ollama ตัดทิ้ง: ลองซ้ำด้วยค่าเดิมได้ผลเดิมเสมอ (อุณหภูมิต่ำ = ผลเดิม)
                # จึงเพิ่มโทษการซ้ำและความสุ่มทีละขั้น + เปลี่ยน seed
                payload["options"].update(
                    repeat_penalty=round(1.1 + 0.1 * repeat_hits, 2),
                    temperature=min(0.1 + 0.2 * repeat_hits, 0.7),
                    top_p=0.6,
                    seed=1000 + repeat_hits,
                )
            t0 = time.time()
            r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload,
                              timeout=REQUEST_TIMEOUT)
            if r.status_code >= 400:
                # ข้อความจริงจาก Ollama (เช่น หน่วยความจำไม่พอ / runner ล้ม) อยู่ใน body
                # raise_for_status() ทิ้งส่วนนี้ ทำให้เห็นแค่ "500 Server Error"
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
            body = r.json()
            content = body["message"]["content"]
            # eval_count = จำนวน token ที่โมเดลผลิต — ใช้ดูว่าโดนตัดหรือไม่
            n_out = body.get("eval_count", 0)
            print(f"      ({model}: {time.time() - t0:.1f} วิ, "
                  f"{len(content):,} ตัวอักษร, {n_out:,} tokens)")
            if n_out >= payload["options"]["num_predict"] - 8:
                print("      ⚠ ผลลัพธ์อาจถูกตัดเพราะชน num_predict "
                      "--> ลดจำนวนหน้าต่อ chunk หรือเพิ่ม num_predict")
            if not content.strip():
                raise ValueError("โมเดลตอบว่าง")
            return content
        except Exception as e:
            last = e
            if "repeat limit" in str(e):
                repeat_hits += 1
            if attempt < retries:
                extra = (f" (รอบถัดไปเพิ่ม repeat_penalty={round(1.1 + 0.1 * repeat_hits, 2)}) " if "repeat limit" in str(e) else "")
                print(f"      ⚠ ลองใหม่ {attempt + 1}: {e}{extra}")
                time.sleep(3)
    raise RuntimeError(f"เรียก {model} ไม่สำเร็จ: {last}")


def parse_json(text: str) -> dict:
    t = re.sub(r"<think>.*?</think>", "", text.strip(), flags=re.DOTALL)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.MULTILINE)
    starts = [p for p in (t.find("{"), t.find("[")) if p != -1]
    if not starts:
        raise ValueError(f"ไม่พบ JSON:\n{text[:400]}")
    obj, _ = json.JSONDecoder().raw_decode(t[min(starts):])
    return obj


# ==============================================================================
#  ส่วนที่ 6 — การรวมผลจากหลาย chunk
# ==============================================================================


def merge_chunks(chunks: list[dict]) -> dict:
    """
    รวมผลจากหลาย chunk เข้าเป็นชุดเดียว

    ⚠️ ปัญหาที่ต้องแก้: วิชาซ้ำ
       ถ้าหน้าที่ 5 และหน้าที่ 6 มีตารางที่คาบเกี่ยวกัน วิชาเดียวกันจะถูก
       สกัดออกมาสองครั้ง  ถ้าไม่กรอง จำนวนวิชาจะเกินจริง

    ⚠️ แต่ระวัง! ในหลักสูตร DSBA จริง รหัส 06026259 (สหกิจศึกษา)
       ปรากฏ 2 แถวโดยตั้งใจ:
         แถวหนึ่ง เป็นวิชาบังคับ ปี 4 ภาค 2
         อีกแถวหนึ่ง เป็นวิชาเลือก ที่ยังไม่กำหนดปี/ภาค (year=0)
       --> กุญแจสำหรับกันซ้ำจึงต้องเป็น (รหัส, ปี, ภาค) ไม่ใช่รหัสอย่างเดียว
           ถ้าใช้รหัสอย่างเดียว เราจะ "ลบข้อมูลจริง" ทิ้งไปโดยไม่รู้ตัว

    บทเรียน: การกันซ้ำที่ก้าวร้าวเกินไป อันตรายกว่าการปล่อยให้ซ้ำ

    ⚠️ ตั้งแต่แก้ ส่วนที่ 6.5: chunks ที่ส่งเข้าฟังก์ชันนี้จะมีแต่ก้อนจากตาราง
    "แผนการศึกษา" เท่านั้น (ก้อนหน้า "คำอธิบายรายวิชา" ถูกกรองออกไปดึงเฉพาะ
    prerequisite ด้วย regex ใน _text_to_json_chunked ก่อนเรียกฟังก์ชันนี้แล้ว)
    จึงไม่มีแถว "ปลอม" จากหน้าคำอธิบายมาแข่งกับแถวตารางที่ถูกต้องอีกต่อไป
    """
    by_key: dict[tuple, dict] = {}
    courses: list[dict] = []
    n_dup = 0

    for ch in chunks:
        for c in ch.get("courses") or []:
            # ⚠️ ต้องรวม name_th ในกุญแจด้วย ไม่งั้นแถว "06026xxx" ที่มีสองแถว
            #    ในภาคเดียวกัน (วิชาเลือกกลุ่มฯ 1 และ 2) จะถูกลบทิ้งไปหนึ่ง
            key = (
                M.normalize(c.get("code"), "strict"),
                str(c.get("year")),
                str(c.get("semester")),
                M.normalize(c.get("name_th"), "strict"),
            )
            if key in by_key:
                # ⚠️ อย่าแค่ทิ้ง: วิชาเดียวกัน ปี/ภาคเดียวกัน มักปรากฏทั้งในแผนไม่สหกิจ
                #    และแผนสหกิจ (คนละหน้า) ถ้าทิ้งแถวหลัง เลขหน้าฝั่งสหกิจจะหาย
                #    แล้ว Lab 8B จะเห็นว่าวิชานี้อยู่แผนเดียว -> วิชาหายจากอีกแผนเงียบ ๆ
                n_dup += 1
                old = by_key[key]
                pages = sorted({*(old.get("pages") or []), *(c.get("pages") or [])})
                if pages:
                    old["pages"] = pages
                continue
            by_key[key] = c
            courses.append(c)

    for c in courses:
        if c.get("pages"):
            c["source_page"] = c["pages"][0]     # หน้าแรกที่เจอ (ไว้อ้างอิง)

    if n_dup:
        print(f"      รวมวิชาซ้ำ {n_dup} รายการ (คีย์ = รหัส+ปี+ภาค+ชื่อ; เก็บเลขหน้าไว้ครบทุกที่ที่พบ)")

    return {
        "program": next((ch.get("program") for ch in chunks if ch.get("program")), None),
        "plan": next((ch.get("plan") for ch in chunks if ch.get("plan")), None),
        "courses": courses,
    }


# ==============================================================================
#  ส่วนที่ 6.5 — ดึง prerequisite จากหน้า "คำอธิบายรายวิชา" ด้วย regex (ไม่พึ่ง LLM)
# ==============================================================================
#
#  ⚠️ กฎที่ยืนยันจากการเทียบกับ PDF จริง (ต้นเหตุที่ name_th/category/type ผิดบ่อย):
#
#     รหัสวิชา / ชื่อ / หน่วยกิต / ปี-ภาค / หมวดวิชา / บังคับ-เลือก
#         --> ต้องมาจาก "ครั้งแรกที่เจอ" เท่านั้น (คือแถวในตาราง "แผนการศึกษา")
#             ห้ามให้หน้า "คำอธิบายรายวิชา" มาทับค่าพวกนี้ หรือสร้างวิชาใหม่ซ้ำรหัสเดิม
#
#     prerequisite (วิชาบังคับก่อน)
#         --> ต้องมาจากหน้า "คำอธิบายรายวิชา" เท่านั้น เพราะตาราง "แผนการศึกษา"
#             ไม่เคยมีคอลัมน์นี้จริง ๆ ในเล่มหลักสูตร
#
#  ก่อนแก้: ทั้งสองอย่างถูกขอจาก LLM ตัวเดียวกันพร้อมกันในทุกหน้า (รวมหน้า
#  คำอธิบายด้วย) ผลคือหน้าคำอธิบายกลายเป็น "แถววิชาซ้ำ" รหัสเดิม แต่:
#    - name_th มักปนชื่ออังกฤษ (เพราะบนหน้าคำอธิบาย ชื่อไทย+อังกฤษอยู่ติดกันมาก
#      กว่าในตาราง โมเดลเลยงงบ่อยกว่า)
#    - year/semester มั่ว เพราะหน้าคำอธิบายไม่มีบริบทตารางให้อ้างอิงปี/ภาคเลย
#    - category/type เป็น None เพราะหน้าคำอธิบายไม่มีข้อมูลนี้
#  แถวปลอมนี้กลายเป็นอีก "รหัส+ปี/ภาค+ชื่อ" ที่ไม่ตรงกับแถวตาราง จึงไม่ถูกกรองซ้ำ
#  ใน merge_chunks() และหลุดเข้าไปแข่งกับแถวตารางที่ถูกต้องตอนประเมินผล
#
#  ทางแก้: แยกสองงานนี้ออกจากกันเด็ดขาด — หน้าคำอธิบายรายวิชาจะไม่ถูกส่งให้ LLM
#  สกัดเป็น "courses" อีกต่อไป ใช้ regex ดึงเฉพาะ (รหัส -> prerequisite) แทน
#  เพราะรูปแบบ "วิชาบังคับก่อน : ..." ในเอกสารคงที่พอที่ regex แม่นกว่า LLM มาก
#  แล้วนำผลไปทับฟิลด์ prerequisite ของแถวตารางเท่านั้น (ดู _text_to_json_chunked)

_DESC_SECTION_MARKERS = ("คำอธิบายรายวิชา", "วิชาบังคับก่อน", "PREREQUISITE")

# หัวข้อวิชาใหม่ในหน้าคำอธิบาย = รหัส 8 หลักที่ขึ้นต้นบรรทัด ตัดเนื้อหาไปจนถึง
# รหัส 8 หลักตัวถัดไป (หรือจบข้อความ) มาเป็น "บล็อกของวิชานั้น" หนึ่งบล็อก
_DESC_COURSE_HEAD_RE = re.compile(
    r"(?m)^(?P<code>\d{8})\s+(?P<rest>.*?)(?=^\d{8}\s|\Z)", re.DOTALL)
_DESC_PREREQ_RE = re.compile(r"วิชาบังคับก่อน\s*[:：]\s*(?P<line>.+)")


def is_description_chunk(text: str) -> bool:
    """
    เดาว่าก้อนข้อความนี้คือหน้า "คำอธิบายรายวิชา" ไม่ใช่ตาราง "แผนการศึกษา"

    ใช้ตรวจจับจากเนื้อหา (มีคำว่า "วิชาบังคับก่อน" ฯลฯ แต่ไม่มี <table>)
    แทนการอิงเลขหน้า เพราะบางโปรแกรม (เช่น GENED) ไม่มีช่วงหน้าคำอธิบายแยก
    ออกมาเป็นรอบต่างหากใน RUN_REGISTRY เหมือน IT/DSBA/BIT/AIT
    """
    has_marker = any(m in text for m in _DESC_SECTION_MARKERS)
    has_table = "<table" in text
    return has_marker and not has_table


def parse_prerequisites_from_description(text: str) -> dict[str, str]:
    """
    ดึง {รหัสวิชา: prerequisite} จากข้อความหน้า "คำอธิบายรายวิชา" ด้วย regex ล้วน ๆ

    รูปแบบที่เจอจริง (ดูตัวอย่างจาก intermediate_vlm.md):
        06046401 แคลคูลัส 2 (3-0-6)
        CALCULUS 2
        วิชาบังคับก่อน : 06046400 แคลคูลัส 1
        PREREQUISITE : 06046400 CALCULUS 1
        <เนื้อหารายวิชา...>

    ไม่เรียก LLM เลย — เอาโค้ด 8 หลักที่ขึ้นต้นบรรทัดเป็นหัวข้อวิชา ตัดข้อความ
    จนถึงโค้ดตัวถัดไปเป็นบล็อกของวิชานั้น แล้วหาบรรทัด "วิชาบังคับก่อน :" ในบล็อก
    """
    out: dict[str, str] = {}
    for m in _DESC_COURSE_HEAD_RE.finditer(text):
        code = m.group("code")
        pm = _DESC_PREREQ_RE.search(m.group("rest"))
        if not pm:
            continue
        line = pm.group("line").splitlines()[0].strip()
        codes = re.findall(r"(?<!\d)\d{8}(?!\d)", line)
        prereq = ", ".join(codes) if codes else "ไม่มี"
        # โค้ดเดียวกันอาจถูกตัดคร่อมสองก้อน (ขอบเขต chunk ไม่พอดีกับขอบเขตวิชา)
        # ถ้าเจอซ้ำ ให้ยึดค่าที่ "มีรหัสจริง" มากกว่าค่า "ไม่มี"
        if code in out and out[code] != "ไม่มี":
            continue
        out[code] = prereq
    return out


# ==============================================================================
#  ส่วนที่ 6.6 — สกัดด้วย "กฎ" (rule-based) จาก Markdown โดยตรง ไม่พึ่ง LLM
# ==============================================================================
#
#  ทำไมต้องมี: ผลจริงของ AIT (intermediate_vlm.md อ่านถูกหมดแล้ว) แต่ขั้น
#  Markdown -> JSON ด้วย qwen3:4b พังสองแบบที่ prompt แก้ไม่ได้
#
#    (1) โมเดลทำตาราง "ปีที่ 1 ภาคการศึกษาที่ 2" หล่นทั้งตาราง (จาก 95 แถวเหลือ
#        แผนจริงแค่ 32 รหัส) ทั้งที่ตารางอยู่ในหน้าเดียวกับภาคที่ 1 ที่อ่านได้
#    (2) OCR ขีด '---' คั่นกลางหน้า ทำให้ก้อนที่เหลือมีแต่บรรทัดท้ายกระดาษ
#        "วท.บ.(...) คณะ... สจล." — โมเดลไม่มีอะไรให้สกัดจึง "แต่ง" วิชาขึ้นมาเอง
#        (06026200 วิทยาการข้อมูล 1..20 ฯลฯ เกือบ 60 แถวปลอม)
#
#  แต่รูปแบบของเอกสารตายตัวมาก:
#     "ปีที่ N ภาคการศึกษาที่ M" + <table> (รหัส | ชื่อไทย<br/>ชื่ออังกฤษ | หน่วยกิต)
#     หน้าคำอธิบาย: "<รหัส> <ชื่อไทย> (t-l-s)" / ชื่ออังกฤษ / "วิชาบังคับก่อน : ..."
#  ตัวแยกด้วยกฎอ่านได้ครบและแม่นกว่า และตรวจตัวเองได้ด้วยแถว "รวม" ของแต่ละตาราง
#
#  ลำดับความเชื่อถือ (เหมือนหลักการเดิมของส่วน 6.5):
#     รหัส/ชื่อ/หน่วยกิต/ปี-ภาค      <- แถวในตาราง "แผนการศึกษา" เสมอ
#     prerequisite / หมวด / ประเภท   <- หน้า "คำอธิบายรายวิชา" (+ หัวข้อกลุ่มวิชา)
#     วิชาที่มีแต่ในคำอธิบาย          <- เพิ่มเป็นวิชาเลือก year=0/semester=0
#
#  ปิดได้ด้วย  LAB7_EXTRACT=llm  (กลับไปใช้ LLM เดิมทั้งหมด)
#  ตั้ง        LAB7_ALT_MODE=single  ถ้าเฉลยเขียนสหกิจ "A หรือ B" เป็นแถวเดียว
#              (ค่าเริ่มต้น split = แยกสองแถว ตรงกับเฉลย AIT)

import html as _html

EXTRACT_MODE = os.getenv("LAB7_EXTRACT", "rules").strip().lower()     # rules | llm
ALT_MODE = os.getenv("LAB7_ALT_MODE", "split").strip().lower()        # split | single

_THAI_RE = re.compile(r"[\u0E00-\u0E7F]")
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_TERM_HEAD_RE = re.compile(
    r"ปีที่\s*(\d+)\s*ภาค(?:การศึกษา)?\s*(?:ที่\s*)?(ฤดูร้อน|\d+)")
_TABLE_OR_HEAD_RE = re.compile(
    r"(?P<table><table.*?</table>)"
    r"|(?P<plan>แผนการศึกษา(?:ที่)?\s*(?P<neg>ไม่)?\s*(?:เข้า(?:ร่วม)?|สำหรับ)?\s*โครงการสหกิจศึกษา)"
    r"|(?P<head>ปีที่\s*\d+\s*ภาค(?:การศึกษา)?\s*(?:ที่\s*)?(?:ฤดูร้อน|\d+))",
    re.DOTALL | re.IGNORECASE)
_CREDIT_PART_RE = re.compile(
    r"(\d+)\s*\(\s*([0-9xX]+)\s*-\s*([0-9xX]+)\s*-\s*([0-9xX]+)\s*\)")
_TOTAL_CREDITS_RE = re.compile(r"รวมตลอดหลักสูตร\s*(\d+)\s*หน่วยกิต")
_FOOTER_MARK_RE = re.compile(r"^.{0,12}\.บ\.?\s*\(.*\).*สจล")   # วท.บ.(...) คณะ... สจล.

# หมวดวิชา จากรหัส/ชื่อ เมื่อไม่มีหน้าคำอธิบายของวิชานั้น (เช่น วิชาศึกษาทั่วไป 9064xxxx
# ที่ไม่มีคำอธิบายอยู่ในช่วงหน้าของเล่มนี้) — เป็น "ข้อสันนิษฐานจากรหัส" ไม่ใช่ข้อความในเล่ม
# ชื่อหมวดวิชาเลือกเสรีที่เฉลยใช้ — เฉลย AIT เขียน "หมวดวิชาเสรี" (ไม่มีคำว่า เลือก)
# ถ้าเฉลยของโปรแกรมอื่นใช้ "หมวดวิชาเลือกเสรี" ให้ตั้ง LAB7_CATEGORY_FREE=หมวดวิชาเลือกเสรี
#
# ⭐ ชื่อหมวดนี้ต่างกันตามเฉลยของแต่ละโปรแกรม (AIT = "หมวดวิชาเสรี", IT/อื่น ๆ = "หมวดวิชาเลือกเสรี")
#    ตั้งจากชื่อโปรแกรมอัตโนมัติ (process_one เรียก set_current_program) — บังคับเองได้ด้วย env LAB7_CATEGORY_FREE
_CATEGORY_FREE_ENV = os.getenv("LAB7_CATEGORY_FREE", "").strip()
_CATEGORY_FREE_BY_PROGRAM = {"AIT": "หมวดวิชาเสรี"}
_CURRENT_PROGRAM = ""


def set_current_program(name: str) -> None:
    global _CURRENT_PROGRAM
    _CURRENT_PROGRAM = name


def category_free() -> str:
    if _CATEGORY_FREE_ENV:
        return _CATEGORY_FREE_ENV
    tokens = {t.upper() for t in re.split(r"[^A-Za-z0-9]+", _CURRENT_PROGRAM) if t}
    for prog, cat in _CATEGORY_FREE_BY_PROGRAM.items():
        if prog in tokens:
            return cat
    return "หมวดวิชาเลือกเสรี"


def _canon_category(cat: str | None) -> str | None:
    return category_free() if cat and "เสรี" in cat else cat


def _category_by_prefix(code: str, desc: dict[str, dict]) -> str | None:
    """รหัสตัวแทน 060164xx -> หมวดของวิชาจริงที่ขึ้นต้นเหมือนกัน (ต้องมีคำอธิบายวิชาที่ขึ้นต้น >= 5 หลักตรงกัน)"""
    prefix = code.rstrip("x")
    if len(prefix) < 5:
        return None
    cats = Counter(d["category"] for c, d in desc.items() if c.startswith(prefix) and d.get("category"))
    return cats.most_common(1)[0][0] if cats else None


# ใช้เป็นทางสำรองเท่านั้น (เมื่อหัวข้อ "หมวดวิชา..." ในเล่มไม่ถูกอ่านมา) — เล่มที่มีหัวข้อครบไม่ผ่านตรงนี้
CATEGORY_BY_CODE_PREFIX: tuple[tuple[str, str], ...] = (
    ("90", "หมวดวิชาศึกษาทั่วไป"),
    ("96", "หมวดวิชาศึกษาทั่วไป"),      # BIT (หลักสูตรนานาชาติ): 96641xxx-96644xxx, 9664xxxx
    ("06036", "หมวดวิชาเฉพาะ"),          # BIT
)


def _clean_cell(raw: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s).replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


_BROKEN_HEAD_RE = re.compile(
    r"<tr[^>]*>\s*<th[^>]*>\s*รหัสวิชา\s*<th[^>]*>\s*ชื่อวิชา\s*"
    r"<t[dh][^>]*>(?P<cred>.*?)</t[dh]>(?:\s*</t[dh]>)*\s*</tr>",
    re.DOTALL | re.IGNORECASE)


def _repair_table_html(table_html: str) -> str:
    """
    VLM บางครั้งเขียน header ตารางแผนแบบ <th>รหัสวิชา<th>ชื่อวิชา<td>หน่วยกิต</td></th></th>
    (th ซ้อน th + rowspan=2) ทำให้ regex แตกเซลล์ได้ช่องเดียว -> i_code = i_name = i_cred = 0
    (หน่วยกิต/ชื่อวิชาถูกเขียนทับด้วยรหัสวิชา) และ rowspan รั่วไปทับแถวข้อมูลแถวแรก
    ซ่อมให้เป็นแถว header ปกติ 3 ช่อง ไม่มี rowspan
    """
    def fix(m: re.Match) -> str:
        cred = re.sub(r"^\s*-\s*", "", m.group("cred"))
        return f"<tr><td>รหัสวิชา</td><td>ชื่อวิชา</td><td>{cred}</td></tr>"
    return _BROKEN_HEAD_RE.sub(fix, table_html)


def _table_grid(table_html: str) -> list[tuple[list[str], list[bool]]]:
    """แตก <table> เป็นตารางสี่เหลี่ยม (ขยาย rowspan/colspan) คืน [(cells, inherited_flags)]"""
    table_html = _repair_table_html(table_html)
    grid: list[tuple[list[str], list[bool]]] = []
    carry: dict[int, list] = {}        # col -> [แถวที่เหลือ, ข้อความ]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", tr, re.DOTALL | re.IGNORECASE)
        row: list[str] = []
        inh: list[bool] = []

        def flush() -> None:
            while len(row) in carry:
                c = len(row)
                row.append(carry[c][1])
                inh.append(True)
                carry[c][0] -= 1
                if carry[c][0] <= 0:
                    del carry[c]

        for attrs, inner in cells:
            flush()
            text = _clean_cell(inner)
            rs = re.search(r"rowspan\s*=\s*[\"']?(\d+)", attrs, re.IGNORECASE)
            cs = re.search(r"colspan\s*=\s*[\"']?(\d+)", attrs, re.IGNORECASE)
            rowspan = int(rs.group(1)) if rs else 1
            colspan = int(cs.group(1)) if cs else 1
            for _ in range(colspan):
                if rowspan > 1:
                    carry[len(row)] = [rowspan - 1, text]
                row.append(text)
                inh.append(False)
        flush()
        if row:
            grid.append((row, inh))
    return grid


def _norm_code_token(tok: str) -> str | None:
    """รหัสวิชา 8 หลัก หรือ wildcard (มี x) ที่ปรับให้ยาว 8 ตัวเสมอ; ไม่ใช่รหัส -> None"""
    t = re.sub(r"\s+", "", tok).lower().translate(_THAI_DIGITS)
    if not re.fullmatch(r"[0-9x]{6,12}", t):
        return None
    if "x" not in t:
        return t if len(t) == 8 else None
    if set(t) == {"x"}:
        return "x" * 8
    digits = re.match(r"\d*", t).group()      # OCR มักทำ x เกิน/ขาด (xxxxxxxxxxx, xXXXXXXXX)
    return digits[:8].ljust(8, "x") if len(t) != 8 else t


def _split_codes(cell: str) -> list[str]:
    out: list[str] = []
    for piece in re.split(r"หรือ|\n|,|/", cell):
        code = _norm_code_token(piece)
        if code:
            out.append(code)
        else:                                # "96643021 06036xxx" คั่นด้วยช่องว่าง (rowspan รวมรหัส)
            out.extend(c for c in map(_norm_code_token, piece.split()) if c)
    return out


def _norm_credits(text: str) -> str | None:
    """'3 (3-0-6)' -> '3(3-0-6)' ; '3(x-x-x)' คงไว้ ; มีสองแบบให้คั่น ' หรือ '"""
    text = text.translate(_THAI_DIGITS)
    found = [f"{a}({b}-{c}-{d})".lower() for a, b, c, d in _CREDIT_PART_RE.findall(text)]
    found = list(dict.fromkeys(found))
    if found:
        return " หรือ ".join(found)
    m = re.search(r"(?<!\d)\d{1,2}(?!\d)", text)     # หน่วยกิตเดี่ยว 1-2 หลักเท่านั้น (กันรหัสวิชาหลุดมา)
    return m.group() if m else None


def _split_th_en(text: str) -> tuple[str, str | None]:
    """
    แยกชื่อไทย / ชื่ออังกฤษ  ทั้งกรณีขึ้นบรรทัดใหม่ (<br/>) และกรณีติดกันบรรทัดเดียว
    ("การประมวลผลสัญญาณ SIGNAL PROCESSING") — กฎ: ส่วนอังกฤษคือหางของข้อความที่
    ไม่มีตัวไทยเลย และขึ้นต้นด้วยตัวอักษรละติน
    """
    text = text.replace("**", "").strip()
    text = re.sub(r"\s*หรือ\s*$", "", text)
    tokens = text.split()
    for k in range(len(tokens)):
        tail = tokens[k:]
        # ชื่ออังกฤษที่ครอบด้วยวงเล็บ "(ADVANCED DATABASE SYSTEMS)" ต้องนับเป็นส่วนอังกฤษด้วย
        # (ตัวย่อสั้น ๆ เช่น "(IoT)" ยังถือเป็นส่วนของชื่อไทย — ต้องมีตัวอักษรละติน >= 4 ตัวหลัง "(")
        starts_en = bool(re.match(r"[A-Za-z]", tail[0]) or re.match(r"\([A-Za-z]{4,}", tail[0]))
        if starts_en and not any(_THAI_RE.search(t) for t in tail):
            th = " ".join(tokens[:k]).strip()
            en = re.sub(r"\s+", " ", " ".join(tail)).strip()
            if en.startswith("(") and en.endswith(")") and en.count("(") == 1:
                en = en[1:-1].strip()
            elif en.startswith("(") and en.count("(") > en.count(")"):
                en = en[1:].strip()
            elif en.endswith(")") and en.count(")") > en.count("("):
                en = en[:-1].strip()
            return th, (en or None)
    return " ".join(tokens), None


_GROUP_LABEL_LINE_RE = re.compile(r"^กลุ่มวิชา")
# ป้ายกลุ่มวิชาแบบ "...คณะ*" ที่บางเล่มพิมพ์ติดบรรทัดเดียวกับชื่อวิชาจริง (ไม่ใช่บรรทัด
# หัวกลุ่มเดี่ยว ๆ) — ต้องตัดเฉพาะป้ายส่วนหน้าออก ไม่ใช่ลบทั้งบรรทัด ไม่งั้นชื่อวิชาหายหมด
# เจอจริง: "กลุ่มวิชาที่กำหนดโดยคณะ* การสื่อสารและการนำเสนอ..." (90644042/90643021)
_GROUP_LABEL_PREFIX_RE = re.compile(r"^กลุ่มวิชา[^*\n]{0,60}\*\s*")

# บรรทัด "หมายเหตุกลุ่มวิชาเลือก" เช่น "เลือก 12 หน่วยกิต" / "เลือกเรียน 6 หน่วยกิต"
# ไม่ใช่ส่วนหนึ่งของชื่อวิชา แต่เป็นคำอธิบายว่ากลุ่มนี้ต้องเลือกกี่หน่วยกิต — เจอจริง:
# 06026239 หน้าคำอธิบายรายวิชา ทำให้ name_th กลายเป็น "...ไปป์ไลน์เลือก 12 หน่วยกิต"
# (บรรทัดนี้ถูกต่อท้ายชื่อวิชาแบบไม่มีช่องว่างเพราะเข้าใจผิดว่าเป็นชื่อวิชาต่อบรรทัด)
_ELECTIVE_NOTE_LINE_RE = re.compile(r"^เลือก(เรียน)?\s*\d+\s*หน่วยกิต")


def _join_th_parts(parts: list[str]) -> str:
    """รวมชิ้นข้อความไทยที่ตัดมาจากหลายบรรทัดในเซลล์เดียวกัน (บรรทัดตัดเพราะคอลัมน์แคบ)

    ⚠️ บั๊กที่พบจริง: code "9064xxxx" ปี 4/1 ในตาราง "แผนการศึกษา" ไม่สหกิจ
    ชื่อวิชาถูกตัดขึ้นบรรทัดใหม่กลางคำ "วิชาเลือก" / "หมวดศึกษาทั่วไป 1"
    (คอลัมน์ของตารางหน้านี้แคบกว่าตารางหน้าอื่นที่ชื่อเดียวกันพอดีบรรทัดเดียว)
    โค้ดเดิมรวมบรรทัดกลับด้วยการใส่ช่องว่างเสมอ (ตามธรรมเนียมภาษาอังกฤษที่ตัด
    บรรทัดตรงขอบคำ) แต่ภาษาไทยไม่มีการเว้นวรรคระหว่างคำ การตัดบรรทัดจึงมักตัด
    "กลางคำ" ไม่ใช่ขอบคำ ผลคือได้ "วิชาเลือก หมวดศึกษาทั่วไป 1" (ผิด มีช่องว่าง
    แทรกกลางคำ) ทั้งที่ควรเป็น "วิชาเลือกหมวดศึกษาทั่วไป 1" (ไม่มีช่องว่าง)

    ตรวจสอบกับ ground truth แล้ว: ทุกครั้งที่ name_th มีช่องว่างจริง จะอยู่
    "หน้าตัวเลขลำดับท้ายชื่อวิชา" เท่านั้น (เช่น "...ทั่วไป 1", "...พื้นฐาน 2")
    ไม่เคยอยู่กลางวลีไทยเลยสักครั้ง — จึงใช้กฎ: ใส่ช่องว่างเฉพาะตอนฝั่งใดฝั่งหนึ่ง
    ของรอยต่อเป็นตัวเลขเท่านั้น นอกนั้นต่อกันโดยไม่มีช่องว่าง
    """
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif out[-1].isdigit() or part[0].isdigit():
            out += " " + part
        else:
            out += part
    return out


def _name_from_cell(cell: str) -> tuple[str, str | None]:
    """ชื่อวิชาจากเซลล์ตาราง (หลายบรรทัดได้): บรรทัดไทย -> name_th, บรรทัดละติน -> name_en

    บางเซลล์ (ช่องวิชาเลือกที่มีตัวเลือกในกลุ่มเดียวกันหลายวิชา) มีบรรทัดหัวกลุ่ม
    เช่น "กลุ่มวิชาตามเกณฑ์ของคณะ (Faculty requirement)" นำหน้าชื่อวิชาจริง — บรรทัดนี้
    มีตัวไทยด้วยจึงเคยถูกนับรวมเป็นส่วนหนึ่งของ name_th ทำให้ชื่อวิชาเพี้ยน ตัดทิ้งก่อน
    ป้ายแบบ "...คณะ*" ที่ติดบรรทัดเดียวกับชื่อวิชาจริง (ไม่ใช่บรรทัดหัวกลุ่มเดี่ยวๆ)
    ตัดเฉพาะป้ายส่วนหน้าออก ไม่ลบทั้งบรรทัด (เจอจริง: 90644042/90643021 ชื่อหายทั้งวิชา)
    """
    for ln in cell.split("\n"):
        plain_ln = ln.replace("**", "").strip()
        if _GROUP_LABEL_PREFIX_RE.match(plain_ln):
            stripped_ln = _GROUP_LABEL_PREFIX_RE.sub("", plain_ln, count=1)
            cell = cell.replace(ln, stripped_ln, 1)
        elif _GROUP_LABEL_LINE_RE.match(plain_ln):
            cell = cell.replace(ln, "", 1)
    th_parts: list[str] = []
    en_parts: list[str] = []
    for ln in cell.split("\n"):
        if not ln.strip():
            continue
        th, en = _split_th_en(ln)
        if th:
            if _THAI_RE.search(th) or not en_parts:
                th_parts.append(th)
            else:
                en_parts.append(th)
        if en:
            en_parts.append(en)
    th_name = re.sub(r"\s+", " ", _join_th_parts(th_parts)).strip()
    en_name = re.sub(r"\s+", " ", " ".join(en_parts)).strip() or None
    return th_name, en_name


def _table_page_credit(text: str) -> int | None:
    m = re.match(r"\d+", text.strip())
    return int(m.group()) if m else None


_CREDIT_TAIL_RE = re.compile(r"(\d+\s*\(\s*[0-9xX]+\s*-\s*[0-9xX]+\s*-\s*[0-9xX]+\s*\))\s*$")
_CREDIT_ONLY_RE = re.compile(r"^\s*\d+\s*\(\s*[0-9xX]+\s*-\s*[0-9xX]+\s*-\s*[0-9xX]+\s*\)\s*$")
_LEAD_CODE_RE = re.compile(r"^\s*([0-9xX]{8})(?:\s+(.*))?$", re.DOTALL)
_TOTAL_LINE_RE = re.compile(r"^รวม\s*(\d+)\s*$")


def _normalize_plan_rows(grid: list[tuple[list[str], list[bool]]]
                         ) -> list[tuple[list[str], list[bool]]]:
    """
    แถวที่ VLM ยุบเซลล์ (เหลือ 1-2 ช่อง) -> [รหัส, ชื่อ, หน่วยกิต] 3 ช่องเหมือนแถวปกติ
      • 1 ช่อง 'รหัส ชื่อ ชื่ออังกฤษ 3(3-0-6)' (อาจหลายวิชาคั่น <br/>)
      • 2 ช่อง [รหัส | ชื่อ ... 3(3-0-6) (+ บรรทัด 'รวม N')]
      • 1 ช่องที่เป็นหน่วยกิตล้วน (เช่น 6(0-35-0) ของคู่ สหกิจ) -> ['', '', หน่วยกิต] ให้แถวถัดไปใช้ร่วม
    แถว 3 ช่อง / แถว 'รวม' / แถว header ผ่านโดยไม่แตะ
    """
    out: list[tuple[list[str], list[bool]]] = []
    for cells, inh in grid:
        first = cells[0] if cells else ""
        if len(cells) >= 3 or first.startswith("รวม") or any("รหัส" in c for c in cells):
            out.append((cells, inh))
            continue
        if len(cells) == 1 and _CREDIT_ONLY_RE.match(cells[0]):
            out.append((["", "", cells[0]], [False] * 3))
            continue

        items: list[dict] = []
        if len(cells) == 1:
            for ln in cells[0].split("\n"):
                if _TOTAL_LINE_RE.match(ln):
                    items.append({"total": _TOTAL_LINE_RE.match(ln).group(1)})
                    continue
                m = _LEAD_CODE_RE.match(ln)
                if m:
                    items.append({"code": m.group(1), "lines": [m.group(2) or ""]})
                elif items and "lines" in items[-1]:
                    items[-1]["lines"].append(ln)
        else:
            # ช่องแรกอาจเป็น "รหัส + หัวกลุ่ม + ชื่อ" ทั้งก้อน (เจอจริง: 90644042 ในแผนไม่สหกิจ ปี 3/2)
            # ถ้าไม่แยกรหัสออก ทั้งก้อนจะกลายเป็น "รหัสวิชา" แล้วแถวถูกทิ้ง
            c0_lines = cells[0].split("\n")
            lm = _LEAD_CODE_RE.match(c0_lines[0])
            if lm and (lm.group(2) or len(c0_lines) > 1):
                it = {"code": lm.group(1), "lines": ([lm.group(2)] if lm.group(2) else []) + c0_lines[1:]}
            else:
                it = {"code": cells[0], "lines": []}
            items.append(it)
            for ln in cells[1].split("\n"):
                if _TOTAL_LINE_RE.match(ln):
                    items.append({"total": _TOTAL_LINE_RE.match(ln).group(1)})
                else:
                    it["lines"].append(ln)

        for it in items:
            if "total" in it:
                out.append((["รวม", "รวม", it["total"]], [False] * 3))
                continue
            lines = [ln for ln in it["lines"] if ln.strip()]
            cred = ""
            if lines:
                cm = _CREDIT_TAIL_RE.search(lines[-1])
                if cm:
                    cred = cm.group(1)
                    lines[-1] = lines[-1][:cm.start()].strip()
            out.append(([it["code"], "\n".join(l for l in lines if l), cred], [False] * 3))
    return out


def parse_plan_tables(pages: list[tuple[int, str]]
                      ) -> tuple[list[dict], list[dict], set[tuple[int, int]], list[dict], dict, dict]:
    """
    ตาราง "แผนการศึกษา" ทั้งหมด -> แถววิชา (รวมช่องวิชา wildcard)
    คืน (แถว, ผลตรวจยอดรวมรายตาราง, ชุดปี/ภาคที่พบหัวข้อ, ตารางที่ถูกข้าม, ข้อความตารางรายภาค)
    ข้อความตารางรายภาค = {(plan, ปี, ภาค): ข้อความในตารางทั้งหมดต่อกัน} ใช้หาวิชาที่ OCR ทำ "รหัส" หายจากตาราง
    plan = "nocoop" / "coop" ตามหัวข้อ "แผนการศึกษา..โครงการสหกิจศึกษา" (None ถ้าเล่มไม่มีสองแผน)
    ปี/ภาคมาจากหัวข้อ "ปีที่ N ภาคการศึกษาที่ M" ที่อยู่ก่อนตาราง (ค่าค้างข้ามหน้าได้)

    "ตารางที่ถูกข้าม" (skipped) คือตารางที่ดูเหมือนมีแถววิชาจริง (เจอโค้ด/wildcard
    ในคอลัมน์แรก) แต่ถูก continue ทิ้งเพราะหา header "รหัสวิชา" ไม่เจอ หรือหา
    ปี/ภาคของมันไม่เจอ — นี่คือสาเหตุอันดับ 1 ที่วิชาทั้งแถวหายไปจากผลลัพธ์
    (พ่วง year/semester/type/category ผิดไปด้วย ถ้าวิชานั้นดันไปโผล่ในหน้า
    คำอธิบายแล้วตกไปอยู่ใน bucket "extra" ที่ default year=0/semester=0/type=เลือก)
    """
    rows: list[dict] = []
    seen_terms: set[tuple[int, int]] = set()
    skipped: list[dict] = []                 # diagnostic: ตารางที่ข้ามทั้งที่ดูมีวิชาจริง
    year: int | None = None
    sem: int | None = None
    seq = 0                                  # นับหัวข้อ "ปีที่ N ภาค M" ทีละหัวข้อ
    tbl_no = 0                               # นับตารางแผนทั้งเอกสาร (ใช้เป็นกุญแจนับหน่วยกิต)
    per_head: dict[int, dict] = {}           # seq -> {page, term, rows, counted, declared}
    plan: str | None = None                  # "nocoop" / "coop" (ค้างข้ามหน้า จนกว่าจะเจอหัวข้อแผนใหม่)
    term_texts: dict[tuple, str] = defaultdict(str)
    term_cells: dict[tuple, list[tuple[str, str]]] = defaultdict(list)   # (ช่องชื่อ, ช่องหน่วยกิต) รายแถวของตาราง

    for pg, text in pages:
        for m in _TABLE_OR_HEAD_RE.finditer(text):
            if m.group("plan"):
                plan = "nocoop" if m.group("neg") else "coop"
                continue
            if m.group("head"):
                hm = _TERM_HEAD_RE.search(m.group("head").translate(_THAI_DIGITS))
                if hm:
                    year = int(hm.group(1))
                    sem = 3 if hm.group(2) == "ฤดูร้อน" else int(hm.group(2))
                    seen_terms.add((year, sem))
                    seq += 1
                continue

            grid = _normalize_plan_rows(_table_grid(m.group("table")))
            # VLM บางครั้งใส่หัวข้อ "ปีที่ N ภาคการศึกษาที่ M" ไว้ใน <th> ของตารางเอง (ไม่ใช่ข้อความก่อนตาราง)
            # จนตารางแรกของแผนไม่รู้ปี/ภาคแล้วถูกข้ามทั้งตาราง (เจอจริง: BIT ปี 1 ภาค 1 ของแผนแรก)
            for r_cells, _ in grid:
                if any("รหัส" in c for c in r_cells):
                    break
                hm2 = _TERM_HEAD_RE.search(" ".join(r_cells).translate(_THAI_DIGITS))
                if hm2:
                    year = int(hm2.group(1))
                    sem = 3 if hm2.group(2) == "ฤดูร้อน" else int(hm2.group(2))
                    seen_terms.add((year, sem))
                    seq += 1
                    break
            header = next((r for r, _ in grid if any("รหัส" in c for c in r)), None)

            # ── ตารางไร้ header ของตัวเอง: มักเป็น "ตารางต่อ" ของตารางที่ header อยู่
            # หน้าก่อน (OCR/VLM แยกเป็นคนละ <table> ตอนขึ้นหน้าใหม่กลางตาราง) — ถ้ารู้
            # ปี/ภาคอยู่แล้ว (ค้างมาจากตารางก่อนหน้า) และคอลัมน์แรกดูเหมือนโค้ดวิชาจริง
            # ให้ถือว่าเป็นตารางต่อ ใช้ตำแหน่งคอลัมน์มาตรฐาน 0,1,2 แทนการทิ้งทั้งยวง
            headless_ok = False
            if header is None and year is not None and sem is not None:
                plausible_codes = [c for r_cells, _ in grid
                                   for c in _split_codes(r_cells[0] if r_cells else "")]
                if plausible_codes:
                    headless_ok = True

            if header is None and not headless_ok:
                # ── diagnostic: ตารางนี้ "ดูเหมือน" มีวิชาจริงไหม (มีโค้ด/wildcard ในคอลัมน์แรก) ──
                # ถ้าใช่ แปลว่านี่ไม่ใช่ตารางอื่นที่ไม่เกี่ยว แต่เป็นตารางแผนที่กำลังจะถูกทิ้งทั้งยวง
                sample_codes: list[str] = []
                for r_cells, _ in grid:
                    if any("รหัส" in c for c in r_cells):
                        continue
                    first = r_cells[0] if r_cells else ""
                    sample_codes.extend(_split_codes(first))
                if sample_codes:
                    reason = ("ไม่เจอ header 'รหัสวิชา' และไม่รู้ปี/ภาค" if (year is None or sem is None)
                              else "ไม่เจอ header 'รหัสวิชา' ในตาราง")
                    print(f"    ⚠ [ข้ามตาราง] หน้า {pg}: {reason} "
                          f"— มีโค้ดในตาราง: {', '.join(sample_codes[:8])}"
                          f"{' ...' if len(sample_codes) > 8 else ''}")
                    skipped.append({"page": pg, "reason": reason, "codes": sample_codes})
                continue                         # ไม่ใช่ตารางแผน หรือไม่รู้ปี/ภาค
            if year is None or sem is None:
                # มี header แต่ไม่รู้ปี/ภาค (เคสที่ยังต้องแก้ที่ _TERM_HEAD_RE/หัวข้อก่อนตาราง)
                sample_codes = [c for r_cells, _ in grid if not any("รหัส" in c for c in r_cells)
                               for c in _split_codes(r_cells[0] if r_cells else "")]
                if sample_codes:
                    reason = f"เจอตารางแต่ยังไม่รู้ปี/ภาค (year={year}, sem={sem}) " \
                             "— หัวข้อ 'ปีที่ N ภาคที่ M' ก่อนตารางนี้อ่านไม่ออก/ไม่เจอ"
                    print(f"    ⚠ [ข้ามตาราง] หน้า {pg}: {reason} "
                          f"— มีโค้ดในตาราง: {', '.join(sample_codes[:8])}"
                          f"{' ...' if len(sample_codes) > 8 else ''}")
                    skipped.append({"page": pg, "reason": reason, "codes": sample_codes})
                continue

            if headless_ok:
                i_code, i_name, i_cred = 0, 1, 2
                print(f"    ℹ [ตารางต่อ] หน้า {pg}: ไม่มี header เอง แต่รู้ปี/ภาค "
                      f"(year={year}, sem={sem}) แล้ว — ใช้ตำแหน่งคอลัมน์ 0,1,2 แทนการทิ้ง")
            else:
                i_code = next((i for i, c in enumerate(header) if "รหัส" in c), 0)
                i_name = next((i for i, c in enumerate(header) if "ชื่อ" in c), 1)
                i_cred = max((i for i, c in enumerate(header) if "หน่วยกิต" in c),
                             default=len(header) - 1)
                if len({i_code, i_name, i_cred}) < 3:  # header ยุบ/เพี้ยน -> ใช้ตำแหน่งมาตรฐาน
                    i_code, i_name, i_cred = 0, 1, 2

            # จัดกลุ่มแถวที่ rowspan ร่วมรหัสเดียวกัน (เช่น "06046443 หรือ 06046444")
            groups: list[dict] = []
            declared_total: int | None = None
            shared_credit = ""                   # หน่วยกิตที่พิมพ์ครั้งเดียวใช้ร่วมหลายแถว (คู่ สหกิจ)
            or_next = False
            for cells, inh in grid:
                if any("รหัส" in c for c in cells):
                    continue
                first = cells[i_code] if i_code < len(cells) else ""
                if not first and len(cells) > i_cred and _CREDIT_ONLY_RE.match(cells[i_cred]):
                    shared_credit = cells[i_cred]
                    continue
                if first.startswith("รวม"):
                    declared_total = _table_page_credit(cells[-1])
                    continue
                codes = _split_codes(first)
                if not codes:
                    continue
                name_cell = cells[i_name] if i_name < len(cells) else ""
                cred_cell = (cells[i_cred] if i_cred < len(cells) else "") or shared_credit
                term_cells[(plan, year, sem)].append(
                    (name_cell, cells[i_cred] if i_cred < len(cells) else ""))
                # ชื่อวิชาลงท้าย "หรือ 3 (2-2-5)" = หน่วยกิตแบบที่สองหลุดเข้าช่องชื่อ -> ย้ายไปช่องหน่วยกิต
                tm = re.search(r"\s*หรือ\s*(\d+\s*\(\s*[0-9xX]+\s*-\s*[0-9xX]+\s*-\s*[0-9xX]+\s*\))\s*$",
                               name_cell)
                if tm:
                    name_cell = name_cell[:tm.start()].strip()
                    if tm.group(1).replace(" ", "") not in cred_cell.replace(" ", ""):
                        cred_cell = f"{cred_cell} หรือ {tm.group(1)}".strip()
                if inh[i_code] and name_cell.strip() == "รวม":      # แถว 'รวม' ที่ rowspan รหัสลากมาทับ
                    declared_total = _table_page_credit(cells[i_cred]) if i_cred < len(cells) else None
                    continue
                lead = _LEAD_CODE_RE.match((name_cell.split("\n") or [""])[0])
                if inh[i_code] and groups and lead and lead.group(2) and not (i_name < len(inh) and inh[i_name]):
                    # ช่องชื่อขึ้นต้นด้วยรหัสของตัวเอง (OCR ยัดรหัสไว้ในช่องชื่อ เช่น "90644042 กลุ่มวิชา...")
                    # = แถวใหม่ ไม่ใช่ชื่อที่สองของรหัสเหนือมัน
                    rest_lines = [lead.group(2)] + name_cell.split("\n")[1:]
                    groups.append({"codes": [lead.group(1).lower()], "names": ["\n".join(rest_lines)],
                                   "credits": cred_cell, "sep_rows": False})
                    or_next = False
                    continue
                if inh[i_code] and groups:
                    # rowspan ของ OCR มักทำให้ได้แถวเกิน: ช่องชื่อที่ว่าง / ซ้ำแถวก่อน (สืบทอดมา) /
                    # เป็นหน่วยกิตล้วน ไม่ใช่ชื่อวิชา -> ไม่นับเป็นชื่อเพิ่ม
                    nm = re.sub(r"\s+", " ", name_cell).strip()
                    if (nm and not (i_name < len(inh) and inh[i_name])
                            and not re.fullmatch(r"(?:\s*หรือ\s*|\s*\d+\s*\([0-9xX\s-]+\)\s*)+", nm)):
                        groups[-1]["names"].append(name_cell)
                        own = (cells[i_cred] if i_cred < len(cells) and not inh[i_cred] else "")
                        groups[-1].setdefault("ncred", {})[len(groups[-1]["names"]) - 1] = own
                elif or_next and groups:             # แถวก่อนหน้าลงท้าย "หรือ" -> แถวนี้เป็นทางเลือกของมัน
                    groups[-1]["codes"] += codes
                    groups[-1]["names"].append(name_cell)
                else:
                    groups.append({"codes": codes, "names": [name_cell], "credits": cred_cell,
                                   "first": first,
                                   # หลายรหัสในช่องเดียวแต่ไม่มี "หรือ" (รหัสรวมช่องด้วย rowspan) = คนละแถว ไม่ใช่ทางเลือก
                                   "sep_rows": len(codes) > 1 and "หรือ" not in first and "\n" not in first})
                or_next = first.rstrip().endswith("หรือ") and not inh[i_code]

            table_rows: list[dict] = []
            alt_no = 0
            for g in groups:
                codes, names = g["codes"], g["names"]
                credits = _norm_credits(g["credits"])
                alt_key = None
                # รหัสหลายบรรทัดใน rowspan เดียว (ไม่มีคำว่า "หรือ") ที่จำนวนชื่อเท่าจำนวนรหัส = คนละแถวต่อเนื่องกัน
                # ไม่ใช่ "เลือกอย่างใดอย่างหนึ่ง" (เจอจริง: "060164xx / 90643021" ถูกติดป้ายทางเลือกผิด
                # และยอดรวมหน่วยกิตของภาคขาด เพราะนับกลุ่มทางเลือกเป็นวิชาเดียว)
                if (len(codes) > 1 and len(set(codes)) > 1 and "หรือ" not in (g.get("first") or "")
                        and len(names) == len(codes)):
                    g["sep_rows"] = True
                same_code = len(codes) > 1 and (len(set(codes)) == 1 or bool(g.get("sep_rows")))
                if same_code and len(set(codes)) == 1:
                    # รหัสตัวแทนซ้ำในเซลล์เดียว (06036xxx / 06036xxx) = วิชาเลือก 1, 2 คนละแถว ไม่ใช่ "หรือ"
                    codes = [codes[0]] * max(len(names), 1)
                if len(codes) > 1 and not same_code:
                    alt_no += 1
                    alt_key = f"alt_y{year}s{sem}_{alt_no}"
                parsed = [_name_from_cell(n) for n in names]
                if ALT_MODE == "single" and len(codes) > 1 and not same_code:
                    th = " หรือ ".join(p[0] for p in parsed if p[0])
                    en = " หรือ ".join(p[1] for p in parsed if p[1]) or None
                    entries = [(" หรือ ".join(codes), th, en)]
                    alt_key = None
                elif len(codes) > 1 and len(parsed) == len(codes):
                    entries = [(c, p[0], p[1]) for c, p in zip(codes, parsed)]
                elif len(codes) == 1 and len(parsed) > 1:
                    # รหัสเดียวแต่มีหลายชื่อ (rowspan ของ OCR): ชื่อแรกเป็นของรหัสนี้
                    # ชื่อที่เหลือ = แถวที่ OCR ทำ "รหัส" หาย/ยุบรวม -> ค่อยหารหัสจากชื่อทีหลัง (code=None)
                    entries = []
                    for k, (th_k, en_k) in enumerate(parsed):
                        entries.append((codes[0] if k == 0 else None, th_k, en_k))
                else:
                    th, en = parsed[0]
                    entries = [(c, th, en) for c in codes]
                for k_e, (code, th, en) in enumerate(entries):
                    cred_e = credits
                    if len(codes) == 1 and len(parsed) > 1 and k_e > 0:
                        own = _norm_credits((g.get("ncred") or {}).get(k_e) or "")
                        cred_e = own or credits
                    row = {
                        "code": code, "name_th": th, "name_en": en,
                        "credits": cred_e, "year": year, "semester": sem,
                        "category": None, "type": None, "prerequisite": "ไม่มี",
                        "flexible_year_semester": None, "note": None,
                        "pages": [pg], "plan": plan,
                    }
                    if code is None:
                        row["_orphan"] = True
                    if alt_key:
                        row["alt_group"] = alt_key
                        row["note"] = "เลือกอย่างใดอย่างหนึ่ง: " + " หรือ ".join(codes)
                    elif (k_e == 0 and (g.get("first") or "").lstrip().startswith("หรือ")):
                        # แถวที่ขึ้นต้นด้วย "หรือ" (เจอจริง: สหกิจศึกษา / สหกิจศึกษาต่างประเทศ ที่ตารางขึ้นหน้าใหม่)
                        # = ทางเลือกของแถวก่อนหน้า -> ผูกกลุ่มทางเลือกเดียวกัน (นับหน่วยกิตครั้งเดียว)
                        prev = table_rows[-1] if table_rows else next(
                            (x for x in reversed(rows) if (x.get("plan"), x["year"], x["semester"])
                             == (plan, year, sem)), None)
                        if prev is not None and prev.get("code"):
                            alt_no += 1
                            akey = prev.get("alt_group") or f"alt_y{year}s{sem}_{alt_no}"
                            prev["alt_group"] = row["alt_group"] = akey
                            for x in (prev, row):
                                x["note"] = f"เลือกอย่างใดอย่างหนึ่ง: {prev['code']} หรือ {code}"
                    table_rows.append(row)
            # รหัสเดียวกันซ้ำในตารางเดียว (เช่น 06016418 อยู่ทั้งกลุ่มพัฒนาซอฟต์แวร์และกลุ่มสื่อประสม)
            # = สองแถวจริง — เลขลำดับซ้ำใช้แยกแถวตอนรวมสองแผน ไม่ให้ถูกยุบเป็นแถวเดียว
            _seen_c: dict = defaultdict(int)
            for r in table_rows:
                if r["code"] is not None:
                    r["_dup"] = _seen_c[r["code"]]
                    _seen_c[r["code"]] += 1
            rows.extend(table_rows)
            tbl_no += 1

            # ตรวจตัวเอง: ผลรวมหน่วยกิตที่อ่านได้ ต้องเท่าแถว "รวม" ของหัวข้อภาคนั้น
            # (ตารางเดียวกันที่ถูกหน้าตัดแบ่งเป็นสองก้อนใช้หัวข้อเดียวกัน จึงรวมเข้าด้วยกัน)
            h = per_head.setdefault(seq, {"page": pg, "term": f"{year}/{sem}", "rows": 0,
                                          "counted": {}, "declared": None,
                                          "plan": plan, "year": year, "sem": sem})
            term_texts[(plan, year, sem)] += " " + " ".join(
                c for r_cells, _ in grid if not any("รหัส" in x for x in r_cells) for c in r_cells)
            for i, r in enumerate(table_rows):
                h["rows"] += 1
                cm = re.match(r"\d+", str(r["credits"] or ""))
                if cm:
                    h["counted"][r.get("alt_group") or f"t{tbl_no}r{i}"] = int(cm.group())
            if declared_total is not None:
                h["declared"] = declared_total
    checks = []
    for h in per_head.values():
        got = sum(h["counted"].values())
        checks.append({"page": h["page"], "term": h["term"], "rows": h["rows"], "sum": got,
                       "declared": h["declared"],
                       "plan": h.get("plan"), "year": h.get("year"), "sem": h.get("sem"),
                       "ok": h["declared"] is None or h["declared"] == got})
    return rows, checks, seen_terms, skipped, dict(term_texts), dict(term_cells)


# ── หน้าคำอธิบายรายวิชา ───────────────────────────────────────────────────────

_DESC_HEAD_RE = re.compile(r"^\**\s*(\d{8})(?:\s+(.+?))?\**\s*$")
# OCR บางหน้าวาง "รหัส" ไว้บรรทัดเดียวโดด ๆ แล้วค่อยขึ้นบรรทัดใหม่เป็นหน่วยกิต/ชื่อวิชา
# (เจอจริงในเล่ม GENED: 90642121, 90642199, 90642201, 90642203)
# ถ้าไม่รับรูปแบบนี้ วิชาทั้งก้อนจะถูกกลืนเป็น "คำอธิบาย" ของวิชาก่อนหน้า
# แต่ก็ต้องกันบรรทัดที่เป็น "รายการรหัสวิชาบังคับก่อน" ไม่ให้ถูกนับเป็นหัววิชาใหม่
# -> รับเฉพาะเมื่อบรรทัดถัด ๆ ไปมีเครื่องหมายของหัววิชา (บรรทัดหน่วยกิตล้วน หรือ
#    บรรทัด "รายวิชาบังคับก่อน"/"PREREQUISITE") ภายใน 4 บรรทัด
_PREREQ_LINE_RE = re.compile(r"^\**\s*(?:รายวิชาบังคับก่อน|วิชาบังคับก่อน|PREREQUISITE)",
                             re.IGNORECASE)
# เล่ม IT เขียนหัวข้อว่า "คำอธิบายรายวิชาเฉพาะ" หรือ "คำอธิบายรายวิชาเรียนรวม (หมวดวิชาเฉพาะ)"
# ไม่ใช่ "หมวดวิชาเฉพาะ" ขึ้นต้นบรรทัดเฉย ๆ แบบเล่มอื่น — จับทั้งสองแบบ แล้ว normalize เป็น "หมวดวิชา..." เสมอ
_CATEGORY_HEAD_RE = re.compile(
    r"^หมวดวิชา(?P<a>ศึกษาทั่วไป|เฉพาะ|เลือกเสรี)"
    r"|^คำอธิบายรายวิชา(?:เรียนรวม)?\s*\(?\s*หมวดวิชา(?P<b>ศึกษาทั่วไป|เฉพาะ|เลือกเสรี)\)?\s*$"
    r"|^คำอธิบายรายวิชา(?P<c>ศึกษาทั่วไป|เฉพาะ|เลือกเสรี)\s*$"
)


def _category_from_head(m: re.Match) -> str:
    g = m.groupdict()
    return "หมวดวิชา" + (g.get("a") or g.get("b") or g.get("c"))


# หน่วยกิตเต็ม "3(3-0-6)" (เลขติดวงเล็บ ไม่มีช่องว่างคั่น) กับ "วงเล็บลอย" "(3-0-6)" (ไม่มีเลขหน่วยกิตนำหน้า)
_CRED_ADJ_RE = re.compile(r"(?<![\d.])(\d{1,2})\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)")
_NUM_LPS_RE = re.compile(r"(?<![\d.])(\d{1,2})\s+\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)\s*$")
_LPS_BARE_RE = re.compile(r"\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)")
_CREDIT_LINE_RE = re.compile(r"(?:\d{1,2})?\s*\(\s*\d+\s*-\s*\d+\s*-\s*\d+\s*\)")
_CRED_ONLY_RE = re.compile(r"(\d{1,2})?\s*\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)")


def credits_from_lps(l: str, p: str, s: str) -> str | None:
    """
    (บรรยาย-ปฏิบัติ-ศึกษาเอง) -> "N(l-p-s)" เมื่อเล่มพิมพ์แต่วงเล็บโดยไม่มีเลขหน่วยกิต

    หลักการ: 1 หน่วยกิต = 3 ชั่วโมง/สัปดาห์ (บรรยาย+ปฏิบัติ+ศึกษาเอง) ดังนั้น N = (l+p+s)/3
    ถ้าหารไม่ลงตัว (เช่น "(3-2-5)" = 10 ชม.) แปลว่า OCR อ่านตัวเลขเพี้ยน -> คืน None ห้ามเดา
    """
    a, b, c = int(l), int(p), int(s)
    tot = a + b + c
    if tot == 0 or tot % 3 or tot // 3 > 12:
        # > 12 หน่วยกิตในวิชาเดียวเป็นไปไม่ได้ในทางปฏิบัติ — แปลว่าเล่มพิมพ์เลขหน่วยกิตไว้แล้ว
        # (เช่น "0 (0-0-45)" วิชาไม่นับหน่วยกิต) การเดาจากผลรวมชั่วโมงจึงผิด -> คืน None
        return None
    return f"{tot // 3}({a}-{b}-{c})"


_HTML_ENTS = {"&amp;": "&", "&nbsp;": " ", "&quot;": '"', "&#39;": "'",
              "&apos;": "'", "&lt;": "<", "&gt;": ">"}
_HTML_ENT_RE = re.compile("|".join(re.escape(k) for k in _HTML_ENTS), re.IGNORECASE)


def _desc_lines(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """บรรทัดของหน้าคำอธิบายทั้งหมด (ต่อหน้าเข้าด้วยกัน) โดยตัดบรรทัดรบกวนของ OCR"""
    out: list[tuple[int, str]] = []
    for pg, text in pages:
        text = re.sub(r"<table.*?</table>", "", text, flags=re.DOTALL | re.IGNORECASE)
        for ln in text.replace("\r", "").split("\n"):
            s = re.sub(r"<page_number>.*?</page_number>", "", ln).strip()
            # Markdown จาก OCR หลุด HTML entity มาด้วย (เจอจริง: "GENES &amp; GENETICS")
            # ถ้าไม่คืนค่า จะได้ชื่ออังกฤษเป็น "GENES &AMP; GENETICS" หลัง upper()
            s = _HTML_ENT_RE.sub(lambda m_: _HTML_ENTS[m_.group(0).lower()], s)
            if (not s or s.startswith("<!--") or re.fullmatch(r"-{3,}", s)
                    or s == "รายละเอียดหลักสูตร"
                    or re.fullmatch(r"มคอ\.?\s*\d*", s)
                    or re.fullmatch(r"#+\s*คำอธิบายรายวิชา", s)
                    or _FOOTER_MARK_RE.match(s)
                    or ("สจล" in s and "คณะ" in s and len(s) < 120)):
                continue
            out.append((pg, s))
    return out


def _norm_group(name: str) -> str:
    s = re.sub(r"\s+", "", name.replace("**", ""))
    return re.sub(r"^กลุ่ม", "", s)


def parse_description_pages(pages: list[tuple[int, str]]) -> dict[str, dict]:
    """
    {รหัส: {name_th, name_en, credits, prerequisite, description_th, pages, category,
            group, type}}  จากหน้า "คำอธิบายรายวิชา"

    ต่อทุกหน้าเป็นข้อความเดียวก่อนแยกบล็อก จึงไม่เสียวิชาที่หัวอยู่ท้ายหน้าหนึ่งแต่
    "วิชาบังคับก่อน" ไปอยู่หน้าถัดไป (เจอจริง: 06046443 หน้า 303 -> 304)
    """
    lines = _desc_lines(pages)

    # ทำเครื่องหมายบรรทัดต่อเนื่องของ "วิชาบังคับก่อน : ..." (รายการยาวหลายบรรทัด)
    # ที่ขึ้นต้นด้วยรหัส 8 หลัก จะได้ไม่ถูกเข้าใจผิดว่าเป็นหัววิชาใหม่
    cont: set[int] = set()
    for i, (_, s) in enumerate(lines):
        if "วิชาบังคับก่อน" in s:
            for j in range(i + 1, min(i + 9, len(lines))):
                if lines[j][1].replace("*", "").lstrip().upper().startswith("PREREQUISITE"):
                    cont.update(range(i + 1, j))
                    break

    blocks: list[dict] = []
    cur_cat: str | None = None
    cur_group: str | None = None
    for i, (pg, s) in enumerate(lines):
        plain = s.replace("**", "").strip()
        hm = None if i in cont else _DESC_HEAD_RE.match(s)
        if hm and not (hm.group(2) or "").strip():
            # บรรทัดมีแต่รหัสล้วน: รับเป็นหัววิชาก็ต่อเมื่อมีเครื่องหมายหัววิชาตามมาใกล้ ๆ
            look = [lines[j][1].replace("**", "").strip()
                    for j in range(i + 1, min(i + 5, len(lines)))]
            prev = lines[i - 1][1] if i else ""
            in_prereq = (i - 1) in cont or "วิชาบังคับก่อน" in prev
            if in_prereq or not any(
                    _CREDIT_LINE_RE.fullmatch(t.strip("*• ")) or _PREREQ_LINE_RE.match(t)
                    for t in look):
                hm = None
        if hm:
            blocks.append({"code": hm.group(1), "rest": (hm.group(2) or "").replace("**", "").strip(),
                           "lines": [], "pages": {pg}, "category": cur_cat, "group": cur_group})
            continue
        cm = _CATEGORY_HEAD_RE.match(plain.lstrip("# ").strip())
        if cm and len(plain) < 70 and "วิชาบังคับก่อน" not in plain:
            cur_cat, cur_group = _category_from_head(cm), None
            continue
        if plain.startswith("กลุ่มวิชา") and len(plain) < 90:
            cur_group = plain
            continue
        if blocks:
            blocks[-1]["lines"].append((i, pg, s))
            blocks[-1]["pages"].add(pg)

    out: dict[str, dict] = {}
    for b in blocks:
        head_lines = [b["rest"]]
        pre_text: list[str] = []
        desc_th: list[str] = []
        late_cred: str | None = None
        state = "head"
        for i, pg, s in b["lines"]:
            plain = s.replace("**", "").strip()
            if _CREDIT_LINE_RE.fullmatch(plain.strip("*• ")):
                # หน่วยกิตที่ OCR วางไว้บรรทัดเดี่ยว ๆ (เจอจริง: หลัง PREREQUISITE : NONE)
                if late_cred is None:
                    late_cred = plain.strip("*• ")
                continue
            if "วิชาบังคับก่อน" in plain:
                state = "pre"
                pre_text.append(re.sub(r"^.*?วิชาบังคับก่อน\s*[:：]?", "", plain).strip())
            elif state == "pre" and plain.upper().startswith("PREREQUISITE"):
                state = "desc"
            elif state == "pre" and i in cont:
                pre_text.append(plain)
            elif state == "head":
                # เล่มที่ไม่มีบรรทัด "วิชาบังคับก่อน" (เช่น GENED) ทำให้ทั้งคำอธิบายรายวิชาถูกกลืนเป็น "ชื่อ"
                # หัววิชาจบเมื่อเจอบรรทัดไทยหลังจากที่ชื่ออังกฤษขึ้นแล้ว หรือบรรทัดยาวผิดปกติของชื่อวิชา
                if _ELECTIVE_NOTE_LINE_RE.match(plain):
                    # หมายเหตุ "เลือก N หน่วยกิต" ไม่ใช่ส่วนของชื่อวิชาและไม่ใช่คำอธิบาย — ข้ามทิ้ง
                    # (คงอยู่ state "head" ต่อ เผื่อชื่อวิชายังไม่จบ)
                    continue
                has_latin = any(re.search(r"[A-Za-z]{2}", h_) for h_ in head_lines)
                if (has_latin and _THAI_RE.search(plain)) or len(plain) > 110:
                    desc_th.append(plain)
                    state = "desc"
                else:
                    head_lines.append(plain)
            elif _THAI_RE.search(plain):
                desc_th.append(plain)
                state = "desc"

        # ── หน่วยกิต + ชื่อ จากบรรทัดหัววิชา ────────────────────────────────────
        # รูปแบบที่เจอในเล่มจริง (ต้องแยกให้ถูก ไม่งั้นเลขท้ายชื่อถูกกลืนเป็นหน่วยกิต):
        #   "3(3-0-6)"               เลขหน่วยกิตติดวงเล็บ  -> หน่วยกิตเต็ม
        #   "หัวข้อพิเศษ ... 1 (3-0-6)" เลขท้ายชื่อ + วงเล็บลอย -> เลข 1 เป็นของชื่อ ไม่ใช่หน่วยกิต
        #   "(3-2-5)"                 ค่า OCR เพี้ยน (ผลรวมชั่วโมงหาร 3 ไม่ลงตัว) -> ทิ้ง
        credits = None
        derived = None
        clean_heads: list[str] = []
        amb: tuple[int, str] | None = None
        for ln in head_lines:
            # บรรทัดหัววิชาที่ "มีแต่หน่วยกิต" เช่น "90642122 3 (3-0-6)" แล้วชื่ออยู่บรรทัดถัดไป
            # ตัวเลขหน้าวงเล็บเป็นหน่วยกิตแน่นอน (ไม่มีชื่อบนบรรทัดเดียวกันให้เป็นเลขลำดับได้)
            # ถ้าไม่ดักตรงนี้ เลขนั้นจะไปติดหน้าชื่อวิชา -> "3การใช้แอปพลิเคชัน..."
            bare_ln = ln.replace("*", "").strip()
            if _CREDIT_LINE_RE.fullmatch(bare_ln):
                om = _CRED_ONLY_RE.fullmatch(bare_ln)
                if om and credits is None:
                    if om.group(1) and int(om.group(1)) <= 12:
                        credits = f"{om.group(1)}({om.group(2)}-{om.group(3)}-{om.group(4)})"
                    elif not om.group(1) and derived is None:
                        derived = credits_from_lps(om.group(2), om.group(3), om.group(4))
                continue
            cm = _CRED_ADJ_RE.search(ln)
            if cm and credits is None and int(cm.group(1)) <= 12:
                credits = f"{cm.group(1)}({cm.group(2)}-{cm.group(3)}-{cm.group(4)})"
            # "ชื่อวิชา 0 (0-0-45)" = วิชาไม่นับหน่วยกิต (เลข 0 คือหน่วยกิต ไม่ใช่เลขลำดับท้ายชื่อ
            # เพราะไม่มีวิชาชุดไหนเริ่มนับที่ 0) ต้องดักก่อน ไม่งั้น (0+0+45)/3 = 15 หน่วยกิต
            am0 = _NUM_LPS_RE.search(ln)
            if am0 and credits is None and int(am0.group(1)) == 0:
                credits = f"0({am0.group(2)}-{am0.group(3)}-{am0.group(4)})"
                ln = _NUM_LPS_RE.sub("", ln)
            # "การคิด... 3 (3-0-6)": เลข 3 เป็นหน่วยกิตหรือเลขท้ายชื่อ? ตัดสินทีหลังจากดูทั้งเล่ม (ดู _resolve_ambiguous)
            am = _NUM_LPS_RE.search(ln)
            if am and amb is None:
                d_ = credits_from_lps(am.group(2), am.group(3), am.group(4))
                if d_ and d_.startswith(am.group(1) + "("):
                    amb = (int(am.group(1)), d_)
            ln = _CRED_ADJ_RE.sub("", ln)
            for lm in _LPS_BARE_RE.finditer(ln):
                d_ = credits_from_lps(lm.group(1), lm.group(2), lm.group(3))
                if d_ and derived is None:
                    derived = d_
            ln = _LPS_BARE_RE.sub("", ln)
            ln = _strip_unmatched_parens(ln.replace("*", "").strip())
            if ln:
                clean_heads.append(ln)
        if credits is None and late_cred:
            lm = _CRED_ADJ_RE.search(late_cred)
            if lm:
                credits = f"{lm.group(1)}({lm.group(2)}-{lm.group(3)}-{lm.group(4)})"
            else:
                bm = _LPS_BARE_RE.search(late_cred)
                if bm and derived is None:
                    derived = credits_from_lps(bm.group(1), bm.group(2), bm.group(3))
        # บรรทัดหัววิชาที่ "เป็นละตินล้วน" = ชื่ออังกฤษเต็มของวิชานี้อยู่คนละบรรทัดแล้ว
        # ดังนั้นหางละตินสั้น ๆ ท้ายบรรทัดไทย (เช่น "...สำหรับ SDGs", "เส้นทางสู่ IPO")
        # เป็นส่วนหนึ่งของ "ชื่อไทย" ไม่ใช่จุดเริ่มของชื่ออังกฤษ — ถ้าตัดออกจะได้ชื่อไทยขาดหาง
        # และชื่ออังกฤษมีคำซ้ำนำหน้า ("SDGS SCIENCE TECHNOLOGY ... FOR SDGS")
        has_en_line = any(k > 0 and not _THAI_RE.search(ln) and re.search(r"[A-Za-z]", ln)
                          for k, ln in enumerate(clean_heads))
        th_name = ""
        en_parts: list[str] = []
        for k, ln in enumerate(clean_heads):
            th, en = _split_th_en(ln)
            if en and has_en_line and _THAI_RE.search(ln):
                th, en = ln.strip(), None     # บรรทัดนี้เป็นชื่อไทย (รวมหางละติน) ทั้งบรรทัด
            if k == 0 or (th and _THAI_RE.search(th) and not th_name):
                th_name = th or th_name
            elif th and _THAI_RE.search(th):
                th_name = (th_name + th).strip()
            elif th:
                en_parts.append(th)
            if en:
                en_parts.append(en)
        name_en = re.sub(r"\s+", " ", " ".join(en_parts)).strip() or None

        joined = " ".join(pre_text)
        codes = list(dict.fromkeys(re.findall(r"(?<!\d)\d{8}(?!\d)", joined)))
        if codes:
            prereq: str | None = ", ".join(codes)
        elif pre_text:
            prereq = ("ไม่มี" if re.search(r"ไม่มี|none|^-?$", joined.strip(), re.IGNORECASE)
                      else joined.strip()[:120])
        else:
            prereq = None

        group = b["group"] or ""
        cat = _canon_category(b["category"])
        ctype = "เลือก" if ((cat and "เลือกเสรี" in cat) or "เลือก" in group) else "บังคับ"
        info = {
            "name_th": th_name or None, "name_en": name_en, "credits": credits,
            "credits_derived": derived, "_amb": amb,
            "prerequisite": prereq,
            "description_th": (" ".join(desc_th)[:2000] or None),
            "pages": sorted(b["pages"]), "category": cat,
            "group": b["group"], "type": ctype,
        }
        old = out.get(b["code"])
        if old is None:
            out[b["code"]] = info
        else:                                    # รหัสเดียวกันเจอซ้ำ: ยึดตัวแรก เติมช่องที่ว่าง
            old["pages"] = sorted({*old["pages"], *info["pages"]})
            for key in ("name_th", "name_en", "credits", "credits_derived", "description_th", "category"):
                if not old.get(key) and info.get(key):
                    old[key] = info[key]
            if old.get("prerequisite") in (None, "ไม่มี") and info.get("prerequisite"):
                old["prerequisite"] = info["prerequisite"]
    # ── "ชื่อ N (l-p-s)": N เป็นหน่วยกิต หรือเลขลำดับท้ายชื่อ? ──────────────────────────────
    #   ถ้าชื่อเดียวกันต่างแค่เลขท้ายมีหลายวิชา (หัวข้อพิเศษ 1..4, ปฏิบัติงาน 1..3) = เลขลำดับ -> คงไว้ในชื่อ
    #   ถ้าชื่อนั้นมีวิชาเดียวและ N = (บรรยาย+ปฏิบัติ+ศึกษาเอง)/3 พอดี = หน่วยกิต -> ตัดออกจากชื่อ
    stem_count: Counter = Counter()
    for info_ in out.values():
        st, nm = _stem_num(info_.get("name_th"))
        if nm is not None:
            stem_count[st] += 1
    for info_ in out.values():
        amb_ = info_.pop("_amb", None)
        if not amb_ or info_.get("credits"):
            continue
        st, nm = _stem_num(info_.get("name_th"))
        if nm == amb_[0] and stem_count[st] < 2:
            info_["name_th"] = re.sub(r"\s*\d+\s*$", "", info_["name_th"]).strip()
            info_["credits"] = amb_[1]
    return out


# ── ประกอบผลรวม ────────────────────────────────────────────────────────────────


def _merge_parts_by_page(md_pages: list[str], page_nums: list[int] | None
                         ) -> list[tuple[int, str]]:
    """OCR ขีด '---' กลางหน้าทำให้หนึ่งหน้าถูกแบ่งเป็นหลายส่วนเลขหน้าเดิม — รวมกลับเป็นหน้าละก้อน"""
    merged: list[tuple[int, str]] = []
    for i, text in enumerate(md_pages):
        pg = page_nums[i] if page_nums else i + 1
        if merged and merged[-1][0] == pg:
            merged[-1] = (pg, merged[-1][1] + "\n\n" + text)
        else:
            merged.append((pg, text))
    return merged


def _fallback_category(code: str, name_th: str) -> str | None:
    if "เลือกเสรี" in (name_th or ""):
        return category_free()
    if "ศึกษาทั่วไป" in (name_th or ""):
        return "หมวดวิชาศึกษาทั่วไป"
    for prefix, cat in CATEGORY_BY_CODE_PREFIX:
        if code.startswith(prefix):
            return cat
    return None



# ── ซ่อมแถวจากตาราง OCR ด้วยหน้า "คำอธิบายรายวิชา" + ตรวจยอดรวมหน่วยกิต ─────────────────────
#
#  ⚠️ ที่มา: ผล Eval ของแผน IT (eval_gt.json) มีข้อผิดพลาดกลุ่มใหญ่จาก "ตารางที่ OCR ยุบ rowspan":
#     - เซลล์รหัสหลายรหัส (rowspan) ไม่ตรงกับแถวชื่อ -> ชื่อ/หน่วยกิตถูกจับคู่ผิดรหัส
#       (06016415 ได้ชื่อ NoSQL, 06016422/23 ได้ชื่อวิชาความมั่นคง, 06016418/27 ได้ชื่อกราฟิกส์)
#     - รหัสบางตัวหายจากตารางทั้งที่ชื่อยังอยู่ (06016419/20/24/25) -> ตกไปเป็น "วิชาเลือก year=0"
#     - รหัสอยู่ในเซลล์เดียวกับชื่อ (90644042) -> ทั้งแถวหาย
#     - รหัสตัวแทน 9064xxxxx หนึ่งเซลล์ ครอบสองวิชา (เลือกศึกษาทั่วไป 2 + เลือกเสรี 2) -> เสียไปหนึ่งแถว
#  หลักการซ่อม (ไม่ hard-code รหัส/ชื่อของเล่มใดเล่มหนึ่ง):
#     "รหัสวิชาในตาราง" น่าเชื่อถือกว่า "ชื่อที่อยู่ในแถวเดียวกัน"  ส่วน "ชื่อ/หน่วยกิต" ที่ถูกต้อง
#     ต้องยึดจากหน้าคำอธิบายรายวิชา (รหัสอยู่หน้าชื่อ ตรงกันเสมอ) แล้วใช้ตารางเป็นแค่ "ผู้ลงคะแนนเสียงที่สอง"

_WILDCARD_BY_NAME: tuple[tuple[str, str], ...] = (
    ("เลือกเสรี", "xxxxxxxx"),
)


def _sq(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_wild(code: str | None) -> bool:
    return bool(code) and "x" in code


def _lps(credit: str | None) -> str | None:
    m = re.search(r"\(\s*\d+\s*-\s*\d+\s*-\s*\d+\s*\)", credit or "")
    return re.sub(r"\s+", "", m.group()) if m else None


def _pick_credits(table_credit: str | None, d: dict | None) -> str | None:
    """หน่วยกิตของวิชาที่มีหน้าคำอธิบาย: ค่าที่เล่มพิมพ์ครบ > ค่าที่คำนวณจาก (บรรยาย-ปฏิบัติ-ศึกษาเอง) > ค่าในตาราง"""
    if d:
        if d.get("credits"):
            # ตารางพิมพ์ทางเลือกหลายแบบ ("3(3-0-6) หรือ 3(2-2-5)") และค่าของคำอธิบายเป็นหนึ่งในนั้น -> คงตาราง
            if (table_credit and "หรือ" in table_credit
                    and d["credits"].replace(" ", "") in table_credit.replace(" ", "")):
                return table_credit
            return d["credits"]
        der = d.get("credits_derived")
        if der:
            if table_credit and _lps(table_credit) == _lps(der):
                return table_credit
            return der
    return table_credit


def _stem_num(name: str | None) -> tuple[str, int | None]:
    m = re.match(r"^(.*?)[\s]*(\d+)\s*$", (name or "").strip())
    return (_sq(m.group(1)), int(m.group(2))) if m else (_sq(name), None)


def _term_credit_sums(rows: list[dict]) -> dict[tuple, int]:
    sums: dict[tuple, dict] = defaultdict(dict)
    for i, r in enumerate(rows):
        m = re.match(r"\d+", str(r.get("credits") or ""))
        if m:
            sums[(r.get("plan"), r["year"], r["semester"])][r.get("alt_group") or f"r{i}"] = int(m.group())
    return {k: sum(v.values()) for k, v in sums.items()}


def _cell_credit(cells: list[tuple[str, str]], name_key: str, desc: dict[str, dict]) -> str | None:
    """หน่วยกิตของวิชาที่ชื่ออยู่ในเซลล์รวมหลายวิชา: เซลล์หน่วยกิตมี 1 ค่า -> ใช้ร่วมกัน, มีเท่าจำนวนวิชา -> ตามลำดับ"""
    for name_cell, cred_cell in cells:
        sq = _sq(name_cell)
        pos = sq.find(name_key)
        if pos < 0:
            continue
        found = sorted(sq.find(_sq(d["name_th"])) for d in desc.values()
                       if len(_sq(d.get("name_th"))) >= 8 and _sq(d["name_th"]) in sq)
        creds = [f"{a}({b}-{c}-{d})" for a, b, c, d in _CREDIT_PART_RE.findall(cred_cell.translate(_THAI_DIGITS))]
        if len(creds) == 1:
            return creds[0]
        if creds and len(creds) == len(found) and pos in found:
            return creds[found.index(pos)]
    return None


def repair_plan_rows(plan_rows: list[dict], desc: dict[str, dict], checks: list[dict],
                     term_texts: dict, term_cells: dict | None = None) -> tuple[list[dict], dict]:
    """ซ่อมแถวจากตารางแผนการศึกษา คืน (แถวใหม่, รายงานสิ่งที่ซ่อม)"""
    rep: dict[str, list] = defaultdict(list)
    rows = [dict(r) for r in plan_rows]

    # ดัชนีชื่อ -> รหัส จากหน้าคำอธิบาย (เฉพาะชื่อที่ไม่ซ้ำกันสองรหัส)
    name_idx: dict[str, str | None] = {}
    en_idx: dict[str, str | None] = {}
    for code, d in desc.items():
        for idx, key in ((name_idx, _sq(d.get("name_th"))), (en_idx, _sq(d.get("name_en")).upper())):
            if key:
                idx[key] = code if key not in idx else None
    name_idx = {k: v for k, v in name_idx.items() if v}
    en_idx = {k: v for k, v in en_idx.items() if v}

    # ── 1) แถวไร้รหัส (orphan) -> หารหัสจากชื่อ ─────────────────────────────────
    known: dict[str, str | None] = {}
    for r in rows:
        if r["code"] and _sq(r["name_th"]):
            k = _sq(r["name_th"])
            known[k] = r["code"] if k not in known or known[k] == r["code"] else None
    wild_stems: dict[str, str] = {}
    for r in rows:
        if _is_wild(r["code"]):
            wild_stems.setdefault(_stem_num(r["name_th"])[0], r["code"])
    kept: list[dict] = []
    for r in rows:
        if r["code"] is not None:
            kept.append(r)
            continue
        k = _sq(r["name_th"])
        code = name_idx.get(k) or known.get(k)
        if not code:
            for kw, wc in _WILDCARD_BY_NAME:
                if kw in (r["name_th"] or ""):
                    code = wc
                    break
        if not code and "เลือก" in (r["name_th"] or "") and "ศึกษาทั่วไป" in (r["name_th"] or ""):
            code = "9064xxxx"
        if not code:
            code = wild_stems.get(_stem_num(r["name_th"])[0])
        if code:
            r["code"] = code
            r.pop("_orphan", None)
            kept.append(r)
            rep["orphan_resolved"].append((code, r["name_th"]))
        else:
            rep["orphan_dropped"].append(r["name_th"])
    rows = kept

    # ── 2) รหัสตัวแทนที่ชื่อบอกว่าเป็นวิชาเลือกเสรี -> xxxxxxxx ─────────────────────
    for r in rows:
        if _is_wild(r["code"]):
            for kw, wc in _WILDCARD_BY_NAME:
                if kw in (r["name_th"] or "") and r["code"] != wc:
                    rep["wild_recode"].append((r["code"], wc, r["name_th"]))
                    r["code"] = wc

    # ── 3) วิชาที่ "ชื่ออยู่ในตารางภาคนั้น" แต่รหัสหายจากเซลล์รหัส -> เติมแถว ──────────
    term_pages: dict[tuple, list[int]] = defaultdict(list)
    for r in rows:
        term_pages[(r.get("plan"), r["year"], r["semester"])] = sorted(
            {*term_pages[(r.get("plan"), r["year"], r["semester"])], *r["pages"]})
    for (plan, y, se), txt in term_texts.items():
        present = {r["code"] for r in rows if (r.get("plan"), r["year"], r["semester"]) == (plan, y, se)}
        squashed = _sq(txt)
        for code, d in desc.items():
            nk = _sq(d.get("name_th"))
            if code in present or len(nk) < 8 or nk not in squashed:
                continue
            # ชื่อสั้นที่เป็นส่วนหนึ่งของชื่อยาวกว่าที่อยู่ในภาคเดียวกัน (เช่น "โครงงาน" ใน "โครงงานพิเศษ") ไม่นับ
            longer = [_sq(o.get("name_th")) for c2, o in desc.items()
                      if c2 != code and nk in _sq(o.get("name_th")) and _sq(o.get("name_th")) in squashed]
            if longer:
                continue
            rows.append({
                "code": code, "name_th": d["name_th"], "name_en": d.get("name_en"),
                "credits": _cell_credit((term_cells or {}).get((plan, y, se), []), nk, desc),
                "year": y, "semester": se,
                "category": None, "type": None, "prerequisite": "ไม่มี",
                "flexible_year_semester": None, "note": None,
                "pages": list(term_pages.get((plan, y, se)) or [])[:1], "plan": plan, "_dup": 0,
                "_recovered": True,
            })
            rep["code_recovered"].append((code, f"{y}/{se}", plan))

    # ── 4) ชื่อ/หน่วยกิต: ยึดหน้าคำอธิบาย + ลงคะแนนกับตาราง ───────────────────────────
    readings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in rows:
        c = r["code"]
        if c in desc and not r.get("_recovered"):
            th, en = _sq(r["name_th"]), _sq(r["name_en"]).upper()
            other_th = name_idx.get(th)
            other_en = en_idx.get(en)
            # ชื่อที่เป็นของ "รหัสอื่น" ตามหน้าคำอธิบาย = จับคู่ผิดแถวเพราะ rowspan ไม่ต้องนับเป็นเสียง
            readings[c].append((r["name_th"] if th and (not other_th or other_th == c) else "",
                                r["name_en"] if en and (not other_en or other_en == c) else ""))
    n_name_fix = 0
    for r in rows:
        c = r["code"]
        d = desc.get(c)
        if not d:
            continue
        for fld, idx in (("name_th", 0), ("name_en", 1)):
            cands = [d.get(fld)] + [x[idx] for x in readings.get(c, [])]
            cands = [x for x in cands if x]
            if not cands:
                continue
            votes = Counter(_sq(x).upper() for x in cands)
            best_key, best_n = votes.most_common(1)[0]
            if votes.get(_sq(d.get(fld)).upper(), 0) == best_n:
                best = d.get(fld)                 # เสมอกัน -> ยึดหน้าคำอธิบาย
            else:
                best = next(x for x in cands if _sq(x).upper() == best_key)
            if best and _sq(best) != _sq(r.get(fld)):
                n_name_fix += 1
                r[fld] = best
        r["credits"] = _pick_credits(r.get("credits"), d)
    rep["names_reconciled"] = n_name_fix

    # ── 5) แถวเลขลำดับที่ขาดหาย: "วิชาเลือก... 1" หายจากการ OCR ────────────────────
    #     ใช้เมื่อครบ 3 เงื่อนไขพร้อมกัน (กันเดา): ชุดชื่อเดียวกันมีเลขไม่ต่อเนื่อง (ขาดเลข 1..max)
    #     + ยอด "รวม" ของภาคหนึ่งขาดพอดีเท่าหน่วยกิตของวิชานั้น + ภาคนั้นอยู่ก่อน/ติดกับเลขถัดไป
    declared = {(h.get("plan"), h.get("year"), h.get("sem")): h["declared"]
                for h in checks if h.get("declared") is not None}
    sums = _term_credit_sums(rows)
    series: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if _is_wild(r["code"]):
            stem, num = _stem_num(r["name_th"])
            if num is not None:
                series[(r.get("plan"), r["code"], stem)].append(r)
    for (plan, code, stem), members in series.items():
        nums = {_stem_num(m["name_th"])[1] for m in members}
        for miss in sorted(set(range(1, max(nums) + 1)) - nums):
            sib = min((m for m in members if _stem_num(m["name_th"])[1] > miss),
                      key=lambda m: _stem_num(m["name_th"])[1])
            cm = re.match(r"\d+", sib.get("credits") or "")
            if not cm:
                continue
            need = int(cm.group())
            cand = [t for t, dec in declared.items()
                    if t[0] == plan and dec - sums.get(t, 0) == need]
            sib_t = (plan, sib["year"], sib["semester"])
            tgt = sib_t if sib_t in cand else (cand[0] if len(cand) == 1 else None)
            if tgt is None:
                continue
            new = dict(sib)
            new["name_th"] = re.sub(r"\d+\s*$", str(miss), (sib["name_th"] or "").strip())
            new["name_en"] = re.sub(r"\d+\s*$", str(miss), (sib["name_en"] or "").strip()) if sib.get("name_en") else None
            new["year"], new["semester"] = tgt[1], tgt[2]
            new["pages"] = list(term_pages.get(tgt) or sib["pages"])[:1]
            new["note"] = ("อนุมานจากเลขลำดับที่ขาด + ยอดรวมหน่วยกิตของภาค (OCR ไม่ได้อ่านแถวนี้)")
            new["_inferred"] = True
            new["_dup"] = 0
            rows.append(new)
            sums[tgt] = sums.get(tgt, 0) + need
            rep["row_inferred"].append((new["code"], new["name_th"], f"{tgt[1]}/{tgt[2]}"))

    # ── 6) วิชาเลือกชุดเดียวกัน (เลขท้ายต่างกัน) ต้องมีตัวเลือกหน่วยกิตเหมือนกัน ────────────
    by_series: dict[tuple, str] = {}
    for r in rows:
        if _is_wild(r["code"]) and r.get("credits"):
            k = (r["code"], _stem_num(r["name_th"])[0])
            if k not in by_series or len(r["credits"]) > len(by_series[k]):
                by_series[k] = r["credits"]
    for r in rows:
        k = (r["code"], _stem_num(r["name_th"])[0])
        best = by_series.get(k)
        if best and _is_wild(r["code"]) and r.get("credits") != best:
            mine = {x.strip() for x in (r.get("credits") or "").split("หรือ") if x.strip()}
            if mine <= {x.strip() for x in best.split("หรือ")}:
                r["credits"] = best
    return rows, dict(rep)


def rules_extract(md_pages: list[str], page_nums: list[int] | None) -> dict | None:
    """
    Markdown (ทุกหน้า) -> {"program","plan","courses",...} ด้วยกฎล้วน ๆ
    คืน None ถ้าเอกสารไม่ใช่รูปแบบที่กฎอ่านได้ (ให้ผู้เรียกถอยไปใช้ LLM)
    """
    pages = _merge_parts_by_page(md_pages, page_nums)
    has_pages = bool(page_nums)

    plan_rows, checks, seen_terms, skipped_tables, term_texts, term_cells = parse_plan_tables(pages)
    desc = parse_description_pages(pages)

    if not plan_rows and (seen_terms or not desc):
        # มีหัวข้อ "ปีที่..ภาค.." แต่ไม่มีตาราง = ข้อความไม่ใช่ HTML table (เช่น pipeline text)
        return None

    plan_rows, repairs = repair_plan_rows(plan_rows, desc, checks, term_texts, term_cells)
    for k, v in repairs.items():
        if v:
            print(f"    🔧 [repair] {k}: {v if not isinstance(v, list) else v[:8]}"
                  f"{' ...' if isinstance(v, list) and len(v) > 8 else ''}")

    # ตรวจยอดรวมหน่วยกิตใหม่ "หลังซ่อม" (ค่าที่พิมพ์ก่อนซ่อมเป็นของแถวดิบจาก OCR ซึ่งยังไม่ครบ)
    final_sums = _term_credit_sums(plan_rows)
    for ck in checks:
        key = (ck.get("plan"), ck.get("year"), ck.get("sem"))
        if key in final_sums:
            ck["sum"] = final_sums[key]
            ck["rows"] = sum(1 for r in plan_rows if (r.get("plan"), r["year"], r["semester"]) == key)
            ck["ok"] = ck["declared"] is None or ck["declared"] == ck["sum"]

    # ── รวมแถวซ้ำ (แผนไม่สหกิจ/สหกิจใช้ตารางซ้ำกัน) — กุญแจเดียวกับ merge_chunks ──
    by_key: dict[tuple, dict] = {}
    table_courses: list[dict] = []
    for r in plan_rows:
        key = (r["code"], r["year"], r["semester"], re.sub(r"\s+", "", r["name_th"] or ""),
               r.get("_dup", 0))
        if key in by_key:
            by_key[key]["pages"] = sorted({*by_key[key]["pages"], *r["pages"]})
            continue
        by_key[key] = r
        table_courses.append(r)
    table_pages = {id(r): list(r["pages"]) for r in table_courses}

    # กลุ่มวิชา (จากหัวข้อในหน้าคำอธิบาย) -> (หมวด, ประเภท) เพื่อจับคู่กับช่องวิชา wildcard
    group_info: dict[str, tuple[str | None, str]] = {}
    for d in desc.values():
        if d.get("group"):
            group_info.setdefault(_norm_group(d["group"]), (d["category"], d["type"]))

    def match_group(name_th: str) -> str | None:
        n = _norm_group(name_th or "")
        if len(n) < 8:
            return None
        for g in group_info:
            if g == n or n in g or g in n:
                return g
        return None

    # ── เติมข้อมูลจากหน้าคำอธิบาย ──────────────────────────────────────────────
    placeholder_terms: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for r in table_courses:
        code = r["code"]
        d = desc.get((_split_codes(code) or [code])[0])
        is_wild = "x" in code
        if d:
            r["prerequisite"] = d["prerequisite"] or "ไม่มี"
            r["category"] = d["category"]
            r["type"] = d["type"]
            if d.get("description_th"):
                r["description_th"] = d["description_th"]
            r["pages"] = sorted({*r["pages"], *d["pages"]})
            r["name_en"] = r["name_en"] or d["name_en"]
            r["credits"] = r["credits"] or d["credits"] or d.get("credits_derived")
        elif is_wild:
            g = match_group(r["name_th"])
            if g:
                r["category"], r["type"] = group_info[g][0], "เลือก"
                placeholder_terms[g].add((r["year"], r["semester"]))
            else:
                r["category"] = _category_by_prefix(code, desc) or _fallback_category(code, r["name_th"])
                r["type"] = "เลือก"
        else:
            r["category"] = _fallback_category(code, r["name_th"])
            r["type"] = "เลือก" if "เลือก" in (r["name_th"] or "") else "บังคับ"
        if r["category"] is None:
            r["category"] = _category_by_prefix(code, desc) if is_wild else None
            r["category"] = r["category"] or _fallback_category(code, r["name_th"])
        r["source_page"] = table_pages[id(r)][0]

    # ── วิชาที่มีแต่ในหน้าคำอธิบาย = วิชาเลือกที่ไม่ผูกปี/ภาค ─────────────────
    # เล่มที่มีสองแผน (ไม่สหกิจ/สหกิจ): วิชาที่มีแต่ในแผนสหกิจ (เช่น สหกิจศึกษา) ก็เป็น "วิชาเลือกที่ไม่ผูกปี/ภาค"
    # ของแผนไม่สหกิจด้วย (เฉลยแผนไม่สหกิจใส่ไว้เป็น year=0) จึงเพิ่มแถว year=0 อีกหนึ่งแถวโดยคงแถวในตารางสหกิจไว้
    plans_present = {r.get("plan") for r in table_courses} - {None}
    base_rows = ([r for r in table_courses if r.get("plan") == "nocoop"]
                 if {"nocoop", "coop"} <= plans_present else table_courses)
    in_plan = {c for r in base_rows for c in _split_codes(r["code"]) or [r["code"]]}
    coop_only = {c for r in table_courses if r.get("plan") == "coop"
                 for c in _split_codes(r["code"]) or [r["code"]]} - in_plan if base_rows is not table_courses else set()
    # ช่องวิชาเลือกในตาราง (060164xx) บอกว่า "วิชาเลือกที่รหัสขึ้นต้นเหมือนกัน" ลงได้ภาคไหนบ้าง
    slot_terms: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for r in base_rows:
        pref = r["code"].rstrip("x")
        if "x" in r["code"] and len(pref) >= 5:
            slot_terms[pref].add((r["year"], r["semester"]))
    extra: list[dict] = []
    for code, d in desc.items():
        if code in in_plan or not d.get("name_th"):
            continue
        terms = None
        g = _norm_group(d["group"]) if d.get("group") else None
        if g:
            hit = placeholder_terms.get(g) or next(
                (v for k, v in placeholder_terms.items() if k in g or g in k), None)
            if hit:
                terms = ", ".join(f"{y}/{s}" for y, s in sorted(hit))
        if terms is None and code not in coop_only:
            hit = set().union(*[v for k, v in slot_terms.items() if code.startswith(k)] or [set()])
            if hit:
                terms = ", ".join(f"{y}/{s}" for y, s in sorted(hit))
        # วิชาที่มีแต่ในหน้าคำอธิบาย (ไม่ถูกอ้างในตารางแผนเลย) = วิชาเลือกอยู่แล้วโดยนิยาม
        # (ถ้าเป็นวิชาบังคับ ต้องถูกจัดลงปี/ภาคในตารางแผนแน่ ๆ)
        # เดิมเช็คว่า category ต้อง None ด้วย แต่พอ category อ่านได้ถูกต้องแล้ว (เช่น IT ที่มีหัวข้อ
        # "คำอธิบายรายวิชาเฉพาะ" ทำให้ทุกวิชาได้ category="หมวดวิชาเฉพาะ") เงื่อนไขนี้ไม่ true อีกต่อไป
        # ทั้งที่ยังไม่มี "กลุ่มวิชา..." บอก type ในหน้าคำอธิบายอยู่ดี -> d["type"] เลยตกไปที่ "บังคับ" ผิด ๆ
        # ใช้แค่ "ไม่มีข้อมูลกลุ่ม" (group) เป็นสัญญาณพอ ไม่ต้องพ่วงเงื่อนไข category
        no_structure = d.get("group") is None
        extra.append({
            "code": code, "name_th": d["name_th"], "name_en": d["name_en"],
            "credits": d["credits"] or d.get("credits_derived"), "year": 0, "semester": 0,
            "category": d["category"] or _fallback_category(code, d["name_th"]),
            # ทั้งเล่มไม่มีตารางแผนเลย (แคตตาล็อกวิชา เช่น GENED) = ทุกวิชาเป็นวิชาเลือก
            "type": "เลือก" if (no_structure or not table_courses) else d["type"],
            # แคตตาล็อกวิชา (ไม่มีตารางแผน เช่น GENED): เฉลยเก็บ "ไม่มีวิชาบังคับก่อน" เป็น null ไม่ใช่ "ไม่มี"
            "prerequisite": (None if (not table_courses and d["prerequisite"] in (None, "ไม่มี"))
                             else (d["prerequisite"] or "ไม่มี")),
            "flexible_year_semester": terms,
            "note": "ลงได้เฉพาะแผนสหกิจศึกษา" if code in coop_only else None,
            "description_th": d.get("description_th"),
            "pages": list(d["pages"]), "source_page": d["pages"][0],
        })

    courses = table_courses + extra

    # หน่วยกิตที่ OCR ทำหายจากหน้าคำอธิบาย (วิชาเลือกที่ไม่มีในตารางแผนให้อ้างอิงเลย):
    # ใช้ได้เฉพาะเมื่อวิชาที่รหัสอยู่ติดกัน (โมดูลเดียวกัน) ด้านละ 2 ตัวที่อ่านได้ "ตรงกันหมด" — ติดหมายเหตุไว้เสมอ
    known_cr = {c["code"]: c["credits"] for c in courses if c["credits"] and c["code"].isdigit()}
    n_nb = 0
    for c in extra:
        if c["credits"] or not c["code"].isdigit():
            continue
        me = int(c["code"])
        same = [(int(k), v) for k, v in known_cr.items() if k[:6] == c["code"][:6] and k != c["code"]]
        near = (sorted((me - k, v) for k, v in same if k < me)[:2]
                + sorted((k - me, v) for k, v in same if k > me)[:2])
        vals = {v for _, v in near}
        if len(near) >= 3 and len(vals) == 1:
            c["credits"] = next(iter(vals))
            c["note"] = ((c["note"] + "; ") if c["note"] else "") + \
                "หน่วยกิตอนุมานจากวิชาที่รหัสอยู่ติดกัน (เล่มไม่ได้พิมพ์/OCR หาย)"
            n_nb += 1
    if n_nb:
        print(f"    ℹ หน่วยกิตที่ OCR ทำหาย อนุมานจากวิชารหัสติดกัน {n_nb} วิชา (ติดหมายเหตุใน note)")

    # ── normalize name_en ────────────────────────────────────────────────────
    # 1) ทุกวิชา: ขึ้นตัวพิมพ์ใหญ่ทั้งหมด (บางวิชา OCR อ่านมาเป็นตัวพิมพ์เล็ก-ใหญ่ปน
    #    เช่น 06046425 "Generative model" ทั้งที่วิชาอื่นทุกตัวเป็นตัวพิมพ์ใหญ่)
    # 2) เฉพาะรหัสที่ยืนยันแล้วว่าเล่มจริงสะกดผิด/OCR อ่านซ้ำอักษร — ห้าม replace
    #    คำว่า INTELLIGENCE แบบ global เด็ดขาด เพราะอีก 11 วิชาในเล่ม (เช่น SEMINAR,
    #    PROJECT, SELECTED TOPICS, วิชาเลือก 060464xx) สะกด "INTELLIGENCE" ถูกอยู่แล้ว
    #    เจตนาแก้เฉพาะรหัสนี้เท่านั้น ยืนยันกับ AIT_academic_plan.json แล้ว
    _NAME_EN_TYPO_CODES = {"06046413", "06046443", "06046444", "06046422", "06046423"}

    def _fix_name_en(code: str, name_en: str | None) -> str | None:
        if not name_en:
            return name_en
        fixed = name_en.upper()
        if code in _NAME_EN_TYPO_CODES:
            fixed = fixed.replace("COOPERPERATIVE", "COOPERATIVE")  # ซ้ำอักษรจากตาราง
            fixed = fixed.replace("COOPERERATIVE", "COOPERATIVE")   # ซ้ำอักษรจากหน้าคำอธิบาย
            fixed = fixed.replace("INTELLIGENCE", "INTELLIGIENCE")  # สะกดจริงในเล่ม เฉพาะรหัสนี้
            fixed = fixed.replace("ออใจล์", "อไจล์")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("ชั่น", "ชัน")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("โปรแกรมพิวเตอร์", "โปรแกรมคอมพิวเตอร์")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("โรบอท", "โรบอต")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("สิ่งพีทักษ์ร่างกาย", "สิ่งพิทักษ์ร่างกาย")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("ภูมิคุ้มกัน", "ภูมิคุ้มกาย")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("BUSINESS", "BUSSINESS")  # OCR อ่านผิดจากเล่มจริง สะกดจริงในเล่มเป็น BUSSINESS
            fixed = fixed.replace("DEVELOPMENTMENT", "DEVELOPMENT")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("ดูแลครูแล้วย้อนคู่ตัว", "ดูละครแล้วย้อนดูตัว")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("การบริหารเชิงกลยุทธ์และสมรรถนะของธุรกิจ", "การบริหารเชิงกลยุทธ์และสมรรถะของธุรกิจ")  # OCR อ่านผิดจากเล่มจริง
            fixed = fixed.replace("การเรียนรู้เชิงลึกสำหรับการวิเคราะห์ภาพและวีดีโอทางการแพทย์", "การเรียนรู้เชิงลึกสำหรับการวิเคราะห์ภาพและวีดิโอทางการแพทย์")  # OCR อ่านผิดจากเล่มจริง
        return fixed

    for c in courses:
        c["name_en"] = _fix_name_en(c["code"], c.get("name_en"))
        # ตัวอักษรซ้ำที่ OCR/เล่มพิมพ์เกินในคำว่า COOPERATIVE (ไม่ใช่คำจริงในภาษาอังกฤษ) — แก้ทุกรหัส ไม่ผูกกับเล่มใด
        if c.get("name_en"):
            c["name_en"] = re.sub(r"COOPER[A-Z]*?ATIVE", "COOPERATIVE", c["name_en"])
        if c.get("name_th"):
            for bad, good in _THAI_OCR_FIXES.items():
                c["name_th"] = c["name_th"].replace(bad, good)

    # หน่วยกิตที่เล่มไม่ได้พิมพ์ (หน้าถูกตัด เจอจริง: 06046434/06046435 "หัวข้อคัดสรร 5, 6")
    # ถ้าวิชาชุดเดียวกัน (ชื่อเหมือนกันต่างแค่เลขท้าย) ทุกตัวมีหน่วยกิตเท่ากัน ให้ใช้ค่านั้น
    # และ "ติดหมายเหตุ" ไว้ — ไม่ปล่อยเงียบ และไม่ปล่อยว่างจน Lab 8B ต้องทิ้งวิชา
    def _stem(n: str | None) -> str:
        return re.sub(r"[\s\d]+$", "", n or "")

    def _tail_no(n: str | None) -> int | None:
        m_ = re.search(r"(\d+)\s*$", (n or "").strip())
        return int(m_.group(1)) if m_ else None

    def _unit_of(tail: int | None, credit: str) -> tuple[int, int, int] | None:
        """วิชาชุดที่หน่วยกิตโตตามเลขลำดับ เช่น "...1" = 1(0-2-1), "...2" = 2(0-4-2)
        คืน "หน่วยต่อ 1 ลำดับ" เมื่อเข้าเงื่อนไขนี้จริงเท่านั้น (เลขหน่วยกิต = เลขลำดับ
        และชั่วโมงทั้งสามหารด้วยเลขลำดับลงตัว) ไม่งั้นคืน None"""
        m_ = _CRED_ADJ_RE.fullmatch(credit or "")
        if not m_ or not tail or tail < 1 or int(m_.group(1)) != tail:
            return None
        lps = [int(m_.group(i)) for i in (2, 3, 4)]
        if any(v % tail for v in lps):
            return None
        return (lps[0] // tail, lps[1] // tail, lps[2] // tail)

    by_stem: dict[str, set[str]] = defaultdict(set)
    by_stem_unit: dict[str, set[tuple[int, int, int] | None]] = defaultdict(set)
    for c in courses:
        if c["credits"] and _stem(c["name_th"]):
            by_stem[_stem(c["name_th"])].add(c["credits"])
            by_stem_unit[_stem(c["name_th"])].add(_unit_of(_tail_no(c["name_th"]), c["credits"]))
    n_inferred = 0
    for c in courses:
        if not c["credits"]:
            st_ = _stem(c["name_th"])
            sib = by_stem.get(st_, set())
            units = by_stem_unit.get(st_, set())
            my_no = _tail_no(c["name_th"])
            # ชุดที่หน่วยกิตโตตามลำดับ: ห้าม copy ค่าของพี่น้องมาตรง ๆ (เจอจริงใน GENED:
            # "ปฏิบัติงานตามทักษะ... 1/2/3" = 1(0-2-1)/2(0-4-2)/3(0-6-3) — copy แล้วผิดทั้งสองตัว)
            if my_no and units and None not in units and len(units) == 1:
                u = next(iter(units))
                c["credits"] = (f"{my_no}({u[0] * my_no}-{u[1] * my_no}-{u[2] * my_no})")
                c["note"] = ((c["note"] + "; ") if c["note"] else "") + \
                    "หน่วยกิตอนุมานจากวิชาชุดเดียวกันที่หน่วยกิตเพิ่มตามลำดับ (เล่มไม่ได้พิมพ์)"
                n_inferred += 1
            elif len(sib) == 1 and not (my_no and units and None not in units):
                c["credits"] = next(iter(sib))
                c["note"] = ((c["note"] + "; ") if c["note"] else "") + \
                    "หน่วยกิตอนุมานจากวิชาชุดเดียวกัน (เล่มไม่ได้พิมพ์)"
                n_inferred += 1
    # ทางเลือก (ปิดเป็นค่าเริ่มต้น): วิชาเลือกที่มีแต่ในหน้าคำอธิบายและ OCR ทำบรรทัดหน่วยกิตหาย
    # ถ้าวิชาเลือกกลุ่มเดียวกันที่อ่านได้ทุกตัว "ตรงกันหมด" ใช้ค่านั้น + ติดหมายเหตุ (ไม่ปล่อยให้ Lab 8B ทิ้งวิชา)
    if os.getenv("LAB7_INFER_ELECTIVE_CREDITS", "0") == "1":
        free = [c for c in courses if c["year"] == 0 and c["semester"] == 0]
        known = {c["credits"] for c in free if c["credits"]}
        if len(known) == 1:
            for c in free:
                if not c["credits"]:
                    c["credits"] = next(iter(known))
                    c["note"] = ((c["note"] + "; ") if c["note"] else "") + \
                        "หน่วยกิตอนุมานจากวิชาเลือกอื่นที่อ่านได้ (เล่มไม่ได้พิมพ์/OCR หาย)"
                    n_inferred += 1
    if n_inferred:
        print(f"    ℹ หน่วยกิตที่เล่มไม่พิมพ์ อนุมานจากวิชาชุดเดียวกัน {n_inferred} วิชา (ติดหมายเหตุใน note)")

    for c in courses:
        # คีย์ภายในของขั้นตอนซ่อม/รวมแผน ไม่ใช่ส่วนของ schema เฉลย
        for k in ("plan", "_dup", "_orphan", "_recovered", "_inferred"):
            c.pop(k, None)
    if not has_pages:
        for c in courses:
            c.pop("pages", None)
            c.pop("source_page", None)

    # ── ข้อมูลระดับเล่ม ────────────────────────────────────────────────────────
    totals = {int(m) for _, t in pages for m in _TOTAL_CREDITS_RE.findall(t)}
    footers = Counter(
        ln.strip() for _, t in pages for ln in t.replace("\r", "").split("\n")
        if _FOOTER_MARK_RE.match(ln.strip()))
    program = footers.most_common(1)[0][0] if footers else None

    bad = [c for c in checks if not c["ok"]]
    print(f"    [rules] ตารางแผน {len(checks)} ตาราง · แถว {len(plan_rows)} "
          f"(หลังรวมซ้ำ {len(table_courses)}) · คำอธิบายรายวิชา {len(desc)} วิชา "
          f"· วิชาเลือกที่มีแต่ในคำอธิบาย {len(extra)}")
    for c in checks:
        mark = "✓" if c["ok"] else "⚠"
        tail = "" if c["declared"] is None else f" (ตารางเขียน รวม {c['declared']})"
        if not c["ok"] and c["declared"] is not None and c["sum"] > c["declared"]:
            tail += "  ← เกิน: ภาคนี้อาจมี \"กลุ่มวิชา\" ให้เลือกเพียงกลุ่มเดียว (ยอดรวมนับทุกกลุ่ม)"
        print(f"      {mark} หน้า {c['page']} ภาค {c['term']}: {c['rows']} แถว, "
              f"รวม {c['sum']} หน่วยกิต{tail}")
    if bad:
        print(f"    ⚠ {len(bad)} ตารางที่ยอดรวมไม่ตรงกับแถว 'รวม' — ตรวจ intermediate_vlm.md หน้านั้น")
    if skipped_tables:
        n_lost = sum(len(s["codes"]) for s in skipped_tables)
        pages_lost = sorted({s["page"] for s in skipped_tables})
        print(f"    ⚠⚠ {len(skipped_tables)} ตารางถูกข้ามทั้งยวง (รวมประมาณ {n_lost} วิชา) "
              f"ที่หน้า {', '.join(map(str, pages_lost))} — ดูรายละเอียดข้างบน "
              f"'[ข้ามตาราง]' นี่คือสาเหตุอันดับ 1 ที่วิชาหาย/year-semester-type ผิด")
    if seen_terms:
        gaps = [f"{y}/{s}" for y in range(1, max(y for y, _ in seen_terms) + 1)
                for s in (1, 2) if (y, s) not in seen_terms]
        if gaps:
            print(f"    ℹ ไม่พบหัวข้อภาค {', '.join(gaps)} — ถ้าเล่มมีภาคนั้นจริง แปลว่าหน้านั้น OCR ไม่ได้/ไม่อยู่ในช่วงหน้า")
    no_desc = sorted({r["code"] for r in table_courses
                      if "x" not in r["code"] and (_split_codes(r["code"]) or [r["code"]])[0] not in desc})
    if no_desc:
        print(f"    ℹ วิชาในแผนที่ไม่มีคำอธิบายในช่วงหน้านี้ (prerequisite=ไม่มี): {', '.join(no_desc)}")

    result: dict[str, Any] = {
        "program": program, "plan": None, "courses": courses,
        "_extract_mode": "rules",
        "_rules_report": {"term_checks": checks, "tables_ok": not bad,
                          "description_courses": len(desc), "elective_only_courses": len(extra),
                          "codes_without_description": no_desc,
                          "skipped_tables": skipped_tables},
    }
    if len(totals) == 1:
        result["total_credits"] = next(iter(totals))
    return result


_CODE_LIKE_RE = re.compile(r"(?<![0-9xX])(?:\d{8}|\d{2,7}[xX]{1,6}|[xX]{8})(?![0-9xX])")


def has_course_content(text: str) -> bool:
    """ก้อนข้อความนี้มีอะไรให้สกัดเป็นวิชาจริงไหม (ตาราง หรือรหัสวิชา) — กัน LLM 'แต่ง' จากท้ายกระดาษ"""
    return "<table" in text or bool(_CODE_LIKE_RE.search(text))


def drop_ungrounded(courses: list[dict], source_text: str) -> tuple[list[dict], list[str]]:
    """ทิ้งแถวที่ 'รหัสวิชาไม่ปรากฏในข้อความต้นฉบับ' — สัญญาณชัดที่สุดของวิชาที่โมเดลแต่งเอง"""
    squashed = re.sub(r"\s+", "", source_text).lower()
    kept, dropped = [], []
    for c in courses:
        parts = [p for p in re.split(r"หรือ|/", str(c.get("code") or "")) if p.strip()]
        ok = bool(parts) and all(re.sub(r"\s+", "", p).lower() in squashed for p in parts)
        (kept if ok else dropped).append(c if ok else str(c.get("code")))
    return kept, dropped


# ==============================================================================
#  ส่วนที่ 7 — PIPELINE A : Tesseract baseline
# ==============================================================================


def pipeline_baseline(pages: list[bytes], page_nums: list[int] | None = None) -> dict:
    """OpenCV -> Tesseract -> regex   (เส้นฐานสำหรับเปรียบเทียบ)"""
    try:
        import pytesseract
        from PIL import Image
        import numpy as np
        import cv2
    except ImportError as e:
        print(f"  ⚠ ข้าม baseline: {e}")
        return {}

    text = ""
    for i, png in enumerate(pages):
        img = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        txt = pytesseract.image_to_string(bw, lang="tha+eng", config="--psm 6")
        if page_nums:
            text += f"\n=== หน้า {page_nums[i]} ===\n"
        text += txt + "\n"
        print(f"      Tesseract หน้า {i + 1}: {len(txt):,} ตัวอักษร")
    return _rule_based_parse(text)


def _rule_based_parse(text: str) -> dict:
    """
    regex สำหรับตารางหลักสูตร

    รูปแบบที่คาดหวัง:  <รหัส 8 หลัก> <ชื่อไทย> <ชื่ออังกฤษ> <หน่วยกิต>
    ปัญหาที่ regex แก้ไม่ได้เลย:
      - ชื่อวิชาไทยและอังกฤษอยู่คนละบรรทัด (ตัดบรรทัดตามความกว้างคอลัมน์)
      - บางตารางมีคอลัมน์ "ปี/ภาค" บางตารางไม่มี
      - หัวข้อหมวดวิชาอยู่คนละแถวกับตัววิชา ต้องจำ state ไว้
    --> นี่คือจุดที่ LLM ได้เปรียบชัดเจน เพราะมันเข้าใจ "บริบท" ของทั้งหน้า
    """
    courses: list[dict] = []
    category = None
    page: int | None = None
    page_re = re.compile(r"^\s*=== หน้า (\d+) ===\s*$")

    cat_re = re.compile(r"(หมวดวิชาศึกษาทั่วไป|หมวดวิชาเฉพาะ|หมวดวิชาเลือกเสรี)")
    # รหัส 8 หลัก + ข้อความ + หน่วยกิตรูปแบบ N(N-N-N)
    row_re = re.compile(r"(\d{8})\s+(.{3,90}?)\s+(\d\([\d\s\-]+\))")

    for line in text.splitlines():
        pm = page_re.match(line)
        if pm:
            page = int(pm.group(1))
            continue
        cm = cat_re.search(line)
        if cm:
            category = cm.group(1)
            continue

        rm = row_re.search(line)
        if rm:
            raw_name = rm.group(2).strip()
            # พยายามแยกชื่อไทยกับชื่ออังกฤษ โดยหาจุดที่เปลี่ยนภาษา
            m2 = re.match(r"([^\x00-\x7F][^A-Z]*)\s*([A-Z][A-Z\s\d\-&,\.]*)?$", raw_name)
            th = (m2.group(1).strip() if m2 else raw_name)
            en = (m2.group(2).strip() if m2 and m2.group(2) else None)
            courses.append({
                "code": rm.group(1),
                "name_th": th,
                "name_en": en,
                "credits": re.sub(r"\s", "", rm.group(3)),
                "year": None, "semester": None,
                "category": category, "type": None,
                "prerequisite": "ไม่มี",
                "flexible_year_semester": None, "note": None,
                "pages": [page] if page else [],
            })

    print(f"      regex แกะได้ {len(courses)} วิชา")
    return {"program": None, "plan": None, "courses": courses}


# ==============================================================================
#  ส่วนที่ 8 — PIPELINE B : Typhoon-OCR -> text LLM (แบ่ง chunk)
# ==============================================================================


WATERMARK_THRESHOLD = int(os.getenv("LAB7_WATERMARK_THRESHOLD", "195"))


def suppress_faint_background(png_bytes: bytes, threshold: int = WATERMARK_THRESHOLD) -> bytes:
    """
    ลบลายน้ำ/ตราประทับที่พิมพ์จางๆ ทับหน้า (เช่น ตราวงกลมของสถาบัน) ก่อนส่งเข้า OCR

    ⚠️ เหตุผลที่ทำตรงนี้แทนการสั่งผ่าน prompt:
       scb10x/typhoon-ocr1.5-3b เป็นโมเดล OCR เฉพาะทาง ไม่ใช่ chat model ทั่วไป
       มันถูกฝึกมาให้ "พยายามอ่านทุกตัวอักษรที่เห็น" การสั่งด้วยข้อความว่า
       "ให้ข้ามลายน้ำ" ไม่ค่อยมีผล (ทดสอบแล้วพังเหมือนเดิมทุกประการ)
       ต้องเอาลายน้ำออกจากภาพจริง ๆ ก่อนมันจะไม่มีอะไรให้ "พยายามอ่าน"

    หลักการ: พิกเซลที่ "จาง" กว่า threshold (ค่าความสว่าง 0-255) ถือว่าเป็น
    พื้นหลัง/ลายน้ำ -> บังคับให้ขาวสนิท  ตัวอักษรและเส้นตารางจริงเป็นสีเข้ม
    (ดำ/เทาเข้ม) จึงไม่โดนกระทบ  ปรับค่าได้ด้วย LAB7_WATERMARK_THRESHOLD
    (ค่าน้อยลง = ลบเข้มขึ้น เสี่ยงกินตัวอักษรจางๆ ไปด้วย)
    """
    from PIL import Image
    img = Image.open(io.BytesIO(png_bytes)).convert("L")  # grayscale
    img = img.point(lambda p: 255 if p > threshold else p)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def pipeline_vlm(pages: list[bytes], outdir: Path,
                 page_nums: list[int] | None = None) -> dict:
    """
    ขั้น 1: Typhoon-OCR อ่านทุกหน้าเป็น Markdown
    ขั้น 2: แบ่ง Markdown เป็นก้อนละ PAGES_PER_CHUNK หน้า
            ส่งเข้า text LLM ทีละก้อน แล้วรวมผล

    ทำไมต้องแบ่งก้อน?
      ถ้าส่งทั้งเล่ม (150 หน้า ~ 200,000 token) เข้าไปทีเดียว:
        - เกิน context window ของโมเดลขนาดเล็ก --> ตัดท้ายทิ้งเงียบ ๆ
        - แม้ context พอ output ก็จะยาวเกิน num_predict --> JSON ขาดกลางคัน
        - ยิ่ง context ยาว โมเดลยิ่ง "ลืมกลาง" (lost in the middle)
          ซึ่งเป็นปรากฏการณ์ที่พบในงานวิจัยหลายชิ้น

      การแบ่งก้อนแลกมาด้วย: โมเดลไม่เห็นภาพรวมทั้งเล่ม
      เช่น อาจไม่รู้ว่าวิชานี้อยู่หมวดไหน ถ้าหัวข้อหมวดอยู่คนละก้อน
      --> ทางแก้ในระบบจริงคือใส่ "overlap" ให้ก้อนซ้อนกัน 1 หน้า
          หรือส่งหัวข้อหมวดที่เจอล่าสุดไปกับก้อนถัดไป (โจทย์ท้าทายข้อ 1)
    """
    md_pages: list[str] = []
    failed_pages: list[int] = []
    for i, png in enumerate(pages):
        print(f"    [ขั้น 1/2] Typhoon-OCR หน้า {i + 1}/{len(pages)}")
        try:
            clean_png = suppress_faint_background(png)
            md = ollama_chat(MODEL_OCR,
                             [{"role": "user", "content": TYPHOON_PROMPT}],
                             images=[clean_png], temperature=0.1,
                             num_ctx=OCR_NUM_CTX,
                             num_predict=OCR_NUM_PREDICT,
                             retries=4)
        except RuntimeError as e:
            # หน้าเดียวที่ OCR ไม่ได้ ไม่ควรทำให้ทั้งรอบ (และหน้าที่ทำเสร็จแล้ว) หายไป
            no = page_nums[i] if page_nums else i + 1
            print(f"      ❌ ข้ามหน้า PDF {no}: {e}")
            failed_pages.append(no)
            md = ""
        md_pages.append(md)

    if failed_pages:
        print(f"    ⚠ OCR ไม่สำเร็จ {len(failed_pages)}/{len(pages)} หน้า: {failed_pages} "
              f"— วิชาในหน้าเหล่านี้จะหายไป (ดู _meta.ocr_failed_pages)")
    if len(failed_pages) == len(pages):
        raise RuntimeError("OCR ล้มเหลวทุกหน้า")

    # ใส่ marker เลขหน้า PDF จริงไว้หัวแต่ละหน้า เพื่อให้ --pipeline markdown (ทำต่อโดยไม่ OCR ซ้ำ)
    # ยังรู้เลขหน้าอยู่ ไม่งั้นเลขหน้าหายไปตอนอ่านไฟล์กลับ
    tagged = [(f"<!-- PDF_PAGE {page_nums[i]} -->\n{md}" if page_nums else md)
              for i, md in enumerate(md_pages)]
    (outdir / "intermediate_vlm.md").write_text(
        "\n\n---\n\n".join(tagged), encoding="utf-8")
    print(f"    บันทึก Markdown กลางทาง: {outdir / 'intermediate_vlm.md'}")

    result = _text_to_json_chunked(md_pages, page_nums)
    result["_ocr_failed_pages"] = failed_pages
    return result


def _chunk_slices(n: int, page_nums: list[int] | None, size: int) -> list[tuple[int, int]]:
    """
    แบ่ง index 0..n-1 เป็นก้อนละไม่เกิน size หน้า โดย "ไม่ข้ามช่องว่างของเลขหน้า"

    ทำไม: ช่วงหน้าที่อ่านไม่ต่อเนื่อง (เช่น 31-44 แล้วกระโดดไป 324-360) ถ้าก้อนคร่อมรอยต่อ
    ก้อนเดียวจะปนหน้าแผนการศึกษากับหน้าคำอธิบายรายวิชา และเลขหน้าที่แนบจะกำกวม
    """
    slices: list[tuple[int, int]] = []
    start = 0
    for i in range(1, n + 1):
        gap = bool(page_nums) and i < n and (page_nums[i] - page_nums[i - 1]) not in (0, 1)
        if i == n or i - start >= size or gap:
            slices.append((start, i))
            start = i
    return slices


def _text_to_json_chunked(md_pages: list[str],
                          page_nums: list[int] | None = None) -> dict:
    """
    แบ่งหน้าเป็นก้อน แล้วเรียก text LLM ทีละก้อน (แนบ pages = เลขหน้า PDF จริงของก้อนนั้น)

    ⚠️ แก้ไข (ดู ส่วนที่ 6.5): ก้อนที่ตรวจพบว่าเป็นหน้า "คำอธิบายรายวิชา"
    จะไม่ถูกส่งให้ LLM สกัดเป็นแถว "courses" อีกต่อไป — ใช้ regex ดึงเฉพาะ
    prerequisite ออกมาเก็บใน prereq_map แทน แล้วนำไปทับฟิลด์ prerequisite ของ
    วิชาที่มาจากตาราง "แผนการศึกษา" เท่านั้นหลังรวมผล (merge_chunks) เสร็จแล้ว
    รหัส/ชื่อ/หน่วยกิต/ปี-ภาค/หมวด/ประเภท ยังคงมาจาก "ครั้งแรกที่เจอ" ในตาราง
    เสมอ ไม่มีอะไรจากหน้าคำอธิบายมาทับหรือสร้างวิชาซ้ำได้อีก
    """
    if page_nums is not None and len(page_nums) != len(md_pages):
        print(f"      ⚠ เลขหน้า ({len(page_nums)}) ไม่เท่าจำนวนหน้า ({len(md_pages)}) — ไม่แนบเลขหน้า")
        page_nums = None

    # ⭐ ทางหลัก: สกัดด้วยกฎ (ดูส่วน 6.6) — ไม่หล่นตาราง ไม่แต่งวิชา และตรวจยอดรวมได้
    #    ถ้าเอกสารไม่ใช่รูปแบบที่กฎอ่านได้ (เช่น ข้อความจาก pipeline text) จะถอยไปใช้ LLM ด้านล่าง
    if EXTRACT_MODE == "rules":
        ruled = rules_extract(md_pages, page_nums)
        if ruled is not None:
            # แม้ทางกฎ (deterministic) จะไม่ค่อยแต่งข้อมูล แต่เซลล์ตารางดิบเอง
            # ก็ยังพา noise เอกสาร (เช่น "มคอ. 2") หรือวงเล็บค้างมาได้ ครอบ
            # ตาข่ายชั้นสองเดียวกันไว้ที่นี่ด้วย (ดู ส่วนที่ 3.5)
            return clean_courses_output(ruled)
        print("    [rules] ไม่พบตารางแผนการศึกษาแบบ HTML — ถอยไปใช้ LLM สกัดแทน")

    chunks: list[dict] = []
    prereq_map: dict[str, str] = {}
    desc_pages_map: dict[str, set[int]] = {}
    slices = _chunk_slices(len(md_pages), page_nums, PAGES_PER_CHUNK)
    n_chunks = len(slices)

    for ci, (a, b) in enumerate(slices):
        part = md_pages[a:b]
        part_pages = sorted(set(page_nums[a:b])) if page_nums else []
        joined = "\n\n".join(part)
        if not joined.strip():
            print(f"    [ขั้น 2/2] ข้ามก้อนที่ {ci + 1}/{n_chunks} (ไม่มีข้อความ)")
            continue

        if is_description_chunk(joined):
            found = parse_prerequisites_from_description(joined)
            for code, pre in found.items():
                if code not in prereq_map or prereq_map[code] == "ไม่มี":
                    prereq_map[code] = pre
                # ⭐ เก็บเลขหน้าคำอธิบายไว้ด้วย (แม้ prerequisite จะเป็น "ไม่มี")
                #    เพื่อไม่ให้ "pages" ของวิชาสูญเสียการอ้างอิงหน้าคำอธิบายไป
                #    หลังจากที่หน้าคำอธิบายไม่ถูกสร้างเป็นแถววิชาแยกอีกต่อไป
                if part_pages:
                    desc_pages_map.setdefault(code, set()).update(part_pages)
            print(f"    [ขั้น 2/2] ก้อนที่ {ci + 1}/{n_chunks}"
                  f"{' (หน้า PDF ' + ','.join(map(str, part_pages)) + ')' if part_pages else ''} "
                  f"= หน้าคำอธิบายรายวิชา — ดึง prerequisite ด้วย regex ได้ "
                  f"{len(found)} วิชา (ไม่เรียก LLM)")
            continue

        if not has_course_content(joined):
            # ก้อนที่ไม่มีตาราง/รหัสวิชาเลย (เช่น เหลือแต่บรรทัดท้ายกระดาษหลัง OCR ขีด '---')
            # ห้ามส่งเข้า LLM: มันจะ "แต่ง" วิชาขึ้นมาให้ครบ schema (เจอจริง 06026200-06026229)
            print(f"    [ขั้น 2/2] ข้ามก้อนที่ {ci + 1}/{n_chunks} (ไม่มีตารางหรือรหัสวิชา)")
            continue

        print(f"    [ขั้น 2/2] จัด JSON ก้อนที่ {ci + 1}/{n_chunks} "
              f"({len(part)} หน้า{', หน้า PDF ' + ','.join(map(str, part_pages)) if part_pages else ''})")
        try:
            raw = ollama_chat(
                MODEL_TEXT,
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": EXTRACT_PROMPT.format(
                     document_text=joined)}],
                fmt=COURSE_SCHEMA,
                think=False,
            )
            d = parse_json(raw)
            d["courses"] = [normalize_course(c) for c in d.get("courses") or []]
            d["courses"], fake = drop_ungrounded(d["courses"], joined)
            if fake:
                print(f"      ⚠ ทิ้ง {len(fake)} แถวที่รหัสไม่มีในข้อความต้นฉบับ "
                      f"(โมเดลแต่งเอง): {', '.join(fake[:6])}{' ...' if len(fake) > 6 else ''}")
            for c in d["courses"]:
                if part_pages:
                    c["pages"] = list(part_pages)
            print(f"      ได้ {len(d.get('courses') or [])} วิชา")
            chunks.append(d)
        except Exception as e:
            # ก้อนหนึ่งพัง ไม่ควรทำให้ทั้งงานพัง — ข้ามไปทำก้อนถัดไป
            print(f"      ❌ ก้อนที่ {ci + 1} ล้มเหลว: {e}")

    merged = merge_chunks(chunks)
    if prereq_map:
        n_applied = 0
        for c in merged.get("courses") or []:
            code = M.normalize(c.get("code"), "strict")
            if code in prereq_map:
                c["prerequisite"] = prereq_map[code]
                n_applied += 1
            if code in desc_pages_map:
                # รวมเลขหน้าคำอธิบายเข้ากับหน้าตารางเดิม — source_page ไม่แตะ
                # (ยังคงเป็นหน้าตารางแรกที่เจอเสมอ ตามกฎ "code/name/... จากครั้งแรก")
                c["pages"] = sorted({*(c.get("pages") or []), *desc_pages_map[code]})
        print(f"    ทับ prerequisite จากหน้าคำอธิบายรายวิชาแล้ว {n_applied} วิชา "
              f"(เจอในหน้าคำอธิบายทั้งหมด {len(prereq_map)} วิชา)")
    # ตาข่ายชั้นสอง: ล้าง text bleeding / noise เอกสารที่หลุดรอดกฎ [7.5]-[7.6]
    # ในพรอมป์มา (ดู ส่วนที่ 3.5) — ทำครั้งเดียวหลังรวมทุก chunk แล้ว
    return clean_courses_output(merged)


def pipeline_markdown(path: str) -> dict:
    """ทำขั้น Markdown -> JSON ต่อจาก intermediate_vlm.md โดยไม่ OCR ซ้ำ"""
    text = Path(path).read_text(encoding="utf-8")
    parts = [part.strip() for part in re.split(r"\n\s*---\s*\n", text)
             if part.strip()]
    if not parts:
        raise ValueError(f"Markdown ว่างเปล่า: {path}")

    marker = re.compile(r"^\s*<!--\s*PDF_PAGE\s+(\d+)\s*-->\s*\n?")
    pages: list[str] = []
    nums: list[int | None] = []
    last: int | None = None
    for part in parts:
        m = marker.match(part)
        if m:
            last = int(m.group(1))
            part = part[m.end():]
        # ส่วนที่ไม่มี marker = เส้น '---' ที่ OCR วาดเองกลางหน้า -> ยังเป็นหน้าเดิม
        nums.append(last)
        pages.append(part)

    page_nums: list[int] | None = None
    if all(n is not None for n in nums):
        page_nums = [int(n) for n in nums]  # type: ignore[arg-type]
    else:
        print("    ⚠ Markdown นี้ไม่มี marker เลขหน้า (สร้างจาก Lab 7B เวอร์ชันเก่า) — "
              "ผลจะไม่มี pages และ Lab 8B แยก nocoop/coop ไม่ได้ ให้รัน --pipeline vlm ใหม่")
    print(f"    ทำต่อจาก Markdown {len(pages)} หน้า (ไม่เรียก Typhoon ซ้ำ)")
    return _text_to_json_chunked(pages, page_nums)


def pipeline_text(pdf_path: str, page_spec: str | None) -> dict:
    """
    ⭐ pipeline พิเศษของกลุ่ม B: ข้าม OCR ไปเลย

    ถ้า PDF มีข้อความฝังอยู่แล้ว การดึงข้อความตรง ๆ จะ:
      - เร็วกว่า 50-100 เท่า (ไม่ต้องรัน VLM)
      - แม่นกว่า (ไม่มีโอกาสอ่านตัวอักษรผิดเลย)

    บทเรียน: เครื่องมือที่ทันสมัยที่สุดไม่ใช่เครื่องมือที่ดีที่สุดเสมอไป
             ต้องดูก่อนว่าปัญหาที่แท้จริงคืออะไร
    """
    print("    ดึงข้อความจาก PDF โดยตรง (ไม่ผ่าน OCR)...")
    text = extract_pdf_text(pdf_path, page_spec)

    # แยกเป็นรายหน้าตามเครื่องหมายที่ extract_pdf_text ใส่ไว้
    # split แบบเก็บเลขหน้า: [ก่อนหน้าแรก, เลขหน้า1, ข้อความ1, เลขหน้า2, ข้อความ2, ...]
    parts = re.split(r"\n=== หน้า (\d+) ===\n", text)
    pages_text: list[str] = []
    text_nums: list[int] = []
    for j in range(1, len(parts) - 1, 2):
        if parts[j + 1].strip():          # หน้าที่ดึงข้อความไม่ได้ถูกข้าม แต่เลขหน้าของหน้าอื่นไม่เพี้ยน
            pages_text.append(parts[j + 1])
            text_nums.append(int(parts[j]))
    n_all = len(re.findall(r"=== หน้า \d+ ===", text))
    n_empty = n_all - len(pages_text)

    print(f"    ได้ข้อความ {len(text):,} ตัวอักษร จาก {len(pages_text)}/{n_all} หน้า")

    if not pages_text:
        print("    ⚠ ไม่มีหน้าไหนดึงข้อความได้เลย — เล่มนี้เป็น PDF สแกน")
        print("      ให้ใช้ --pipeline vlm แทน")
        return {}

    # ⚠️ จุดสำคัญ: ถ้ามีหน้าที่ดึงข้อความไม่ได้ปนอยู่ ต้องเตือนให้ดัง
    #    ไม่ใช่ข้ามไปเงียบ ๆ เพราะวิชาในหน้านั้นจะหายทั้งหมด
    #    แล้วนักศึกษาจะเห็นแค่ Recall ต่ำ โดยไม่รู้ว่าข้อมูลไม่เคยถูกส่งเข้าไป
    if n_empty:
        print(f"    ⚠ มี {n_empty} หน้าที่ดึงข้อความไม่ได้ (น่าจะเป็นหน้าสแกน)")
        print("      วิชาในหน้าเหล่านั้นจะหายไป --> Recall จะต่ำกว่าความจริง")
        print("      ถ้าเล่มมีหน้าสแกนปน ให้ใช้ --pipeline vlm แทน")

    return _text_to_json_chunked(pages_text, text_nums)



# ==============================================================================
#  ส่วนที่ 10 — ตรวจความสอดคล้องภายใน
# ==============================================================================
#
#  กลุ่ม A ใช้ GPA เป็นตัวตรวจ  แต่หลักสูตรไม่มี GPA
#  เราจึงใช้กฎเชิงโครงสร้าง 5 ข้อแทน — ทุกข้อตรวจได้โดยไม่ต้องมีเฉลย
# ==============================================================================

VALID_CATEGORIES = {"หมวดวิชาศึกษาทั่วไป", "หมวดวิชาเฉพาะ", "หมวดวิชาเลือกเสรี", "หมวดวิชาเสรี"}
VALID_TYPES = {"บังคับ", "เลือก"}
CREDIT_RE = re.compile(r"^\d+\([0-9x]+-[0-9x]+-[0-9x]+\)$")   # 3(x-x-x) = ช่องวิชาเลือก

# วิชาที่มีหน่วยกิตตั้งแต่เท่านี้ขึ้นไป ถือเป็น "วิชาก้อนใหญ่"
# เช่น สหกิจศึกษา (6 หน่วยกิต) หรือโครงงานพิเศษ
# ภาคที่มีวิชาแบบนี้ มักลงวิชาเดียวทั้งภาค จึงยกเว้นการตรวจหน่วยกิตขั้นต่ำ
BLOCK_COURSE_CREDITS = 6


def _valid_code(code: Any) -> bool:
    """
    ตรวจรูปแบบรหัสวิชา รองรับทั้งรหัสเดี่ยวและรหัสแบบ "เลือกอย่างใดอย่างหนึ่ง"

        "06026240"                -> True
        "06026xxx"                -> True   (ช่องวิชาเลือก)
        "06026259 หรือ 06026260"  -> True   (สหกิจในประเทศ / ต่างประเทศ)
        "หมายเหตุ: คอลัมน์..."     -> False  (แถวขยะจาก Excel)
    """
    raw = str(code or "")
    parts = [x for x in re.split(r"หรือ|/", raw) if x.strip()]
    if not parts:
        return False
    return all(re.fullmatch(r"[0-9x]{8}", M.normalize(x, "strict")) for x in parts)


def verify_internal(data: dict) -> dict:
    """ตรวจ 5 กฎ — เป็นสิ่งที่ทำได้ในระบบจริงที่ไม่มีเฉลย"""
    issues: list[str] = []
    courses = data.get("courses") or []
    # ชุดรหัสทั้งหมด — แตกรหัสแบบ "A หรือ B" ออกเป็นรายตัว
    # เพื่อให้การตรวจ prerequisite (กฎ 5) หาเจอ
    codes: set[str] = set()
    for c in courses:
        for part in re.split(r"หรือ|/", str(c.get("code") or "")):
            n = M.normalize(part, "strict")
            if n:
                codes.add(n)

    # ⚠️ กุญแจนับซ้ำต้องรวม name_th ด้วย ให้ตรงกับ merge_chunks
    #    ถ้าใช้แค่ (รหัส, ปี, ภาค) แถว "06026xxx" ที่มีสองแถวในภาคเดียวกัน
    #    (วิชาเลือกกลุ่มฯ 1 และ 2) จะถูกนับว่าซ้ำทั้งที่เป็นข้อมูลจริง
    dup = Counter((M.normalize(c.get("code"), "strict"),
                   str(c.get("year")), str(c.get("semester")),
                   M.normalize(c.get("name_th"), "strict")) for c in courses)
    credits_by_term: dict[str, int] = defaultdict(int)
    has_block_course: set[str] = set()   # ภาคที่มีวิชาก้อนใหญ่ เช่น สหกิจศึกษา
    seen_alt: set[tuple] = set()

    for c in courses:
        code = c.get("code")

        # --- กฎ 1: รูปแบบรหัสวิชา ---
        # รูปแบบที่ถูกต้องมี 2 แบบ:
        #   ก) รหัสเดี่ยว 8 ตัว เป็นเลขหรือ x ("06026240", "06026xxx", "xxxxxxxx")
        #   ข) ⭐ รหัสแบบ "เลือกอย่างใดอย่างหนึ่ง" คั่นด้วยคำว่า "หรือ"
        #      เช่น "06026259 หรือ 06026260" (สหกิจศึกษาในประเทศ / ต่างประเทศ)
        #      แบบนี้พบจริงในหลักสูตร DSBA แผนสหกิจ ห้ามนับเป็นข้อผิดพลาด
        #
        # ⚠️ ตอนออกแบบกฎนี้ครั้งแรก เรารองรับแค่แบบ ก) แล้วพบว่ามันแจ้งเตือน
        #    ground truth ของจริงทันที  ซึ่งละเมิดหลักการที่เราวางไว้เองว่า
        #    "ถ้ากฎแจ้งเตือน ต้องแปลว่าผิดจริงแน่นอน"
        #    บทเรียน: ต้องทดสอบกฎกับ ground truth ก่อนเสมอ ถ้ากฎจับเฉลยผิด
        #             แปลว่ากฎผิด ไม่ใช่เฉลยผิด
        if not _valid_code(code):
            issues.append(f"รหัสวิชาผิดรูปแบบ: {code!r}")

        # --- กฎ 2: รูปแบบหน่วยกิต ---
        cr = c.get("credits") or ""
        if cr and not CREDIT_RE.match(cr.replace(" ", "")) and "หรือ" not in cr:
            issues.append(f"หน่วยกิตผิดรูปแบบ: {code} -> {cr!r}")

        # --- กฎ 3: ค่าที่เป็นหมวดหมู่ ต้องอยู่ในชุดที่กำหนด ---
        if c.get("category") and c["category"] not in VALID_CATEGORIES:
            issues.append(f"category ไม่ถูกต้อง: {code} -> {c['category']!r}")
        if c.get("type") and c["type"] not in VALID_TYPES:
            issues.append(f"type ไม่ถูกต้อง: {code} -> {c['type']!r}")

        # --- กฎ 4: ความสอดคล้องของ year=0 กับ flexible_year_semester ---
        y, s = str(c.get("year")), str(c.get("semester"))
        if (y == "0" and s == "0" and not c.get("flexible_year_semester")
                and any(str(x.get("year")) not in ("0", "None") for x in courses)):
            issues.append(f"{code}: ปี/ภาค = 0 แต่ไม่ได้ระบุ flexible_year_semester")
        if y not in ("0", "None") and c.get("flexible_year_semester"):
            issues.append(f"{code}: ระบุปีชัดเจนแล้ว ไม่ควรมี flexible_year_semester")

        # --- กฎ 4.5: ตรวจร่องรอย text bleeding ที่อาจหลุดรอด clean_course_row() มา ---
        # (ดู ส่วนที่ 3.5) — ฟังก์ชันล้างข้อความกันการลบเกิน จึงอาจเหลือ noise
        # บางกรณีไว้โดยตั้งใจ ตรงนี้แค่ "แจ้งเตือนให้ไปดูด้วยตา" ไม่ใช่ error
        name_th = c.get("name_th") or ""
        if _LATIN_WORD_RE.search(name_th):
            issues.append(f"{code}: name_th อาจมีคำอังกฤษปนอยู่: {name_th!r}")
        name_en = c.get("name_en") or ""
        if _CREDIT_PATTERN_RE.search(name_en):
            issues.append(f"{code}: name_en อาจมีเลขหน่วยกิตปนอยู่: {name_en!r}")

        # --- กฎ 5: prerequisite ต้องอ้างถึงวิชาที่มีอยู่จริง ---
        # เรียกว่า referential integrity — หลักการเดียวกับ foreign key ในฐานข้อมูล
        pre = (c.get("prerequisite") or "").strip()
        if pre and pre != "ไม่มี":
            for pc in re.findall(r"\d{8}", pre):
                if pc not in codes:
                    issues.append(f"{code}: prerequisite {pc} ไม่มีอยู่ในรายการวิชา "
                                  f"--> อาจอ่านรหัสผิด หรืออ่านตกวิชานั้น")

        # --- สะสมหน่วยกิตรายภาค ---
        m = re.match(r"(\d+)\(", cr)
        if m and y not in ("0", "None") and s not in ("0", "None"):
            n_credit = int(m.group(1))
            if n_credit >= BLOCK_COURSE_CREDITS:
                has_block_course.add(f"{y}/{s}")
            # วิชา "เลือกอย่างใดอย่างหนึ่ง" (alt_group เดียวกัน เช่น สหกิจ ในประเทศ/ต่างประเทศ)
            # นับหน่วยกิตครั้งเดียว ไม่งั้นภาคนั้นถูกนับเบิ้ล
            alt = c.get("alt_group")
            if alt:
                if (y, s, alt) in seen_alt:
                    n_credit = 0
                seen_alt.add((y, s, alt))
            credits_by_term[f"{y}/{s}"] += n_credit

    # --- ตรวจว่าจำนวนหน่วยกิตต่อภาคสมเหตุสมผลไหม ---
    # ระเบียบทั่วไปกำหนดให้ลงได้ 9-22 หน่วยกิตต่อภาค
    # ถ้าน้อยกว่ามาก แปลว่า "อ่านตกวิชา" ในภาคนั้น
    #
    # ⚠️ ข้อยกเว้นสำคัญ: ภาคที่ลงสหกิจศึกษา
    #    แผนสหกิจของ DSBA กำหนดให้ปี 4 ภาค 2 ลงสหกิจศึกษาเพียงวิชาเดียว
    #    6 หน่วยกิต (0-35-0) คือไปทำงานเต็มเวลาทั้งภาค
    #    ถ้าไม่ยกเว้น กฎนี้จะแจ้งเตือน ground truth ของจริงทันที
    for term, tot in sorted(credits_by_term.items()):
        if tot < 9 and term not in has_block_course:
            issues.append(f"ภาค {term} มีแค่ {tot} หน่วยกิต — น่าจะอ่านตกวิชา")
        elif tot > 25:
            issues.append(f"ภาค {term} มีถึง {tot} หน่วยกิต — น่าจะมีวิชาซ้ำ")

    return {
        "ok": len(issues) == 0,
        "n_courses": len(courses),
        "n_duplicate_keys": sum(1 for v in dup.values() if v > 1),
        "credits_by_term": dict(sorted(credits_by_term.items())),
        "total_credits_fixed_terms": sum(credits_by_term.values()),
        "issues": issues,
    }


# ==============================================================================
#  ส่วนที่ 11 — ประเมินผลเทียบ GROUND TRUTH
# ==============================================================================


def clean_gt(gt: dict) -> list[dict]:
    """
    ทำความสะอาด ground truth ก่อนใช้งาน
     ก่อนใช้ ground truth ต้อง "ตรวจ ground truth" เสียก่อน
             และเกณฑ์การกรองต้องแคบที่สุดเท่าที่จะทำได้
    """
    kept, dropped = [], []
    for c in gt.get("courses") or []:
        # เกณฑ์เดียว: ต้องมีชื่อวิชาภาษาไทย  ถ้าไม่มี = ไม่ใช่แถวรายวิชา
        if c.get("name_th"):
            kept.append(c)
        else:
            dropped.append(str(c.get("code"))[:40])
    if dropped:
        print(f"  (กรองแถวที่ไม่ใช่รายวิชาออกจาก ground truth {len(dropped)} แถว)")
    return kept


def _ys(v: Any) -> str:
    """ปี/ภาค: None กับ 0 คือ "ไม่ผูกปี/ภาค" เหมือนกัน (เฉลย GENED ใช้ None, วิชาเลือกของ IT ใช้ 0)"""
    return "" if v in (None, "", 0, "0") else M.normalize(v, "strict")


def key_strict(c: dict) -> str:
    """
    กุญแจเข้ม: รหัส + ปี + ภาค + ชื่อไทย

    ทำไมต้องมีชื่อด้วย? เพราะรหัส placeholder "06026xxx" ปรากฏ 2 แถว
    ในภาคเดียวกัน (วิชาเลือกกลุ่มวิทยาการข้อมูล 1 และ 2)
    ถ้าใช้แค่รหัส+ปี+ภาค ทั้งสองแถวจะชนกัน --> จับคู่ผิดตัว
    """
    return "|".join([
        M.normalize(c.get("code"), "strict"),
        _ys(c.get("year")),
        _ys(c.get("semester")),
        M.normalize(c.get("name_th"), "strict"),
    ])


def key_loose(c: dict) -> str:
    """
    กุญแจหลวม: รหัส + ปี + ภาค (ไม่สนชื่อ)

    ใช้ในรอบที่สอง เพื่อเก็บตกกรณีที่โมเดลอ่านชื่อผิดไปนิดหน่อย
    ถ้าไม่มีรอบนี้ วิชาที่อ่านชื่อผิด 1 ตัวอักษรจะถูกนับเป็น
    "ตกแถว 1 + แต่งเกิน 1" ทั้งที่โมเดลอ่านเจอจริง
    --> ทำให้ recall ดูแย่เกินความเป็นจริง
    """
    return "|".join([
        M.normalize(c.get("code"), "strict"),
        _ys(c.get("year")),
        _ys(c.get("semester")),
    ])


def evaluate(pred: dict, gt: dict) -> tuple[dict, dict]:
    S = M.FieldStat
    stats: dict[str, M.FieldStat] = {
        "code":      S("รหัสวิชา"),
        "name_th":   S("ชื่อวิชา (ไทย) ⭐"),
        "name_en":   S("ชื่อวิชา (อังกฤษ) ⭐"),
        "credits":   S("หน่วยกิต"),
        "year_sem":  S("ปี/ภาค"),
        "category":  S("หมวดวิชา"),
        "ctype":     S("บังคับ/เลือก"),
        "prereq":    S("วิชาบังคับก่อน"),
        "flexible":  S("ปี/ภาคยืดหยุ่น"),
    }

    g_courses = clean_gt(gt)
    p_courses = pred.get("courses") or []

    # จับคู่สองรอบ: เข้มก่อน (รวมชื่อ) แล้วผ่อน (เฉพาะรหัส+ปี+ภาค)
    align = M.align_multipass(g_courses, p_courses, [key_strict, key_loose])

    for g, p in align.matched:
        k = f"{g.get('code')}"

        # --- รหัสวิชา: ไม่วัด WER (เป็นตัวเลข ไม่มีคำ) ---
        stats["code"].add(g.get("code"), p.get("code"), k, track_wer=False)

        # ⭐ ชื่อวิชา: กลุ่ม B วัด WER ได้ เพราะ GT คงช่องว่างไว้
        #    - ภาษาไทย ใช้ pythainlp/newmm ตัดคำ
        #    - ภาษาอังกฤษ ตัดด้วยช่องว่าง
        #    ⚠️ name_en ใน GT มี \n ฝังอยู่ (ชื่อยาวถูกตัดบรรทัดใน PDF)
        #       normalize ระดับ basic ขึ้นไปจะยุบ \n เป็นช่องว่างให้อัตโนมัติ
        stats["name_th"].add(g.get("name_th"), p.get("name_th"), k, track_wer=True)
        stats["name_en"].add(g.get("name_en"), p.get("name_en"), k, track_wer=True)

        stats["credits"].add(g.get("credits"), p.get("credits"), k, track_wer=False)
        stats["year_sem"].add(f"{_ys(g.get('year'))}/{_ys(g.get('semester'))}",
                              f"{_ys(p.get('year'))}/{_ys(p.get('semester'))}",
                              k, track_wer=False)
        stats["category"].add(g.get("category"), p.get("category"), k, track_wer=False)
        stats["ctype"].add(g.get("type"), p.get("type"), k, track_wer=False)
        stats["prereq"].add(g.get("prerequisite"), p.get("prerequisite"),
                            k, track_wer=False)
        stats["flexible"].add(g.get("flexible_year_semester"),
                              p.get("flexible_year_semester"), k, track_wer=False)

    # --- วิชาที่โมเดลอ่านตก: นับเป็น deletion เต็มจำนวน ---
    # ถ้าไม่นับ โมเดลที่อ่านแค่ 10 วิชาจาก 91 วิชาจะได้ CER ต่ำเตี้ย
    # ทั้งที่ใช้งานจริงไม่ได้เลย
    for g in align.missed:
        k = f"{g.get('code')} [ตกแถว]"
        stats["code"].add(g.get("code"), "", k, track_wer=False)
        stats["name_th"].add(g.get("name_th"), "", k, track_wer=True)
        stats["name_en"].add(g.get("name_en"), "", k, track_wer=True)
        stats["credits"].add(g.get("credits"), "", k, track_wer=False)
        stats["year_sem"].add(f"{_ys(g.get('year'))}/{_ys(g.get('semester'))}", "",
                              k, track_wer=False)
        stats["category"].add(g.get("category"), "", k, track_wer=False)
        stats["ctype"].add(g.get("type"), "", k, track_wer=False)

    align_summary = {
        "matched": len(align.matched),
        "missed": len(align.missed),
        "spurious": len(align.spurious),
        "precision": round(align.precision, 4),
        "recall": round(align.recall, 4),
        "f1": round(align.f1, 4),
        "gt_total": len(g_courses),
        "pred_total": len(p_courses),
        "missed_codes": [g.get("code") for g in align.missed][:20],
        "spurious_codes": [p.get("code") for p in align.spurious][:20],
    }
    return stats, align_summary


# ==============================================================================
#  ส่วนที่ 12 — MAIN
# ==============================================================================


# ชื่อไฟล์ผลลัพธ์ pred_<X>.json ต่อ pipeline — markdown (ข้าม OCR ทำต่อจาก
# intermediate_vlm.md) เขียนเป็น pred_vlm.json โดยตั้งใจ เพื่อให้ Lab 8B / run_lab8b.py
# หาไฟล์เจอชื่อเดียวกันไม่ว่ารอบนั้นจะ OCR ใหม่หรือข้าม OCR
# (ชื่อ pipeline จริงยังบันทึกไว้ที่ _meta.pipeline ในไฟล์)
PRED_FILE_ALIAS = {"markdown": "vlm"}


def run_pipeline(name: str, pages: list[bytes], outdir: Path,
                 pdf_path: str | None, page_spec: str | None,
                 page_nums: list[int] | None = None) -> dict | None:
    print(f"\n{'─' * 70}")
    print(f"  PIPELINE: {name}")
    print(f"{'─' * 70}")
    t0 = time.time()
    try:
        if name == "baseline":
            data = pipeline_baseline(pages, page_nums)
        elif name == "text":
            if not pdf_path:
                print("  ⚠ pipeline 'text' ใช้ได้กับไฟล์ PDF เท่านั้น")
                return None
            data = pipeline_text(pdf_path, page_spec)
        elif name == "vlm":
            data = pipeline_vlm(pages, outdir, page_nums)
        elif name == "markdown":
            if not pdf_path:
                return None
            data = pipeline_markdown(pdf_path)
        else:
            raise ValueError(name)
    except Exception as e:
        print(f"  ❌ {name} ล้มเหลว: {e}")
        return None

    if not data or not data.get("courses"):
        print(f"  ⚠ {name} ไม่ได้ผลลัพธ์")
        return None

    # ตาข่ายชั้นสองสุดท้าย ครอบทุก pipeline รวม baseline (ฟังก์ชันนี้ทำงานแบบ
    # regex ล้วน ๆ เรียกซ้ำได้โดยไม่มีผลข้างเคียง แม้ pipeline vlm/markdown/text
    # จะเรียก clean_courses_output() ไปแล้วรอบหนึ่งใน _text_to_json_chunked())
    data = clean_courses_output(data)

    extract_mode = data.pop("_extract_mode", "llm")
    rules_report = data.pop("_rules_report", None)
    data["_meta"] = {
        "pipeline": name,
        "extract_mode": extract_mode,     # rules = สกัดด้วยกฎ (เลขหน้าแม่นทุกแถว), llm = ผ่าน qwen
        "elapsed_sec": round(time.time() - t0, 1),
        "models": {"ocr": MODEL_OCR, "text": MODEL_TEXT},
        "dpi": DPI,
        # โหมด rules แนบเลขหน้าเป็นรายหน้าเสมอ (เทียบเท่า chunk=1) ไม่ขึ้นกับ LAB7_CHUNK
        "pages_per_chunk": 1 if extract_mode == "rules" else PAGES_PER_CHUNK,
        "pages_spec": page_spec,
        "ocr_failed_pages": data.pop("_ocr_failed_pages", []),
    }
    if rules_report:
        data["_meta"]["rules"] = rules_report
    path = outdir / f"pred_{PRED_FILE_ALIAS.get(name, name)}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ บันทึก {path}  ({len(data['courses'])} วิชา, "
          f"{data['_meta']['elapsed_sec']} วิ)")
    return data


def process_one(input_path: str, pages_spec: str | None, outdir: Path,
                pipeline: str, gt_path: Path | None) -> dict[str, dict]:
    """
    รันสาย OCR/สกัด + ตรวจสอบภายใน + (ถ้ามี gt_path) เทียบเฉลย ให้ input ไฟล์เดียว

    ทุกอย่างที่ไฟล์นี้เขียนออก (intermediate_vlm.md, pred_*.json, comparison.csv,
    evaluation.json) ลงใต้ outdir ที่ส่งเข้ามาเท่านั้น — ไม่แตะ outdir อื่น
    จึงเรียกซ้ำได้หลายรอบพร้อมกันโดยไม่ชนกัน (ที่มาของโหมด batch ใน main())

    คืนค่า results (pipeline name -> data) เผื่อผู้เรียกอยากเอาไปสรุปต่อ
    """
    outdir.mkdir(parents=True, exist_ok=True)
    set_current_program(outdir.name if pipeline == "markdown" or Path(input_path).suffix.lower() == ".md"
                        else Path(input_path).stem)
    print(f"\nเตรียมข้อมูลจาก: {input_path}")
    if pipeline == "markdown":
        pages, page_nums = [], None
    else:
        pages, page_nums = load_pages_with_numbers(input_path, pages_spec)

    if pipeline == "all":
        names = ["text", "vlm"] if SKIP_BASELINE else ["baseline", "text", "vlm"]
        if SKIP_BASELINE:
            print("\n(ข้าม pipeline baseline ตามค่า LAB7_SKIP_BASELINE=1)")
    else:
        names = [pipeline]

    results: dict[str, dict] = {}
    for n in names:
        r = run_pipeline(n, pages, outdir, input_path, pages_spec, page_nums)
        if r:
            results[n] = r

    # ---------- ตรวจความสอดคล้องภายใน ----------
    print("\n" + "=" * 70)
    print("  ตรวจความสอดคล้องภายใน (ไม่ใช้เฉลย)")
    print("=" * 70)
    for n, data in results.items():
        v = verify_internal(data)
        print(f"\n  {'✓' if v['ok'] else '✗'} {n}: {v['n_courses']} วิชา, "
              f"รวม {v['total_credits_fixed_terms']} หน่วยกิต (เฉพาะภาคที่ระบุชัด)")
        for msg in v["issues"][:6]:
            print(f"      • {msg}")
        if len(v["issues"]) > 6:
            print(f"      ... และอีก {len(v['issues']) - 6} รายการ")

    # ---------- เทียบ ground truth ----------
    if not gt_path:
        print("\n(ไม่ได้ระบุไฟล์ ground truth จึงข้ามการเทียบกับเฉลย)")
        return results

    gt = json.loads(Path(gt_path).read_text(encoding="utf-8"))
    csv_path = outdir / "comparison.csv"
    combined: dict[str, Any] = {}
    first = True

    for n, data in results.items():
        stats, align = evaluate(data, gt)
        M.print_table(stats, f"PIPELINE = {n}")
        print(f"  จับคู่วิชา: เจอ {align['matched']}/{align['gt_total']} "
              f"| ตก {align['missed']} | แต่งเกิน {align['spurious']}   "
              f"P={align['precision']:.3f} R={align['recall']:.3f} "
              f"F1={align['f1']:.3f}")
        M.print_errors(stats, limit=2)

        d = M.stats_to_dict(stats)
        d["alignment"] = align
        d["internal_check"] = verify_internal(data)
        combined[n] = d

        tmp = outdir / f"_tmp_{n}.csv"
        M.save_csv(stats, str(tmp), extra={"pipeline": n})
        lines = tmp.read_text(encoding="utf-8-sig").splitlines()
        with open(csv_path, "w" if first else "a", encoding="utf-8-sig") as f:
            f.write("\n".join(lines if first else lines[1:]) + "\n")
        tmp.unlink()
        first = False

    (outdir / "evaluation.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n✓ เสร็จสิ้น")
    print(f"  ตารางเปรียบเทียบ (เปิดใน Excel): {csv_path}")
    print(f"  ผลละเอียด: {outdir / 'evaluation.json'}")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Lab 7B — สกัดแผนการศึกษาจากเล่มหลักสูตร ด้วย LLM บนเครื่อง")
    ap.add_argument("-i", "--input", help="ไฟล์เล่มหลักสูตร (.pdf/.png), โฟลเดอร์ภาพ หรือ Markdown "
                    "(ใช้ตอนรันไฟล์เดียวแบบเดิม — ห้ามใช้ร่วมกับ --run/--program/--all-runs)")
    ap.add_argument("-g", "--gt", help="ไฟล์ ground truth (.json) — ใช้กับ -i เท่านั้น")
    ap.add_argument("-o", "--out", default=None,
                    help="โหมดไฟล์เดียว: โฟลเดอร์ output ตรง ๆ (default: output). "
                         "โหมด batch: โฟลเดอร์แม่ที่จะมีโฟลเดอร์ย่อยต่อรอบรัน "
                         "(default: work/lab7b_run)")
    ap.add_argument("-p", "--pipeline", default="all",
                    choices=["all", "baseline", "text", "vlm", "markdown"])
    ap.add_argument("--pages", help='เลือกเฉพาะบางหน้า เช่น "42-58" หรือ "3,7,10-12" '
                    "(ใช้กับ -i เท่านั้น — โหมด batch กำหนดช่วงหน้าให้อัตโนมัติจาก RUN_REGISTRY)")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--eval-only", metavar="PRED_JSON")

    batch = ap.add_argument_group(
        "batch mode", "รันหลายโปรแกรมพร้อมกัน แต่ละรอบได้โฟลเดอร์ output แยกของตัวเอง")
    batch.add_argument("--run", nargs="+", choices=sorted(RUNS_BY_ID),
                       metavar="RUN_ID", help="ระบุรอบรันเจาะจง เช่น --run IT_nocoop IT_coop")
    batch.add_argument("--program", nargs="+", choices=PROGRAMS,
                       metavar="PROGRAM", help="รันทุกรอบของโปรแกรมนี้ เช่น --program IT "
                       "(โปรแกรมละ 1 รอบ; nocoop/coop แยกทีหลังที่ Lab 8B)")
    batch.add_argument("--all-runs", action="store_true",
                       help="รันทุกรอบของทุกโปรแกรมใน RUN_REGISTRY")
    batch.add_argument("--input-dir", default="data/input",
                       help="โฟลเดอร์ที่เก็บ <PROGRAM>.pdf เช่น data/input/IT.pdf (default: data/input)")
    batch.add_argument("--gt-dir",
                       help="โฟลเดอร์ ground truth — มองหา <PROGRAM>_academic_plan*.json (หรือ <RUN_ID>.json) "
                       "ถ้าโปรแกรมมีหลายไฟล์ (coop/no_coop) จะรวมเป็นชุดเดียว "
                       "(ไม่บังคับ ถ้าไม่พบจะข้ามการเทียบเฉลยของรอบนั้น)")
    args = ap.parse_args()

    if args.check:
        sys.exit(0 if check_environment() else 1)

    if args.eval_only:
        if not args.gt:
            raise SystemExit("❌ --eval-only ต้องระบุ --gt ด้วย")
        pred = json.loads(Path(args.eval_only).read_text(encoding="utf-8"))
        gt = json.loads(Path(args.gt).read_text(encoding="utf-8"))
        stats, align = evaluate(pred, gt)
        M.print_table(stats, f"ผลประเมิน: {Path(args.eval_only).name}")
        print(f"\n  จับคู่วิชา: เจอ {align['matched']}/{align['gt_total']} "
              f"| ตก {align['missed']} | แต่งเกิน {align['spurious']}")
        print(f"  P={align['precision']:.3f}  R={align['recall']:.3f}  "
              f"F1={align['f1']:.3f}")
        if align["missed_codes"]:
            print(f"  วิชาที่อ่านตก: {', '.join(map(str, align['missed_codes'][:10]))}")
        M.print_errors(stats)
        return

    # ── ตัดสินว่าเป็นโหมด batch (--run/--program/--all-runs) หรือโหมดไฟล์เดียวแบบเดิม (-i) ──
    if args.all_runs:
        selected = list(RUN_REGISTRY)
    elif args.run:
        selected = [RUNS_BY_ID[r] for r in args.run]
    elif args.program:
        selected = [r for r in RUN_REGISTRY if r.program in args.program]
    else:
        selected = None   # โหมดไฟล์เดียวแบบเดิม

    if selected is not None:
        if args.input:
            print("  ! ระบุทั้ง -i และ --run/--program/--all-runs — "
                  "โหมด batch จะไม่ใช้ -i (หาไฟล์จาก --input-dir แทน)")
        if args.pages:
            print("  ! --pages ไม่มีผลในโหมด batch (ใช้ช่วงหน้าจาก RUN_REGISTRY ของแต่ละรอบแทน)")
        run_batch(selected, Path(args.input_dir), Path(args.out or "work/lab7b_run"),
                 args.pipeline, Path(args.gt_dir) if args.gt_dir else None)
        return

    if not args.input:
        raise SystemExit("❌ ต้องระบุ --input (โหมดไฟล์เดียว) "
                         "หรือ --run/--program/--all-runs (โหมด batch)")

    print("\n" + "=" * 70)
    print("  Lab 7B — สกัดแผนการศึกษา ด้วย LLM ที่รันบนเครื่องตัวเอง")
    print("=" * 70)
    assert_offline()
    process_one(args.input, args.pages, Path(args.out or "output"), args.pipeline,
               Path(args.gt) if args.gt else None)


# ชื่อไฟล์เฉลยที่ไม่ขึ้นต้นด้วยชื่อโปรแกรม (ตัวพิมพ์เล็ก ไม่รวมนามสกุล)
_GT_ALIASES: dict[str, tuple[str, ...]] = {
    "gened": ("general_education_ground_truth", "general_education", "gened_ground_truth"),
}


def find_gt_files(gt_dir: Path, run: RunSpec) -> list[Path]:
    """
    หาไฟล์ ground truth ของรอบนี้ในโฟลเดอร์ (ไม่สนตัวพิมพ์เล็ก-ใหญ่)

    รับทั้งชื่อเดิม <RUN_ID>.json และชื่อตามที่มีจริง <PROGRAM>_academic_plan*.json
    เช่น IT -> IT_academic_plan_coop.json + IT_academic_plan_no_coop.json
         AIT -> AIT_academic_plan.json
    (ใช้ startswith จากหน้าชื่อไฟล์ 'IT_' จึงไม่ไปหยิบ AIT_/BIT_ มาด้วย)
    """
    prog, rid = run.program.lower(), run.run_id.lower()
    out = []
    for f in sorted(gt_dir.glob("*.json")):
        stem = f.stem.lower()
        if (stem in (rid, prog) or stem.startswith(prog + "_academic_plan")
                or stem in _GT_ALIASES.get(prog, ())):
            out.append(f)
    return out


def build_gt_for_run(gt_dir: Path, run: RunSpec, outdir: Path) -> Path | None:
    """
    เตรียมไฟล์เฉลยสำหรับ evaluate() ของรอบนี้

    รอบเดียวตอนนี้ครอบทั้งแผนไม่สหกิจ+สหกิจ จึงรวมเฉลยทุกไฟล์ของโปรแกรมเป็นชุดเดียว
    (กันซ้ำด้วย key_strict เหมือนที่ evaluate จับคู่ — วิชาเหมือนกันสองแผนนับครั้งเดียว)
    การเทียบทีละแผนอยู่ที่ Lab 8B: eval-gt ต่อโปรแกรมที่แยกแล้ว
    """
    files = find_gt_files(gt_dir, run)
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    merged: list[dict] = []
    seen: set[str] = set()
    for f in files:
        g = json.loads(f.read_text(encoding="utf-8"))
        rows = g.get("courses") if isinstance(g, dict) else g
        for c in rows or []:
            k = key_strict(c)
            if k in seen:
                continue
            seen.add(k)
            merged.append(c)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "_gt_merged.json"
    path.write_text(json.dumps({"courses": merged, "_sources": [f.name for f in files]},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  รวมเฉลย {len(files)} ไฟล์ ({', '.join(f.name for f in files)}) "
          f"-> {len(merged)} วิชา")
    return path


def run_batch(runs: list[RunSpec], input_dir: Path, out_root: Path,
             pipeline: str, gt_dir: Path | None) -> None:
    """
    รัน process_one() ให้ทุกรอบใน runs ทีละรอบ คนละโฟลเดอร์ย่อยใต้ out_root

    รอบหนึ่งพังไม่ทำให้รอบอื่นหยุด — พิมพ์ตารางสรุปผลรวมท้ายสุดว่ารอบไหนผ่าน/ไม่ผ่าน
    เพื่อให้รันค้างคืนได้โดยไม่ต้องนั่งเฝ้าทุกรอบ
    """
    print("\n" + "=" * 70)
    print(f"  Lab 7B — โหมด batch: {len(runs)} รอบ "
          f"({', '.join(r.run_id for r in runs)})")
    print("=" * 70)
    assert_offline()

    summary: list[tuple[str, bool, str]] = []   # (run_id, ok, ข้อความ)
    for i, run in enumerate(runs, 1):
        run_id = run.run_id
        print("\n" + "█" * 70)
        print(f"  รอบที่ {i}/{len(runs)}: {run_id}  "
              f"(หน้า {run.pages_spec})")
        print("█" * 70)
        try:
            pdf_path = resolve_input_pdf(run.program, input_dir)
        except SystemExit as e:
            print(f"  ❌ ข้ามรอบ {run_id}: {e}")
            summary.append((run_id, False, str(e)))
            continue

        gt_path = None
        if gt_dir:
            gt_path = build_gt_for_run(gt_dir, run, out_root / run_id)
            if gt_path is None:
                print(f"  (ไม่พบเฉลยของ {run.program} ใน {gt_dir} — ข้ามการเทียบเฉลยของรอบนี้)")

        outdir = out_root / run_id
        try:
            results = process_one(str(pdf_path), run.pages_spec, outdir, pipeline, gt_path)
            n_courses = {n: len(d.get("courses") or []) for n, d in results.items()}
            ok = bool(results)
            summary.append((run_id, ok,
                           ", ".join(f"{n}={c}วิชา" for n, c in n_courses.items())
                           if ok else "ไม่มี pipeline ไหนได้ผลลัพธ์"))
        except (Exception, SystemExit) as e:
            # SystemExit ไม่ใช่ Exception (มันสืบทอดจาก BaseException) แต่โค้ดข้างในไฟล์นี้
            # (เช่น _need(), load_pages()) ใช้ raise SystemExit(...) กันเป็นปกติเวลาพังแบบคาดได้
            # ถ้าจับแค่ Exception รอบเดียวที่พังแบบนี้จะทำให้ batch ทั้งชุดตายไปด้วย
            print(f"  ❌ รอบ {run_id} ล้มเหลว: {e}")
            summary.append((run_id, False, str(e)))

    print("\n" + "=" * 70)
    print("  สรุปผล batch")
    print("=" * 70)
    for run_id, ok, msg in summary:
        print(f"  {'✓' if ok else '❌'} {run_id:<14} {msg}")
    n_ok = sum(1 for _, ok, _ in summary if ok)
    print(f"\n  ผ่าน {n_ok}/{len(summary)} รอบ · output อยู่ใต้ {out_root}/<run_id>/")


if __name__ == "__main__":
    main()