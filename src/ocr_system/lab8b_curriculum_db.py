#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lab8b_curriculum_db.py — Lab 8B : จากข้อความที่สกัดได้ สู่ฐานข้อมูลที่ตอบคำถามได้
วิชา 06026240 การพัฒนาระบบอัจฉริยะ 

ต่อยอดจาก Lab 7B ซึ่งสกัดเล่มหลักสูตรออกมาเป็น Markdown ได้แล้ว
Lab 8B พาข้อมูลนั้นเดินต่ออีกสามก้าว

    Markdown  ->  JSON ที่ผ่านการตรวจ  ->  ฐานข้อมูล  ->  คำตอบ

ทำไมต้องผ่านฐานข้อมูล ไม่ถาม LLM ตรง ๆ กับข้อความเลย
    เพราะคำถามจริงของนักศึกษาคือคำถามเชิงคำนวณและเชิงความสัมพันธ์
    "ปี 3 เทอม 1 มีกี่หน่วยกิต"  "วิชาไหนต้องเรียน 06026240 มาก่อน"
    ซึ่ง LLM ที่อ่านข้อความยาว ๆ จะนับผิดเสมอ แต่ SQL นับถูกทุกครั้ง
    LLM เก่งเรื่อง "แปลภาษาคนเป็น SQL"  ไม่ใช่ "เป็นเครื่องคิดเลข"

คำสั่งหลัก
  python3 lab8b_curriculum_db.py check
  python3 lab8b_curriculum_db.py selftest
  python3 lab8b_curriculum_db.py demo    -o work/
  python3 lab8b_curriculum_db.py schema  -o work/schema/
  python3 lab8b_curriculum_db.py extract -i work/curriculum.md -o work/curriculum.json
  python3 lab8b_curriculum_db.py import-lab7b -i output/pred_vlm.json -o work/curriculum.json
  python3 lab8b_curriculum_db.py load    -i work/curriculum.json -d work/curriculum.db
  python3 lab8b_curriculum_db.py verify  -d work/curriculum.db
  python3 lab8b_curriculum_db.py ask     -d work/curriculum.db -q "ปี 2 เทอม 1 เรียนกี่หน่วยกิต"
  python3 lab8b_curriculum_db.py eval    -d work/curriculum.db -q work/gold_questions.json
  python3 lab8b_curriculum_db.py eval-gt -p work/curriculum.json -g data/ground_truth/

ลำดับที่แนะนำให้ทำ
    1) eval-gt ก่อนแก้อะไรทั้งสิ้น เพื่อให้มีตัวเลขตั้งต้นไว้เทียบ
    2) แก้การสกัด แล้วรัน eval-gt ซ้ำ ดูว่าฟิลด์ไหนดีขึ้น/แย่ลง
    3) load + verify ให้กฎ 7 ข้อผ่าน
    4) eval เพื่อดูคุณภาพการตอบคำถามและอัตราการอ้างอิงหน้า
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
#  ค่าคงที่
# ═══════════════════════════════════════════════════════════════════════

OLLAMA_URL = os.environ.get("LAB8_OLLAMA_URL", "http://127.0.0.1:11434")
MODEL_TEXT = os.environ.get("LAB8_MODEL_TEXT", "qwen3:4b")

# ตารางนี้เป็น "fallback เดิม" เท่านั้น — ค่าเริ่มต้นตอนนี้คือ detect_sections() ซึ่งจับ
# ช่วงหน้าจากป้ายหัวข้อภาษาไทย ("รายวิชา" / "แผนการศึกษา" / "คำอธิบายรายวิชา") ในเนื้อหาเอง
# แทนที่จะพึ่งเลขหน้าที่จดไว้ล่วงหน้า (ดูคอมเมนต์ยาวเหนือ detect_sections() ด้านบนของไฟล์)
# ตารางนี้ยังใช้เป็นทางสำรองในจุดที่ยังไม่มี Markdown ต้นทางให้สแกน เช่น import-lab7b
# --split-dir ตอนที่ไม่ได้ระบุ --source-md (มีแต่ pred JSON จาก Lab 7B ไม่มี markdown ดิบ)
# key ระดับในสุดคือชื่อ section: nocoop / coop / plan / courses
PROGRAM_PAGE_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "IT":    {"nocoop": (31, 37), "coop": (38, 44), "courses": (324, 360), "course_list": (21, 30)},
    "DSBA":  {"nocoop": (23, 29), "coop": (30, 36), "courses": (314, 341), "course_list": (16, 22)},
    "BIT":   {"nocoop": (26, 30), "coop": (31, 35), "courses": (238, 257), "course_list": (20, 25)},
    "AIT":   {"plan": (23, 26), "courses": (287, 304), "course_list": (18, 22)},
    "GENED": {"courses": (39, 117), "course_list": (12, 30)},   # ไม่มีแผนของตัวเอง — courses + course_list
    # --- books 2560 (added; originals above untouched) ---
    # nocoop/coop split inside the first range is not known -> not hard-coded. With --source-md
    # (run_lab8b passes it) the split is detected from the headings; this table is only the fallback.
    "IT_2560":   {"courses": (223, 269), "course_list": (19, 40)},
    "DSBA_2560": {"courses": (176, 207), "course_list": (19, 34)},
    "BIT_2560":  {"courses": (171, 192),  "course_list": (18, 30)},
    "GENED_2559": {"courses": (42, 85),  "course_list": (14, 23)},
    "GENED_2564": {"courses": (44, 117), "course_list": (16, 30)},
}

# ชื่อ section -> ส่วนท้ายชื่อไฟล์เฉลย เช่น IT_academic_plan_no_coop.json
# (ชื่อ section ในโค้ดคือ "nocoop" แต่ไฟล์เฉลยของผู้ใช้ใช้ "no_coop")
SECTION_GT_SUFFIX = {"nocoop": "no_coop", "coop": "coop"}

MAX_REPAIR_ROUNDS = 3      # จำนวนครั้งสูงสุดที่ยอมให้ LLM แก้ JSON ของตัวเอง
SQL_ROW_LIMIT = 200        # กันไม่ให้ query เผลอดึงทั้งตารางมาใส่ prompt

# ระเบียบหน่วยกิตต่อภาคเรียนของหลักสูตรปริญญาตรี (ใช้ในการตรวจ CHK7)
MIN_CREDITS_PER_SEM = 9
MAX_CREDITS_PER_SEM = 22


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 0 — ตรวจสภาพแวดล้อม
# ═══════════════════════════════════════════════════════════════════════

def check_environment() -> bool:
    print("=" * 68)
    print("  ตรวจสภาพแวดล้อม Lab 8B")
    print("=" * 68)
    ok = True

    required = [
        ("pydantic", "pydantic", "ตรวจความถูกต้องของ JSON และสร้างข้อความ error ให้ LLM แก้"),
        ("requests", "requests", "เรียก Ollama"),
    ]
    for mod, pipname, why in required:
        try:
            __import__(mod)
            print(f"  [ ok ] {pipname:<12} — {why}")
        except ImportError:
            print(f"  [FAIL] {pipname:<12} — {why}")
            print(f"         แก้ด้วย:  pip install {pipname}")
            ok = False

    # sqlite3 มากับ Python อยู่แล้ว แต่ต้องตรวจว่ารุ่นรองรับ foreign key
    v = sqlite3.sqlite_version_info
    if v >= (3, 6, 19):
        print(f"  [ ok ] sqlite3      — เวอร์ชัน {sqlite3.sqlite_version} รองรับ foreign key")
    else:
        print(f"  [FAIL] sqlite3      — เวอร์ชัน {sqlite3.sqlite_version} เก่าเกินไป")
        ok = False

    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        names = [m["name"] for m in r.json().get("models", [])]
        print(f"  [ ok ] Ollama ทำงานอยู่ที่ {OLLAMA_URL}")
        if any(n == MODEL_TEXT or n.startswith(MODEL_TEXT.split(":")[0]) for n in names):
            print(f"  [ ok ] พบโมเดล {MODEL_TEXT}")
        else:
            print(f"  [FAIL] ไม่พบโมเดล {MODEL_TEXT}")
            print(f"         แก้ด้วย:  ollama pull {MODEL_TEXT}")
            ok = False
    except Exception as e:
        print(f"  [FAIL] ต่อ Ollama ไม่ได้ ({type(e).__name__}) — เปิดด้วย  ollama serve")
        ok = False

    print("=" * 68)
    print("  พร้อมทำแล็บ" if ok else "  ยังไม่พร้อม — แก้ตามข้อความ [FAIL] ข้างบนก่อน")
    print("=" * 68)
    return ok


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 1 — ออกแบบ Schema ก่อน แล้วค่อยสกัด
# ═══════════════════════════════════════════════════════════════════════
#
#  ลำดับที่ถูกต้องคือ  ออกแบบ schema -> สกัด -> ตรวจ
#  ไม่ใช่  สกัด -> ดูว่าได้อะไรมา -> ค่อยคิด schema
#
#  ถ้าปล่อยให้ LLM คิดโครงสร้างเอง จะเกิดสองปัญหาที่แก้ทีหลังไม่ได้
#    1) แต่ละหน้าได้ชื่อฟิลด์ไม่ตรงกัน (หน้าหนึ่ง "หน่วยกิต" อีกหน้า "credit")
#       ทำให้รวมข้อมูลไม่ได้
#    2) ไม่มีเกณฑ์ตัดสินว่า "ผิด" คืออะไร จึงตรวจอัตโนมัติไม่ได้เลย
#
#  Schema คือสัญญาที่เขียนไว้ก่อน ทั้งฝั่งสกัดและฝั่งตรวจจึงพูดภาษาเดียวกัน
# ═══════════════════════════════════════════════════════════════════════

#  รหัสวิชาที่ระบบนี้ยอมรับมีสองแบบ
#    1) ตัวเลข 8 หลัก            — วิชาจริงที่มีคำอธิบายรายวิชาในเล่ม
#    2) PLACEHOLDER_90644XXX    — "ช่องวิชา" ที่เล่มเขียนเป็น 90644xxx
#
#  ทำไมต้องมีแบบที่สอง
#      เล่มจริงเขียนช่องวิชาภาษา/วิชาเลือกเป็น 90644xxx พร้อมหน่วยกิต 3
#      ถ้าโยนทั้งแถวทิ้งเพราะหาเลข 8 หลักไม่เจอ หน่วยกิตของภาคนั้นจะหายไป 3
#      แล้ว CHK7 จะเตือนว่า "หน่วยกิตต่ำกว่าเกณฑ์" ทั้งที่เล่มไม่ได้ต่ำ
#      คือสร้างคำเตือนผิดจากข้อมูลที่เราทำหายเอง ซึ่งแย่กว่าไม่ตรวจเลย
#  เราจึงเก็บช่องวิชาไว้ให้ "นับหน่วยกิตได้" แม้จะ "ถามรายละเอียดวิชาไม่ได้"
PLACEHOLDER_PREFIX = "PLACEHOLDER_"
_CODE_RE = re.compile(r"^\d{8}$")
_PLACEHOLDER_RE = re.compile(r"^PLACEHOLDER_[0-9A-Za-z_]+$")
# รูปแบบรหัส wildcard ที่พบในเล่ม เช่น 90644xxx, 0602 6xxx
# รวมรหัสที่เป็น x ล้วน (xxxxxxxx = วิชาเลือกเสรี) ด้วย — เดิมต้องมีเลขนำหน้า 2 หลักขึ้นไป
# ทำให้ช่องวิชาเลือกเสรีถูกข้ามและหน่วยกิตหายจากแผน
_WILDCARD_RE = re.compile(r"^(?=.{4,12}$)\d{0,7}[xX]{1,8}$")


def normalize_code(value: Any, what: str = "รหัสวิชา") -> str:
    """ตรวจรูปแบบรหัสวิชา คืนรหัสที่ตัดช่องว่างแล้ว หรือโยน ValueError"""
    v = str(value or "").strip()
    if _CODE_RE.match(v) or _PLACEHOLDER_RE.match(v):
        return v
    raise ValueError(f"{what}ต้องเป็นตัวเลข 8 หลัก "
                     f"หรือช่องวิชา {PLACEHOLDER_PREFIX}... แต่ได้ '{v}'")


def is_placeholder(code: str) -> bool:
    return str(code or "").startswith(PLACEHOLDER_PREFIX)


def build_models():
    """
    สร้าง Pydantic models

    ห่อไว้ในฟังก์ชันเพื่อให้ไฟล์นี้ยัง import ได้แม้ยังไม่ได้ติดตั้ง pydantic
    (คำสั่ง check จะได้บอกวิธีติดตั้งแทนที่จะพังตั้งแต่บรรทัด import)
    """
    from pydantic import BaseModel, Field, field_validator

    # รหัสวิชา 8 หลัก — รูปแบบมาตรฐานของ สจล.
    CODE_RE = re.compile(r"^\d{8}$")

    class Course(BaseModel):
        """รายวิชาหนึ่งวิชา ตามที่ปรากฏในหมวดคำอธิบายรายวิชา"""
        code: str
        name_th: str
        name_en: str | None = None
        # None = เล่มไม่พิมพ์หน่วยกิตของวิชานี้ (เช่น วิชาเลือกที่มีแต่ในหน้าคำอธิบายแล้ว OCR ทำบรรทัดหายไป)
        # เก็บวิชาไว้ดีกว่าทิ้งทั้งวิชา — แถวในแผน (PlanItem) ยังบังคับต้องมีหน่วยกิตเหมือนเดิม
        credits: int | None = Field(default=None, ge=0, le=12)
        # สหกิจศึกษาในเล่มจริงใช้ 6(0-35-0) จึงห้ามจำกัดชั่วโมงไว้แค่ 30
        lecture_h: int | None = Field(default=None, ge=0, le=60)
        lab_h: int | None = Field(default=None, ge=0, le=60)
        self_h: int | None = Field(default=None, ge=0, le=60)
        # ข้อความหน่วยกิตเต็มเมื่อเล่มให้หลายแบบ เช่น "3(3-0-6) หรือ 3(2-2-5)" (ตัวเลขด้านบนเก็บแบบแรก)
        credits_text: str | None = None
        description_th: str | None = None
        # เลขหน้าทั้งหมดในเล่มหลักสูตรที่พบข้อมูลนี้ (เช่น หน้าตารางแผน + หน้าคำอธิบายรายวิชา)
        # — ใช้อ้างอิงตอนตอบคำถาม (แทน source_page เดิมที่เก็บได้หน้าเดียว)
        pages: list[int] | None = None

        @field_validator("code")
        @classmethod
        def _code_format(cls, v: str) -> str:
            return normalize_code(v, "รหัสวิชา")

    class PlanItem(BaseModel):
        """
        หนึ่งบรรทัดในแผนการศึกษา

        alt_group คือกลไกจัดการ "วิชาเลือกอย่างใดอย่างหนึ่ง"
        เล่มหลักสูตรเขียนว่า  06026259 หรือ 06026260
        เราแตกเป็นสองแถวที่มี alt_group เดียวกัน
        เวลานับหน่วยกิตจึงนับ alt_group ละครั้งเดียว ไม่นับซ้ำ

        นี่คือบทเรียนตรงจาก Lab 7B: กฎตรวจที่ไม่รู้จักกรณีนี้
        จะเตือนผิดทุกครั้งที่เจอวิชาเลือก จนนักศึกษาเลิกอ่านคำเตือน

        category / type แยกเป็นคอลัมน์จริง ไม่ยัดรวมใน note
            category = "หมวดวิชาเฉพาะ" / "หมวดวิชาศึกษาทั่วไป" / "หมวดวิชาเลือกเสรี"
            type     = "บังคับ" / "เลือก"
        เหตุผล: คำถามจริงคือ "วิชาบังคับมีกี่วิชา" "หน่วยกิตวิชาเลือกรวมเท่าไร"
        ถ้าเก็บรวมเป็นข้อความเดียว ต้องพึ่ง LIKE '%บังคับ%' ซึ่งพังทันที
        ที่เล่มเขียนว่า "ไม่บังคับ" หรือ "วิชาบังคับก่อน"
        """
        year: int = Field(ge=1, le=8)
        semester: int = Field(ge=1, le=3)   # 3 = ภาคฤดูร้อน
        code: str
        credits: int = Field(ge=0, le=12)
        alt_group: str | None = None
        note: str | None = None
        pages: list[int] | None = None
        category: str | None = None
        type: str | None = None

        @field_validator("code")
        @classmethod
        def _code_format(cls, v: str) -> str:
            return normalize_code(v, "รหัสวิชาในแผน")

    class ElectiveSlot(BaseModel):
        """
        วิชาที่เล่มไม่ผูกไว้กับปี/เทอมเดียว แต่บอกว่า "เรียนได้ปีไหนบ้าง"

        เล่มจริงเขียน year: 0, semester: 0 พร้อม flexible_year_semester
        เช่น "3/1, 3/2, 4/1"
        ถ้าโยนทิ้งเพราะปี/เทอมไม่อยู่ในช่วง 1..8 / 1..3 ข้อมูลจะหายเงียบ
        แล้วระบบจะตอบ "ไม่พบข้อมูลนี้ในเล่มหลักสูตร" ทั้งที่เล่มมีคำตอบอยู่
        """
        code: str
        allowed_terms: str | None = None    # เก็บข้อความ "3/1, 3/2, 4/1" ตรง ๆ
        name_th: str | None = None
        name_en: str | None = None
        credits: int | None = Field(default=None, ge=0, le=12)
        credits_text: str | None = None
        category: str | None = None
        type: str | None = None
        note: str | None = None
        pages: list[int] | None = None

        @field_validator("code")
        @classmethod
        def _code_format(cls, v: str) -> str:
            return normalize_code(v, "รหัสวิชาเลือก")

    class Prerequisite(BaseModel):
        """ความสัมพันธ์วิชาบังคับก่อน / วิชาเรียนควบ"""
        code: str
        requires: str
        kind: str = "pre"       # pre = บังคับก่อน, co = เรียนควบ

        @field_validator("code", "requires")
        @classmethod
        def _code_format(cls, v: str) -> str:
            # ความสัมพันธ์ต้องชี้ไปที่วิชาจริงเท่านั้น จึงไม่รับ placeholder
            v = str(v).strip()
            if not CODE_RE.match(v):
                raise ValueError(f"รหัสในเงื่อนไขรายวิชาต้องเป็นตัวเลข 8 หลัก แต่ได้ '{v}'")
            return v

        @field_validator("kind")
        @classmethod
        def _kind_ok(cls, v: str) -> str:
            if v not in ("pre", "co"):
                raise ValueError("kind ต้องเป็น 'pre' หรือ 'co' เท่านั้น")
            return v

    class Program(BaseModel):
        """ข้อมูลหลักสูตรระดับบนสุด"""
        program_id: str
        name_th: str
        name_en: str | None = None
        degree: str | None = None
        # 0 = "แคตตาล็อกวิชาที่ไม่มีแผนรายเทอม" (เช่น GENED) ไม่มีหน่วยกิตรวมตลอดหลักสูตรให้ประกาศ
        # หลักสูตรที่มีแผนจริงยังต้อง 30..300 — บังคับใน convert_lab7b()
        total_credits: int = Field(ge=0, le=300)
        years: int = Field(ge=1, le=8)

    class Curriculum(BaseModel):
        """เอกสารทั้งเล่มหนึ่งฉบับ"""
        program: Program
        courses: list[Course] = []
        plan: list[PlanItem] = []
        prerequisites: list[Prerequisite] = []
        elective_slots: list[ElectiveSlot] = []

    return Curriculum


# ── SQL DDL ────────────────────────────────────────────────────────────
# เขียนแยกจาก Pydantic โดยตั้งใจ เพราะสองอย่างนี้ทำหน้าที่ต่างกัน
#   Pydantic ตรวจ "รูปร่างของข้อมูลแต่ละชิ้น"  (ก่อนเข้าฐานข้อมูล)
#   SQL constraint ตรวจ "ความสัมพันธ์ระหว่างชิ้น" (ตอนเข้าฐานข้อมูล)

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS program (
    program_id    TEXT PRIMARY KEY,
    name_th       TEXT NOT NULL,
    name_en       TEXT,
    degree        TEXT,
    total_credits INTEGER NOT NULL CHECK (total_credits BETWEEN 0 AND 300),
    years         INTEGER NOT NULL CHECK (years BETWEEN 1 AND 8)
);

CREATE TABLE IF NOT EXISTS course (
    code           TEXT PRIMARY KEY,
    name_th        TEXT NOT NULL,
    name_en        TEXT,
    credits        INTEGER CHECK (credits IS NULL OR credits BETWEEN 0 AND 12),
    lecture_h      INTEGER,
    lab_h          INTEGER,
    self_h         INTEGER,
    description_th TEXT,
    pages          TEXT      -- JSON array ของเลขหน้าในเล่ม เช่น [23, 287]; NULL = ไม่รู้
);

CREATE TABLE IF NOT EXISTS plan_item (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id TEXT NOT NULL REFERENCES program(program_id),
    year       INTEGER NOT NULL CHECK (year BETWEEN 1 AND 8),
    semester   INTEGER NOT NULL CHECK (semester BETWEEN 1 AND 3),
    -- FOREIGN KEY จริง ไม่ใช่แค่ JOIN ได้เฉย ๆ
    -- ความสัมพันธ์ "ทุกแถวในแผนต้องมีคำอธิบายรายวิชา" ถูกบังคับที่ฐานข้อมูล
    -- CHK2 ยังมีอยู่ เพราะใช้ตรวจฐานที่โหลดมาแบบผ่อนปรน (--allow-orphan)
    code       TEXT NOT NULL REFERENCES course(code),
    credits    INTEGER NOT NULL CHECK (credits BETWEEN 0 AND 12),
    alt_group  TEXT,
    category   TEXT,          -- หมวดวิชาเฉพาะ / หมวดวิชาศึกษาทั่วไป / เลือกเสรี
    type       TEXT,          -- บังคับ / เลือก
    note       TEXT,
    pages      TEXT          -- JSON array ของเลขหน้าในเล่ม เช่น [23, 287]; NULL = ไม่รู้
);

CREATE TABLE IF NOT EXISTS prerequisite (
    code     TEXT NOT NULL,
    requires TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('pre','co')),
    PRIMARY KEY (code, requires, kind)
);

-- วิชาที่เล่มไม่ผูกกับปี/เทอมเดียว แต่บอกว่าเรียนได้ปี/เทอมไหนบ้าง
-- เล่มเขียน year=0 semester=0 แล้วระบุ flexible_year_semester = "3/1, 3/2, 4/1"
CREATE TABLE IF NOT EXISTS elective_slot (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id    TEXT NOT NULL REFERENCES program(program_id),
    code          TEXT NOT NULL,
    allowed_terms TEXT,       -- เก็บ "3/1, 3/2, 4/1" ตรง ๆ ตามเล่ม
    name_th       TEXT,
    name_en       TEXT,
    credits       INTEGER CHECK (credits IS NULL OR credits BETWEEN 0 AND 12),
    category      TEXT,
    type          TEXT,
    note          TEXT,
    pages         TEXT,       -- JSON array ของเลขหน้าในเล่ม เช่น [23, 287]; NULL = ไม่รู้
    UNIQUE (program_id, code)
);

CREATE INDEX IF NOT EXISTS ix_plan_sem ON plan_item(year, semester);
CREATE INDEX IF NOT EXISTS ix_plan_code ON plan_item(code);
CREATE INDEX IF NOT EXISTS ix_slot_code ON elective_slot(code);

-- VIEW ทำให้การถามคำถามง่ายขึ้นมาก
-- แทนที่ LLM จะต้อง JOIN เองทุกครั้ง เราเตรียมตารางแบนไว้ให้
-- นี่คือเหตุผลที่ VIEW มีอยู่ในโลก: ซ่อนความซับซ้อนของการ normalize
CREATE VIEW IF NOT EXISTS v_plan AS
SELECT p.id, p.year, p.semester, p.code, c.name_th, c.name_en,
       p.credits, p.alt_group, p.category, p.type, p.note,
       COALESCE(p.pages, c.pages) AS pages
FROM plan_item p
LEFT JOIN course c ON c.code = p.code;

-- ตอบคำถาม "วิชานี้เรียนได้ตอนไหน" ได้ทั้งวิชาที่ล็อกเทอมและวิชาเลือกยืดหยุ่น
-- ถ้าไม่มี VIEW นี้ LLM ต้องรู้เองว่าต้องไปดูสองตาราง ซึ่งมันจะลืม
CREATE VIEW IF NOT EXISTS v_course_terms AS
SELECT p.code AS code, c.name_th AS name_th,
       (p.year || '/' || p.semester) AS terms,
       p.credits AS credits, 'plan' AS source,
       COALESCE(p.pages, c.pages) AS pages
FROM plan_item p LEFT JOIN course c ON c.code = p.code
UNION ALL
SELECT e.code, COALESCE(c.name_th, e.name_th),
       e.allowed_terms, COALESCE(e.credits, c.credits), 'elective_slot',
       COALESCE(e.pages, c.pages)
FROM elective_slot e LEFT JOIN course c ON c.code = e.code;

-- VIEW ที่สองนี้สำคัญกว่าที่เห็น
--
-- ถ้าให้ LLM เขียน SUM(credits) FROM v_plan เอง มันจะได้คำตอบผิด
-- เพราะวิชาเลือก "A หรือ B" มีสองแถว แต่ต้องนับหน่วยกิตครั้งเดียว
-- ปี 2 เทอม 1 จะได้ 12 แทนที่จะเป็น 9
--
-- ทางแก้ที่ผิดคือ ไปเขียนใน prompt ว่า "อย่าลืมหักวิชาเลือกออก"
-- เพราะ prompt เป็นการขอร้อง โมเดลจะลืมเป็นบางครั้ง แล้วเราจะจับไม่ได้
--
-- ทางแก้ที่ถูกคือ ย้ายตรรกะนี้มาไว้ใน VIEW
-- แล้ว LLM แค่ SELECT ธรรมดา ไม่มีโอกาสทำผิดเลย
-- หลักการ: อะไรที่ต้อง "ถูกเสมอ" ให้เขียนเป็นโค้ด ไม่ใช่เขียนเป็นคำสั่งให้ AI
CREATE VIEW IF NOT EXISTS v_semester_credits AS
SELECT year, semester, SUM(credits) AS credits, COUNT(*) AS n_courses
FROM (
    SELECT year, semester,
           COALESCE(alt_group, 'x' || id) AS grp,
           MIN(credits) AS credits
    FROM plan_item
    GROUP BY year, semester, COALESCE(alt_group, 'x' || id)
)
GROUP BY year, semester;
"""


def cmd_schema(args) -> None:
    """เขียน JSON Schema และ SQL DDL ออกเป็นไฟล์ เพื่อใช้อ้างอิงและส่งงาน"""
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    Curriculum = build_models()
    (out / "curriculum.schema.json").write_text(
        json.dumps(Curriculum.model_json_schema(), ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "schema.sql").write_text(DDL, encoding="utf-8")
    print(f"  เขียน {out}/curriculum.schema.json")
    print(f"  เขียน {out}/schema.sql")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 2 — สกัด JSON พร้อมวงจรซ่อม (repair loop)
# ═══════════════════════════════════════════════════════════════════════

def ollama_generate(prompt: str, fmt: Any | None = None,
                    timeout: int = 600, model: str | None = None,
                    num_ctx: int = 8192, num_predict: int = 4096) -> str:
    """เรียก Ollama บนเครื่องตัวเอง"""
    import requests
    payload: dict[str, Any] = {
        "model": model or MODEL_TEXT,
        # qwen3:4b บาง build ของ Ollama ยังไม่ปิด reasoning จาก field think
        # จึงใส่ /no_think ใน prompt ซ้ำเพื่อให้งาน SQL สั้นๆ คืนคำตอบใน content
        "messages": [{"role": "user", "content": prompt + "\n/no_think"}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_ctx": num_ctx,
                    "num_predict": num_predict},
    }
    if fmt:
        payload["format"] = fmt
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return (r.json().get("message") or {}).get("content", "")

PAGE_MARKER_RE = re.compile(r"--- Page (\d+) ---")
# ตัวคั่นหน้าดิบที่ intermediate_vlm.md (ผลลัพธ์ VLM/OCR ก่อนเข้า Lab 7B) ใช้จริง — คนละแบบกับ
# --- Page N --- ที่ pipeline.py ฝังใน curriculum.md ที่ Lab 7B ทำความสะอาดแล้ว
_PDF_PAGE_MARKER_RE = re.compile(r"<!--\s*PDF_PAGE\s+(\d+)\s*-->")


def _iter_pages(text: str) -> list[tuple[int, str]]:
    """แยกข้อความเป็น [(เลขหน้า, เนื้อหาของหน้ารวมตัวคั่นเอง), ...]

    รองรับตัวคั่นทั้งสองแบบที่พบในไฟล์จริงของแล็บนี้ — ลอง --- Page N --- (curriculum.md
    จาก Lab 7B) ก่อน ถ้าไม่เจอเลยค่อยลอง <!-- PDF_PAGE N --> (intermediate_vlm.md ดิบ)
    ทำให้ทั้ง slice_pages() และ detect_sections() ใช้ไฟล์จากขั้นไหนของ pipeline ก็ได้
    """
    parts = PAGE_MARKER_RE.split(text)
    if len(parts) > 1:
        return [(int(parts[i]), f"--- Page {parts[i]} ---{parts[i + 1]}")
                for i in range(1, len(parts), 2)]
    markers = list(_PDF_PAGE_MARKER_RE.finditer(text))
    if not markers:
        return []
    pages = []
    for i, m in enumerate(markers):
        start_pos = m.start()
        end_pos = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        pages.append((int(m.group(1)), text[start_pos:end_pos]))
    return pages


def slice_pages(text: str, start: int, end: int) -> str:
    """ตัด Markdown เหลือเฉพาะช่วงหน้า [start, end] จากตัวคั่นหน้า (ดู _iter_pages)"""
    pages = _iter_pages(text)
    if not pages:
        raise ValueError("ไม่พบตัวคั่นหน้าในเอกสาร (รองรับ --- Page N --- หรือ "
                         "<!-- PDF_PAGE N -->) — ตรวจว่าไฟล์มาจาก pipeline.py/Lab 7B จริงหรือไม่")
    out = [chunk for page_no, chunk in pages if start <= page_no <= end]
    if not out:
        raise ValueError(f"ไม่พบตัวคั่นหน้าในช่วง {start}-{end}")
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════
#  จับ section จากป้ายหัวข้อภาษาไทยในเนื้อหาเอง แทนตาราง PROGRAM_PAGE_RANGES
# ═══════════════════════════════════════════════════════════════════════
#
#  ทำไมเปลี่ยนจากตาราง hardcode เลขหน้า มาเป็นจับป้ายหัวข้อ
#    ตารางเดิมต้องนั่งไล่หาเลขหน้าเองทุกครั้งที่มีโปรแกรมใหม่ หรือเล่มหลักสูตรพิมพ์ใหม่
#    แล้วเลขหน้าขยับ (เช่นเพิ่ม/ลดวิชา) ตารางเก่าก็ผิดทันทีโดยไม่มีอะไรเตือน
#    ป้ายหัวข้อ "รายวิชา" / "แผนการศึกษา" / "คำอธิบายรายวิชา" อยู่ในเนื้อหาเองอยู่แล้ว
#    ขยับไปกับเล่มเสมอ ไม่ต้องแก้โค้ดตามทุกครั้ง
#
#  ข้อควรระวังที่เจอจริงตอนตรวจกับ BIT/IT/DSBA/AIT/GENED ทั้ง 5 โปรแกรม
#    1) "3.1.9 คำอธิบายรายวิชา (ภาคผนวก จ)" เป็นแค่ตัวชี้ไปภาคผนวก ไม่ใช่หัวข้อจริง
#       ตัวจริงคือ "คำอธิบายรายวิชาเฉพาะ" หรือหัวข้อ # เปล่า ๆ "# คำอธิบายรายวิชา"
#       หรือ "ภาคผนวก ก คำอธิบายรายวิชา" (ดู DESC_START_RE)
#    2) DSBA มีประโยคแทรก "สำหรับแผนการศึกษาที่ไม่เข้าร่วมโครงการสหกิจศึกษา" อยู่ในหมวด
#       รายวิชา (component 1) ก่อนถึงหัวข้อแผนจริง "...ที่ไม่เข้าโครงการสหกิจศึกษา"
#       (ไม่มี "ร่วม") — ตัวจริงกับตัวหลอกต่างกันแค่คำว่า "ร่วม" เท่านั้น
#       ดู negative lookahead (?!ร่วม) ใน NOCOOP_RE/COOP_RE
#    3) หัวข้อ "แผนการศึกษา" เฉย ๆ (ไม่ระบุ นอกจาก/ใน โครงการสหกิจ) เป็นแค่หัวข้อแม่ที่
#       บางเล่มพิมพ์นำหน้า nocoop/coop (เช่น IT: "3.1.4 แผนการศึกษา" ตามด้วย "3.1.4.1 ...")
#       ใช้เป็น section เดี่ยว "plan" เฉพาะตอนที่เล่มนั้นไม่มี nocoop/coop แยกเลย (เช่น AIT)
#    4) ท้ายแต่ละแผนการศึกษาจะมีบรรทัด "รวมตลอดหลักสูตร N หน่วยกิต" เสมอ (พิมพ์ซ้ำท้ายทุก
#       แผน ถ้ามีมากกว่าหนึ่งแผน) ใช้เป็นจุดตัดท้าย section แผน แทนการเดาว่า "จบตรงก่อนหน้า
#       section ถัดไป" เพราะระหว่างท้ายแผนกับหัวข้อคำอธิบายรายวิชามักมีเนื้อหาอื่นคั่นอยู่
#       (รหัสวิชา, ระบบการศึกษา, ฯลฯ) หลายสิบหน้าที่ไม่ใช่ของ section ไหนเลย
#
#  ตรวจแล้วว่าให้ผลตรงกับตาราง PROGRAM_PAGE_RANGES (hand-tuned) เป๊ะทั้ง 16 ค่าใน 5 โปรแกรม
DESC_START_RE = re.compile(
    r"(?:^#{1,4}\s*คำอธิบายรายวิชา\s*$"          # หัวข้อ markdown เปล่า ๆ (AIT/DSBA)
    r"|คำอธิบายรายวิชาเฉพาะ"                       # "...เฉพาะ" (BIT/IT)
    r"|ภาคผนวก\s*[ก-ฮ]\.?\s*คำอธิบายรายวิชา)",   # ภาคผนวกที่มีเนื้อหาเต็ม (GENED)
    re.M)

COURSE_LIST_RE = re.compile(
    r"(?:^\s*#{0,4}\s*\d+(?:\.\d+)*\.?\s+รายวิชา(?:ในหมวด[^\n]*)?\s*$"  # "3.1.3 รายวิชา" ฯลฯ
    r"|^\s*#{0,4}\s*รายวิชา\s*$"                                        # หัวข้อเปล่า ๆ
    r"|\*\*\s*\d+(?:\.\d+)*\.?\s+รายวิชา\s*\*\*)",                      # ตัวหนาในตาราง (GENED)
    re.M)

NOCOOP_RE = re.compile(r"แผนการศึกษาที่ไม่เข้า(?!ร่วม)โครงการสหกิจศึกษา")
COOP_RE = re.compile(r"แผนการศึกษา(?:สำหรับ|ที่เข้า(?!ร่วม))?โครงการสหกิจศึกษา")   # DSBA_2560 พิมพ์ \"แผนการศึกษาโครงการสหกิจศึกษา\" (ไม่มี สำหรับ/ที่เข้า)
GENERIC_PLAN_RE = re.compile(r"แผนการศึกษา")
TOTAL_CREDITS_RE = re.compile(r"รวมตลอดหลักสูตร")

_PLAN_KEYS = ("nocoop", "coop", "plan")


def detect_sections(text: str) -> dict[str, tuple[int, int]]:
    """หาช่วงหน้าของแต่ละ section จากป้ายหัวข้อภาษาไทยในเนื้อหาเอง

    คืน dict คีย์ที่อาจปรากฏ (มีเฉพาะ key ที่หาเจอจริงในเอกสารนี้เท่านั้น):
      course_list — หมวด "รายวิชา" (รหัส/ชื่อ/หน่วยกิต ไม่มีปี/เทอม; key ใหม่ ตารางเดิมไม่มี)
      nocoop/coop — หมวด "แผนการศึกษา" สองแผน (สหกิจ/ไม่สหกิจ) ถ้าเล่มแยกไว้
      plan        — หมวด "แผนการศึกษา" แผนเดียว ถ้าเล่มไม่แยกสหกิจ/ไม่สหกิจ (เช่น AIT)
      courses     — หมวด "คำอธิบายรายวิชา" (คำอธิบาย/วิชาบังคับก่อน; ชื่อคีย์ตามตารางเดิม
                    PROGRAM_PAGE_RANGES เพื่อให้โค้ดเดิมที่เรียก sections["courses"] ใช้ได้ต่อ)

    ผู้เรียกต้องเช็คว่า key ที่ต้องการมีอยู่จริงก่อนใช้ เหมือนตอนเช็ค
    PROGRAM_PAGE_RANGES[program] เดิม — เอกสารบางแบบ (เช่น GENED) ไม่มีหมวดแผนการศึกษาเลย
    """
    pages = _iter_pages(text)
    if not pages:
        raise ValueError("ไม่พบตัวคั่นหน้าในเอกสาร (รองรับ --- Page N --- หรือ "
                         "<!-- PDF_PAGE N -->) — ใช้ --start-page/--end-page เองถ้าไฟล์นี้ไม่มี"
                         "ตัวคั่นหน้า")

    first_hit: dict[str, int] = {}
    generic_plan_pages: list[int] = []
    total_pages: list[int] = []

    for page_no, chunk in pages:
        if "courses" not in first_hit and DESC_START_RE.search(chunk):
            first_hit["courses"] = page_no
        if "course_list" not in first_hit and COURSE_LIST_RE.search(chunk):
            first_hit["course_list"] = page_no
        if "nocoop" not in first_hit and NOCOOP_RE.search(chunk):
            first_hit["nocoop"] = page_no
        if "coop" not in first_hit and COOP_RE.search(chunk):
            first_hit["coop"] = page_no
        if GENERIC_PLAN_RE.search(chunk):
            generic_plan_pages.append(page_no)
        if TOTAL_CREDITS_RE.search(chunk):
            total_pages.append(page_no)

    # "plan" (แผนเดียว) ใช้เฉพาะตอนไม่มี nocoop/coop แยกเลยในทั้งเอกสาร — ถ้ามีอย่างใด
    # อย่างหนึ่งแล้ว แปลว่าหัวข้อ "แผนการศึกษา" เปล่า ๆ ที่เจอเป็นแค่หัวข้อแม่ ไม่ใช่ section ใหม่
    if "nocoop" not in first_hit and "coop" not in first_hit and generic_plan_pages:
        first_hit["plan"] = generic_plan_pages[0]

    if not first_hit:
        raise ValueError(
            "ไม่พบหัวข้อ 'รายวิชา' / 'แผนการศึกษา' / 'คำอธิบายรายวิชา' ในเอกสารนี้เลย — "
            "ตรวจว่าเป็น Markdown จาก Lab 7B จริงหรือไม่ หรือใช้ --start-page/--end-page เอง")

    last_page = max(p for p, _ in pages)
    ordered = sorted(first_hit.items(), key=lambda kv: kv[1])
    ranges: dict[str, tuple[int, int]] = {}
    for idx, (key, start) in enumerate(ordered):
        next_start = ordered[idx + 1][1] if idx + 1 < len(ordered) else None
        fallback_end = (next_start - 1) if next_start is not None else last_page
        if key in _PLAN_KEYS:
            # section แผนการศึกษา: จบที่บรรทัด "รวมตลอดหลักสูตร" ถัดไปหลังจุดเริ่ม ไม่ใช่แค่
            # ก่อนหน้า section ถัดไป — กันไม่ให้กินเนื้อหาอื่นที่คั่นอยู่ระหว่างกลาง (ดูข้อ 4 ด้านบน)
            candidates = [p for p in total_pages
                         if p >= start and (next_start is None or p < next_start)]
            end = min(candidates) if candidates else fallback_end
        else:
            end = fallback_end
        ranges[key] = (start, end)
    return ranges

def parse_json_loose(s: str) -> dict:
    """ดึง JSON ออกจากคำตอบ แม้จะมี <think> หรือ fence ปนมา"""
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


EXTRACT_PROMPT = """คุณคือผู้ช่วยแปลงเอกสารหลักสูตรเป็นข้อมูลที่มีโครงสร้าง

แปลงข้อความเล่มหลักสูตรต่อไปนี้เป็น JSON ตาม schema นี้เท่านั้น

{
  "program":  {"program_id":"", "name_th":"", "name_en":"", "degree":"",
               "total_credits":0, "years":0},
  "courses":  [{"code":"12345678","name_th":"","name_en":"","credits":0,
                "lecture_h":0,"lab_h":0,"self_h":0,"description_th":"",
                "source_page":null}],
  "plan":     [{"year":1,"semester":1,"code":"12345678","credits":0,
                "alt_group":null,"category":null,"type":null,"note":null,
                "source_page":null}],
  "prerequisites": [{"code":"12345678","requires":"12345678","kind":"pre"}],
  "elective_slots": [{"code":"12345678","allowed_terms":"3/1, 3/2, 4/1",
                      "name_th":"", "name_en": "", "credits":0,"category":null,"type":null,
                      "source_page":null}]
}

กติกา
1. รหัสวิชาต้องเป็นตัวเลข 8 หลักเสมอ
2. ถ้าเล่มเขียนว่า "รหัส A หรือ รหัส B" ให้แตกเป็นสองรายการในแผน
   โดยใส่ alt_group เป็นข้อความเดียวกัน เช่น "elective_y3s1_1"
3. ค่าที่หาไม่พบ ให้ใส่ null ห้ามเดาและห้ามคำนวณเอง
4. semester ใช้ 1, 2 หรือ 3 (3 หมายถึงภาคฤดูร้อน)
5. ข้อความมีตัวคั่น --- Page N --- บอกเลขหน้า
   ทุกวิชาที่อยู่ใต้ตัวคั่นนั้น ให้ใส่ N ลงใน source_page ของวิชานั้น
   ห้ามเดาเลขหน้า ถ้าไม่มีตัวคั่นอยู่ข้างบนให้ใส่ null
6. category คือหมวดวิชา เช่น "หมวดวิชาเฉพาะ" "หมวดวิชาศึกษาทั่วไป"
   "หมวดวิชาเลือกเสรี"  ส่วน type คือ "บังคับ" หรือ "เลือก"
   ใส่แยกสองฟิลด์ ห้ามรวมเป็นข้อความเดียว และห้ามใส่ลงใน note
7. วิชาที่เล่มไม่ได้ล็อกปี/เทอม แต่บอกว่าเรียนได้หลายเทอม
   (เช่น "เรียนได้ในภาค 3/1, 3/2 หรือ 4/1") ให้ใส่ใน elective_slots
   ห้ามใส่ใน plan และห้ามเดาปี/เทอมให้
8. ตอบเป็น JSON ล้วน ไม่ต้องมีคำอธิบาย

ข้อความ:
"""

REPAIR_PROMPT = """JSON ที่คุณสร้างมาไม่ผ่านการตรวจสอบ นี่คือรายการข้อผิดพลาด

{errors}

แก้เฉพาะจุดที่ระบุไว้ ห้ามแก้ส่วนอื่น ห้ามลบรายการที่ถูกต้องอยู่แล้ว
ถ้าข้อผิดพลาดเกิดเพราะข้อมูลไม่มีในเอกสารจริง ให้ลบรายการนั้นออก แทนที่จะเดาค่า

ตอบกลับเป็น JSON ฉบับสมบูรณ์ที่แก้แล้ว ไม่ต้องมีคำอธิบาย

JSON เดิม:
{payload}
"""


def format_errors(exc) -> str:
    """
    แปลง ValidationError ของ Pydantic เป็นข้อความที่ LLM แก้ตามได้จริง

    จุดสำคัญ: ต้องบอก "ตำแหน่ง" ให้ชัด (plan -> 12 -> code)
    ถ้าบอกแค่ "รหัสวิชาผิด" โมเดลจะไม่รู้ว่าต้องแก้รายการไหน
    แล้วมักจะรื้อทั้งก้อนใหม่ ซึ่งทำให้ข้อมูลที่ถูกอยู่แล้วพังไปด้วย
    """
    lines = []
    for e in exc.errors()[:25]:      # จำกัดไว้ไม่ให้ prompt ยาวเกิน
        loc = " -> ".join(str(x) for x in e["loc"])
        lines.append(f"- ตำแหน่ง {loc}: {e['msg']}")
    if len(exc.errors()) > 25:
        lines.append(f"- (และอีก {len(exc.errors()) - 25} ข้อ)")
    return "\n".join(lines)


def extract_with_repair(text: str, max_rounds: int = MAX_REPAIR_ROUNDS,
                        verbose: bool = True) -> tuple[dict, dict]:
    """
    สกัด JSON แล้ววนซ่อมจนผ่าน หรือจนครบจำนวนรอบ

    ทำไมต้องจำกัดจำนวนรอบ
        ถ้าปล่อยให้วนไม่จำกัด จะเจอกรณีที่โมเดลแก้วนไปวนมาไม่จบ
        (แก้ข้อ A แล้วข้อ B พัง แก้ข้อ B แล้วข้อ A พังอีก)
        การจำกัดรอบแล้ว "ยอมแพ้อย่างมีเกียรติ" คือพฤติกรรมที่ถูกต้อง
        ระบบที่ดีต้องรู้ว่าเมื่อไรควรส่งงานให้คนตรวจ

    คืน (data, meta) โดย meta บอกว่าใช้กี่รอบและผ่านหรือไม่
    """
    from pydantic import ValidationError
    Curriculum = build_models()

    raw = ollama_generate(EXTRACT_PROMPT + text, fmt="json")
    data = parse_json_loose(raw)
    meta = {"rounds": 0, "valid": False, "errors": []}

    for attempt in range(max_rounds + 1):
        try:
            model = Curriculum.model_validate(data)
            meta.update({"rounds": attempt, "valid": True, "errors": []})
            if verbose:
                print(f"  ผ่านการตรวจในรอบที่ {attempt}")
            return model.model_dump(), meta
        except ValidationError as exc:
            errs = format_errors(exc)
            meta["errors"] = errs.splitlines()
            if verbose:
                print(f"  รอบที่ {attempt}: พบข้อผิดพลาด {len(exc.errors())} ข้อ")
            if attempt >= max_rounds:
                meta.update({"rounds": attempt, "valid": False})
                if verbose:
                    print(f"  ! ซ่อมครบ {max_rounds} รอบแล้วยังไม่ผ่าน "
                          f"— ทำเครื่องหมายให้คนตรวจ")
                return data, meta
            raw = ollama_generate(
                REPAIR_PROMPT.format(
                    errors=errs,
                    payload=json.dumps(data, ensure_ascii=False)),
                fmt="json")
            new = parse_json_loose(raw)
            if new:
                data = new

    return data, meta


def cmd_extract(args) -> None:
    text = Path(args.input).read_text(encoding="utf-8")

    if args.start_page and args.end_page:
        text = slice_pages(text, args.start_page, args.end_page)
    elif not args.no_detect:
        # ค่าเริ่มต้น: จับ section จากป้ายหัวข้อภาษาไทยในไฟล์เอง (ดู detect_sections())
        # แทนตาราง PROGRAM_PAGE_RANGES ที่ hardcode เลขหน้าไว้ล่วงหน้า
        try:
            ranges = detect_sections(text)
        except ValueError as exc:
            if args.program:
                # เอกสารนี้จับป้ายหัวข้อไม่ได้ (เช่นไม่มีตัวคั่นหน้า) — ถอยไปใช้ตาราง
                # legacy ถ้าผู้ใช้ระบุ --program ไว้ ไม่งั้นก็ส่ง error ของ detect_sections ต่อ
                ranges = PROGRAM_PAGE_RANGES.get(args.program)
                if ranges is None:
                    raise SystemExit(str(exc)) from exc
                print(f"  ! จับป้ายหัวข้อในเนื้อหาไม่ได้ ({exc}) — ใช้ตาราง legacy "
                      f"ของ {args.program} แทน")
            else:
                raise SystemExit(str(exc)) from exc
        section = args.section or next(iter(ranges))
        if section not in ranges:
            raise SystemExit(f"ไม่พบ section '{section}' ในเอกสารนี้ "
                             f"(เจอแค่ {list(ranges)})")
        start, end = ranges[section]
        print(f"  ตัดเฉพาะหน้า {start}-{end} (section: {section}"
              f"{f', โปรแกรม {args.program}' if args.program else ''})")
        text = slice_pages(text, start, end)

    if args.max_chars and len(text) > args.max_chars:
        print(f"  ! ข้อความยาว {len(text):,} ตัวอักษร ตัดเหลือ {args.max_chars:,}")
        text = text[:args.max_chars]
    t0 = time.time()
    data, meta = extract_with_repair(text, args.rounds)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["seconds"] = round(time.time() - t0, 1)
    out.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  เขียน {out}  ({meta['seconds']}s · "
          f"{'ผ่าน' if meta['valid'] else 'ต้องให้คนตรวจ'})")


# ── นำ JSON จาก Lab 7B มาใช้ต่อโดยไม่เรียก LLM ซ้ำ ─────────────────────────

# นำหน้าชื่อวิชาบางรายวิชา (กลุ่มวิชาเลือกที่คณะกำหนด) ด้วยข้อความคงที่นี้ในเล่ม
# แต่ Lab 7B OCR/VLM ดันดึงติดมาเป็นส่วนหนึ่งของ name_th แทนที่จะแยกออก —
# ตัดออกตรงนี้เพื่อให้ name_th ตรงกับชื่อวิชาจริงตามเฉลย (GT ไม่มีข้อความนี้)
_FACULTY_ELECTIVE_PREFIX_RE = re.compile(r"^กลุ่มวิชาที่กำหนดโดยคณะ\*?\s*")

# ชื่อย่อหมวดวิชาที่ Lab 7B อ่านมาไม่ตรงกับชื่อเต็มที่ใช้ในเฉลย (GT) — แม็ปให้ตรงกัน
_CATEGORY_ALIASES = {
    "หมวดวิชาเสรี": "หมวดวิชาเลือกเสรี",
}


def _normalize_name_th(name_th: str | None) -> str | None:
    """ตัดข้อความนำหน้าคงที่ (กลุ่มวิชาที่กำหนดโดยคณะ*) ออกจากชื่อวิชา ถ้ามี"""
    if not name_th:
        return name_th
    return _FACULTY_ELECTIVE_PREFIX_RE.sub("", name_th).strip() or name_th


# ── ตัดข้อความที่ Lab 7B ดึงติดท้ายชื่อวิชา กลับเป็นชื่อตามเล่ม ──────────────────
# บั๊กที่พบจริงกับ IT (หน้า 29, รายการโมดูลอาชีพ M1/M2/M3): bullet สุดท้ายของแต่ละโมดูล
# ถูกต่อด้วยย่อหน้าถัดไปเป็นส่วนหนึ่งของ name_th เช่น
#   06016430 "...แอปพลิเคชัน" + "M2: โมดูล / ประกอบด้วยรายวิชาดังต่อไปนี้"
#   06016441 "...เครือข่ายและระบบ" + "M3: โมดูลประกอบด้วย..."
#   06016448 "...เกมเอนจิ้น" + "วิชาเลือกทางเทคโนโลยีสารสนเทศจากกลุ่มวิชาบังคับเฉพาะสาขา"
# markdown ต้นทางสะอาด (ชื่ออยู่บรรทัดของตัวเอง) จึงใช้ชื่อในเล่มเป็นหลักฐาน: ตัดเฉพาะเมื่อ
# name_th ขึ้นต้นด้วยชื่อที่พบในเล่มและยาวกว่า — ไม่เขียนทับชื่อที่แค่สะกดต่างกัน
_CODE_NAME_LINE_RE = re.compile(
    r"(?m)^[\s\*\-]*\**(\d{8})\s+([^\n*]+?)\s*(?:\d\(\d-\d-\d\))?\**\s*$")


def build_canonical_names(md_text: str) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for m in _CODE_NAME_LINE_RE.finditer(md_text or ""):
        names.setdefault(m.group(1), []).append(m.group(2).strip())
    return names


def trim_names_to_canonical(courses: list[dict], md_text: str
                            ) -> tuple[list[dict], list[str]]:
    canon = build_canonical_names(md_text)
    notes: list[str] = []
    out: list[dict] = []
    for src in courses:
        row = dict(src)
        name = str(row.get("name_th") or "")
        code = str(row.get("code") or "").strip()
        best = max((o for o in canon.get(code, [])
                    if name.startswith(o) and name != o), key=len, default=None)
        if best:
            notes.append(f"{code}: ตัดข้อความที่ติดท้ายชื่อวิชาออก "
                         f"({name!r} -> {best!r}) ตามชื่อในเล่มดิบ")
            row["name_th"] = best
        out.append(row)
    return out, notes


# ── คืนช่องว่างในชื่อวิชา (BIT) ──────────────────────────────────────────────────────────
# พบจริงกับ BIT: เล่มพิมพ์ "วิชาเลือกหมวดวิชาศึกษาทั่วไป สำหรับหลักสูตรนานาชาติ 1" และ
# "วิชาเลือกทางเทคโนโลยีสารสนเทศทางธุรกิจ 1 หรือ กลุ่มวิชาที่ 1-4" (เฉลยมีช่องว่าง) แต่ name_th ที่ออกมาติดกันหมด
# สาเหตุ: เล่มพิมพ์ชื่อเดียวกันซ้ำหลายตาราง บางสำเนาตัดบรรทัดด้วย <br/> กลางชื่อ (".. ทั่วไป<br/>สำหรับ.."
# ".. 1 หรือ<br/>กลุ่มวิชาที่ 1-4") และ Lab 7B ต่อสองบรรทัดโดยไม่ใส่ช่องว่าง ตัวไปป์ไลน์เองไม่ได้ลบช่องว่าง
# (ตรวจแล้ว: ไม่มีขั้นใดใน convert_lab7b ตัดช่องว่างของ name_th)
# ฟังก์ชันนี้อ่านชื่อจากเซลล์ที่ชื่ออยู่บรรทัดเดียว (ไม่ถูก <br/> ตัดกลางชื่อ) แล้วคืนช่องว่างให้ name_th ที่
# ตัวอักษรเหมือนกันทุกตัว ต่างกันแค่ช่องว่าง -- ไม่แก้ตัวสะกดและไม่เติมคำ
# ใช้ชื่อที่เล่มพิมพ์เป็นคีย์ (ไม่ใช้รหัส) เพราะแถว placeholder (9664xxxx, 06036xxx) ไม่มีรหัสจริง
NAME_SPACING_RESTORE_PROGRAMS: set[str] = {"BIT"}


def _table_single_line_name_variants(md_text: str) -> dict[str, set[str]]:
    """ชื่อไทยแบบมีช่องว่างตามที่เล่มพิมพ์ จัดกลุ่มด้วยรูปที่ตัดช่องว่างทิ้ง (เฉพาะเซลล์ที่ชื่อไทยอยู่บรรทัดเดียว)"""
    out: dict[str, set[str]] = {}
    for tbl in re.findall(r"<table>.*?</table>", md_text or "", flags=re.S):
        for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tbl, flags=re.S):
            txt = re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", cell))
            lines = [re.sub(r"\s+", " ", ln).strip() for ln in txt.split("\n")]
            lines = [ln for ln in lines if ln]
            if not lines or not re.search(r"[\u0E00-\u0E7F]", lines[0]):
                continue
            # บรรทัดแรกต้องเป็นชื่อไทยทั้งบรรทัด และบรรทัดถัดไป (ถ้ามี) ต้องเป็นชื่ออังกฤษ ไม่ใช่ไทยที่ถูกตัดต่อ
            if len(lines) > 1 and re.search(r"[\u0E00-\u0E7F]", lines[1]) and not re.match(r"[A-Z]", lines[1]):
                continue
            th = lines[0]
            if len(lines) == 1:      # ชื่อไทย+อังกฤษอยู่บรรทัดเดียว: ตัดที่คำอังกฤษตัวพิมพ์ใหญ่คำแรก (รวมคำสั้นอย่าง 'GE')
                cut = re.search(r"\s[A-Z]{2,}\b", th)
                th = th[:cut.start()] if cut else th
            th = th.strip()
            if th and " " in th:
                out.setdefault(re.sub(r"\s+", "", th), set()).add(th)
    return out


def restore_name_spacing_from_tables(courses: list[dict], program: str | None, text: str | None
                                     ) -> tuple[list[dict], list[str]]:
    """name_th ที่เหมือนชื่อในตารางทุกตัวอักษรแต่ไม่มีช่องว่าง -> ใช้ชื่อมีช่องว่างตามที่เล่มพิมพ์

    กันพลาด: ต้องมีรูปแบบเดียวที่เล่มพิมพ์ (ถ้ามีหลายรูปแบบ -> ไม่แตะ) และรูปนั้นต้องมีช่องว่างมากกว่าค่าเดิม
    """
    if not text or program not in NAME_SPACING_RESTORE_PROGRAMS:
        return courses, []
    variants = _table_single_line_name_variants(text)
    notes: list[str] = []
    out: list[dict] = []
    for src in courses:
        row = dict(src)
        name = str(row.get("name_th") or "")
        cands = variants.get(re.sub(r"\s+", "", name)) or set()
        if len(cands) == 1:
            good = next(iter(cands))
            if good != name and good.count(" ") > name.count(" "):
                notes.append(f"{row.get('code')}: name_th คืนช่องว่างตามที่เล่มพิมพ์ ({name!r} -> {good!r})")
                row["name_th"] = good
        elif len(cands) > 1 and name not in cands:
            notes.append(f"{row.get('code')}: เล่มพิมพ์ชื่อ {name!r} ไว้หลายแบบช่องว่าง {sorted(cands)} -- ไม่แก้ ให้คนตรวจ")
        out.append(row)
    return out, notes



def _normalize_category(category: str | None) -> str | None:
    """แม็ปชื่อย่อหมวดวิชาที่ไม่ตรงเฉลยให้เป็นชื่อเต็มมาตรฐาน"""
    if not category:
        return category
    return _CATEGORY_ALIASES.get(category, category)


def _credit_parts(value: Any) -> tuple[int | None, int | None, int | None, int | None]:
    """แปล 3(2-2-5) ของ Lab 7B เป็นคอลัมน์ตัวเลขของ Lab 8B

    บางวิชาในเล่ม (เช่น วิชาเลือกเสรี, สหกิจศึกษา, โครงงาน) เขียนเป็น 3(x-x-x)
    แทนที่จะเป็นตัวเลข เพราะชั่วโมงบรรยาย-ปฏิบัติ-ศึกษาด้วยตนเองไม่คงที่/ไม่ระบุ
    ไม่ใช่ข้อมูลอ่านผิด — ต้องรับได้ ไม่งั้นทั้งแถวจะถูกข้าม (ข้ามพร้อมทั้งวิชา ไม่ใช่แค่ชั่วโมง)
    """
    text = str(value or "").strip()
    m = re.search(r"(\d+)\s*\(\s*(\d+|[xX]+)\s*-\s*(\d+|[xX]+)\s*-\s*(\d+|[xX]+)\s*\)", text)
    if m:
        credit = int(m.group(1))
        if credit > 12:        # เกินขอบของ schema (credits <= 12) = อ่านผิด เช่น เลข "15 ชั่วโมง" ในคำอธิบายหลุดมา
            raise ValueError(f"หน่วยกิต {credit} เกิน 12 (น่าจะอ่านผิด): {value!r}")
        hours = tuple(int(g) if g.isdigit() else None for g in m.groups()[1:])
        return (credit,) + hours  # type: ignore[return-value]
    # หน่วยกิตเดี่ยวต้องเป็นเลข 1-2 หลักล้วน ๆ — เลข 6 หลักขึ้นไปคือรหัสวิชาที่หลุดเข้าช่องหน่วยกิต
    m = re.fullmatch(r"(\d{1,2})(?:\s*หน่วยกิต)?", text)
    if not m:
        raise ValueError(f"อ่านหน่วยกิตไม่ได้: {value!r}")
    if int(m.group(1)) > 12:   # schema: credits <= 12 -> เลขเดี่ยวเกิน 12 = อ่านผิด (เช่น 21 จาก "ศตวรรษที่ 21")
        raise ValueError(f"หน่วยกิต {m.group(1)} เกิน 12 (น่าจะอ่านผิด): {value!r}")
    return int(m.group(1)), None, None, None


def _lab7b_codes(value: Any) -> list[str]:
    """แตกรหัส `A หรือ B`; คืนเฉพาะรหัสตัวเลข 8 หลักที่โหลด DB ได้"""
    return re.findall(r"(?<!\d)\d{8}(?!\d)", str(value or ""))


# CREDITS_OVERRIDE (รหัส->ค่าหน่วยกิตที่ตรวจมือ 9 รายการ) ถูกถอดออกแล้ว — แทนที่ด้วยกฎทั่วไป
# สองข้อที่ไม่พึ่งคำตอบเฉลย:
#   1) repair_credits_from_raw_tables() — parse <table> ดิบใน intermediate_vlm.md ตรง ๆ แบบ
#      อิงตำแหน่ง (cell สุดท้ายของแถว) ไม่อิง header เก็บคืนได้ 6/9 รายการเป๊ะ (06036100,
#      06036101, 96641001, 96641003, 96644007, 96644042) เพราะพิสูจน์แล้วว่าแถวข้อมูลดิบของ
#      ตาราง "ปีที่ 1 ภาคการศึกษาที่ 1" ยังครบถูกต้องทุกแถว มีแค่ header แถวเดียวที่โครงสร้าง
#      HTML พัง — ต้นเหตุจริงอยู่ที่ขั้นตอน Lab 7B แปล markdown->JSON สับสนกับ header ที่พัง
#      ไม่ใช่ข้อมูลดิบหายจริง (ดู comment ที่ตัวฟังก์ชัน)
#   2) flag_inferred_credits_for_review() — อีก 3 รายการที่เหลือ (06036131, 06036134, 06036135)
#      ไม่ใช่แถวในตารางแผนเลย (year=semester=0 มีแต่หน้าคำอธิบาย) จึงไม่มี <table> ให้ parse คืน
#      ทดลองใช้กฎ "ตัดเป็น null ถ้าหน่วยกิตตรงกับ default ที่พบบ่อยสุดในเล่ม + description_th
#      ไม่มีวงเล็บชั่วโมงยืนยัน" แล้วพบว่า *ทำลาย* แถวที่ถูกอยู่แล้วไปเยอะกว่าที่แก้ได้จริง (เช่น
#      06036128 มี note เดียวกันกับ 06036134 เป๊ะ แต่ 06036128 อนุมานถูก ส่วน 06036134 อนุมานผิด
#      — ไม่มีสัญญาณอื่นในข้อมูลแยกสองกรณีนี้ออกจากกันได้เลย) ตอนนั้นจึงเปลี่ยนมา "รายงานให้คนตรวจ"
#      (flag_inferred_credits_for_review) แทนการเดาค่าใด ๆ ทั้งสองทาง
#
#   นโยบายเปลี่ยน (รอบ DSBA นี้): ผู้ใช้ระบุชัดว่าไม่ต้องการให้ไปป์ไลน์เดา/อนุมานค่าแทนเลย — ไม่รู้
#   แน่ชัดให้เป็น null เสมอ แม้จะรู้ว่าเสีย recall ของแถวที่บังเอิญอนุมานถูกไปบ้างก็ตาม จึงเพิ่ม
#   null_inferred_credits() (แทนที่จุดเรียก flag_inferred_credits_for_review() ใน
#   split_lab7b_by_plan()) ให้ตั้งหน่วยกิตเป็น null จริงทุกแถวที่มี note นี้ ไม่ใช่แค่รายงาน
#   ฟังก์ชันเดิมยังเก็บไว้เป็นข้อมูลอ้างอิง ไม่ได้ลบ — ทางแก้ระยะยาวที่แท้จริงยังเหมือนเดิมคือ
#   กลับไปแก้ Lab 7B (lab7b_curriculum.py ไม่ได้อัปโหลดรอบนี้) ให้ใส่ null เองตั้งแต่ต้นเมื่อไม่มั่นใจ
#   แทนที่จะพิมพ์ค่าที่เดามาพร้อม note ว่า "อนุมาน" ออกมาให้ downstream ต้องมาแก้เอง


# บั๊กที่พบจริงกับ pred_vlm.json ของ BIT (session ตรวจ credits field): Lab 7B แตกโน้ต
# "เลือกอย่างใดอย่างหนึ่ง: 96643021 หรือ 06036xxx หรือ xxxxxxxx" ออกเป็นหนึ่งแถวต่อหนึ่ง
# ตัวเลือก (index 34/44/46/... ใน pred_vlm.json) แต่ทุกแถวถูกยัด name_th/name_en/credits
# ชุดเดียวกัน (ชื่อกลุ่ม + "1" หน่วยกิต) ซ้ำกันหมด ทั้งที่แต่ละรหัสเป็นวิชา/ช่องวิชาคนละตัว
# (96643021 ตัวจริงคือ "ผู้ประกอบการสมัยใหม่" 3(3-0-6) บังคับ อยู่คนละแถว/หน้าเลยด้วยซ้ำ)
# ถ้าปล่อยให้แถวสังเคราะห์นี้กำหนดชื่อ/หน่วยกิตของรหัสนั้น จะทับข้อมูลจริง (ถ้าอยู่คนละหน้า/
# section ที่ถูกแยกไปประมวลผลกันคนละรอบ — ดู split_lab7b_by_plan() — ก็ไม่มีข้อมูลจริงมาทับคืน
# เลยด้วย) หรือสร้างวิชาผีขึ้นมาแทน โดยเฉพาะกับรหัส wildcard ทั่วไป (06036xxx, xxxxxxxx) ที่ชน
# กับช่องวิชาเลือกจริงที่ไม่เกี่ยวข้องกันเลย (PLACEHOLDER_XXXXXXXX ชนกับ "วิชาเลือกเสรี")
_ALT_NOTE_RE = re.compile(r"เลือกอย่างใดอย่างหนึ่ง[:：]?\s*(.+)")


def _alt_group_note_codes(note: Any) -> list[str]:
    """แยกรหัส/wildcard ที่ระบุไว้ในโน้ต 'เลือกอย่างใดอย่างหนึ่ง: A หรือ B หรือ C'"""
    m = _ALT_NOTE_RE.search(str(note or ""))
    if not m:
        return []
    return [tok.strip() for tok in re.split(r"\s*หรือ\s*", m.group(1)) if tok.strip()]


def _is_synth_alt_filler(raw_code: str, note: Any, alt_group: Any,
                         alt_group_names: dict[str, set[str]]) -> bool:
    """
    True ถ้าแถวนี้คือ "ตัวเลือกที่สังเคราะห์" จากโน้ต ไม่ใช่ข้อมูลจริงของรหัสนี้

    เงื่อนไขต้องเจอครบทั้งคู่ ไม่ใช่แค่ข้อใดข้อหนึ่ง (กันจับผิดตัว):
      1) รหัสของแถวนี้เองถูกระบุเป็นหนึ่งในตัวเลือกของโน้ต "เลือกอย่างใดอย่างหนึ่ง: ..."
      2) ทุกแถวที่แชร์ alt_group เดียวกัน ใช้ชื่อวิชา (name_th) ซ้ำกันหมดเป็นชื่อเดียว —
         คือลายเซ็นของ "ชื่อกลุ่มถูกก็อปวางซ้ำ" ต่างจาก alt_group ของสหกิจ "A หรือ B" เดิม
         ที่แต่ละแถวมีชื่อจริงของตัวเองอยู่แล้ว (ชื่อจึงต่างกัน ไม่เข้าเงื่อนไขนี้)
    """
    if not alt_group:
        return False
    note_codes = _alt_group_note_codes(note)
    if not note_codes:
        return False
    token = raw_code.strip().replace(" ", "").upper()
    if not any(token == c.replace(" ", "").upper() for c in note_codes):
        return False
    return len(alt_group_names.get(str(alt_group), ())) == 1


def _is_junk_ocr_placeholder_row(raw_code: str, name_th: Any) -> bool:
    """
    True ถ้า name_th คือ "รหัส wildcard + หน่วยกิต" ที่หลุดมาจากตารางตรงๆ ไม่ใช่ชื่อวิชาจริง

    บั๊กที่พบจริง (BIT ปี 4 เทอม 2 หน้า 30): มีแถว 06036xxx ที่ name_th="06036xxx 3(3-0-6)"
    name_en=None ปนอยู่กับอีก 2 แถวที่เป็นชื่อจริง ("...หรือกลุ่มวิชาที่ 1-4" x2) เดาว่า Lab 7B
    ดึงตัวเลขในคอลัมน์หน่วยกิตของตารางมาต่อท้ายรหัสแทนที่จะอ่านชื่อในคอลัมน์ถัดไป ผลคือได้
    ช่องวิชาที่ 3 ปลอมขึ้นมาซึ่งไม่มีในเฉลย (ดู eval-gt: fp ตรงกับ PLACEHOLDER_06036XXX_3)

    เกณฑ์: ชื่อ (ตัดช่องว่าง) ตรงกับรูปแบบ "<รหัสเดียวกับ code> <ตัวเลข(ตัวเลข-ตัวเลข-ตัวเลข)>"
    เป๊ะ ๆ — ไม่ใช่แค่ "มีรหัสอยู่ในชื่อ" เพื่อไม่ให้จับผิดชื่อวิชาจริงที่บังเอิญพูดถึงรหัสตัวเอง
    """
    name = str(name_th or "").strip()
    code = str(raw_code or "").strip()
    if not name or not code:
        return False
    m = re.fullmatch(re.escape(code) + r"\s+\d+\(\d+-\d+-\d+\)", name, re.IGNORECASE)
    return bool(m)


# แถวที่ Lab 7B "อนุมาน" ขึ้นเองจากยอดหน่วยกิตรวม/เลขลำดับที่ขาด (โน้ตประกาศเองว่า "OCR ไม่ได้
# อ่านแถวนี้") แต่อนุมานผิด — ตรวจกับ pred_vlm.json ของ BIT แล้วว่าอนุมานผิดจริง: ระบุปี/เทอม
# เป็น 4/1 หน้า 29 (nocoop) ทั้งที่ของจริง (2 ช่องวิชาเลือกทางธุรกิจ) อยู่ที่ 4/2 หน้า 30 คนละ
# ภาคเรียนกันเลย และเฉลยยืนยันว่าไม่มีวิชานี้อยู่จริง (ดู eval-gt: fp ตรงกับ
# PLACEHOLDER_06036XXX_4 พอดี, gt=null) ระบุด้วยลายเซ็น (year, semester, source_page) ที่ตรวจ
# มือแล้วเท่านั้น ไม่ใช่ทิ้งทุกแถวที่มีคำว่า "อนุมาน" ในเล่ม เพราะโปรแกรม/เทอมอื่นอาจมีแถวอนุมาน
# ที่ถูกต้องจริงอยู่ก็ได้ (การอนุมานจากยอดหน่วยกิตไม่ได้ผิดเสมอไป — ที่นี่ผิดเฉพาะกรณีนี้)
FABRICATED_ROW_OVERRIDE: dict[str, set[tuple[int, int, int]]] = {
    "BIT": {(4, 1, 29)},
}


def _is_known_bad_fabricated_row(program: str | None, year: int, semester: int,
                                 page: int | None, note: Any) -> bool:
    """True ถ้าแถวนี้ตรงกับลายเซ็นที่ตรวจมือแล้วว่าเป็นการอนุมานผิดใน FABRICATED_ROW_OVERRIDE"""
    if not note or "OCR ไม่ได้อ่านแถวนี้" not in str(note):
        return False
    sig = (year, semester, page)
    return sig in FABRICATED_ROW_OVERRIDE.get(program or "", set())


def _placeholder_code(raw_code: str) -> str | None:
    """
    แปลงรหัส wildcard ของเล่ม (90644xxx) เป็นรหัสช่องวิชาที่เก็บลงฐานข้อมูลได้

    คืน None ถ้าไม่ใช่รูปแบบ wildcard — ผู้เรียกจะได้ข้ามอย่างมีเหตุผล
    """
    token = str(raw_code or "").strip().replace(" ", "")
    if _WILDCARD_RE.match(token):
        return PLACEHOLDER_PREFIX + token.upper()
    return None


def _lab7b_pages(src: dict) -> list[int] | None:
    """เลขหน้าทั้งหมดของแถว Lab 7B (ไม่ซ้ำ คงลำดับตามที่ Lab 7B ให้มา) — None = ไม่รู้

    อ่านจาก pages (list) ก่อน แล้วค่อยถอยไป source_page/page/page_no/page_number
    เพื่อให้ pred JSON เวอร์ชันเก่าที่มีแต่เลขหน้าเดียวยังใช้ได้
    """
    out: list[int] = []
    for key in ("pages", "source_page", "page", "page_no", "page_number"):
        value = src.get(key)
        if value in (None, "", []):
            continue
        for item in (value if isinstance(value, list) else [value]):
            m = re.search(r"\d+", str(item))
            if m and int(m.group()) > 0 and int(m.group()) not in out:
                out.append(int(m.group()))
        if out:
            break
    return out or None


def _lab7b_page(src: dict) -> int | None:
    """
    ดึงเลขหน้าจากเรกคอร์ดของ Lab 7B

    Lab 7B เรียกฟิลด์นี้ไม่เหมือนกันในแต่ละ pipeline (source_page / page / page_no)
    จึงรับทุกชื่อที่เคยเจอ แทนที่จะบังคับให้ต้นทางแก้ชื่อ
    ถ้าต้นทางยังไม่เก็บเลขหน้าเลย จะได้ None ซึ่งแปลว่า "ไม่รู้" ไม่ใช่ "หน้า 0"
    """
    for key in ("source_page", "pages", "page", "page_no", "page_number"):
        value = src.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            value = value[0]
        m = re.search(r"\d+", str(value))
        if m:
            return int(m.group())
    return None


# วิชาที่ตารางแผนรายเทอมในเล่มจัดตำแหน่งปี/เทอมและ type='บังคับ' ไว้ชัดเจน และยอด
# หน่วยกิตต่อเทอมในเล่มก็รวมนับตามตำแหน่งนั้นจริง (ตรวจกับ pred_vlm.json แล้ว: field
# _meta.rules.term_checks ของ BIT ยืนยันว่าเทอม nocoop 3/2 และ 4/1 ที่ 06036145/06036146
# อยู่ reconcile หน่วยกิตครบพอดี — จึงไม่ใช่ OCR อ่านผิดหรือรหัสหลุดหน้า)
#
# ⚠️ เฉลยของสอง section ไม่ตรงกัน (ต่างจากที่เข้าใจผิดตอนแรกว่าตรงกันทั้งคู่):
#   - nocoop: เฉลยเห็นด้วยกับเล่ม (year=3/2, year=4/1, type='บังคับ') — ไม่ต้อง override
#   - coop:   เฉลยไม่ผูกปี/เทอม และ type='เลือก' — คนละค่ากับที่เล่มพิมพ์ไว้บนหน้า 29
# สมเหตุสมผลกับความจริงของหลักสูตร: แผนสหกิจเลื่อนตารางเรียนไปเพราะมีภาคสหกิจคั่นกลาง
# วิชาโครงงานนี้จึงกลายเป็นวิชาเลือกที่ยืดหยุ่นเทอมเฉพาะฝั่งสหกิจ ไม่ใช่ฝั่งปกติ
# override นี้จึงต้อง "ผูกกับ section" ด้วย ไม่ใช่ผูกกับ program เฉยๆ — เดิม (ตอนแรก)
# บังคับทั้งสอง section เท่ากันหมด ทำให้ nocoop ที่เคยตรงอยู่แล้วพังไปแทน
# (ตรวจกับ eval-gt จริงแล้วเห็นผลนี้ชัดเจน — นี่คือบทเรียนที่ต้องแก้ทันที)
# ยังไม่ได้ตรวจ IT/DSBA ว่ามีวิชาโครงงานแบบเดียวกันหรือไม่
# โปรแกรมที่เปิดใช้การกู้คืนจากตารางดิบ (ทางเลือก rowspan ที่หาย, หน่วยกิตที่เป็น null, ลำดับช่อง
# ตามเอกสาร, category/type ตามรหัส) — ตรวจกับ DSBA แล้วเท่านั้น; IT/BIT/AIT/GENED ยังไม่ได้ตรวจกับ
# markdown ดิบ จึงไม่เปิดจนกว่าจะตรวจ (เพิ่มชื่อโปรแกรมในเซ็ตนี้เมื่อตรวจแล้ว)
RAW_TABLE_RECOVERY_PROGRAMS: set[str] = {"DSBA", "BIT"}

# หมายเหตุที่ติดให้ elective_slot ที่ถูกบังคับเป็นวิชาเลือก แต่หน่วยกิตยังรวมอยู่ในยอดหลักสูตร
# (CHK1 ต้องนับหน่วยกิตของแถวที่มีป้ายนี้ ไม่งั้นยอดแผนขาดไปเท่าหน่วยกิตของวิชานั้น)
FORCED_ELECTIVE_COUNTED_MARK = "[นับในยอดหลักสูตร]"

# (โปรแกรม, section) ที่วิชาซึ่งถูกบังคับเป็นวิชาเลือก "ยังอยู่ในยอดหลักสูตรที่ประกาศ" จริง จึงให้ CHK1 บวกหน่วยกิตเพิ่ม
# ตอนนี้ว่างเปล่าโดยตั้งใจ: BIT coop เคยอยู่ในเซ็ตนี้ (06036145/06036146 = โครงงาน 1/2 รวม 6 หน่วยกิต)
# แต่ตรวจกับเล่มแล้วว่ายอดต่อเทอมของแผนสหกิจที่เล่มพิมพ์ (18+18+18+18+18+15+15+6) รวมได้ 126 พอดี "โดยไม่มี" โครงงาน
# และเล่มประกาศ 126 -- การบวกโครงงานอีก 6 จึงนับซ้ำ (CHK1 ได้ 132 ไม่ตรง 126)
# ค่าเดิมเคยชดเชยยอดที่ขาด 6 หน่วยกิตตอนที่ช่อง "เลือก 1 จาก 3" ของ 3/2 ถูกนับเป็นช่องเดียว
# (ดู split_cross_category_alt_groups) พอแก้ต้นเหตุนั้นแล้วตัวชดเชยจึงกลายเป็นตัวนับซ้ำ
FORCED_ELECTIVE_COUNTED_IN_TOTAL: set[tuple[str, str]] = set()

FORCE_ELECTIVE_TYPE_OVERRIDE: dict[str, dict[str, set[str]]] = {
    "BIT": {"coop": {"06036145", "06036146"}},
}



_CREDIT_LIKE_RE = re.compile(r"\d{1,2}\s*\(\s*[0-9xX]+\s*-\s*[0-9xX]+\s*-\s*[0-9xX]+\s*\)")


def _raw_table_credits_map(md_text: str) -> dict[str, list[str]]:
    """
    เดินตาราง <table> ดิบใน intermediate_vlm.md แล้วคืน {รหัส/wildcard -> [หน่วยกิตดิบ, ...]}

    ไม่สนใจว่า header แถวแรกของตารางจะพังแค่ไหน (<th> ซ้อน <td> ฯลฯ) เพราะไม่ได้อ่าน
    header เลย — อ่านเฉพาะแถวข้อมูลที่ cell แรก "หลังตัดช่องว่าง" ตรงกับรูปแบบรหัสวิชา
    (เลข 8 หลัก) หรือ wildcard (มีตัว x/X ปนอยู่) แล้วเก็บ "cell สุดท้าย" ของแถวนั้นไว้เป็น
    หน่วยกิตดิบ ตามตำแหน่งเสมอ ไม่อิงชื่อคอลัมน์ — วิธีนี้ทนต่อ header ที่พังได้ เพราะแถวข้อมูล
    ของบั๊กที่พบจริง (ตาราง "ปีที่ 1 ภาคการศึกษาที่ 1" ของ BIT) ยังเป็น <tr><td>...</td>...</tr>
    ที่ปกติสมบูรณ์ทุกแถว มีแต่แถว header เดียวที่ผิดโครงสร้าง — บั๊กจริงจึงอยู่ที่ขั้นตอนที่ LLM
    อ่าน markdown ไปสร้างเป็น JSON (สับสนเพราะ header พัง) ไม่ใช่ที่ตัวข้อมูลดิบเอง

    หนึ่งรหัสอาจมีค่าได้หลายค่า (ตารางเดียวกันพิมพ์ซ้ำหลายหน้าคนละแผน) — คืนเป็นลิสต์ตามลำดับ
    ที่เจอในเอกสาร ให้ผู้เรียกเลือกเองว่าจะเอาค่าไหน (ดู _pick_best_raw_credits)
    """
    out: dict[str, list[str]] = {}
    for table in re.findall(r"<table>.*?</table>", md_text, flags=re.S):
        for row in re.findall(r"<tr>.*?</tr>", table, flags=re.S):
            cells = [re.sub(r"<[^>]+>", " ", c).strip()
                     for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
            if not cells:
                continue
            token = cells[0].replace(" ", "").upper()
            is_code = bool(re.fullmatch(r"\d{8}", token))
            is_wildcard = bool(re.fullmatch(r"[0-9X]{4,8}", token) and "X" in token)
            if not (is_code or is_wildcard):
                continue
            # หน่วยกิต = เซลล์ \"ขวาสุดที่หน้าตาเป็นหน่วยกิต\" ไม่ใช่เซลล์สุดท้ายตามตำแหน่งดื้อ ๆ
            # (เจอจริง DSBA: ตาราง 4 คอลัมน์ที่ช่องท้ายว่าง -> cells[-1] ว่างแล้วทิ้งรหัส เช่น 06026217;
            # ตาราง colspan=3 ที่ช่องท้ายคือ \"ชื่อวิชา\" -> ชื่อถูกเขียนลงช่องหน่วยกิต เช่น 06026258)
            credits_cell = next((c.strip() for c in reversed(cells[1:])
                                 if _CREDIT_LIKE_RE.search(c)), "")
            if not credits_cell and len(cells) > 1 and re.fullmatch(
                    r"\d{1,2}(?:\s*หน่วยกิต)?", cells[-1].strip()):
                credits_cell = cells[-1].strip()        # เลขเดี่ยวล้วน (พฤติกรรมเดิม)
            if not credits_cell:
                continue
            out.setdefault(token, []).append(credits_cell)
    return out


def _pick_best_raw_credits(candidates: list[str]) -> str | None:
    """เลือกค่าที่ดีที่สุดจากหลายค่าดิบของรหัสเดียวกัน: เอาค่าที่ parse ผ่าน _credit_parts()
    ก่อนเสมอ (มีวงเล็บชั่วโมงครบ) ถ้าไม่มีเลยค่อยยอมรับค่าแรกที่เจอ"""
    for c in candidates:
        try:
            _credit_parts(c)
            return c
        except ValueError:
            continue
    return candidates[0] if candidates else None


def _credits_needs_repair(raw_credits: Any) -> bool:
    """True ถ้าค่าหน่วยกิตปัจจุบันน่าสงสัยพอที่จะลองหาค่าจากตารางดิบมาแทน:
    ว่างไปเลย, หรือเป็นเลขเดี่ยวล้วน ๆ ที่ไม่มีวงเล็บชั่วโมงกำกับ (ลายเซ็นของบั๊ก 96644007
    ที่ตัวเลขหลุดมาจากที่อื่นแทนคอลัมน์หน่วยกิตจริง)"""
    text = str(raw_credits or "").strip()
    if not text:
        return True
    return bool(re.fullmatch(r"\d{1,2}(?:\s*หน่วยกิต)?", text))


# โปรแกรมที่ยอมให้ "ช่องเลือก 1 จาก N ที่เล่มพิมพ์หน่วยกิตช่องเดียวคลุมทุกรหัส" ใช้เป็นหน่วยกิตของทุกรหัสในช่อง
SHARED_CELL_CREDIT_PROGRAMS: set[str] = {"DSBA"}


def _raw_table_shared_credit_map(md_text: str) -> dict[str, list[str]]:
    """รหัสที่อยู่ในเซลล์ 'A หรือ B' เซลล์เดียว โดยเล่มพิมพ์หน่วยกิตเซลล์เดียว (rowspan >= 2) คลุมทั้งช่อง

    พบจริงกับ DSBA: หน้า 36 มี <td rowspan="3">06026259<br/>หรือ 06026260</td> คู่กับ
    <td rowspan="3">6 (0-35-0)</td> -- หน่วยกิตพิมพ์ครั้งเดียวคลุมทั้งสหกิจศึกษาและสหกิจศึกษาต่างประเทศ
    _raw_table_credits_map() มองไม่เห็นเพราะ cell แรก 'ไม่ใช่รหัสเดี่ยว' จึงไม่มีทั้งสองรหัส
    (ตารางแผนหน้า 22 ก็พังคนละแบบ: รหัส 06026259 ติดคำว่า 'รหัสวิชา' และ 06026260 ไม่มีช่องหน่วยกิต)

    เข้มงวดโดยตั้งใจ: ต้องมีคำว่า 'หรือ' คั่นรหัสในเซลล์ และเซลล์หน่วยกิตต้อง rowspan >= 2 เท่านั้น
    ไม่ใช้กับเซลล์รหัสซ้อนหลายบรรทัดที่ไม่มีคำว่า 'หรือ' (เช่นกลุ่ม 06016416/417/418 ของ IT ที่แต่ละ
    ชื่อวิชามีหน่วยกิตจริงต่างกัน การแจกหน่วยกิตช่องเดียวให้ทุกรหัสจะผิด)
    """
    out: dict[str, list[str]] = {}
    for table in re.findall(r"<table>.*?</table>", md_text, flags=re.S):
        for row in re.findall(r"<tr>.*?</tr>", table, flags=re.S):
            cells = [(attrs, re.sub(r"<[^>]+>", " ", inner).strip())
                     for attrs, inner in re.findall(r"<t[dh]([^>]*)>(.*?)</t[dh]>", row, flags=re.S)]
            if len(cells) < 2:
                continue
            codes = re.findall(r"(?<!\d)\d{8}(?!\d)", cells[0][1])
            if len(set(codes)) < 2 or "หรือ" not in cells[0][1]:
                continue
            credit = next((txt for attrs, txt in reversed(cells[1:])
                           if _CREDIT_LIKE_RE.search(txt)
                           and int((re.search(r'rowspan="?(\d+)', attrs) or [0, 1])[1]) >= 2), "")
            if not credit:
                continue
            for code in dict.fromkeys(codes):
                out.setdefault(code, []).append(credit)
    return out


def merge_shared_cell_credits(raw_map: dict[str, list[str]] | None, md_text: str
                              ) -> dict[str, list[str]]:
    """เติมเฉพาะรหัสที่ _raw_table_credits_map() ไม่มีเลย -- ไม่แตะรหัสที่มีค่าอยู่แล้ว"""
    merged = {k: list(v) for k, v in (raw_map or {}).items()}
    for code, vals in _raw_table_shared_credit_map(md_text).items():
        merged.setdefault(code, vals)
    return merged


def repair_credits_from_raw_tables(
        courses: list[dict], raw_map: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
    """
    เติม/แก้หน่วยกิตของแถวที่น่าสงสัย (ว่าง หรือเลขเดี่ยวไม่มีวงเล็บ) ด้วยค่าที่ parse ได้จาก
    ตาราง <table> ดิบใน intermediate_vlm.md โดยตรง — ไม่พึ่งเลขรหัสที่ตรวจมือ/เทียบเฉลยไว้ล่วงหน้า
    (แทนที่ CREDITS_OVERRIDE เดิมสำหรับกรณีที่ยังอยู่ในตารางแผน — ดูคอมเมนต์ที่
    _raw_table_credits_map ว่าทำไมวิธีนี้ทนบั๊ก header พังได้)

    ไม่ครอบคลุมวิชาที่ไม่มีตำแหน่งในตารางแผนเลย (year=semester=0, มีแต่หน้าคำอธิบาย) เพราะ
    รหัสพวกนั้นไม่ได้อยู่ใน <table> ของเล่มตั้งแต่ต้น — ดู repair_hallucinated_default() แทน
    """
    notes: list[str] = []
    repaired: list[dict] = []
    for src in courses:
        row = dict(src)
        raw_code = str(row.get("code") or "").strip().upper()
        current = row.get("credits")
        if raw_code and _credits_needs_repair(current):
            candidates = raw_map.get(raw_code)
            if not candidates:
                # แถวที่ Lab 7B รวมรหัสไว้ในช่องเดียว เช่น "06026259 หรือ 06026260"
                parts = _lab7b_codes(raw_code)
                if len(parts) > 1:
                    candidates = [c for pc in parts for c in raw_map.get(pc, [])]
            if candidates:
                best = _pick_best_raw_credits(candidates)
                if best and best != current:
                    notes.append(
                        f"{raw_code}: หน่วยกิตจากตารางดิบ ({current!r}) น่าสงสัย — "
                        f"แทนที่ด้วย {best!r} ที่ parse ได้จาก <table> ดิบ intermediate_vlm.md "
                        f"โดยตรง (ไม่ใช่ค่าที่ตรวจมือ/เทียบเฉลยไว้ล่วงหน้า)")
                    row["credits"] = best
        repaired.append(row)
    return repaired, notes


_CREDITS_INFERRED_NOTE_RE = re.compile(r"หน่วยกิตอนุมาน|อนุมานจากเลขลำดับ")


# ── กู้คืนทางเลือกที่หายไปในกลุ่ม "เลือก 1 จาก N" จากตารางดิบ ─────────────────
# บั๊กที่พบจริงกับ DSBA (session ตรวจ code field): เล่มพิมพ์กลุ่มทางเลือกแบบ "06026xxx"
# เป็นแถวติดกันใต้รหัส wildcard เดียวกัน (rowspan) — เช่น ปีที่ 3/1: "วิชาเลือกกลุ่ม
# วิทยาการข้อมูล 1" / "วิชาเลือกกลุ่มการวิเคราะห์เชิงสถิติ 1" / "วิชาเลือกกลุ่มวิศวกรรมข้อมูล 1"
# สามแถวคือสามทางเลือกของช่องเดียวกัน แต่ Lab 7B เก็บมาได้แค่ทางเลือกแรก (วิทยาการข้อมูล) แล้ว
# ทิ้งอีกสองทางเลือกไปเงียบ ๆ ระหว่างขั้นตอนแปลง markdown -> JSON — ตรวจกับ eval_gt ของ DSBA แล้ว
# ว่านี่คือสาเหตุหลักของ code ที่หายไปจากผลสกัด (fn ส่วนใหญ่ของฟิลด์ code คือทางเลือกที่ 2/3 ของ
# กลุ่มพวกนี้ นับได้ 12 กลุ่ม/สล็อตทั่วเอกสาร) ข้อความของทุกทางเลือกยังอยู่ครบใน
# intermediate_vlm.md ตัวเดิม (ตรวจแล้วว่าไม่ได้หายจาก markdown เอง) จึงกู้คืนได้โดยอ่านข้อความ
# ที่มีอยู่แล้วมาเติม ไม่ใช่เดา/แต่งขึ้นใหม่
#
# ข้อควรระวัง: rowspan attribute ที่พิมพ์ไว้ *ไม่นิ่ง* — ตรวจแล้วว่าสำเนาตารางเดียวกันที่พิมพ์ซ้ำ
# สำหรับแผน nocoop กับแผน coop มีโครงสร้าง cell พังไม่เหมือนกัน (บางสำเนามี cell ว่าง/รหัสหลุด
# ตำแหน่งเพิ่มมาเมื่อเทียบกับอีกสำเนา) โค้ดด้านล่างนี้จึงไม่พึ่งค่า rowspan เลย ใช้ลำดับแถวแทน
# (แถวที่ cell แรกเป็นรหัสวิชา = เริ่มกลุ่มใหม่ แถวถัดไปที่ cell แรกไม่ใช่รหัส = ยังอยู่กลุ่มเดิม)
# และจับคู่หน่วยกิตด้วย "รูปแบบตัวเลข n(n-n-n) ที่เจอในกลุ่ม" แทนตำแหน่ง cell เพราะเฉลยยืนยันว่า
# ทุกทางเลือกในกลุ่มเดียวกันได้หน่วยกิตแบบรวมเดียวกันหมด (เช่น "3(3-0-6) หรือ 3(2-2-5)") ไม่ใช่
# คนละค่าตามทางเลือก

_ALT_GROUP_CREDIT_RE = re.compile(
    r"\d+\s*\(\s*(?:\d+|[xX]+)\s*-\s*(?:\d+|[xX]+)\s*-\s*(?:\d+|[xX]+)\s*\)")
_LATIN_NAME_RE = re.compile(r"[A-Z]{3,}[A-Z0-9 /\-]*")
# คำนำหน้า 'กลุ่มวิชาที่กำหนดโดยคณะ*' ที่ติดมาในเซลล์เดียวกับรหัส (เช่น 90644042) ไม่ใช่ส่วนของชื่อวิชา
_FACULTY_GROUP_PREFIX_RE = re.compile(r"^\s*กลุ่มวิชาที่กำหนดโดยคณะ\*?\s*")


def _looks_like_course_name_text(text: str) -> bool:
    """True ถ้าข้อความเป็น 'ชื่อไทย ... ENGLISH NAME' แบบเซลล์ชื่อวิชาจริง ไม่ใช่ป้ายกำกับ/
    ตัวคั่นอย่าง 'หรือ', 'รวม', หรือเซลล์ว่างที่หลุดมาจาก rowspan ที่พัง"""
    t = (text or "").strip()
    if not t or t in ("หรือ", "รวม"):
        return False
    return bool(re.search(r"[\u0E00-\u0E7F]", t)) and bool(_LATIN_NAME_RE.search(t))


def _split_thai_english_name(text: str) -> tuple[str, str | None]:
    """แยก 'ชื่อไทย ... ENGLISH NAME' ที่ต่อกันในเซลล์เดียว เป็น (name_th, name_en)

    หาโดยตำแหน่งที่ตัวอักษรละตินตัวใหญ่ยาว ๆ เริ่มต้น (เกณฑ์เดียวกับ _looks_like_course_name_text)
    ไม่ใช่การเดา — ทั้งสองส่วนเป็นข้อความดิบที่ตัดจากตำแหน่งเดิมในเซลล์ตรง ๆ
    """
    t = re.sub(r"\s+", " ", text or "").strip()
    m = _LATIN_NAME_RE.search(t)
    if not m:
        return t, None
    return t[:m.start()].strip(), t[m.start():].strip()


def _table_rows_cells(table_html: str) -> list[list[str]]:
    """แตกตารางดิบเป็นลิสต์ของแถว แต่ละแถวเป็นลิสต์ข้อความเซลล์ (ตัด tag ออกหมด รวม <br/>
    ที่กลายเป็นช่องว่างคั่น) — เหมือน _raw_table_credits_map แต่คืนทุกเซลล์ ไม่ใช่แค่ตัวแรก/
    ตัวสุดท้าย เพราะฟังก์ชันนี้ต้องอ่านชื่อวิชาทุกทางเลือกในกลุ่ม ไม่ใช่แค่รหัส/หน่วยกิต"""
    rows = []
    for row in re.findall(r"<tr>.*?</tr>", table_html, flags=re.S):
        cells = [re.sub(r"<[^>]+>", " ", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)]
        rows.append(cells)
    return rows


def _is_wildcard_or_code_token(text: str) -> bool:
    token = (text or "").strip().replace(" ", "").upper()
    if not token:
        return False
    if re.fullmatch(r"\d{8}", token):
        return True
    return bool(re.fullmatch(r"[0-9X]{4,8}", token) and "X" in token)


_LEADING_CODE_RE = re.compile(r"^\s*(\d{8}|[0-9Xx]{4,8})\b")


def _leading_code_and_rest(text: str) -> tuple[str, str] | None:
    """ถ้าเซลล์ขึ้นต้นด้วยรหัส/wildcard ตามด้วยข้อความอื่นต่อในเซลล์เดียวกัน (พบจริง: เซลล์
    '90644042 กลุ่มวิชาที่กำหนดโดยคณะ* ...' — โค้ดกับคำอธิบายติดกันในเซลล์เดียว ไม่แยกคอลัมน์)
    คืน (รหัส, ข้อความที่เหลือ) — ถ้าไม่ใช่แถวขึ้นต้นด้วยรหัสเลยคืน None

    สำคัญ: ถ้าไม่ตรวจกรณีนี้ แถวแบบนี้จะไม่ถูกมองว่าเป็นจุดเริ่มกลุ่มใหม่ (เพราะเซลล์แรกไม่ตรง
    รูปแบบรหัสล้วน ๆ) แล้วจะถูกยัดเข้ากลุ่มก่อนหน้าผิด ๆ ทำให้ทั้งรหัสและชื่อของกลุ่มก่อนหน้าปนกับ
    วิชาคนละตัว — ตรวจกับ DSBA แล้วว่าเกิดขึ้นจริงกับ 90644042
    """
    m = _LEADING_CODE_RE.match(text or "")
    if not m or not _is_wildcard_or_code_token(m.group(1)):
        return None
    return m.group(1), text[m.end():].strip()


# _PDF_PAGE_MARKER_RE ย้ายไปนิยามรวมกับ _iter_pages()/detect_sections() ด้านบนแล้ว

def _table_page_positions(md_text: str) -> list[tuple[int, int | None]]:
    """คืน [(ตำแหน่ง char ที่ <table> แต่ละใบเริ่มต้น, เลขหน้า PDF ของ marker ล่าสุดก่อนหน้า)]

    เอกสารพิมพ์ตารางเนื้อหาเดียวกันซ้ำคนละหน้าให้แผน nocoop/coop คนละสำเนา — ถ้าไม่รู้ว่ากำลัง
    อ่านตารางของสำเนาไหน แถวที่กู้คืนจะได้ source_page ผิดแผน แล้ว split_lab7b_by_plan() จะส่ง
    ไปแผนที่ผิดทั้งที่ตัวข้อความถูก (ดูคอมเมนต์ที่ recover_alt_group_siblings_from_raw_tables)
    """
    markers = [(m.start(), int(m.group(1))) for m in _PDF_PAGE_MARKER_RE.finditer(md_text)]
    out: list[tuple[int, int | None]] = []
    mi = 0
    current: int | None = None
    for tm in re.finditer(r"<table>", md_text):
        pos = tm.start()
        while mi < len(markers) and markers[mi][0] <= pos:
            current = markers[mi][1]
            mi += 1
        out.append((pos, current))
    return out


def recover_alt_group_siblings_from_raw_tables(
        courses: list[dict], md_text: str) -> tuple[list[dict], list[str]]:
    """
    เติมวิชาทางเลือกของกลุ่ม "เลือก 1 จาก N" ที่ Lab 7B เก็บมาได้แค่ทางเลือกแรกของกลุ่ม แล้ว
    ทิ้งทางเลือกที่เหลือไปเงียบ ๆ ระหว่างแปลง markdown -> JSON (ดูคอมเมนต์ก่อนหน้าฟังก์ชันนี้)

    ไม่เดา: ชื่อ (ไทย+อังกฤษ) ของทุกทางเลือกที่เติมมา คัดลอกมาจากข้อความที่มีอยู่แล้วใน
    intermediate_vlm.md ตรง ๆ ตำแหน่ง (ปี/เทอม/category/type) ก็คัดลอกจากทางเลือกพี่น้องกลุ่ม
    เดียวกันที่ Lab 7B เก็บมาได้แล้วจริงเท่านั้น (เลือกสำเนาที่อยู่หน้าใกล้กับตารางที่กำลังอ่าน
    ที่สุด ไม่ใช่สำเนาแรกที่เจอเฉย ๆ เพราะเนื้อหาเดียวกันพิมพ์ซ้ำคนละหน้าให้แผน nocoop/coop —
    ดูคอมเมนต์ที่ _table_page_positions) ส่วน source_page ของแถวที่กู้คืนใช้เลขหน้าของตารางที่
    เจอข้อความนั้นจริง ๆ ไม่ใช่เลขหน้าของต้นแบบ เพื่อให้ split_lab7b_by_plan() จัดแผนถูกทั้งสองข้าง
    ถ้าทั้งกลุ่มไม่มีทางเลือกไหนรอดเลย (ไม่มีต้นแบบให้คัดลอกตำแหน่งจาก) จะข้ามกลุ่มนั้นและ
    แจ้งเตือนแทนการเดาปี/เทอม/ประเภทเอาเอง

    คืนค่า (courses เดิม + แถวใหม่ที่กู้คืนมา, รายการโน้ตอธิบายว่ากู้คืนอะไรจากไหน)
    """
    notes: list[str] = []

    candidates_by_code_name: dict[tuple[str, str], list[dict]] = {}
    candidates_by_name_any_code: dict[str, list[dict]] = {}
    for c in courses:
        code_norm = str(c.get("code") or "").strip().replace(" ", "").upper()
        if not code_norm:
            continue
        name_norm = _normalize_name_th(str(c.get("name_th") or "").strip())
        candidates_by_code_name.setdefault((code_norm, name_norm), []).append(c)
        candidates_by_name_any_code.setdefault(name_norm, []).append(c)

    def closest_candidate(cands: list[dict], page: int | None) -> dict | None:
        if not cands:
            return None
        if page is None:
            return cands[0]
        def dist(c: dict) -> int:
            p = _lab7b_page(c)
            return abs(p - page) if p is not None else 10 ** 6
        return min(cands, key=dist)

    new_rows: list[dict] = []
    seen_new: set[tuple[str, str, int | None]] = set()
    group_counter = 0

    table_matches = list(re.finditer(r"<table>.*?</table>", md_text, flags=re.S))
    table_pages = dict(_table_page_positions(md_text))

    for tm in table_matches:
        table = tm.group(0)
        table_page = table_pages.get(tm.start())
        cur_code: str | None = None
        group_cells: list[str] = []
        # (ปี, เทอม) ของตารางนี้ = ค่าที่พบบ่อยสุดของแถวที่มีอยู่แล้วบนหน้าเดียวกันและรหัสอยู่ในตารางนี้
        _tcodes = set()
        for _r in _table_rows_cells(table):
            _l = _leading_code_and_rest(_r[0]) if _r else None
            if _l:
                _tcodes.add(_l[0].strip().replace(' ', '').upper())
        _ys = [(c.get('year'), c.get('semester')) for c in courses
               if table_page in _row_pages(c)
               and str(c.get('code') or '').strip().replace(' ', '').upper() in _tcodes
               and c.get('year') and c.get('semester')]
        table_ys = max(set(_ys), key=_ys.count) if _ys else None

        def flush_group() -> None:
            nonlocal group_counter
            if not cur_code or not group_cells:
                return
            seen_norm: set[str] = set()
            name_texts: list[str] = []
            for text in group_cells:
                if _looks_like_course_name_text(text):
                    norm = _normalize_name_th(_split_thai_english_name(text)[0])
                    if norm not in seen_norm:
                        seen_norm.add(norm)
                        name_texts.append(text)
            if len(name_texts) < 2:
                return  # ไม่ใช่กลุ่มทางเลือกหลายแบบจริง — ไม่มีอะไรต้องกู้

            credit_frags: list[str] = []
            for text in group_cells:
                for m in _ALT_GROUP_CREDIT_RE.finditer(text):
                    frag = re.sub(r"\s+", "", m.group(0))
                    if frag not in credit_frags:
                        credit_frags.append(frag)
            combined_credit = " หรือ ".join(credit_frags) if credit_frags else None

            code_norm = cur_code.strip().replace(" ", "").upper()

            # หา "ต้นแบบ" ตำแหน่ง (ปี/เทอม/category/type) จากทางเลือกในกลุ่มนี้ที่ Lab 7B เก็บมา
            # ได้แล้วจริง — เลือกสำเนาที่หน้าใกล้กับตารางที่กำลังอ่านที่สุด (ดู docstring ด้านบน)
            template: dict | None = None
            for text in name_texts:
                norm = _normalize_name_th(_split_thai_english_name(text)[0])
                found = closest_candidate(
                    candidates_by_code_name.get((code_norm, norm), []), table_page)
                if found is not None:
                    template = found
                    break

            group_counter += 1
            alt_group_id = f"raw_alt_recovered_{code_norm}_{group_counter}"

            for name_text in name_texts:
                name_th_part, name_en_part = _split_thai_english_name(name_text)
                norm = _normalize_name_th(name_th_part)
                # ทางเลือกนี้ Lab 7B เก็บมาแล้วจริงในสำเนาหน้านี้เอง (หรือใกล้ที่สุด) หรือยัง
                already = closest_candidate(
                    candidates_by_code_name.get((code_norm, norm), []), table_page)
                if already is not None and table_page in _row_pages(already):
                    continue  # มีอยู่แล้วตรงหน้านี้เป๊ะ — ไม่ต้องเติมซ้ำ
                elsewhere = [c for c in candidates_by_name_any_code.get(norm, [])
                             if str(c.get("code") or "").strip().replace(" ", "").upper()
                             != code_norm]
                if elsewhere:
                    # ชื่อนี้มีอยู่แล้วจริงในผลสกัด แต่อยู่ใต้รหัสอื่น — สัญญาณว่าการจัดกลุ่มแถว
                    # ของฟังก์ชันนี้พลาดในกรณีนี้ (พบจริง: ตารางที่โครงสร้าง rowspan พังจนรหัส
                    # ที่แท้จริงของแถวถัดไปหายไปเงียบ ๆ ทำให้แถวนั้นถูกนับรวมเป็นทางเลือกของกลุ่ม
                    # ก่อนหน้าผิด ๆ) ปลอดภัยกว่าคือข้ามไม่สร้างซ้ำ ไม่ใช่เดาว่ารหัสไหนถูก
                    notes.append(
                        f"{code_norm} (หน้า {table_page}): ข้าม {name_text!r} — มีอยู่แล้วจริงใน "
                        f"ผลสกัดภายใต้รหัส {elsewhere[0].get('code')!r} ไม่ใช่ {code_norm!r} "
                        f"(การจัดกลุ่มแถวของตารางดิบช่วงนี้น่าจะพังคนละแบบ — ไม่เดาว่ารหัสไหนถูก)")
                    continue
                if template is None:
                    notes.append(
                        f"{code_norm} (หน้า {table_page}): พบทางเลือกที่หายไป {name_text!r} "
                        f"ในตารางดิบ แต่ไม่มีทางเลือกอื่นในกลุ่มเดียวกันที่ Lab 7B เก็บมาได้เลย "
                        f"เพื่อใช้เป็นต้นแบบปี/เทอม/ประเภท — ข้ามแทนการเดาตำแหน่งเอง")
                    continue
                key = (code_norm, norm, table_page)
                if key in seen_new:
                    continue
                new_rows.append({
                    "code": cur_code,
                    "name_th": name_th_part,
                    "name_en": name_en_part,
                    "credits": combined_credit,
                    "year": (table_ys[0] if table_ys and table_page not in _row_pages(template)
                             else template.get("year")),
                    "semester": (table_ys[1] if table_ys and table_page not in _row_pages(template)
                                 else template.get("semester")),
                    "category": template.get("category"),
                    "type": template.get("type"),
                    "alt_group": alt_group_id,
                    "flexible_year_semester": template.get("flexible_year_semester"),
                    "note": (f"กู้คืนจากตารางดิบ intermediate_vlm.md ด้วย "
                             f"recover_alt_group_siblings_from_raw_tables — Lab 7B ไม่ได้แปลง "
                             f"แถวนี้เป็น JSON แม้ข้อความจะอยู่ในตารางจริง (ทางเลือกเดียวกับ "
                             f"{template.get('code')!r} {template.get('name_th')!r})"),
                    "source_page": table_page,
                })
                seen_new.add(key)
                notes.append(
                    f"{code_norm} (หน้า {table_page}): กู้คืนทางเลือก {name_th_part!r} "
                    f"({name_en_part!r}) จากตารางดิบ หน่วยกิต={combined_credit!r}")

        for row in _table_rows_cells(table):
            if not row:
                continue
            lead = _leading_code_and_rest(row[0])
            if lead:
                flush_group()
                cur_code, rest0 = lead
                rest0 = _FACULTY_GROUP_PREFIX_RE.sub("", rest0)
                group_cells = ([rest0] if rest0 else []) + list(row[1:])
            elif cur_code is not None:
                group_cells.extend(row)
        flush_group()

    return courses + new_rows, notes


def flag_inferred_credits_for_review(courses: list[dict]) -> list[str]:
    """
    [ไม่ได้ใช้งานแล้วใน split_lab7b_by_plan() — ดู null_inferred_credits() ด้านล่าง]

    รายงาน (ไม่แก้ค่า!) แถวที่ Lab 7B ประกาศเองใน note ว่าหน่วยกิต "อนุมาน" ไม่ได้อ่านจากเล่มตรง ๆ

    เดิมทีตรวจกับ BIT แล้วว่า *แก้ไม่ได้แบบทั่วไปด้วยการเดา*: กลุ่มนี้มีทั้งที่อนุมานถูก (เช่น
    06036115/128/129/133/136/140/141, 06036147/148 ที่ค่าตรงกับเฉลยอยู่แล้ว) และอนุมานผิด
    (06036134/135 ที่เฉลยจริงคือ "3(2-2-5)" ไม่ใช่ "3(3-0-6)" ที่อนุมานมา) โดยไม่มีสัญญาณอื่นใน
    ข้อมูลที่แยกสองกลุ่มนี้ออกจากกันได้เลย ตอนนั้นจึงเลือก "รายงานให้คนตรวจ" แทนการเดาไปทางใด
    ทางหนึ่ง (null หรือคงค่าไว้) — เก็บฟังก์ชันนี้ไว้เป็นข้อมูลอ้างอิง/เผื่อย้อนกลับมาใช้ ไม่ใช่
    ลบทิ้ง แต่ผู้ใช้ระบุนโยบายใหม่ชัดเจนแล้ว (ห้ามให้ไปป์ไลน์เดา/อนุมานเอง ไม่รู้แน่ชัดให้ null)
    จึงเปลี่ยนมาใช้ null_inferred_credits() แทนที่จุดเรียกใน split_lab7b_by_plan()
    """
    flagged = []
    for src in courses:
        note = str(src.get("note") or "")
        if _CREDITS_INFERRED_NOTE_RE.search(note):
            flagged.append(
                f"{src.get('code')}: หน่วยกิต {src.get('credits')!r} เป็นค่าที่ Lab 7B อนุมานเอง "
                f"(note={note!r}) ไม่ใช่ค่าที่อ่านจากเล่มตรง ๆ — ไม่มีกฎทั่วไปที่แยกได้ว่าอนุมานถูก "
                f"หรือผิด ต้องให้คนตรวจทีละแถว (ดู flag_inferred_credits_for_review docstring)")
    return flagged


def null_inferred_credits(courses: list[dict], keep: set[int] | None = None) -> tuple[list[dict], list[str]]:
    """
    ตั้งหน่วยกิตเป็น null ทุกแถวที่ Lab 7B ประกาศเองใน note ว่าหน่วยกิต "อนุมาน" มา ไม่ได้อ่าน
    จากเล่มตรง ๆ (แทนที่ flag_inferred_credits_for_review() ด้านบนซึ่งแค่รายงานแล้วปล่อยค่า
    อนุมานไว้เหมือนเดิม)

    นโยบาย (ระบุโดยผู้ใช้ชัดเจน ไม่ใช่กฎที่ derive มาจากข้อมูล): ไปป์ไลน์นี้ต้องไม่เดา/อนุมานค่า
    ที่ Lab 7B เองก็ไม่แน่ใจแทนผู้ใช้ — ถ้าไม่รู้แน่ชัดให้เป็น null แล้วให้คนตรวจภายหลัง ดีกว่าเก็บ
    ค่าที่เดามาซึ่งอาจถูกหรือผิดก็ได้โดยไม่มีทางแยกได้จากข้อมูลที่มี (ดู docstring ของ
    flag_inferred_credits_for_review สำหรับเหตุผลว่าทำไมแยกไม่ได้จริง ๆ — 06036128/06036134 มี
    note เดียวกันเป๊ะ แต่ค่าหนึ่งถูกอีกค่าหนึ่งผิด)

    รู้อยู่แล้วว่านโยบายนี้จะเสีย recall ของแถวที่บังเอิญอนุมานถูก (พบใน BIT ว่ามีมากกว่าที่แก้ไม่ได้
    จริง — ดู comment เดิม) แต่ผู้ใช้เลือกทางนี้แทนโดยรู้ trade-off แล้ว: precision/ความน่าเชื่อถือ
    ของค่าที่เก็บไว้สำคัญกว่าการเดาถูกบางส่วน credits ที่ถูก null ไปด้วยวิธีนี้ยังนับเป็น "รู้ปี/เทอม
    แต่ไม่รู้หน่วยกิต" เหมือนกรณีอื่นที่ _credit_parts() ล้มเหลว (ดู convert_lab7b) — วิชายังอยู่ใน
    แผนเหมือนเดิม เพียงไม่มีหน่วยกิตให้นับรวม ไม่ใช่ทิ้งทั้งแถว

    คืนค่า (courses ที่แก้แล้ว, รายการโน้ตอธิบายว่าแถวไหนถูกตั้งเป็น null และค่าเดิมคืออะไร
    เผื่อต้องตรวจย้อนหลังหรือย้อนกลับ)
    """
    notes: list[str] = []
    out: list[dict] = []
    for idx, src in enumerate(courses):
        row = dict(src)
        note = str(row.get("note") or "")
        if keep and idx in keep:
            out.append(row)       # เล่มพิมพ์ยอดรวมยืนยันค่านี้แล้ว (corroborated_inferred_credit_indexes)
            continue
        if _CREDITS_INFERRED_NOTE_RE.search(note):
            old = row.get("credits")
            if old not in (None, ""):
                notes.append(
                    f"{row.get('code')}: หน่วยกิต {old!r} เป็นค่าที่ Lab 7B อนุมานเอง "
                    f"(note={note!r}) ไม่ใช่ค่าที่อ่านจากเล่มตรง ๆ — ตั้งเป็น null ตามนโยบาย "
                    f"'ไม่รู้แน่ชัดห้ามเดา' (ค่าที่อนุมานมาก่อน null คือ {old!r})")
                row["credits"] = None
        out.append(row)
    return out, notes


# ── จัดกลุ่มทางเลือกของแผนหลังแปลง (ต้นเหตุ CHK1 เกินใน DSBA) ─────────────────────
# พบจริงกับ DSBA: CHK1 ได้ 156 (nocoop) / 159 (coop) แต่ประกาศ 132 เพราะ 2 เรื่อง
#   1) ช่องวิชาเลือกกลุ่ม "วิชาเลือกกลุ่ม<ก> n / <ข> n / <ค> n" ในเทอมเดียวกันคือ
#      "เลือก 1 จาก 3" แต่ไม่มี alt_group เลย (coop 3/2 ช่อง 4 มีครึ่งเดียว: recover_alt_group_
#      siblings_from_raw_tables ใส่กลุ่มให้เฉพาะพี่น้องที่กู้คืน ไม่ใส่ให้ "ต้นแบบ" ที่ Lab 7B
#      เก็บมาแล้วเอง) -> v_semester_credits นับทุกช่องแยกกัน
#   2) coop 4/2: 06026259 โผล่สองแถวในเทอมเดียวกัน (กลุ่มเดิม alt_y4s2_1 + แถวที่กู้คืนซ้ำ
#      ใต้กลุ่ม raw_alt_recovered_*) -> สหกิจ 6 หน่วยกิตถูกนับสองครั้ง
# ฟังก์ชันนี้แก้ที่ข้อมูลแผน (alt_group) ไม่แตะ CHK1 — CHK1 ต้องเป็นด่านตรวจอิสระต่อไป
_RECOVERED_ALT_PREFIX = "raw_alt_recovered_"
_MAJOR_ELECTIVE_SLOT_RE = re.compile(r"^วิชาเลือกกลุ่ม\s*(.+?)\s+(\d+)\s*$")


def split_cross_category_alt_groups(plan: list[dict]) -> list[str]:
    """แก้ plan (in-place): alt_group ที่สมาชิกมี category ต่างกัน -> แยกเป็นช่องวิชาเดี่ยว

    ทางเลือกจริง (เช่น สหกิจศึกษา / สหกิจศึกษาต่างประเทศ) อยู่ category เดียวกันเสมอ
    ส่วนกลุ่มที่ข้ามหมวด (ทั่วไป / เฉพาะ / เลือกเสรี) เกิดจาก Lab 7B อ่านเซลล์รหัสที่ merge
    ซ้อนกันหลายบรรทัด (เช่น BIT coop 3/2: 96643021 / 06036xxx / xxxxxx) เป็น "เลือกอย่างใดอย่างหนึ่ง"
    ทั้งที่เล่มพิมพ์เป็นสามช่องแยกกัน (รวมเทอม 15) ผลคือ CHK1 นับขาด 6 หน่วยกิต
    ปิดได้ด้วย LAB8_SPLIT_CROSS_CATEGORY_ALT=0
    """
    if os.environ.get("LAB8_SPLIT_CROSS_CATEGORY_ALT", "1").strip().lower() in ("0", "false", "no", "off"):
        return []
    members: dict[tuple, list[int]] = {}
    for i, row in enumerate(plan):
        ag = row.get("alt_group")
        if ag:
            members.setdefault((row["year"], row["semester"], str(ag)), []).append(i)
    notes: list[str] = []
    for (y, s, ag), idxs in sorted(members.items()):
        if len(idxs) < 2:
            continue
        cats = {str(plan[i].get("category") or "") for i in idxs}
        if len(cats) < 2:
            continue
        for i in idxs:
            plan[i]["alt_group"] = None
            if _ALT_NOTE_RE.search(str(plan[i].get("note") or "")):
                plan[i]["note"] = None
        notes.append(f"{y}/{s}: alt_group {ag!r} ข้าม {len(cats)} หมวด "
                     f"({', '.join(sorted(cats))}) -> แยกเป็น {len(idxs)} ช่องเดี่ยว")
    return notes



def normalize_plan_alternatives(plan: list[dict], course_by_code: dict[str, dict],
                                *, group_slots: bool | None = None) -> list[str]:
    """แก้ plan (in-place) ให้ทางเลือกที่เป็นตัวเลือกเดียวกันอยู่ใน alt_group เดียวกัน

    1) แถวเดียวกัน (ปี/เทอม/รหัส) ที่โผล่ซ้ำ โดยแถวหนึ่งเป็น alt_group ที่ถูกกู้คืน
       (raw_alt_recovered_*) -> ตัดแถวกู้คืนทิ้ง และย้ายพี่น้องของกลุ่มนั้นไปกลุ่มของแถวที่เหลือ
    2) ช่อง PLACEHOLDER ชื่อ "วิชาเลือกกลุ่ม<ชื่อกลุ่ม> <n>" ที่เทอมเดียวกัน เลข n เดียวกัน
       และมี "ชื่อกลุ่ม" ต่างกันตั้งแต่ 2 ชื่อขึ้นไป -> alt_group เดียวกัน
       (ไม่ทับ alt_group ที่ Lab 7B ให้มาเอง ยกเว้นกลุ่มที่ถูกกู้คืน)
       ปิดได้ด้วย LAB8_GROUP_ELECTIVE_SLOTS=0 (ข้อ 1 ทำงานเสมอ)

    คืนรายการโน้ตสำหรับใส่ warnings
    """
    notes: list[str] = []
    if group_slots is None:
        group_slots = os.environ.get("LAB8_GROUP_ELECTIVE_SLOTS", "1").strip().lower() \
            not in ("0", "false", "no", "off")

    # ── 1) แถวซ้ำที่เกิดจากการกู้คืน ────────────────────────────────
    by_key: dict[tuple, list[int]] = {}
    for i, row in enumerate(plan):
        by_key.setdefault((row["year"], row["semester"], row["code"]), []).append(i)
    drop: set[int] = set()
    regroup: dict[str, str] = {}
    for (y, s, code), idxs in by_key.items():
        if len(idxs) < 2:
            continue
        keep = [i for i in idxs
                if not str(plan[i].get("alt_group") or "").startswith(_RECOVERED_ALT_PREFIX)]
        extra = [i for i in idxs if i not in keep]
        if not keep or not extra:
            continue          # ซ้ำแบบอื่น (ไม่ใช่แถวกู้คืน) — ไม่แตะ ให้ CHK6 รายงานเอง
        survivor = plan[keep[0]]
        for i in extra:
            old = plan[i].get("alt_group")
            drop.add(i)
            if survivor.get("alt_group"):
                regroup[old] = survivor["alt_group"]
            else:
                survivor["alt_group"] = old      # ไม่ให้พี่น้องที่กู้คืนมากลายเป็นกลุ่มกำพร้า
            notes.append(
                f"{code} ({y}/{s}): ตัดแถวซ้ำที่กู้คืน (alt_group={old!r}) เพราะมีแถวเดียวกันอยู่แล้ว "
                f"(alt_group={survivor.get('alt_group')!r}) — ไม่งั้นนับหน่วยกิตสองครั้ง")
    if regroup:
        for row in plan:
            if row.get("alt_group") in regroup:
                row["alt_group"] = regroup[row["alt_group"]]
    if drop:
        plan[:] = [row for i, row in enumerate(plan) if i not in drop]

    # ── 2) ช่องวิชาเลือกกลุ่มเดียวกันข้ามกลุ่มวิชา ───────────────────
    if group_slots:
        buckets: dict[tuple, list[tuple[int, str]]] = {}
        for i, row in enumerate(plan):
            if not is_placeholder(row["code"]):
                continue
            ag = row.get("alt_group")
            if ag and not str(ag).startswith(_RECOVERED_ALT_PREFIX):
                continue      # Lab 7B จัดกลุ่มมาเองแล้ว — เชื่อค่าเดิม
            name = str((course_by_code.get(row["code"]) or {}).get("name_th") or "").strip()
            m = _MAJOR_ELECTIVE_SLOT_RE.match(name)
            if m:
                buckets.setdefault((row["year"], row["semester"], m.group(2)),
                                   []).append((i, m.group(1).strip()))
        for (y, s, n), members in sorted(buckets.items()):
            labels = sorted({lab for _, lab in members})
            if len(labels) < 2:
                continue      # มีชื่อกลุ่มเดียว ไม่ใช่ตัวเลือกข้ามกลุ่ม
            gid = f"major_elective_y{y}s{s}_slot{n}"
            old_ids = {plan[i]["alt_group"] for i, _ in members if plan[i].get("alt_group")}
            for i, _ in members:
                plan[i]["alt_group"] = gid
            for row in plan:
                if row.get("alt_group") in old_ids:
                    row["alt_group"] = gid
            notes.append(
                f"{y}/{s}: จัดช่องวิชาเลือกกลุ่มลำดับที่ {n} ({len(members)} ช่อง: "
                f"{', '.join(labels)}) เป็น alt_group เดียว {gid!r} — "
                f"สมมติฐาน 'เลือก 1 จาก {len(labels)} กลุ่ม' ตรวจกับตารางในเล่มก่อนใช้จริง")
    return notes


def convert_lab7b(data: dict, *, program: str | None = None,
                  section: str | None = None,
                  program_id: str | None = None,
                  program_name: str | None = None,
                  total_credits: int | None = None,
                  years: int | None = None) -> tuple[dict, dict]:
    """
    แปล schema ผลลัพธ์ Lab 7B เป็น Lab 8B ด้วยกฎคงที่ โดยไม่เรียก LLM

    หลักการเดียวของฟังก์ชันนี้คือ "ห้ามทำข้อมูลหายเงียบ"
    ทุกแถวของ Lab 7B ต้องลงเอยที่ใดที่หนึ่งเสมอ
        ปี/เทอมชัดเจน          -> plan
        ปี/เทอมยืดหยุ่น (0/0)   -> elective_slot พร้อม allowed_terms
        รหัส wildcard 90644xxx -> ช่องวิชา PLACEHOLDER_ ที่ยังนับหน่วยกิตได้
        อ่านหน่วยกิตไม่ออกจริง  -> warnings ใน conversion report
    """
    warnings: list[str] = []
    course_by_code: dict[str, dict] = {}
    course_fingerprints: dict[str, tuple] = {}
    plan: list[dict] = []
    prerequisites: list[dict] = []
    slot_by_code: dict[str, dict] = {}
    slot_fingerprints: dict[str, tuple] = {}
    seen_plan: set[tuple] = set()
    seen_pre: set[tuple] = set()
    wildcard_placeholders = 0
    flexible_slots = 0
    synth_alt_filler_rows = 0

    # ต้องดูทั้งชุดก่อนเข้าลูปหลัก เพราะสัญญาณของแถวสังเคราะห์คือ "สมาชิก alt_group
    # เดียวกันชื่อซ้ำกันหมด" (ดูคอมเมนต์ที่ _is_synth_alt_filler) — เช็คทีละแถวระหว่างลูป
    # หลักไม่พอ ต้องรู้ชื่อของเพื่อนร่วม alt_group ทุกตัวก่อน
    alt_group_names: dict[str, set[str]] = {}
    for src0 in (data.get("courses") or []):
        ag0 = src0.get("alt_group")
        if not ag0:
            continue
        alt_group_names.setdefault(str(ag0), set()).add(
            _normalize_name_th(str(src0.get("name_th") or "").strip()))

    # รหัสที่มีตำแหน่งปี/เทอมจริงในแผน (ใช้ตัดสินว่าวิชา year 0 เป็นวิชาเลือกล้วนหรือไม่)
    _scheduled_codes: set[str] = set()
    for _s in data.get("courses") or []:
        try:
            _y, _t = int(_s.get("year")), int(_s.get("semester"))
        except (TypeError, ValueError):
            continue
        if 1 <= _y <= 8 and 1 <= _t <= 3:
            _scheduled_codes.update(_lab7b_codes(str(_s.get("code") or "")))

    for index, src in enumerate(data.get("courses") or []):
        raw_code = str(src.get("code") or "").strip()
        codes = _lab7b_codes(raw_code)
        page = _lab7b_page(src)
        pages = _lab7b_pages(src)
        category = _normalize_category(
            str(src.get("category")).strip() if src.get("category") else None)
        ctype = str(src.get("type")).strip() if src.get("type") else None
        note = str(src.get("note")).strip() if src.get("note") else None

        try:
            year_probe = int(src.get("year"))
            sem_probe = int(src.get("semester"))
        except (TypeError, ValueError):
            year_probe = sem_probe = 0

        if _is_known_bad_fabricated_row(program, year_probe, sem_probe, page, note):
            # ข้ามแถวนี้ทั้งแถว — Lab 7B ประกาศเองว่าแถวนี้ไม่ได้มาจาก OCR แต่อนุมานจากยอด
            # หน่วยกิต และตรวจมือแล้วว่าอนุมานผิด (ดูคอมเมนต์ที่ FABRICATED_ROW_OVERRIDE)
            warnings.append(
                f"courses[{index}] {raw_code}: ข้ามแถว — ตรงกับ FABRICATED_ROW_OVERRIDE "
                f"(ปี {year_probe}/{sem_probe} หน้า {page}: แถวอนุมานที่ตรวจแล้วว่าผิด)")
            continue

        if _is_junk_ocr_placeholder_row(raw_code, src.get("name_th")):
            # ข้ามแถวนี้ทั้งแถว — ชื่อคือ "รหัส + หน่วยกิต" ที่หลุดมาจากตาราง ไม่ใช่ชื่อวิชาจริง
            # (ดูคอมเมนต์ที่ _is_junk_ocr_placeholder_row)
            warnings.append(
                f"courses[{index}] {raw_code}: ข้ามแถว — name_th={src.get('name_th')!r} "
                f"เป็นรูปแบบ 'รหัส+หน่วยกิต' ที่หลุดจากตาราง ไม่ใช่ชื่อวิชาจริง")
            continue

        if _is_synth_alt_filler(raw_code, note, src.get("alt_group"), alt_group_names):
            # ข้ามแถวนี้ทั้งแถว — "ตัวรหัส" ที่มันอ้างถึง (96643021, 06036xxx, ...) ยังนับได้
            # ตามจริงจากแถวอื่นที่เป็นข้อมูลจริงของรหัสนั้น (ถ้ามีอยู่ในเล่ม/section เดียวกัน)
            # แถวนี้เองไม่มีข้อมูลจริงอะไรให้เก็บ มีแต่ชื่อ/หน่วยกิตที่ยืมมาจากทั้งกลุ่ม
            synth_alt_filler_rows += 1
            warnings.append(
                f"courses[{index}] {raw_code}: ข้ามแถว — เป็นตัวเลือกที่สังเคราะห์จากโน้ต "
                f"{note!r} (ชื่อ/หน่วยกิตซ้ำกับตัวเลือกอื่นในกลุ่มเดียวกันทั้งหมด ไม่ใช่ข้อมูล "
                f"จริงของรหัสนี้โดยเฉพาะ)")
            continue

        is_slot = False
        if not codes:
            placeholder = _placeholder_code(raw_code)
            if placeholder is None:
                warnings.append(f"courses[{index}] รหัส {raw_code!r} "
                                f"ไม่ใช่เลข 8 หลักและไม่ใช่ wildcard; ข้ามรายการ")
                continue
            codes = [placeholder]
            is_slot = True
            wildcard_placeholders += 1
            warnings.append(f"{raw_code}: เก็บเป็นช่องวิชา {placeholder} "
                            f"เพื่อให้หน่วยกิตยังถูกนับ (ถามรายละเอียดวิชาไม่ได้)")

        raw_credits = src.get("credits")
        # CREDITS_OVERRIDE ปิดใช้งานแล้ว — แทนที่ด้วย repair_credits_from_raw_tables() /
        # repair_hallucinated_default() ที่รันมาก่อนหน้านี้ใน split_lab7b_by_plan() แล้ว
        # (กฎทั่วไป ไม่ใช่ตารางรหัสที่ตรวจมือ/เทียบเฉลย)

        try:
            credit, lecture, lab, self_h = _credit_parts(raw_credits)
        except ValueError as exc:
            try:
                y0, s0 = int(src.get("year")), int(src.get("semester"))
            except (TypeError, ValueError):
                y0 = s0 = 0
            if 1 <= y0 <= 8 and 1 <= s0 <= 3:
                # เดิม: ข้าม (continue) ทิ้งทั้งวิชาเงียบๆ เมื่ออ่านหน่วยกิตไม่ออก แม้ปี/เทอม
                # จะชัดเจน — ขัดกับหลักการของฟังก์ชันนี้เอง ("ห้ามทำข้อมูลหายเงียบ")
                # พบจริงกับวิชาปี 1/1 ที่มี credits=null จาก Lab 7B (เช่น 06036100, 06036101,
                # 96641001, 96641003): ทั้งวิชาหายไปจาก courses/plan ทั้งที่ปี/เทอมรู้แน่นอน
                # ตอนนี้เก็บวิชาไว้ในแผนเหมือนเดิม เพียงไม่มีหน่วยกิตให้นับรวม (จะทำให้ยอดรวม
                # ของเทอมนั้นนับได้น้อยกว่าจริงถ้าไม่ได้ระบุ --total-credits เอง แต่ดีกว่าวิชา
                # หายไปทั้งตัวจากทุกที่ รวมถึงตอน eval-gt ที่จะเห็นเป็น fn ของทุกฟิลด์)
                credit = lecture = lab = self_h = None
                warnings.append(f"courses[{index}] {exc}; เก็บวิชาไว้ในแผนโดยไม่มีหน่วยกิต")
            else:
                # วิชาเลือกที่ไม่ผูกปี/เทอม (รวมวิชาที่มีแต่ในหน้าคำอธิบาย) ไม่กระทบยอดหน่วยกิตของแผน
                # เก็บไว้โดยไม่มีหน่วยกิต เพื่อให้ตอบ "วิชานี้คืออะไร/บังคับก่อนอะไร" ได้ (ห้ามทำข้อมูลหายเงียบ)
                credit = lecture = lab = self_h = None
                warnings.append(f"{raw_code}: {exc}; เก็บวิชาไว้โดยไม่มีหน่วยกิต")
        credits_text = None
        if "หรือ" in str(src.get("credits") or ""):
            warnings.append(f"{raw_code}: หน่วยกิตมีหลายแบบ; ตัวเลขใช้แบบแรก เก็บข้อความเต็มใน credits_text")
            credits_text = re.sub(r"\s+", " ", str(src.get("credits")).strip())

        try:
            year = int(src.get("year"))
            semester = int(src.get("semester"))
        except (TypeError, ValueError):
            year = semester = 0

        if program in RAW_TABLE_RECOVERY_PROGRAMS:
            code_u = raw_code.replace(" ", "").upper()
            # ตาราง DSBA ไม่มีหัวข้อหมวด — รหัส 06… คือหมวดวิชาเฉพาะ (เฉลยยืนยัน)
            if category is None and code_u.startswith("06"):
                category = "หมวดวิชาเฉพาะ"
            # วิชา 06026… ที่ไม่มีตำแหน่งปี/เทอมในแผนเลย = อยู่ใต้ 'กลุ่มวิชาชีพเฉพาะด้าน - กลุ่ม…'
            # ซึ่งเป็นวิชาเลือกทั้งหมด (หัวกลุ่มวิศวกรรมข้อมูลไม่มีคำว่า 'เลือก' ทำให้ default เป็นบังคับ)
            if (not (1 <= year <= 8 and 1 <= semester <= 3) and code_u.startswith("06026")
                    and not any(c in _scheduled_codes for c in codes) and ctype != "เลือก"):
                ctype = "เลือก"

        force_elective_codes = FORCE_ELECTIVE_TYPE_OVERRIDE.get(
            program or "", {}).get(section or "", set())
        if force_elective_codes and any(c in force_elective_codes for c in codes):
            # เฉลยทั้งสองแผนยืนยันตรงกันว่าวิชานี้เป็น "เลือก" ไม่ผูกปี/เทอมตายตัว แม้เล่มจะ
            # พิมพ์ตำแหน่งไว้ชัดเจนในตารางแผนก็ตาม (ดูคอมเมนต์ที่ FORCE_ELECTIVE_TYPE_OVERRIDE
            # ด้านบน — ตรวจกับ pred_vlm.json แล้วว่าไม่ใช่ OCR อ่านผิด) บังคับให้ตกไปเป็น
            # elective_slot แทนแถว plan ที่ตำแหน่งตายตัว และปรับ type ให้ตรงกับเฉลย
            warnings.append(
                f"{raw_code}: บังคับเป็นวิชาเลือกไม่ผูกปี/เทอมตาม FORCE_ELECTIVE_TYPE_OVERRIDE "
                f"(เล่มพิมพ์ปี {year}/{semester} type={ctype!r} แต่เฉลยทั้งสองแผนไม่ตรงกับตำแหน่งนี้)")
            year = semester = 0
            ctype = "เลือก"
            if (program or "", section or "") in FORCED_ELECTIVE_COUNTED_IN_TOTAL:
                note = (f"{note} " if note else "") + FORCED_ELECTIVE_COUNTED_MARK

        flexible = str(src.get("flexible_year_semester") or "").strip() or None

        # รหัส wildcard เดียวกัน (เช่น 90644xxx) โผล่คนละปี/เทอมได้จริง = คนละวิชา
        # ต้องเช็ค fingerprint (ชื่อ+ปี+เทอม) ก่อนรวม ไม่ใช่ dict merge ตรงๆ — ใช้ helper
        # เดียวกับ _index_by_code() ที่ฝั่ง eval-gt ใช้ (ดูคอมเมนต์ที่ _dedup_insert)
        # มิฉะนั้นวิชาที่ 2/3/4 จะถูกทับเงียบๆ ตั้งแต่ขั้น convert ก่อน eval จะได้เห็นด้วยซ้ำ
        resolved_codes: list[str] = []
        for code in codes:
            candidate = {
                "code": code,
                "name_th": _normalize_name_th(
                    str(src.get("name_th") or raw_code or code).strip()),
                "name_en": (str(src["name_en"]).replace("\n", " ").strip()
                            if src.get("name_en") else None),
                "credits": credit,
                "credits_text": credits_text,
                "lecture_h": lecture,
                "lab_h": lab,
                "self_h": self_h,
                "description_th": src.get("description_th"),
                "pages": pages,
            }
            fp = (candidate["name_th"], str(year), str(semester))
            resolved_codes.append(
                _dedup_insert(course_by_code, course_fingerprints, code, fp, candidate))

        if not (1 <= year <= 8 and 1 <= semester <= 3):
            # ── ปี/เทอมไม่ชัดเจน — เก็บเป็น elective_slot แทนการทิ้ง ──────
            #    เดิมโค้ดนับ skipped_flexible แล้วปล่อยผ่าน ทำให้วิชาเลือกกว่า
            #    30 วิชาหายไปทั้งกลุ่ม พอมีคนถาม "06026240 เรียนได้ตอนไหน"
            #    ระบบตอบว่าไม่พบ ทั้งที่เล่มเขียนไว้ว่า 3/1, 3/2 หรือ 4/1
            flexible_slots += 1
            for code in resolved_codes:
                slot = {
                    "code": code,
                    "allowed_terms": flexible,
                    "name_th": _normalize_name_th(
                        str(src.get("name_th") or "").strip() or None),
                    "credits": credit,
                    "credits_text": credits_text,
                    "category": category,
                    "type": ctype,
                    "note": note,
                    "pages": pages,
                }
                fp = (slot["name_th"] or "", str(flexible or ""))
                _dedup_insert(slot_by_code, slot_fingerprints, code, fp, slot)
            if not flexible:
                warnings.append(
                    f"{raw_code}: ปี/เทอม={year}/{semester} และไม่มี "
                    f"flexible_year_semester; เก็บเป็นวิชาเลือกที่ไม่ระบุเทอม")
        else:
            # alt_group จาก Lab 7B (สหกิจ "A หรือ B" ที่แยกเป็นสองแถวแล้ว) มาก่อน
            # ถ้าไม่มีค่อยใช้กฎเดิม: แถวเดียวที่มีหลายรหัส "A หรือ B"
            alt_group = (str(src["alt_group"]).strip() if src.get("alt_group")
                         else (f"lab7b_alt_{index}" if len(resolved_codes) > 1 else None))
            # PlanItem.credits เป็น int บังคับ (ห้าม None) ต่างจาก Course.credits ที่เป็น
            # None ได้ — วิชาที่อ่านหน่วยกิตไม่ออก (ดูคอมเมนต์ตอน except ValueError ด้านบน)
            # จึงใส่ 0 เป็นตัวยึดที่นี่แทน (แจ้งเตือนไว้แล้วว่ายอดรวมเทอมนี้จะนับได้น้อยกว่า
            # จริง) ส่วนวิชาในแคตตาล็อก (course_by_code) ยังคง credits=None ตามจริง
            plan_credit = credit if credit is not None else 0
            for code in resolved_codes:
                key = (year, semester, code, alt_group)
                if key not in seen_plan:
                    plan.append({"year": year, "semester": semester,
                                 "code": code, "credits": plan_credit,
                                 "alt_group": alt_group,
                                 "category": category, "type": ctype,
                                 "note": note, "pages": pages})
                    seen_plan.add(key)
                elif is_slot:
                    # ช่องวิชาเดียวกันปรากฏซ้ำในภาคเดียวกัน (เช่น วิชาภาษา 2 ช่อง)
                    # ต้องแยกรหัสไม่ให้ชนกัน ไม่งั้น CHK6 จะเตือนว่าวิชาซ้ำ
                    #
                    # เดิมเช็คแค่ seen_plan (year,semester,code,alt_group) แต่ _dedup_insert()
                    # ก็ใช้ suffix _2/_3/... เดียวกันนี้กับ course_by_code จากคนละเงื่อนไข (ต่างปี/เทอม)
                    # ถ้าเช็คแค่ seen_plan อาจเลือก n ที่ _dedup_insert() จับจองไปแล้วใน course_by_code
                    # แล้วเขียนทับวิชาคนละตัวเงียบๆ ตรงนี้ — ต้องเช็ค course_by_code ด้วยเสมอ
                    n = 2
                    while ((year, semester, f"{code}_{n}", alt_group) in seen_plan
                           or f"{code}_{n}" in course_by_code):
                        n += 1
                    dup_code = f"{code}_{n}"
                    course_by_code[dup_code] = dict(course_by_code[code],
                                                    code=dup_code)
                    # ลงทะเบียน fingerprint ของ dup_code ด้วย ไม่งั้น _dedup_insert() ในรอบถัดไป
                    # จะเห็น fingerprints.get(dup_code) เป็น None แล้วเข้าใจว่า "ช่องว่าง" ยอมทับ/รวมได้
                    course_fingerprints[dup_code] = (
                        course_by_code[dup_code].get("name_th"), str(year), str(semester))
                    plan.append({"year": year, "semester": semester,
                                 "code": dup_code, "credits": plan_credit,
                                 "alt_group": alt_group,
                                 "category": category, "type": ctype,
                                 "note": note, "pages": pages})
                    seen_plan.add((year, semester, dup_code, alt_group))

        pre_codes = _lab7b_codes(src.get("prerequisite"))
        for code in resolved_codes:
            if is_placeholder(code):
                continue            # ช่องวิชาไม่มีเงื่อนไขรายวิชาของตัวเอง
            for required in pre_codes:
                if required == code:
                    warnings.append(f"{code}: ข้าม prerequisite ที่อ้างถึงตัวเอง")
                    continue
                key = (code, required, "pre")
                if key not in seen_pre:
                    prerequisites.append({"code": code, "requires": required,
                                          "kind": "pre"})
                    seen_pre.add(key)

    warnings.extend(normalize_plan_alternatives(plan, course_by_code))
    warnings.extend(split_cross_category_alt_groups(plan))
    warnings.extend(apply_term_alt_merge_override(plan, program))

    max_year = max((p["year"] for p in plan), default=4)
    effective_years = years or max_year
    if total_credits is None and isinstance(data.get("total_credits"), int):
        # ยอด "รวมตลอดหลักสูตร N หน่วยกิต" ที่ Lab 7B อ่านจากเล่มจริง (ถ้าเจอค่าเดียว)
        # ใช้เป็นค่าประกาศ แทนการคำนวณจากแผนเอง ซึ่งทำให้ CHK1 ผ่านเสมอไม่ว่าอ่านผิดแค่ไหน
        total_credits = data["total_credits"]
    if total_credits is None:
        groups: dict[tuple, int] = {}
        for i, item in enumerate(plan):
            group = item.get("alt_group") or f"row_{i}"
            groups[(item["year"], item["semester"], group)] = item["credits"]
        # บางแถวตอนนี้เก็บ credits=None ไว้แทนการทิ้งวิชาทั้งตัว (ดูคอมเมนต์ที่ except
        # ValueError ด้านบน) — กันไม่ให้ sum() พังตอนไม่ได้ระบุ --total-credits เอง
        unknown_credit_groups = sum(1 for v in groups.values() if v is None)
        total_credits = sum(v for v in groups.values() if isinstance(v, int))
        if unknown_credit_groups:
            warnings.append(
                f"{unknown_credit_groups} รายการในแผนไม่มีหน่วยกิต (อ่านจากเล่มไม่ออก) "
                "จึงไม่ถูกนับรวมในยอดที่คำนวณนี้ — ยอดจริงน่าจะมากกว่านี้")
        warnings.append(f"ไม่ได้ระบุ --total-credits; คำนวณจากแผนที่แปลได้ = {total_credits}")
    if not plan and not total_credits:
        # แคตตาล็อกวิชา (เช่น GENED): ทุกแถวเป็นวิชาเลือกที่ไม่ผูกปี/ภาค จึงไม่มีแผนให้รวมหน่วยกิต
        # ห้ามเดาตัวเลขหลักสูตร — เก็บ 0 ไว้ตรง ๆ แล้วให้ CHK1 ข้ามการเทียบ
        total_credits = 0
        warnings[:] = [w for w in warnings if not w.startswith("ไม่ได้ระบุ --total-credits")]
        warnings.append("ไม่มีแผนรายเทอมเลย (แคตตาล็อกวิชา): total_credits=0 และไม่ตรวจช่วง 30..300")
    elif not 30 <= total_credits <= 300:
        raise ValueError(f"หน่วยกิตรวม {total_credits} อยู่นอกช่วง 30..300; "
                         "ระบุ --total-credits จากเล่มหลักสูตร")

    pid = str(program_id or data.get("program") or "curriculum").strip()
    result = {
        "program": {
            "program_id": pid,
            "name_th": str(program_name or data.get("program") or pid).strip(),
            "name_en": None,
            "degree": None,
            "total_credits": total_credits,
            "years": effective_years,
        },
        "courses": list(course_by_code.values()),
        "plan": plan,
        "prerequisites": prerequisites,
        "elective_slots": list(slot_by_code.values()),
    }
    Curriculum = build_models()
    result = Curriculum.model_validate(result).model_dump()
    with_page = sum(1 for c in result["courses"] if c.get("pages"))
    report = {
        "source_courses": len(data.get("courses") or []),
        "converted_courses": len(result["courses"]),
        "plan_items": len(result["plan"]),
        "prerequisites": len(result["prerequisites"]),
        "elective_slots": len(result["elective_slots"]),
        # เดิมสองตัวนี้คือ "จำนวนข้อมูลที่ทิ้ง" ตอนนี้คือ "จำนวนข้อมูลที่กู้ไว้ได้"
        "wildcard_placeholders": wildcard_placeholders,
        "flexible_courses_kept": flexible_slots,
        "synth_alt_filler_rows_skipped": synth_alt_filler_rows,
        "courses_with_source_page": with_page,
        "courses_without_source_page": len(result["courses"]) - with_page,
        "warnings": warnings,
    }
    if with_page == 0 and result["courses"]:
        report["warnings"].append(
            "ไม่มีวิชาใดมี source_page/pages เลย — pred JSON นี้สร้างจาก Lab 7B เวอร์ชันเก่า "
            "(ก่อนแนบเลขหน้า) ให้รัน lab7b_curriculum.py ใหม่ด้วย --pipeline vlm")
    return result, report


def plan_sections(program: str | None, text: str | None = None
                  ) -> dict[str, tuple[int, int]]:
    """section แผนการศึกษา (nocoop/coop) — ว่างถ้าโปรแกรมมีแผนเดียว (หรือไม่มีแผนเลย)

    ถ้ามี text (Markdown ต้นทางของโปรแกรมนี้) จะจับ nocoop/coop จากป้ายหัวข้อในเนื้อหาเอง
    ด้วย detect_sections() — ไม่ใช้ตาราง PROGRAM_PAGE_RANGES เลย
    ถ้าไม่มี text (เช่นตอนมีแค่ pred JSON จาก Lab 7B ไม่มี markdown ดิบให้สแกน) จะถอยไปใช้
    ตาราง PROGRAM_PAGE_RANGES เป็น fallback แบบเดิม
    """
    if text is not None:
        try:
            ranges = detect_sections(text)
        except ValueError:
            ranges = {}
    else:
        ranges = PROGRAM_PAGE_RANGES.get(program or "", {})
    return {k: v for k, v in ranges.items() if k in ("nocoop", "coop")}


# วิชาที่รู้อยู่แล้วว่าอยู่ในทั้งสองแผน (nocoop/coop) ของหลักสูตรจริง แต่เล่มพิมพ์ตาราง
# ของวิชานั้นไว้เพียงครั้งเดียว (ต่างจากวิชาส่วนใหญ่ที่พิมพ์ตารางซ้ำคนละหน้าในแต่ละแผน)
# split_lab7b_by_plan() ที่จำแนกด้วยเลขหน้าอย่างเดียวจึงเห็นวิชาพวกนี้อยู่แผนเดียว —
# เจอจริงกับ BIT ปี 3 เทอม 2 (06036145/06036146): ตารางพิมพ์บนหน้า 29 (อยู่ในช่วง nocoop)
# เท่านั้น แต่ทั้ง BIT_academic_plan_no_coop.json และ BIT_academic_plan_coop.json ยืนยันว่า
# วิชาทั้งสองอยู่ในแผนทั้งคู่ — override นี้บังคับให้รหัสที่ระบุไปอยู่ทุก section เสมอ
# ไม่ว่าเลขหน้าจะบอกว่าอย่างไร (ทางแก้ที่ถูกกว่าแต่หยาบกว่าการตรวจหัวข้อ "แผนการศึกษา...
# ไม่ใช่สหกิจ/สหกิจศึกษา" จริงในเนื้อหา — ดู handoff เรื่อง Bug 2)
# รายชื่อนี้ตรวจด้วยมือทีละโปรแกรม ยังไม่ได้ตรวจ IT/DSBA ว่ามี pattern เดียวกันหรือไม่
# แม้จะมีโครงสร้างช่วงหน้า nocoop/coop เหมือนกัน
SHARED_ACROSS_PLANS: dict[str, set[str]] = {
    "BIT": {"06036145", "06036146"},
}


def _row_pages(src: dict) -> list[int]:
    """เลขหน้า PDF จริงทั้งหมดที่แนบมากับแถวของ Lab 7B (ว่าง = ไม่รู้)"""
    raw = None
    for key in ("pages", "source_page", "page", "page_no", "page_number"):
        if src.get(key) not in (None, "", []):
            raw = src[key]
            break
    if raw is None:
        return []
    out: set[int] = set()
    for item in (raw if isinstance(raw, list) else [raw]):
        m = re.search(r"\d+", str(item))
        if m:
            out.add(int(m.group()))
    return sorted(out)


def _enrich_alt_group_fillers(courses: list[dict]) -> tuple[list[dict], list[str]]:
    """
    กฎ: ก่อนแยกเป็น nocoop/coop ให้เติมข้อมูลจริงของรหัสให้แถว "ตัวเลือกสังเคราะห์"
    (แถวที่ Lab 7B แตกจากโน้ต "เลือกอย่างใดอย่างหนึ่ง: A หรือ B หรือ C" แล้วยัดชื่อกลุ่ม/
    หน่วยกิตซ้ำกันทุกแถว — ดูคอมเมนต์ที่ _is_synth_alt_filler) โดยค้นหาข้อมูลจริงจาก "ทั้งเล่ม"
    ไม่ใช่แค่หน้าที่แถวสังเคราะห์นั้นอยู่ — เพราะข้อมูลจริงกับโน้ตอาจพิมพ์อยู่คนละหน้า/คนละแผน

    บั๊กที่พบจริง (BIT ปี 3 เทอม 2): 96643021 "ผู้ประกอบการสมัยใหม่" ตัวจริงพิมพ์อยู่หน้า 29
    (แผน nocoop) เพียงหน้าเดียว ส่วนโน้ต "เลือกอย่างใดอย่างหนึ่ง: 96643021 หรือ 06036xxx หรือ
    xxxxxxxx" พิมพ์อยู่หน้า 34 (แผนสหกิจ) เท่านั้น พอ split_lab7b_by_plan() แยกตามหน้าแล้วส่ง
    ไปแปลงทีละ section, ฝั่ง coop ไม่มีแถวจริงของ 96643021 ให้อ้างอิงในตัวมันเองเลย
    _is_synth_alt_filler() (ที่ convert_lab7b เรียกทีหลัง) จึงทิ้งทั้งกลุ่ม (96643021, 06036xxx,
    xxxxxxxx) หายไปจากแผนสหกิจทั้งที่เฉลยยืนยันว่าต้องอยู่ (ตรวจกับ eval-gt แล้วเห็น fn=3 ตรงเป๊ะ)

    กติกา:
      1. รหัสใดมี "แถวจริง" อยู่ที่ใดก็ได้ในเล่ม (ไม่มี alt_group เลย หรือมี alt_group แต่ชื่อ
         ไม่ซ้ำกับเพื่อนร่วมกลุ่ม — เกณฑ์เดียวกับ _is_synth_alt_filler) ให้ถือเป็นต้นแบบ
      2. แถวสังเคราะห์ที่มีรหัสตรงกับต้นแบบ -> คัดลอก name_th/name_en/credits/category/type
         จากต้นแบบมาทับ คง alt_group/note/pages/source_page ของแถวสังเคราะห์ไว้เดิม (ยังรู้ว่า
         อยู่หน้าไหนของ section ที่กำลังแปลงอยู่)
      3. ผลข้างเคียงที่ตั้งใจ: เมื่อสมาชิกกลุ่มหนึ่งถูกเติมชื่อจริงแล้ว ชื่อในกลุ่มจะไม่ซ้ำกันอีก
         ต่อไป -> เงื่อนไขข้อ 2 ของ _is_synth_alt_filler (ชื่อซ้ำกันหมดทั้งกลุ่ม) จะไม่เป็นจริง
         อีกต่อไป -> ทั้งกลุ่มเปลี่ยนจาก "ถูกทิ้ง" เป็น "เก็บเป็นแถวจริง" โดยไม่ต้องแก้
         convert_lab7b/_is_synth_alt_filler เลย
      4. รหัสที่หาแถวจริงไม่เจอเลยในเล่ม (เช่น wildcard ที่ไม่มีคำอธิบายเดี่ยว ๆ ของตัวเอง)
         -> ปล่อยผ่านเหมือนเดิม ให้ _is_synth_alt_filler ตัดสินใจต่อตามกฎเดิม
      5. ฟังก์ชันนี้ถูกเรียกจาก split_lab7b_by_plan() เท่านั้น ซึ่งถูกข้ามไปเลยสำหรับโปรแกรม
         ที่ไม่มี nocoop/coop (AIT, GENED — ดู plan_sections()); เมื่อ sections ว่าง
         _import_split() ไม่เรียก split_lab7b_by_plan() เลย จึงไม่กระทบ AIT/GENED
    """
    alt_group_names: dict[str, set[str]] = {}
    for src in courses:
        ag = src.get("alt_group")
        if ag:
            alt_group_names.setdefault(str(ag), set()).add(
                _normalize_name_th(str(src.get("name_th") or "").strip()))

    def is_filler(src: dict) -> bool:
        ag = src.get("alt_group")
        return bool(ag) and len(alt_group_names.get(str(ag), ())) == 1

    real_by_code: dict[str, dict] = {}
    for src in courses:
        if is_filler(src):
            continue
        key = str(src.get("code") or "").strip().replace(" ", "").upper()
        if key:
            real_by_code.setdefault(key, src)

    enriched: list[dict] = []
    notes: list[str] = []
    for src in courses:
        if is_filler(src):
            key = str(src.get("code") or "").strip().replace(" ", "").upper()
            real = real_by_code.get(key)
            if real is not None and real is not src:
                row = dict(src)
                for field in ("name_th", "name_en", "credits", "category", "type"):
                    row[field] = real.get(field)
                notes.append(
                    f"{key}: เติมข้อมูลจริงจากหน้า {real.get('source_page') or real.get('pages')} "
                    f"ให้แถวสังเคราะห์ (เดิมชื่อกลุ่มซ้ำ) ที่หน้า "
                    f"{src.get('source_page') or src.get('pages')}")
                enriched.append(row)
                continue
        enriched.append(src)
    return enriched, notes


def _dup_group_key(src: dict) -> tuple | None:
    """
    คีย์กลุ่ม "แถวเดียวกันพิมพ์ซ้ำหลายหน้า" สำหรับ _enrich_duplicate_row_fields

    รหัสตัวเลข 8 หลักจริงระบุตัวตนวิชาได้เฉพาะเจาะจงอยู่แล้วด้วยตัวมันเอง (ต่างจาก wildcard
    ที่รหัสดิบเดียวกันซ้ำกันได้ระหว่างคนละวิชา/คนละช่องเลือก) จึงกลุ่มด้วยแค่ (รหัส, ปี, เทอม)
    พอ ไม่ต้องพึ่ง name_th ตรงเป๊ะเหมือน _norm_for_dup_check — บั๊กที่พบจริง: 96644042 พิมพ์
    ตารางซ้ำสองหน้า หน้าหนึ่งเขียนชื่อขาดตัว "อ" ไปตัวหนึ่ง ("...นำเสนอย่างมืออาชีพ") เทียบกับอีก
    หน้า ("...นำเสนออย่างมืออาชีพ") ถ้าใช้ fingerprint เดิม (ต้องชื่อตรงกันเป๊ะ) สองแถวนี้จะไม่ถูก
    มองว่าเป็นแถวเดียวกันเลย ทำให้ backfill credits ข้ามหน้าไม่ทำงาน

    รหัส wildcard/placeholder ยังต้องใช้ name_th ช่วยแยกเหมือนเดิม (เกณฑ์เดียวกับ
    _norm_for_dup_check) เพราะรหัสดิบเดียวกัน (06036xxx) อาจหมายถึงคนละช่องวิชาเลือกที่ต่างกันจริง
    แม้อยู่ปี/เทอมเดียวกัน (เช่น "วิชาเลือกเสรี 1" กับ "วิชาเลือกเสรี 2")
    """
    raw_code = str(src.get("code") or "").strip().upper()
    if not raw_code:
        return None
    year = str(src.get("year") or "")
    sem = str(src.get("semester") or "")
    if _lab7b_codes(raw_code):
        return (raw_code, year, sem, "")
    return (raw_code, year, sem, str(src.get("name_th") or "").strip())


def _enrich_duplicate_row_fields(courses: list[dict]) -> tuple[list[dict], list[str]]:
    """
    กฎ: ก่อนแยกเป็น nocoop/coop ให้เติมฟิลด์ที่ยังว่าง (โดยเฉพาะ credits) ของแถวที่เล่มพิมพ์
    ตารางซ้ำกันหลายหน้า จากแถวคู่แฝดที่มีข้อมูลครบกว่า — ดูจากทั้งเล่ม ไม่ใช่แค่ section เดียว

    บั๊กที่พบจริง (BIT): 96644042 พิมพ์ตาราง "ปีที่ 1 ภาคการศึกษาที่ 1" ซ้ำสองหน้า — หน้า 26
    (อยู่ในช่วงหน้า nocoop) อ่านหน่วยกิตไม่ออก (credits=null) ส่วนหน้า 31 (อยู่ในช่วงหน้า coop)
    อ่านได้ถูก ("3(3-0-6)") ทั้งสองแถวเป็นวิชาเดียวกันจริง (รหัส/ปี/เทอมตรงกัน) แม้ name_th จะ
    OCR ไม่ตรงกันเป๊ะ (หน้า 26 ขาดตัว "อ" ไปตัวหนึ่งเทียบกับหน้า 31 — ดูคอมเมนต์ที่
    _dup_group_key) แต่ split_lab7b_by_plan() ส่งแต่ละแถวไปคนละ section ตามเลขหน้าของแถวนั้นเอง
    (หน้า 26/31 ไม่คาบเกี่ยวช่วงกัน) ฝั่ง nocoop จึงเหลือแต่แถว credits=null โดยไม่มีแถวคู่
    (หน้า 31) เข้ามาให้ _dedup_insert() ของ convert_lab7b() เห็นและเติมให้ในขั้นนั้นเลย (แถวนั้น
    ถูกส่งไปอีก section ไปแล้วตั้งแต่ก่อนถึง convert_lab7b) ต้องเติมให้ *ก่อน* แยก section เหมือน
    _enrich_alt_group_fillers()

    กติกา: จับกลุ่มด้วย _dup_group_key จากทั้งเล่ม แล้วเติมเฉพาะฟิลด์ที่ยังว่าง (None/"") ของ
    แต่ละแถวจากเพื่อนร่วมกลุ่มที่มีค่าอยู่ ไม่แตะ pages/source_page ของแถวเดิม (แต่ละแถวยังต้อง
    คงรู้ว่าตัวเองเจอที่หน้าไหน สำหรับตอนแยก section ต่อ)
    """
    groups: dict[tuple, list[dict]] = {}
    for src in courses:
        key = _dup_group_key(src)
        if key is None:
            continue
        groups.setdefault(key, []).append(src)

    notes: list[str] = []
    enriched: list[dict] = []
    fill_fields = ("credits", "name_en", "description_th", "category", "type", "prerequisite")
    for src in courses:
        key = _dup_group_key(src)
        siblings = groups.get(key, [src]) if key is not None else [src]
        if len(siblings) < 2:
            enriched.append(src)
            continue
        row = dict(src)
        for field in fill_fields:
            if row.get(field) not in (None, ""):
                continue
            for sib in siblings:
                if sib is src:
                    continue
                v = sib.get(field)
                if v not in (None, ""):
                    row[field] = v
                    notes.append(
                        f"{key[0]}: เติม {field} จากแถวซ้ำที่หน้า "
                        f"{sib.get('source_page') or sib.get('pages')} ให้แถวที่หน้า "
                        f"{src.get('source_page') or src.get('pages')} (วิชาเดียวกันพิมพ์ซ้ำ "
                        "หลายหน้า แต่จะถูกแยกไปคนละ section)")
                    break
        enriched.append(row)
    return enriched, notes


def _sort_placeholder_rows_doc_order(rows: list[dict], text: str) -> None:
    """เรียงแถวรหัส wildcard รหัสเดียวกันตามลำดับในเอกสาร (หน้า, ตำแหน่งชื่อในหน้า) แบบ in-place

    ตัวเลขต่อท้าย (_2, _3, …) ของช่อง wildcard ถูกกำหนดจากลำดับแถว และเฉลยนับตามลำดับในเอกสาร
    แถวที่กู้คืนมาถูกต่อท้ายลิสต์ จึงต้องเรียงใหม่ ไม่งั้นชื่อ/ปี/เทอมของแต่ละช่องคลาดกันหมด
    ตำแหน่งที่หาไม่พบอยู่ท้ายสุดและคงลำดับเดิม (stable sort)"""
    page_text = {p: re.sub(r"\s+", "", t) for p, t in _iter_pages(text)}

    def pos(c: dict) -> tuple[int, int]:
        p = _lab7b_page(c)
        name = re.sub(r"\s+", "", str(c.get("name_th") or ""))
        i = page_text.get(p, "").find(name) if name and p is not None else -1
        return (p if p is not None else 10 ** 6, i if i >= 0 else 10 ** 6)

    by_code: dict[str, list[int]] = {}
    for i, c in enumerate(rows):
        code = str(c.get("code") or "").strip().replace(" ", "").upper()
        if is_placeholder(code) or re.search(r"[X]", code):
            by_code.setdefault(code, []).append(i)
    for idxs in by_code.values():
        ordered = sorted((rows[i] for i in idxs), key=pos)
        for i, r in zip(idxs, ordered):
            rows[i] = r


# ── IT: กลุ่ม "เลือก 1" ที่เล่มพิมพ์เป็นเซลล์รหัสหลายบรรทัด + หน่วยกิตที่อนุมานแล้วตรงกับยอดรวมที่เล่มพิมพ์ ──
# พบจริงกับ IT (ตรวจกับ pred_vlm.json + intermediate_vlm.md):
#   1) ตาราง 3/1 พิมพ์กลุ่มสื่อประสมเป็นเซลล์เดียว "06016426<br/>06016427<br/>06016418" (เลือก 1) แต่ Lab 7B
#      ไม่ใส่ alt_group ให้ 426/427 และทิ้ง 06016418 เป็นแถวเดี่ยวอีกแถว -> นับเกิน 6 (nocoop) / 3 (coop)
#   2) nocoop 3/2 ช่อง "วิชาเลือกทางเทคโนโลยีสารสนเทศ 1" OCR อ่านไม่ได้ Lab 7B อนุมานหน่วยกิตเอง แล้วนโยบาย
#      "ห้ามเดา" ตั้งเป็น null -> เทอมนับได้ 12 แทน 15 ที่เล่มพิมพ์
# สองข้อนี้แก้เฉพาะ IT (โปรแกรมอื่นยังไม่ได้ตรวจ จึงไม่เปิด) และอ้างอิงเฉพาะสิ่งที่เล่มพิมพ์จริง ไม่เดา
MULTICODE_CELL_GROUP_PROGRAMS: set[str] = {"IT"}
CORROBORATED_INFERRED_CREDIT_PROGRAMS: set[str] = {"IT"}

# บังคับรวมแถวของเทอมหนึ่งเป็น alt_group เดียว เมื่อเล่มพิมพ์ยอดรวมเทอมไม่ตรงกับโครงสร้างตารางที่อ่านได้
# และยังไม่ทราบกติกาจริง (ดู warning ที่ฟังก์ชันใช้งาน) — ใช้เพื่อให้ยอดหน่วยกิตตรงกับที่เล่มพิมพ์
# IT 2/2: บังคับ 12 (วิชาบังคับ 4 ตัว) + 3 (414|415) + 3 = 18 ตามที่เล่มพิมพ์ "รวม 18" ทั้งสองแผน
# แต่ตารางมี 3 กลุ่มวิชา (พัฒนาซอฟต์แวร์ / โครงสร้างพื้นฐาน / สื่อประสม) ซึ่งตามกติกา "เลือก 1 ต่อกลุ่ม" จะได้ 21
TERM_ALT_MERGE_OVERRIDE: dict[str, list[dict]] = {
    "IT": [{
        "year": 2, "semester": 2,
        "codes": {"06016419", "06016420", "06016424", "06016425"},
        "alt_group": "alt_y2s2_override",
        "reason": ("เล่มพิมพ์ยอดรวม 2/2 = 18 แต่ตารางมี 3 กลุ่มวิชาเลือก (กติกา 'เลือก 1 ต่อกลุ่ม' ได้ 21) — "
                   "รวมกลุ่มโครงสร้างพื้นฐานกับสื่อประสมเป็น 'เลือก 1' เดียวเพื่อให้ยอดตรงที่เล่มพิมพ์ "
                   "กติกาจริงยังไม่ได้ยืนยัน ต้องให้คนตรวจกับหลักสูตร"),
    }],
}

_MULTICODE_CELL_RE = re.compile(r"<td[^>]*>\s*((?:\d{8}\s*<br\s*/?>\s*)+\d{8})\s*</td>")
_PRINTED_TOTAL_RE = re.compile(r"รวม(?:\*\*)?\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>")


def group_multicode_cells_from_raw_tables(courses: list[dict], md_text: str,
                                          sections: dict[str, tuple[int, int]]
                                          ) -> tuple[list[dict], list[str]]:
    """เซลล์รหัสหลายบรรทัดในตารางแผน (เช่น 426<br/>427<br/>418) = 'เลือกอย่างใดอย่างหนึ่ง'
    ถ้า Lab 7B ยังไม่มี alt_group ครอบรหัสชุดนั้นเลย -> ใส่ให้ (ไม่เพิ่ม/ลบแถว ไม่เดาข้อมูลใหม่)
    ข้ามถ้ามีกลุ่มเดิมที่สมาชิกตรงกับรหัสในเซลล์พอดี และข้ามถ้าได้สมาชิกไม่ถึง 2 แถว
    """
    notes: list[str] = []
    out = [dict(c) for c in courses]
    plan_pages = {pg for a, b in sections.values() for pg in range(a, b + 1)}
    tables = list(re.finditer(r"<table>.*?</table>", md_text, flags=re.S))
    positions = _table_page_positions(md_text)
    counter: dict[tuple, int] = {}
    for tm, (_, pg) in zip(tables, positions):
        if pg is None or pg not in plan_pages:
            continue
        for cm in _MULTICODE_CELL_RE.finditer(tm.group(0)):
            codes = re.findall(r"\d{8}", cm.group(1))
            code_set = set(codes)
            if len(code_set) < 2:
                continue
            picked: list[int] = []
            terms: set[tuple] = set()
            for i, row in enumerate(out):
                if (str(row.get("code")) in code_set and pg in _row_pages(row)
                        and not row.get("alt_group")):
                    picked.append(i)
                    terms.add((row.get("year"), row.get("semester")))
            if len(picked) < 2 or len(terms) != 1:
                continue
            term = next(iter(terms))
            existing: dict[str, set[str]] = {}
            for row in out:
                if row.get("alt_group") and (row.get("year"), row.get("semester")) == term:
                    existing.setdefault(str(row["alt_group"]), set()).add(str(row.get("code")))
            if any(members == code_set for members in existing.values()):
                continue
            counter[term] = counter.get(term, 0) + 1
            gid = f"alt_y{term[0]}s{term[1]}_cell{counter[term]}"
            for i in picked:
                out[i]["alt_group"] = gid
            notes.append(
                f"{term[0]}/{term[1]} (หน้า {pg}): เซลล์รหัส {'/'.join(codes)} พิมพ์เป็นช่อง 'เลือก 1' "
                f"แต่ไม่มี alt_group -> ใส่ {gid!r} ให้ {len(picked)} แถว")
    return out, notes


def corroborated_inferred_credit_indexes(courses: list[dict], md_text: str) -> tuple[set[int], list[str]]:
    """ดัชนีแถวที่หน่วยกิตถูก Lab 7B อนุมาน แต่ 'ยอดรวมที่เล่มพิมพ์ของหน้านั้น - หน่วยกิตของแถวอื่น
    ในเทอมเดียวกัน' ได้ค่าเท่ากับค่าที่อนุมานพอดี -> เล่มยืนยันค่านี้ ไม่ต้อง null
    เงื่อนไขเข้ม: หน้านั้นต้องมียอด 'รวม' เพียงค่าเดียว และแถวอื่นทุกแถวต้องมีหน่วยกิตที่อ่านได้
    """
    markers = [(m.start(), int(m.group(1))) for m in _PDF_PAGE_MARKER_RE.finditer(md_text)]
    page_totals: dict[int, list[int]] = {}
    for k, (start, pg) in enumerate(markers):
        end = markers[k + 1][0] if k + 1 < len(markers) else len(md_text)
        page_totals[pg] = [int(x) for x in _PRINTED_TOTAL_RE.findall(md_text[start:end])]

    def lead(v: Any) -> int | None:
        m = re.match(r"\s*(\d+)\s*\(", str(v or ""))
        return int(m.group(1)) if m else None

    keep: set[int] = set()
    notes: list[str] = []
    for i, row in enumerate(courses):
        if not _CREDITS_INFERRED_NOTE_RE.search(str(row.get("note") or "")):
            continue
        val = lead(row.get("credits"))
        if val is None:
            continue
        term = (row.get("year"), row.get("semester"))
        for pg in _row_pages(row):
            totals = page_totals.get(pg) or []
            if len(totals) != 1:
                continue
            seen_groups: set[str] = set()
            others_sum, ok = 0, True
            for j, o in enumerate(courses):
                if j == i or pg not in _row_pages(o) or (o.get("year"), o.get("semester")) != term:
                    continue
                ag = o.get("alt_group")
                if ag:
                    if ag in seen_groups:
                        continue
                    seen_groups.add(ag)
                c = lead(o.get("credits"))
                if c is None:
                    ok = False
                    break
                others_sum += c
            if ok and totals[0] - others_sum == val:
                keep.add(i)
                notes.append(
                    f"{row.get('code')} ({term[0]}/{term[1]}): หน่วยกิตที่ Lab 7B อนุมาน ({val}) ตรงกับยอดรวมที่เล่มพิมพ์ "
                    f"(หน้า {pg}: {totals[0]} - แถวอื่น {others_sum}) -> คงค่าไว้ ไม่ตั้งเป็น null")
                break
    return keep, notes


# โปรแกรมที่ใช้ "ค่าที่เล่มพิมพ์ใน <table> ดิบ" แทนค่าที่ Lab 7B อนุมาน (ดู repair_inferred_credits_...)
# ใส่เฉพาะโปรแกรมที่ตรวจแล้ว เพื่อไม่ให้โปรแกรมที่อนุมัติแล้ว (DSBA/AIT/GENED) เปลี่ยนผลโดยไม่ตั้งใจ
RAW_PRINTED_CREDIT_REPAIR_PROGRAMS: set[str] = {"IT", "BIT", "DSBA", "AIT", "GENED",
                                                 "IT_2560", "BIT_2560", "DSBA_2560",
                                                 "GENED_2559", "GENED_2564"}


def repair_inferred_credits_from_raw_tables(
        courses: list[dict], raw_map: dict[str, list[str]]
) -> tuple[list[dict], set[int], list[str]]:
    """แถวที่ Lab 7B ประกาศใน note ว่า 'อนุมาน' หน่วยกิต แต่เล่มดิบพิมพ์ไว้ตรง ๆ ใน <table>
    -> ใช้ค่าที่เล่มพิมพ์ (ไม่ใช่ค่าอนุมาน) แล้วกันไม่ให้ null_inferred_credits() ตัดทิ้ง

    ไม่ขัดนโยบาย 'ไม่รู้แน่ชัดห้ามเดา' เพราะค่านี้อ่านจากเล่มตรง ๆ เงื่อนไข: ทุกครั้งที่รหัสนี้
    โผล่ใน <table> ต้องได้หน่วยกิตค่าเดียวกันเท่านั้น (ถ้าขัดกันเอง/ไม่พบ -> ปล่อยให้ถูก null ต่อ)

    พบจริง: IT 06016453/54 (ค่าอนุมานถูก) และ BIT 06036128/129/133/134/135/136/140/141/131
    -- อยู่ในตารางรายวิชาเลือก หน้า 23-25 พิมพ์ครบ แต่ถูก null ทั้งหมด และ 131/134/135 ค่าอนุมาน
    (3(3-0-6)) ผิดจากที่เล่มพิมพ์ (3(2-2-5)) -- คอมเมนต์เดิมที่ว่า 3 รายการนี้ 'ไม่มี <table>'
    ไม่จริง: _raw_table_credits_map() อ่านทุก <table> ไม่ได้จำกัดเฉพาะตารางแผน

    คืน (courses ที่แก้แล้ว, ดัชนีที่ต้องคงค่าไว้, โน้ต)
    """
    triple = re.compile(r"\d+\(\d+-\d+-\d+\)")
    out: list[dict] = []
    keep: set[int] = set()
    notes: list[str] = []
    for i, src in enumerate(courses):
        row = dict(src)
        out.append(row)
        if not _CREDITS_INFERRED_NOTE_RE.search(str(row.get("note") or "")):
            continue
        code = str(row.get("code") or "").strip().upper()
        printed = {t.replace(" ", "") for cand in raw_map.get(code, [])
                   for t in triple.findall(str(cand).replace(" ", ""))}
        if len(printed) != 1:
            continue
        val = next(iter(printed))
        old = row.get("credits")
        row["credits"] = val
        keep.add(i)
        notes.append(
            f"{code}: หน่วยกิตที่ Lab 7B อนุมาน ({old!r}) "
            + (f"แก้เป็น {val!r} ตามที่เล่มพิมพ์ใน <table> ดิบ" if str(old).replace(' ', '') != val
               else "ตรงกับที่เล่มพิมพ์ใน <table> ดิบ -> คงค่าไว้")
            + " ไม่ตั้งเป็น null")
    return out, keep, notes


# ── ชื่อวิชาที่มีหมายเหตุ/หัวข้อถัดไปติดมา (AIT/GENED: 90641008) ─────────────────────────────
# พบจริง: เล่มพิมพ์ชื่อวิชาใน <table> เป็น "พื้นฐานทักษะการสื่อสารภาษาอังกฤษ" แต่ใต้ตารางมีเชิงอรรถ
# "** 90641008 พื้นฐานทักษะ... เป็นรายวิชาบังคับก่อน ที่ไม่นับหน่วยกิต ..." แล้วตามด้วยหัวข้อ
# "ข. หมวดวิชาเฉพาะ" -- Lab 7B อ่านเชิงอรรถทั้งก้อนเป็นชื่อวิชา (ตัดช่องว่างทิ้ง) ทำให้ name_th ยาวผิดปกติ
# trim_names_to_canonical() เดิมแก้ไม่ได้ เพราะ "ชื่อมาตรฐาน" ของมันสร้างจากบรรทัดข้อความ `CODE ชื่อ`
# ซึ่งในกรณีนี้คือเชิงอรรถเอง (ไม่ใช่ชื่อวิชา) และ AIT/GENED ไม่ผ่าน split_lab7b_by_plan() อยู่แล้ว
# ฟังก์ชันนี้อ่านชื่อจากเซลล์ชื่อวิชาใน <table> โดยตรง (ส่วนก่อน <br/>) -- เป็นค่าที่เล่มพิมพ์ ไม่ใช่การเดา
UNSPLIT_NAME_TRIM_PROGRAMS: set[str] = {"AIT"}   # GENED มีอาการเดียวกันใน pred แต่ยังไม่ได้ตรวจคำเตือนของ GENED -> ยังไม่ใส่
_MIN_GLUED_TAIL = 8          # ส่วนที่เกินต้องยาวอย่างน้อยเท่านี้ (ไม่นับช่องว่าง) กันไปตัดเลขลำดับท้ายชื่อ เช่น "1", "2"


def _table_name_th_map(md_text: str) -> dict[str, set[str]]:
    """รหัส -> ชื่อไทยที่พิมพ์ในเซลล์ชื่อวิชาของ <table> (ทุกครั้งที่รหัสนั้นโผล่)"""
    out: dict[str, set[str]] = {}
    for tbl in re.findall(r"<table>.*?</table>", md_text or "", flags=re.S):
        for row in re.findall(r"<tr>.*?</tr>", tbl, flags=re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, flags=re.S)
            if len(cells) < 2:
                continue
            code = re.sub(r"[\s*]", "", re.sub(r"<[^>]+>", "", cells[0]))
            if not re.fullmatch(r"\d{8}", code):
                continue
            cell = re.sub(r"<br\s*/?>", "\n", cells[1])
            cell = re.sub(r"<[^>]+>", " ", cell)
            if "\n" in cell.strip():
                th = cell.strip().split("\n")[0]
            else:
                th, _ = _split_thai_english_name(cell)
            th = re.sub(r"\s+", " ", th).strip()
            if th and re.search(r"[\u0E00-\u0E7F]", th):
                out.setdefault(code, set()).add(th)
    return out


def trim_glued_names_from_tables(courses: list[dict], program: str | None, text: str | None
                                 ) -> tuple[list[dict], list[str]]:
    """name_th ที่ขึ้นต้นด้วยชื่อในตารางเป๊ะ (เทียบโดยไม่นับช่องว่าง) แต่ยาวเกินมาก -> ใช้ชื่อในตาราง

    เงื่อนไขกันตัดผิด: (1) รหัสนี้ต้องมีชื่อในตารางเพียงชื่อเดียว (ถ้าตารางขัดกันเอง -> ไม่แตะ)
    (2) ส่วนที่เกินต้องยาว >= _MIN_GLUED_TAIL ตัวอักษร (ไม่นับช่องว่าง) (3) ไม่แตะชื่อที่สั้นกว่า/สะกดต่าง
    """
    if not text or program not in UNSPLIT_NAME_TRIM_PROGRAMS:
        return courses, []
    table = _table_name_th_map(text)
    notes: list[str] = []
    out: list[dict] = []
    ns = lambda t: re.sub(r"\s+", "", t)
    for src in courses:
        row = dict(src)
        code = str(row.get("code") or "").strip()
        name = str(row.get("name_th") or "")
        names = table.get(code) or set()
        if len(names) == 1:
            good = next(iter(names))
            if (len(ns(name)) - len(ns(good)) >= _MIN_GLUED_TAIL
                    and ns(name).startswith(ns(good))):
                notes.append(f"{code}: name_th มีข้อความอื่นติดท้ายชื่อวิชา ({name!r}) -- "
                             f"ใช้ชื่อที่เล่มพิมพ์ในตาราง {good!r}")
                row["name_th"] = good
        out.append(row)
    return out, notes



# โปรแกรมที่ "ไม่มีแผน nocoop/coop" (plan_sections() ว่าง -> ไม่เรียก split_lab7b_by_plan()) และต้องซ่อมหน่วยกิต
# จาก <table> ดิบด้วย repair_credits_unsplit() ใส่เฉพาะโปรแกรมที่ตรวจแล้ว: AIT ผ่านการอนุมัติแล้วโดยไม่ผ่านขั้นนี้
# จึงห้ามใส่เองโดยไม่อ่านคำเตือนของ AIT ก่อน
UNSPLIT_CREDIT_REPAIR_PROGRAMS: set[str] = {"GENED", "GENED_2559", "GENED_2564"}

_PRINTED_TRIPLE_RE = re.compile(r"\d+\s*\(\s*\d+\s*-\s*\d+\s*-\s*\d+\s*\)")


def _unanimous_printed_credit_map(raw_map: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[str]]:
    """แปลง _raw_table_credits_map() ให้เหลือเฉพาะรูป n(a-b-c) ล้วน ๆ ต่อรหัส

    ตารางแบบ colspan ใส่ชื่อวิชาติดมากับเซลล์หน่วยกิต (เช่น 'ศัลยกรรมชีวิต 3 (3-0-6)') -- ตัดชื่อออก เก็บแค่
    ตัวเลข และเก็บเฉพาะรหัสที่ทุกครั้งที่โผล่ใน <table> ได้ค่าเดียวกัน (ถ้าเล่มพิมพ์ขัดกันเอง -> ไม่ซ่อม ปล่อยเป็น null)
    """
    out: dict[str, list[str]] = {}
    notes: list[str] = []
    for code, cands in raw_map.items():
        vals = {re.sub(r"\s+", "", t) for c in cands for t in _PRINTED_TRIPLE_RE.findall(str(c))}
        if len(vals) == 1:
            out[code] = [next(iter(vals))]
        elif len(vals) > 1:
            notes.append(f"{code}: เล่มพิมพ์หน่วยกิตขัดกันเองใน <table> ({sorted(vals)}) -- ไม่ซ่อม ปล่อยตามค่าเดิม/null")
    return out, notes


def repair_credits_unsplit(courses: list[dict], program: str | None, text: str | None,
                           raw_map: dict[str, list[str]] | None = None
                           ) -> tuple[list[dict], list[str]]:
    """ซ่อมหน่วยกิตสำหรับโปรแกรมที่ไม่ผ่าน split_lab7b_by_plan() (ตอนนี้ = GENED เท่านั้น)

    ปัญหาที่พบจริงกับ GENED: plan_sections('GENED') ว่าง -> _import_split() ไม่เรียก split_lab7b_by_plan()
    ทำให้ขั้นซ่อมหน่วยกิตทั้งหมดไม่ทำงาน แถวที่ Lab 7B ปล่อยว่าง (หรืออนุมานแล้วผิด เช่น 90642084) จึงค้างทั้งที่เล่ม
    พิมพ์ค่าไว้ใน <table> (ตรวจแล้ว: 37/37 แถวที่น่าสงสัยมีค่าพิมพ์ใน <table>)

    ลำดับเดียวกับ split_lab7b_by_plan(): เติมแถวว่าง -> ใช้ค่าที่เล่มพิมพ์แทนค่าอนุมาน -> null ส่วนที่ยังอนุมานค้าง
    ไม่แตะแถวที่มีหน่วยกิตครบและไม่ได้ถูกประกาศว่าอนุมาน และอ่านเฉพาะค่าที่เล่มพิมพ์ตรง ๆ (ไม่เดา)
    """
    if not text or program not in UNSPLIT_CREDIT_REPAIR_PROGRAMS:
        return courses, []
    # เลขเดี่ยวเกิน 12 ในช่องหน่วยกิต = เลขในชื่อวิชาหลุดเข้ามา (เช่น "ศตวรรษที่ 21") -> ตั้งว่างก่อน
    # แล้วให้ขั้นเติมจาก <table> ดิบอ่านค่าที่เล่มพิมพ์จริง (อ่านไม่ได้ก็ค้างเป็น null ไม่เดา)
    courses = [dict(c) for c in courses]
    bad_notes: list[str] = []
    for c in courses:
        v = str(c.get("credits") or "").strip()
        if re.fullmatch(r"\d{1,2}", v) and int(v) > 12:
            bad_notes.append(f"{c.get('code')}: หน่วยกิต {v!r} เกิน 12 (เลขจากชื่อวิชาหลุดมา) -> ตั้งว่างเพื่อเติมจาก <table> ดิบ")
            c["credits"] = None
    printed, notes = _unanimous_printed_credit_map(raw_map if raw_map is not None
                                                   else _raw_table_credits_map(text))
    notes = bad_notes + notes
    rows, fill_notes = repair_credits_from_raw_tables(courses, printed)
    notes.extend(fill_notes)
    rows, keep, inferred_notes = repair_inferred_credits_from_raw_tables(rows, printed)
    notes.extend(inferred_notes)
    rows, null_notes = null_inferred_credits(rows, keep)
    notes.extend(null_notes)
    return rows, notes


def apply_term_alt_merge_override(plan: list[dict], program: str | None) -> list[str]:
    notes: list[str] = []
    for rule in TERM_ALT_MERGE_OVERRIDE.get(program or "", []):
        hit = [r for r in plan if (r["year"], r["semester"]) == (rule["year"], rule["semester"])
               and r["code"] in rule["codes"]]
        if len(hit) < 2:
            continue
        for r in hit:
            r["alt_group"] = rule["alt_group"]
        notes.append(f"{rule['year']}/{rule['semester']}: {rule['reason']} (รวม {len(hit)} แถว)")
    return notes


def split_lab7b_by_plan(data: dict, program: str, *, raw_table_credits: dict | None = None,
                        text: str | None = None
                        ) -> tuple[dict[str, dict], dict[str, int], list[str]]:
    """
    แยกผล Lab 7B ที่รวมสองแผนไว้ในรอบเดียว ออกเป็นทีละ section จากเลขหน้า PDF

    กติกา (ไม่เรียก LLM และไม่ทิ้งข้อมูล):
      - ก่อนแยก: เติมข้อมูลจริงให้แถวตัวเลือกสังเคราะห์ก่อน (ดู _enrich_alt_group_fillers)
        เพื่อไม่ให้ convert_lab7b ทิ้งทั้งกลุ่มวิชาตอนแปลงทีละ section
      - แถวที่มีหน้าอยู่ในช่วง section ใด -> ไปอยู่ section นั้น
      - แถวที่เจอทั้งสองช่วง (วิชาเดียวกัน ปี/ภาคเดียวกัน ทั้งสองแผน) -> อยู่ทั้งสองฝั่ง
      - แถวที่จำแนกไม่ได้ (ไม่มีเลขหน้า หรืออยู่นอกช่วงแผน เช่นหน้าคำอธิบายรายวิชา)
        -> เก็บไว้ทั้งสองฝั่ง

    text: Markdown ต้นทางของโปรแกรมนี้ (ถ้ามี) — ส่งให้ plan_sections() จับ nocoop/coop
    จากป้ายหัวข้อในเนื้อหาเองแทนตาราง PROGRAM_PAGE_RANGES ที่ hardcode ไว้
    """
    sections = plan_sections(program, text=text)
    warnings: list[str] = []
    stats = {"rows": 0, "only_one_plan": 0, "in_both_plans": 0,
             "unclassified_kept_in_both": 0, "no_page_info": 0, "forced_shared": 0}
    parts = {s: {**{k: v for k, v in data.items() if k != "courses"}, "courses": []}
             for s in sections}
    shared_codes = SHARED_ACROSS_PLANS.get(program, set())
    forced_hits: set[str] = set()

    chunk = int((data.get("_meta") or {}).get("pages_per_chunk") or 1)
    if chunk > 1:
        warnings.append(
            f"Lab 7B รันด้วย pages_per_chunk={chunk}: หนึ่งก้อนมีหลายหน้า วิชาทุกตัวในก้อนถูกแนบ "
            f"เลขหน้าทุกหน้าของก้อน ก้อนที่คร่อมรอยต่อ nocoop/coop จะทำให้วิชาไปอยู่สองฝั่งเกินจริง "
            f"(ตั้ง LAB7_CHUNK=1 เพื่อให้แยกได้แม่น)")

    if text and program in RAW_TABLE_RECOVERY_PROGRAMS:
        # กู้ทางเลือก rowspan ที่ Lab 7B ทิ้ง + ซ่อมหน่วยกิต null จากตารางดิบ (ดูคอมเมนต์ที่ฟังก์ชันกู้คืน)
        recovered, rec_notes = recover_alt_group_siblings_from_raw_tables(
            data.get("courses") or [], text)
        data = {**data, "courses": recovered}
        warnings.extend(rec_notes)
        if raw_table_credits is None:
            raw_table_credits = _raw_table_credits_map(text)
        if program in SHARED_CELL_CREDIT_PROGRAMS:
            raw_table_credits = merge_shared_cell_credits(raw_table_credits, text)

    if text and program in MULTICODE_CELL_GROUP_PROGRAMS:
        grouped, grp_notes = group_multicode_cells_from_raw_tables(
            data.get("courses") or [], text, sections)
        data = {**data, "courses": grouped}
        warnings.extend(grp_notes)

    if text:
        name_fixed, name_notes = trim_names_to_canonical(data.get("courses") or [], text)
        data = {**data, "courses": name_fixed}
        warnings.extend(name_notes)
        name_fixed, space_notes = restore_name_spacing_from_tables(
            data.get("courses") or [], program, text)
        data = {**data, "courses": name_fixed}
        warnings.extend(space_notes)

    dup_filled_courses, dup_notes = _enrich_duplicate_row_fields(data.get("courses") or [])
    warnings.extend(dup_notes)
    if raw_table_credits:
        dup_filled_courses, table_notes = repair_credits_from_raw_tables(
            dup_filled_courses, raw_table_credits)
        warnings.extend(table_notes)
    keep_inferred: set[int] = set()
    if text and program in CORROBORATED_INFERRED_CREDIT_PROGRAMS:
        keep_inferred, keep_notes = corroborated_inferred_credit_indexes(dup_filled_courses, text)
        warnings.extend(keep_notes)
    if text and program in RAW_PRINTED_CREDIT_REPAIR_PROGRAMS:
        dup_filled_courses, raw_keep, raw_notes = repair_inferred_credits_from_raw_tables(
            dup_filled_courses, raw_table_credits or _raw_table_credits_map(text))
        keep_inferred = keep_inferred | raw_keep
        warnings.extend(raw_notes)
    dup_filled_courses, inferred_null_notes = null_inferred_credits(dup_filled_courses, keep_inferred)
    warnings.extend(inferred_null_notes)
    enriched_courses, enrich_notes = _enrich_alt_group_fillers(dup_filled_courses)
    warnings.extend(enrich_notes)

    for src in enriched_courses:
        stats["rows"] += 1
        pages = _row_pages(src)
        hit = {name for name, (a, b) in sections.items()
               if any(a <= pg <= b for pg in pages)}
        if not pages:
            stats["no_page_info"] += 1
        forced = shared_codes and set(_lab7b_codes(src.get("code"))) & shared_codes
        if forced and hit != set(sections):
            # รหัสอยู่ใน override list ของโปรแกรมนี้ — บังคับเข้าทุก section แม้เลขหน้า
            # จะบอกว่าอยู่แผนเดียว (ดูคอมเมนต์ที่ SHARED_ACROSS_PLANS ด้านบน)
            stats["forced_shared"] += 1
            forced_hits |= forced
            hit = set(sections)
        if not hit:
            stats["unclassified_kept_in_both"] += 1
        elif len(hit) > 1:
            stats["in_both_plans"] += 1
        else:
            stats["only_one_plan"] += 1
        for name in (hit or set(sections)):
            a, b = sections[name]
            own = [pg for pg in pages if a <= pg <= b]
            # หน้าที่อยู่นอกช่วงแผนทุกแผน (เช่น หน้าคำอธิบายรายวิชา) เป็นหลักฐานของวิชานี้ในทั้งสองแผน -> เก็บไว้
            # ส่วนหน้าของแผนอีกฝั่งตัดทิ้ง เพื่อไม่ให้วิชา coop อ้างหน้าของ nocoop (และกลับกัน)
            outside = [pg for pg in pages
                       if not any(x <= pg <= y for x, y in sections.values()) and pg not in own]
            row = dict(src)
            row["pages"] = (own + outside) or pages
            row["source_page"] = (own or pages or [None])[0]
            parts[name]["courses"].append(row)

    if text and program in RAW_TABLE_RECOVERY_PROGRAMS:
        for part in parts.values():
            _sort_placeholder_rows_doc_order(part["courses"], text)

    failed = (data.get("_meta") or {}).get("ocr_failed_pages") or []
    if failed:
        warnings.append(f"Lab 7B OCR หน้า PDF {failed} ไม่สำเร็จ — วิชาในหน้าเหล่านั้นไม่อยู่ในข้อมูล")
    if stats["no_page_info"]:
        warnings.append(f"{stats['no_page_info']} แถวไม่มีเลขหน้า (pred JSON เก่า?) — เก็บไว้ทั้งสองฝั่ง")
    if forced_hits:
        warnings.append(
            f"{stats['forced_shared']} แถว (รหัส {sorted(forced_hits)}) ถูกบังคับให้อยู่ทุกแผน "
            "ตาม SHARED_ACROSS_PLANS แม้เลขหน้าจะบอกว่าอยู่แผนเดียว")
    missing_forced = shared_codes - forced_hits
    if missing_forced:
        # รหัสอยู่ใน override list แต่ไม่เจอในข้อมูลรอบนี้เลย — อาจเป็นเพราะ pred JSON
        # เปลี่ยนไปแล้ว (คนละรุ่นของ Lab 7B) ไม่ใช่เพราะ override ทำงานผิด แจ้งเตือนไว้เฉยๆ
        warnings.append(
            f"SHARED_ACROSS_PLANS ของ {program} มีรหัส {sorted(missing_forced)} "
            "แต่ไม่พบแถวเหล่านี้ใน pred JSON รอบนี้เลย — ตรวจว่ารหัสยังตรงกับเล่มหรือไม่")
    return parts, stats, warnings


def _write_converted(part: dict, pid: str, meta: dict, fallback: dict, outdir: Path,
                     program: str | None = None, section: str | None = None
                     ) -> tuple[dict, dict]:
    converted, report = convert_lab7b(
        part,
        program=program,
        section=section,
        program_id=pid,
        program_name=meta.get("name") or fallback.get("program_name"),
        total_credits=meta.get("total_credits", fallback.get("total_credits")),
        years=meta.get("years", fallback.get("years")),
    )
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "curriculum.json"
    out.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_suffix(".conversion.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return converted, report


def _import_split(args, data: dict) -> None:
    """import-lab7b แบบ --split-dir: หนึ่ง pred JSON -> หนึ่งหรือสองโปรแกรม + manifest.json"""
    root = Path(args.split_dir)
    root.mkdir(parents=True, exist_ok=True)
    meta_all = (json.loads(Path(args.program_meta).read_text(encoding="utf-8"))
                if args.program_meta else {})
    source_text = (Path(args.source_md).read_text(encoding="utf-8")
                  if getattr(args, "source_md", None) else None)
    if source_text is None:
        print(f"  ! ไม่ได้ระบุ --source-md — จำแนก nocoop/coop ด้วยตาราง legacy "
              f"PROGRAM_PAGE_RANGES[{args.program!r}] แทนการจับป้ายหัวข้อ")
    sections = plan_sections(args.program, text=source_text)

    manifest: dict[str, Any] = {
        "program": args.program, "source": str(args.input),
        "source_md": str(args.source_md) if getattr(args, "source_md", None) else None,
        "split_by_plan": bool(sections), "split_stats": None,
        "warnings": [], "programs": [],
    }
    if sections:
        parts, stats, warns = split_lab7b_by_plan(data, args.program, text=source_text)
        manifest["split_stats"], manifest["warnings"] = stats, warns
        jobs = [(f"{args.program}_{name}", name, parts[name], Path(name))
                for name in sections]
        fallback: dict = {}       # ค่า CLI ตัวเดียวใช้กับสองโปรแกรมไม่ได้ — ใช้ --program-meta แทน
        forced_note = (f" · {stats['forced_shared']} บังคับทั้งสองแผน (override)"
                       if stats.get("forced_shared") else "")
        print(f"  แยก {args.program} ตามเลขหน้า: {stats['only_one_plan']} วิชาอยู่แผนเดียว · "
              f"{stats['in_both_plans']} ทั้งสองแผน · "
              f"{stats['unclassified_kept_in_both']} จำแนกไม่ได้ (เก็บทั้งสองฝั่ง)"
              f"{forced_note}")
        for w in warns:
            print(f"    ⚠ {w}")
    else:
        fixed, repair_notes = repair_credits_unsplit(
            data.get("courses") or [], args.program, source_text)
        fixed, name_notes = trim_glued_names_from_tables(fixed, args.program, source_text)
        repair_notes = repair_notes + name_notes
        if repair_notes:
            data = {**data, "courses": fixed}
            manifest["warnings"] = repair_notes
            for w in repair_notes:
                print(f"    ⚠ {w}")
        jobs = [(args.program, None, data, Path("."))]
        fallback = {"program_name": args.program_name,
                    "total_credits": args.total_credits, "years": args.years}

    for pid, section, part, rel in jobs:
        entry: dict[str, Any] = {
            "program_id": pid, "section": section, "dir": str(rel),
            "curriculum": str(rel / "curriculum.json"), "status": "ok",
            "source_courses": len(part.get("courses") or []),
        }
        try:
            _, report = _write_converted(part, pid, meta_all.get(pid, {}), fallback,
                                         root / rel, program=args.program, section=section)
            entry.update(courses=report["converted_courses"], plan_items=report["plan_items"],
                         elective_slots=report["elective_slots"],
                         courses_with_source_page=report["courses_with_source_page"])
            print(f"  ✓ {pid}: course={report['converted_courses']}  "
                  f"plan={report['plan_items']}  elective_slot={report['elective_slots']}  "
                  f"มีเลขหน้า {report['courses_with_source_page']}/{report['converted_courses']}")
        except Exception as exc:   # แผนหนึ่งพังไม่ทำให้อีกแผนหยุด
            entry.update(status="failed", error=str(exc))
            print(f"  ❌ {pid}: {exc}")
        manifest["programs"].append(entry)

    mpath = root / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  manifest {mpath}")
    if not any(e["status"] == "ok" for e in manifest["programs"]):
        raise SystemExit(1)


def cmd_import_lab7b(args) -> None:
    src = Path(args.input)
    data = json.loads(src.read_text(encoding="utf-8"))

    if args.split_dir:
        if not args.program:
            raise SystemExit("--split-dir ต้องระบุ --program (IT/DSBA/BIT/AIT/GENED)")
        _import_split(args, data)
        return
    if not args.output:
        raise SystemExit("ต้องระบุ -o (แปลงเป็นไฟล์เดียว) หรือ --split-dir --program (แยกแผนอัตโนมัติ)")

    if getattr(args, "source_md", None) and (args.program in UNSPLIT_CREDIT_REPAIR_PROGRAMS
                                              or args.program in UNSPLIT_NAME_TRIM_PROGRAMS):
        _txt = Path(args.source_md).read_text(encoding="utf-8")
        _fixed, _notes = repair_credits_unsplit(data.get("courses") or [], args.program, _txt)
        _fixed, _name_notes = trim_glued_names_from_tables(_fixed, args.program, _txt)
        _notes = _notes + _name_notes
        if _notes:
            data = {**data, "courses": _fixed}
            for w in _notes:
                print(f"    ⚠ {w}")

    converted, report = convert_lab7b(
        data,
        program=args.program,
        program_id=args.program_id,
        program_name=args.program_name,
        total_credits=args.total_credits,
        years=args.years,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path = out.with_suffix(".conversion.json")
    meta_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  แปล Lab 7B JSON -> Lab 8B JSON โดยไม่เรียก LLM")
    print(f"  เขียน {out}")
    print(f"  รายงาน {meta_path}")
    print(f"    course={report['converted_courses']}  plan={report['plan_items']}  "
          f"prerequisite={report['prerequisites']}  "
          f"elective_slot={report['elective_slots']}")
    print(f"    ช่องวิชา wildcard ที่เก็บหน่วยกิตไว้ {report['wildcard_placeholders']} · "
          f"วิชาเลือกยืดหยุ่นที่เก็บไว้ {report['flexible_courses_kept']}")
    if report["synth_alt_filler_rows_skipped"]:
        print(f"    ข้ามแถวสังเคราะห์จากโน้ต alt_group {report['synth_alt_filler_rows_skipped']} "
              f"รายการ (ดูรายละเอียดใน warnings)")
    print(f"    มีเลขหน้าอ้างอิง {report['courses_with_source_page']}/"
          f"{report['converted_courses']} วิชา")
    if report["warnings"]:
        print(f"    ต้องตรวจ {len(report['warnings'])} รายการ — ดูได้ใน {meta_path}")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 3 — โหลดเข้าฐานข้อมูล
# ═══════════════════════════════════════════════════════════════════════

def open_db(path: str | Path, readonly: bool = False) -> sqlite3.Connection:
    """
    เปิดฐานข้อมูล

    readonly=True ใช้ตอนตอบคำถาม ซึ่งเป็นด่านความปลอดภัยชั้นที่หนึ่ง
    ต่อให้ LLM สร้าง SQL ที่เป็น DROP TABLE ขึ้นมา ฐานข้อมูลก็ปฏิเสธเอง
    เราไม่พึ่ง prompt ในการป้องกัน เพราะ prompt เป็นเพียงการขอร้อง
    """
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


TABLES = ("program", "course", "plan_item", "prerequisite", "elective_slot")


def _pages_for_db(row: dict) -> str | None:
    """pages (list) -> JSON text สำหรับคอลัมน์ pages; รับ curriculum.json เก่าที่มีแต่ source_page ด้วย"""
    pages = _lab7b_pages({"pages": row.get("pages"), "source_page": row.get("source_page")})
    return json.dumps(pages) if pages else None


def load_curriculum(conn: sqlite3.Connection, data: dict) -> None:
    """
    โหลด dict ของ Lab 8B เข้าฐานข้อมูลที่เปิดอยู่แล้ว

    เขียนชื่อคอลัมน์ทุกครั้ง ไม่ใช้ VALUES (?,?,?) แบบอิงลำดับ
    เพราะการเพิ่มคอลัมน์ใหม่ใน DDL จะทำให้โค้ดแบบอิงลำดับพังเงียบ ๆ
    (ค่าเลื่อนไปผิดช่อง แต่ไม่มี error) ซึ่งหาสาเหตุยากที่สุด
    """
    prog = data["program"]
    pid = prog["program_id"]
    conn.execute(
        "INSERT OR REPLACE INTO program (program_id, name_th, name_en, degree,"
        " total_credits, years) VALUES (?,?,?,?,?,?)",
        (pid, prog["name_th"], prog.get("name_en"), prog.get("degree"),
         prog["total_credits"], prog["years"]))

    for c in data.get("courses", []):
        conn.execute(
            "INSERT OR REPLACE INTO course (code, name_th, name_en, credits,"
            " lecture_h, lab_h, self_h, description_th, pages)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (c["code"], c["name_th"], c.get("name_en"), c["credits"],
             c.get("lecture_h"), c.get("lab_h"), c.get("self_h"),
             c.get("description_th"), _pages_for_db(c)))

    conn.execute("DELETE FROM plan_item WHERE program_id = ?", (pid,))
    for p in data.get("plan", []):
        conn.execute(
            "INSERT INTO plan_item (program_id, year, semester, code, credits,"
            " alt_group, category, type, note, pages)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, p["year"], p["semester"], p["code"], p["credits"],
             p.get("alt_group"), p.get("category"), p.get("type"),
             p.get("note"), _pages_for_db(p)))

    for r in data.get("prerequisites", []):
        conn.execute(
            "INSERT OR REPLACE INTO prerequisite (code, requires, kind)"
            " VALUES (?,?,?)",
            (r["code"], r["requires"], r.get("kind", "pre")))

    conn.execute("DELETE FROM elective_slot WHERE program_id = ?", (pid,))
    for s in data.get("elective_slots", []):
        conn.execute(
            "INSERT OR REPLACE INTO elective_slot (program_id, code,"
            " allowed_terms, name_th, credits, category, type, note,"
            " pages) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, s["code"], s.get("allowed_terms"), s.get("name_th"),
             s.get("credits"), s.get("category"), s.get("type"),
             s.get("note"), _pages_for_db(s)))
    conn.commit()


def cmd_load(args) -> None:
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    db = Path(args.database)
    if db.exists() and args.replace:
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)

    conn = open_db(db)
    conn.executescript(DDL)
    if args.allow_orphan:
        # ปิด FK ชั่วคราวเพื่อให้โหลดข้อมูลที่ยังไม่สมบูรณ์เข้าไปได้
        # แล้วให้ CHK2 เป็นคนรายงานว่ารหัสไหนไม่มีคำอธิบาย
        # ใช้ตอน "กำลังไล่แก้การสกัด" ไม่ใช่ตอนส่งงาน
        conn.execute("PRAGMA foreign_keys = OFF")

    try:
        load_curriculum(conn, data)
    except sqlite3.IntegrityError as e:
        conn.close()
        print(f"  ! โหลดไม่สำเร็จ: {e}")
        print("    สาเหตุที่พบบ่อยที่สุดคือมีรหัสวิชาในแผน "
              "ที่ไม่มีคำอธิบายรายวิชาในเล่ม (FOREIGN KEY)")
        print("    ถ้าต้องการโหลดเพื่อไล่ดูว่ารหัสไหนขาด ให้ใช้ --allow-orphan "
              "แล้วรัน verify เพื่อดูรายชื่อจาก CHK2")
        sys.exit(1)

    n = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in TABLES}
    pages = conn.execute(
        "SELECT COUNT(*) FROM course WHERE pages IS NOT NULL").fetchone()[0]
    conn.close()
    print(f"  โหลดเข้า {db} แล้ว")
    for t, c in n.items():
        print(f"    {t:<14} {c:>5} แถว")
    print(f"    course ที่มีเลขหน้าอ้างอิง {pages}/{n['course']}")
    if n["course"] and pages == 0:
        print("    ! ไม่มีเลขหน้าเลย — คำตอบจะอ้างอิงหน้าไม่ได้ "
              "ตรวจว่า Lab 7B แนบ pages/source_page มาหรือยัง")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 4 — ตรวจความสอดคล้องของข้อมูลในฐานข้อมูล 7 ข้อ
# ═══════════════════════════════════════════════════════════════════════
#
#  Pydantic ตรวจได้แค่ "แต่ละชิ้นหน้าตาถูกไหม"
#  แต่ตรวจไม่ได้ว่า "ชิ้นทั้งหมดรวมกันแล้วสมเหตุสมผลไหม"
#  เช่น รหัสวิชา 8 หลักถูกรูปแบบ แต่เป็นวิชาที่ไม่มีอยู่ในเล่ม — Pydantic ผ่าน
#
#  บทเรียนสำคัญจาก Lab 7A/7B ที่นำมาใช้ตรงนี้
#      กฎที่เตือนผิดบ่อย แย่กว่าไม่มีกฎเลย
#      เพราะเมื่อคนเห็นคำเตือนผิดสามครั้ง เขาจะเลิกอ่านคำเตือนทั้งหมด
#      รวมถึงครั้งที่สี่ที่เป็นของจริง  (alarm fatigue)
#  กฎทั้ง 7 ข้อนี้จึงถูกออกแบบให้รู้จักข้อยกเว้นที่มีอยู่จริงในหลักสูตร
# ═══════════════════════════════════════════════════════════════════════

def _sem_credits(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """
    หน่วยกิตรวมต่อภาคเรียน โดยนับ alt_group ครั้งเดียว

    ถ้าไม่มี alt_group จะนับวิชาเลือก "A หรือ B" เป็นสองวิชา
    ทำให้หน่วยกิตเกินจริงทุกภาคที่มีวิชาเลือก
    """
    return conn.execute(
        "SELECT year, semester, credits, n_courses "
        "FROM v_semester_credits ORDER BY year, semester").fetchall()


def verify_db(conn: sqlite3.Connection) -> list[dict]:
    """รันการตรวจทั้ง 7 ข้อ คืนรายการผลลัพธ์"""
    results: list[dict] = []

    def add(cid, name, ok, detail=""):
        results.append({"id": cid, "name": name, "ok": ok, "detail": detail})

    prog = conn.execute("SELECT * FROM program LIMIT 1").fetchone()
    if prog is None:
        add("CHK0", "มีข้อมูลหลักสูตร", False, "ตาราง program ว่าง")
        return results

    # ── CHK1 หน่วยกิตรวมของแผน ต้องเท่ากับที่หลักสูตรประกาศ ────────
    rows = _sem_credits(conn)
    total = sum(r["credits"] for r in rows)
    # วิชาที่ถูกบังคับเป็นวิชาเลือก (ไม่ผูกเทอม) แต่ยังรวมอยู่ในยอดหลักสูตร
    forced = conn.execute(
        "SELECT COALESCE(SUM(credits), 0) FROM elective_slot WHERE note LIKE ?",
        (f"%{FORCED_ELECTIVE_COUNTED_MARK}%",)).fetchone()[0]
    total += forced
    declared = prog["total_credits"]
    # ยอมให้ต่างได้ ถ้าหลักสูตรมีหมวดวิชาเลือกเสรีที่ไม่ระบุในแผนรายเทอม
    # ใช้คอลัมน์ category จริง ไม่ใช่ note LIKE '%เลือกเสรี%' แบบเดิม
    # เพราะการค้นข้อความในหมายเหตุพังทันทีที่เล่มเขียนคำนั้นด้วยเหตุผลอื่น
    free = conn.execute(
        "SELECT COUNT(*) FROM plan_item "
        "WHERE category LIKE '%เสรี%' OR note LIKE '%เลือกเสรี%'").fetchone()[0]
    slots = conn.execute("SELECT COUNT(*) FROM elective_slot").fetchone()[0]
    n_plan = conn.execute("SELECT COUNT(*) FROM plan_item").fetchone()[0]
    if n_plan == 0 and declared == 0:
        # แคตตาล็อกวิชา (เช่น GENED) ไม่มีแผนรายเทอมให้เทียบยอด
        add("CHK1", "หน่วยกิตรวมของแผน = หน่วยกิตที่หลักสูตรประกาศ", True,
            "แคตตาล็อกวิชาไม่มีแผนรายเทอม — ข้ามการเทียบ")
    else:
        add("CHK1", "หน่วยกิตรวมของแผน = หน่วยกิตที่หลักสูตรประกาศ", total == declared,
            f"แผนรวม {total} · ประกาศไว้ {declared}"
            + (f" (รวมวิชาเลือกที่นับในยอด {forced} หน่วยกิต)" if forced else "")
            + (f" · มีวิชาเลือกเสรี {free} รายการ" if free else "")
            + (f" · วิชาเลือกที่ไม่ระบุเทอม {slots} รายการ (ไม่นับในแผน)" if slots else ""))

    # ── CHK2 ทุกรหัสในแผน ต้องมีคำอธิบายรายวิชาในเล่ม ───────────────
    orphan = conn.execute("""
        SELECT DISTINCT p.code FROM plan_item p
        LEFT JOIN course c ON c.code = p.code
        WHERE c.code IS NULL
    """).fetchall()
    add("CHK2", "ทุกรหัสวิชาในแผน มีคำอธิบายรายวิชา", not orphan,
        "ไม่พบคำอธิบายของ: " + ", ".join(r["code"] for r in orphan[:8])
        + (f" (และอีก {len(orphan) - 8})" if len(orphan) > 8 else "")
        if orphan else "ครบทุกรหัส")

    # ── CHK3 รูปแบบรหัสวิชา ────────────────────────────────────────
    #    ยกเว้นช่องวิชา PLACEHOLDER_ ที่เราตั้งใจสร้างจากรหัส wildcard ในเล่ม
    #    (ถ้าไม่ยกเว้น กฎนี้จะเตือนทุกครั้งที่เล่มเขียน 90644xxx ซึ่งเล่มเขียนถูกแล้ว)
    bad = conn.execute("""
        SELECT code FROM (
            SELECT code FROM course UNION SELECT code FROM plan_item
        )
        WHERE code NOT LIKE 'PLACEHOLDER\\_%' ESCAPE '\\'
          AND (code GLOB '*[^0-9]*' OR LENGTH(code) <> 8)
    """).fetchall()
    n_slot = conn.execute(
        "SELECT COUNT(*) FROM course WHERE code LIKE 'PLACEHOLDER\\_%' ESCAPE '\\'"
    ).fetchone()[0]
    add("CHK3", "รหัสวิชาเป็นตัวเลข 8 หลักทุกรายการ", not bad,
        "ผิดรูปแบบ: " + ", ".join(r["code"] for r in bad[:8]) if bad else
        "ถูกต้องทุกรายการ" + (f" (ยกเว้นช่องวิชา {n_slot} รายการ)" if n_slot else ""))

    # ── CHK4 หน่วยกิตในแผน ต้องตรงกับหน่วยกิตในคำอธิบายรายวิชา ──────
    mismatch = conn.execute("""
        SELECT p.code, p.credits AS plan_cr, c.credits AS course_cr
        FROM plan_item p JOIN course c ON c.code = p.code
        WHERE p.credits <> c.credits
    """).fetchall()
    add("CHK4", "หน่วยกิตในแผน ตรงกับคำอธิบายรายวิชา", not mismatch,
        "; ".join(f"{r['code']} แผน {r['plan_cr']} แต่คำอธิบาย {r['course_cr']}"
                  for r in mismatch[:5]) if mismatch else "ตรงกันทุกรายการ")

    # ── CHK5 วิชาบังคับก่อน ต้องอยู่ภาคเรียนที่มาก่อนจริง ────────────
    #    ใช้ (year*10 + semester) เป็นลำดับเวลาอย่างง่าย
    viol = conn.execute("""
        SELECT r.code, r.requires,
               a.year || '/' || a.semester AS at_course,
               b.year || '/' || b.semester AS at_prereq
        FROM prerequisite r
        JOIN plan_item a ON a.code = r.code
        JOIN plan_item b ON b.code = r.requires
        WHERE r.kind = 'pre'
          AND (b.year * 10 + b.semester) >= (a.year * 10 + a.semester)
    """).fetchall()
    add("CHK5", "วิชาบังคับก่อน อยู่ภาคเรียนก่อนวิชาที่อ้างถึง", not viol,
        "; ".join(f"{r['code']} ({r['at_course']}) ต้องเรียน {r['requires']} "
                  f"({r['at_prereq']}) มาก่อน" for r in viol[:5])
        if viol else "ลำดับถูกต้องทุกคู่")

    # ── CHK6 ห้ามมีวิชาซ้ำในภาคเรียนเดียวกัน ───────────────────────
    dup = conn.execute("""
        SELECT year, semester, code, COUNT(*) AS n
        FROM plan_item
        WHERE alt_group IS NULL          -- วิชาเลือกกลุ่มเดียวกันไม่นับเป็นซ้ำ
        GROUP BY year, semester, code
        HAVING n > 1
    """).fetchall()
    add("CHK6", "ไม่มีวิชาซ้ำในภาคเรียนเดียวกัน", not dup,
        "; ".join(f"{r['code']} ที่ปี {r['year']}/{r['semester']} ซ้ำ {r['n']} ครั้ง"
                  for r in dup[:5]) if dup else "ไม่มีรายการซ้ำ")

    # ── CHK7 ภาระหน่วยกิตต่อภาคเรียน อยู่ในเกณฑ์ ────────────────────
    #    ข้อยกเว้นสำคัญ: ภาคสหกิจศึกษา / ฝึกงาน มีวิชาเดียว 6 หน่วยกิต
    #    ถ้าไม่ยกเว้น กฎนี้จะเตือนผิดทุกหลักสูตรที่มีสหกิจ
    #    (บทเรียนตรงจากบั๊ก has_block_course ใน Lab 7B)
    #
    #    ข้อจำกัดที่ต้องรู้ตัว: ทุกข้อยกเว้นคือจุดบอด
    #    เกณฑ์ "มีวิชา >= 6 หน่วยกิต" แปลว่าถ้าสกัดหน่วยกิตผิดจาก 3 เป็น 6
    #    ภาคเรียนนั้นจะถูกยกเว้นทันที และ CHK7 จะเงียบทั้งที่ข้อมูลผิด
    #    นี่คือราคาที่ต้องจ่ายเพื่อลดการเตือนผิด — ไม่มีกฎใดได้ทั้งสองอย่าง
    #    สิ่งที่ทำได้คือรู้ว่าจุดบอดอยู่ตรงไหน แล้วให้ CHK4 ช่วยคุมอีกชั้น
    block_rows = conn.execute("""
        SELECT DISTINCT year, semester FROM plan_item
        WHERE credits >= 6
           OR note LIKE '%สหกิจ%' OR note LIKE '%ฝึกงาน%'
           OR category LIKE '%สหกิจ%' OR type LIKE '%สหกิจ%'
           OR code IN (SELECT code FROM course
                       WHERE name_th LIKE '%สหกิจ%' OR name_th LIKE '%ฝึกงาน%')
    """).fetchall()
    block = {(r["year"], r["semester"]) for r in block_rows}
    out_of_range = []
    for r in rows:
        key = (r["year"], r["semester"])
        if key in block:
            continue                       # ภาคบล็อก ไม่ใช้เกณฑ์ปกติ
        if r["semester"] == 3:
            continue                       # ภาคฤดูร้อน หน่วยกิตน้อยเป็นปกติ
        if not (MIN_CREDITS_PER_SEM <= r["credits"] <= MAX_CREDITS_PER_SEM):
            out_of_range.append(f"ปี {r['year']}/{r['semester']} = {r['credits']} หน่วยกิต")
    add("CHK7", f"หน่วยกิตต่อภาคเรียนอยู่ระหว่าง {MIN_CREDITS_PER_SEM}"
                f"–{MAX_CREDITS_PER_SEM}", not out_of_range,
        "; ".join(out_of_range[:5]) if out_of_range
        else f"ผ่านทุกภาค (ยกเว้นภาคบล็อก {len(block)} ภาค และภาคฤดูร้อน)")

    return results


def cmd_verify(args) -> None:
    conn = open_db(args.database, readonly=True)
    results = verify_db(conn)
    conn.close()

    print()
    print("  ผลการตรวจความสอดคล้องของข้อมูล")
    print("  " + "=" * 74)
    n_fail = 0
    for r in results:
        mark = "ผ่าน  " if r["ok"] else "ไม่ผ่าน"
        if not r["ok"]:
            n_fail += 1
        print(f"  [{mark}] {r['id']}  {r['name']}")
        if r["detail"]:
            print(f"           {r['detail']}")
    print("  " + "=" * 74)
    print(f"  ผ่าน {len(results) - n_fail} จาก {len(results)} ข้อ")
    if n_fail:
        print()
        print("  ข้อที่ไม่ผ่านอาจเกิดได้สองทาง และต้องแยกให้ออกก่อนแก้")
        print("    (ก) สกัดผิด        -> กลับไปแก้ prompt หรือแก้ JSON")
        print("    (ข) เล่มเขียนแบบนั้นจริง -> ต้องแก้กฎให้รู้จักข้อยกเว้นนี้")
    if args.output:
        Path(args.output).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  บันทึกผลที่ {args.output}")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 5 — ถามเป็นภาษาคน ตอบด้วย SQL
# ═══════════════════════════════════════════════════════════════════════

# คำสั่งที่ห้ามปรากฏใน SQL ที่ LLM สร้าง
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex|truncate)\b", re.I)


def guard_sql(sql: str) -> str:
    """
    ด่านความปลอดภัยชั้นที่สอง — ตรวจ SQL ก่อนรัน

    ชั้นที่หนึ่งคือการเปิดฐานข้อมูลแบบอ่านอย่างเดียว
    ทำไมต้องมีสองชั้น: ชั้นแรกกันการ "แก้ข้อมูล" ได้ก็จริง
    แต่กันการดึงข้อมูลจนล้น หรือ query ที่รันไม่จบไม่ได้
    ชั้นนี้จึงเสริมเรื่องนั้น และทำให้ข้อผิดพลาดอ่านง่ายขึ้นด้วย
    """
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise ValueError("SQL ว่างเปล่า")
    if ";" in s:
        raise ValueError("ห้ามมีหลายคำสั่งใน query เดียว")
    if not re.match(r"^\s*(select|with)\b", s, re.I):
        raise ValueError("อนุญาตเฉพาะ SELECT หรือ WITH เท่านั้น")
    if FORBIDDEN_SQL.search(s):
        raise ValueError("พบคำสั่งที่ไม่อนุญาตใน SQL")
    if not re.search(r"\blimit\b", s, re.I):
        s += f" LIMIT {SQL_ROW_LIMIT}"
    return s


SQL_PROMPT = """คุณคือผู้ช่วยแปลงคำถามภาษาไทยเป็นคำสั่ง SQL ของ SQLite

โครงสร้างฐานข้อมูล
{ddl}

ตัวอย่าง
คำถาม: ปี 2 เทอม 1 เรียนกี่หน่วยกิต
SQL: SELECT credits FROM v_semester_credits WHERE year=2 AND semester=1

คำถาม: วิชาไหนบ้างที่ต้องเรียน 06026240 มาก่อน
SQL: SELECT code FROM prerequisite WHERE requires='06026240' AND kind='pre'

คำถาม: ต้องเรียนวิชาอะไรมาก่อนจึงจะลงเรียน 06026215 ได้
SQL: SELECT requires FROM prerequisite WHERE code='06026215' AND kind='pre'

คำถาม: หลักสูตรนี้มีกี่หน่วยกิต
SQL: SELECT total_credits FROM program

คำถาม: วิชา 06026240 เรียนได้ตอนไหน
SQL: SELECT code, name_th, terms, source FROM v_course_terms WHERE code='06026240'

คำถาม: ปี 3 เทอม 1 มีวิชาบังคับกี่วิชา
SQL: SELECT COUNT(*) FROM plan_item WHERE year=3 AND semester=1 AND type='บังคับ'

คำถาม: หน่วยกิตวิชาเลือกทั้งหมดเท่าไร
SQL: SELECT SUM(credits) FROM plan_item WHERE type='เลือก'

กติกา
- เขียน SQL คำสั่งเดียว ขึ้นต้นด้วย SELECT หรือ WITH เท่านั้น
- ห้ามใช้ INSERT UPDATE DELETE DROP หรือคำสั่งที่แก้ไขข้อมูล
- ถามว่าภาคเรียนไหนมีกี่หน่วยกิต ให้ใช้ v_semester_credits เสมอ
  ห้ามใช้ SUM(credits) จาก v_plan เพราะจะนับวิชาเลือกซ้ำ
- ถามว่าเรียนวิชาอะไรบ้าง ให้ใช้ v_plan เพราะมีชื่อวิชาอยู่แล้ว
- ถามว่า "วิชานี้เรียนปีไหน/เทอมไหน/ตอนไหน" ให้ใช้ v_course_terms เสมอ
  เพราะวิชาเลือกบางวิชาไม่ได้อยู่ในแผนรายเทอม แต่อยู่ในตาราง elective_slot
  ซึ่ง v_course_terms รวมมาให้แล้วทั้งสองทาง
- ถามเรื่องวิชาบังคับ/วิชาเลือก ให้ใช้คอลัมน์ type ('บังคับ' หรือ 'เลือก')
  ถามเรื่องหมวดวิชา ให้ใช้คอลัมน์ category — ห้ามค้นจาก note
- ให้เลือกคอลัมน์ pages ติดมาด้วยเสมอถ้าตารางหรือวิวนั้นมีคอลัมน์นี้ (ฐานเก่าใช้ชื่อ source_page)
  เพราะคำตอบต้องอ้างอิงเลขหน้าในเล่มหลักสูตรได้ — pages เก็บเป็นข้อความ JSON เช่น [23, 287]
  ห้ามเอาไปกรองหรือเทียบตัวเลขโดยตรง ให้เลือกมาเฉย ๆ
- ตอบเป็น SQL ล้วน ไม่ต้องมีคำอธิบายและไม่ต้องมี markdown fence

คำถาม: {question}
SQL:"""

ANSWER_PROMPT = """ตอบคำถามต่อไปนี้เป็นภาษาไทย โดยใช้ผลลัพธ์จากฐานข้อมูลเท่านั้น

คำถาม: {question}

ผลลัพธ์จากฐานข้อมูล (รูปแบบ JSON):
{rows}

กติกา
- ตอบสั้น ตรงประเด็น ไม่ต้องอธิบายวิธีการ
- ใช้เฉพาะตัวเลขและข้อความที่ปรากฏในผลลัพธ์ ห้ามเพิ่มข้อมูลจากความรู้ของคุณเอง
- ถ้าผลลัพธ์ว่างเปล่า ให้ตอบว่า "ไม่พบข้อมูลนี้ในเล่มหลักสูตร"
- ถ้าผลลัพธ์มีคอลัมน์ pages (หรือ source_page) ให้ใส่เลขหน้าเหล่านั้นลงใน source_pages
  ใช้เฉพาะเลขที่ปรากฏในผลลัพธ์ ห้ามเดาเลขหน้าเอง ถ้าไม่มีให้ใส่ []
- ตอบเป็น JSON รูปแบบนี้เท่านั้น
  {{"answer": "...", "source_pages": [12, 13]}}
"""

# หมายเหตุสำหรับคนอ่านโค้ด: วงเล็บปีกกาในบรรทัดบนต้องเขียนเป็น {{ }}
# เพราะสตริงนี้ถูกส่งเข้า .format() — ถ้าเขียน { } เดี่ยว Python จะมองว่า
# เป็นชื่อตัวแปรแล้วโยน KeyError ทุกครั้งที่ถามคำถาม


def clean_sql_output(s: str) -> str:
    """ตัด <think> และ fence ออกจาก SQL ที่โมเดลตอบมา"""
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)
    s = re.sub(r"```(?:sql)?", "", s).strip()
    # งานนี้ใช้ query บรรทัดเดียว: เก็บเฉพาะบรรทัด SQL แรก
    # เพื่อไม่ให้ reasoning หรือคำอธิบายที่หลุดมาถูกส่งเข้า SQLite
    m = re.search(r"(?im)^\s*(select|with)\b[^\r\n]*", s)
    return m.group(0).strip() if m else s


def pages_of(rows: list[dict]) -> list[int]:
    """
    รวมเลขหน้าจากแถวผลลัพธ์

    รับทุกคอลัมน์ที่ลงท้ายด้วย pages หรือ source_page เพราะ JOIN มักเปลี่ยนชื่อคอลัมน์
    เป็น c.pages หรือ p.pages ตามที่ LLM เขียน SQL มา; ค่าอาจเป็นข้อความ JSON "[23, 287]",
    list หรือเลขเดี่ยว (ฐานเก่า) — เก็บเลขทุกตัว ไม่ใช่แค่ตัวแรก
    """
    pages: set[int] = set()
    for r in rows:
        for key, value in r.items():
            k = str(key).lower()
            if not (k.endswith("pages") or k.endswith("source_page")):
                continue
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                items = list(value)
            else:
                items = re.findall(r"\d+", str(value))
            for item in items:
                if str(item).isdigit() and int(item) > 0:
                    pages.add(int(item))
    return sorted(pages)


def with_citation(answer: str, pages: list[int]) -> str:
    """
    ต่อท้ายคำตอบด้วยการอ้างอิงหน้า

    ทำไมต้องต่อในโค้ด ไม่ปล่อยให้โมเดลเขียนเอง
        เพราะการอ้างอิงคือคำสัญญาว่า "ไปเปิดหน้านี้แล้วจะเจอ"
        ถ้าปล่อยให้โมเดลพิมพ์เลขหน้าเอง มันจะเดาเมื่อไม่รู้ ซึ่งอันตรายกว่าไม่อ้างเลย
        เลขที่ต่อท้ายตรงนี้มาจากคอลัมน์ source_page ของแถวที่ query ได้จริงเท่านั้น
    """
    answer = (answer or "").strip()
    if not pages or not answer:
        return answer
    if "อ้างอิงหน้า" in answer:
        return answer
    if len(pages) == 1:
        return f"{answer} (อ้างอิงหน้า {pages[0]})"
    return f"{answer} (อ้างอิงหน้า {', '.join(str(p) for p in pages)})"


def ask(conn: sqlite3.Connection, question: str,
        verbose: bool = True) -> dict:
    """
    ถามหนึ่งคำถาม — คืน dict ที่มี sql, rows, answer, error

    ขั้นตอน: สร้าง SQL -> ตรวจ -> รัน -> สรุปเป็นภาษาไทย
    ถ้ารันไม่ผ่าน จะให้โมเดลลองใหม่หนึ่งครั้งพร้อมข้อความ error
    แล้วถ้ายังไม่ผ่านอีก ให้ยอมแพ้ ไม่เดาคำตอบ
    """
    result: dict[str, Any] = {
        "question": question, "sql": None, "rows": [], "answer": None,
        "error": None, "sql_model_output": None, "answer_model_output": None,
        "source_pages": [], "page_warning": None,
    }
    ddl = DDL.strip()
    prompt = SQL_PROMPT.format(ddl=ddl, question=question)

    for attempt in range(2):
        try:
            raw_sql = ollama_generate(
                prompt + '\nตอบเป็น JSON รูปแบบ {"sql": "SELECT ..."} เท่านั้น',
                fmt={
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                    "additionalProperties": False,
                }, num_ctx=4096, num_predict=256)
            result["sql_model_output"] = raw_sql
            parsed_sql = parse_json_loose(raw_sql)
            sql = clean_sql_output(
                str(parsed_sql.get("sql", "")) if isinstance(parsed_sql, dict)
                else raw_sql)
            sql = guard_sql(sql)
            result["sql"] = sql
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
            result["rows"] = rows
            result["error"] = None
            break
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
            if verbose:
                print(f"    รอบที่ {attempt + 1} รันไม่ผ่าน: {e}")
            if attempt == 1:
                result["answer"] = "ไม่สามารถตอบคำถามนี้ได้ กรุณาตรวจสอบเอง"
                return result
            prompt = (SQL_PROMPT.format(ddl=ddl, question=question)
                      + f"\n\nSQL ที่ลองไปแล้วมีข้อผิดพลาด: {e}\nเขียนใหม่ให้ถูก\nSQL:")

    # ปฏิเสธที่จะเดา เมื่อไม่มีข้อมูล — จุดนี้สำคัญกว่าที่คิด
    if not result["rows"]:
        result["answer"] = "ไม่พบข้อมูลนี้ในเล่มหลักสูตร"
        return result

    # เลขหน้าที่ "ของจริง" คือเลขที่ติดมากับแถวผลลัพธ์ ไม่ใช่เลขที่โมเดลพิมพ์
    # เราจึงเก็บไว้เองก่อน แล้วค่อยเอาไปเทียบกับสิ่งที่โมเดลตอบ
    result["source_pages"] = pages_of(result["rows"])

    raw_answer = ollama_generate(
        ANSWER_PROMPT.format(
            question=question,
            rows=json.dumps(result["rows"][:40], ensure_ascii=False)),
        fmt={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "source_pages": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["answer"],
            "additionalProperties": False,
        }, num_ctx=4096, num_predict=256).strip()
    result["answer_model_output"] = raw_answer
    parsed_answer = parse_json_loose(raw_answer)
    result["answer"] = (
        str(parsed_answer.get("answer", "")).strip()
        if isinstance(parsed_answer, dict) else raw_answer)
    result["answer"] = re.sub(
        r"<think>.*?</think>", "", result["answer"], flags=re.S).strip()

    # ยึดเลขหน้าจากฐานข้อมูลเป็นหลัก รับเฉพาะเลขที่ยืนยันได้จากแถวผลลัพธ์
    # ถ้าโมเดลแต่งเลขหน้าขึ้นมาเอง จะถูกตัดทิ้งตรงนี้ ไม่หลุดไปถึงผู้ใช้
    if isinstance(parsed_answer, dict):
        claimed = parsed_answer.get("source_pages") or []
        if isinstance(claimed, list):
            confirmed = [int(p) for p in claimed
                         if str(p).isdigit() and int(p) in result["source_pages"]]
            invented = [p for p in claimed
                        if not (str(p).isdigit() and int(p) in result["source_pages"])]
            if invented:
                result["page_warning"] = f"โมเดลอ้างหน้าที่ไม่มีในผลลัพธ์: {invented}"
            if confirmed:
                result["source_pages"] = sorted(set(confirmed))

    result["answer"] = with_citation(result["answer"], result["source_pages"])
    return result


def cmd_ask(args) -> None:
    conn = open_db(args.database, readonly=True)
    r = ask(conn, args.question)
    conn.close()
    print()
    print(f"  คำถาม : {r['question']}")
    print(f"  SQL   : {r['sql']}")
    print(f"  แถว   : {len(r['rows'])}")
    print(f"  คำตอบ : {r['answer']}")
    print(f"  อ้างอิง: " + (", ".join(f"หน้า {p}" for p in r["source_pages"])
                            or "ไม่มีเลขหน้าในผลลัพธ์"))
    print(f"  Raw SQL   : {r['sql_model_output']}")
    print(f"  Raw answer: {r['answer_model_output']}")
    if r.get("page_warning"):
        print(f"  ! {r['page_warning']}")
    if r["error"]:
        print(f"  หมายเหตุ: {r['error']}")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 6 — ประเมินด้วยชุดคำถามทอง
# ═══════════════════════════════════════════════════════════════════════
#
#  วิธีให้คะแนน: เทียบที่ "ผลลัพธ์ของ SQL" ไม่ใช่ "ข้อความคำตอบ"
#
#  ถ้าเทียบข้อความ จะเจอปัญหาว่า "19 หน่วยกิต" กับ "รวม 19 หน่วยกิต"
#  ควรได้คะแนนเท่ากัน แต่เทียบตรง ๆ จะนับเป็นผิด
#  การเทียบที่ค่าตัวเลข/ชุดรหัสวิชาจึงยุติธรรมและทำอัตโนมัติได้จริง
# ═══════════════════════════════════════════════════════════════════════

def _values_of(rows: list[dict]) -> set[str]:
    """ดึงค่าทั้งหมดในผลลัพธ์ออกมาเป็นชุดข้อความ เพื่อเทียบแบบไม่สนลำดับคอลัมน์"""
    out = set()
    for r in rows:
        for v in r.values():
            if v is not None:
                out.add(str(v).strip())
    return out


def score_one(expect: dict, got: dict) -> tuple[bool, str]:
    """
    ให้คะแนนหนึ่งข้อ ตามชนิดของคำถาม

    value  — ต้องมีค่านี้อยู่ในผลลัพธ์
    set    — ชุดคำตอบต้องตรงกันทั้งหมด (ใช้กับคำถาม "มีวิชาอะไรบ้าง")
    count  — จำนวนแถวต้องเท่ากับที่คาด
    none   — ต้องตอบว่าไม่พบ (ใช้ทดสอบว่าระบบยอมรับได้ว่าไม่รู้)
    """
    kind = expect.get("type", "value")
    rows = got.get("rows") or []
    vals = _values_of(rows)

    if kind == "none":
        ok = (len(rows) == 0)
        return ok, "ตอบว่าไม่พบตามที่ควร" if ok else f"ควรไม่พบ แต่ได้ {len(rows)} แถว"

    if kind == "count":
        ok = (len(rows) == int(expect["value"]))
        return ok, f"ได้ {len(rows)} แถว คาด {expect['value']}"

    if kind == "set":
        want = {str(x).strip() for x in expect["value"]}
        ok = want.issubset(vals)
        missing = want - vals
        return ok, "ครบ" if ok else f"ขาด {', '.join(sorted(missing)[:5])}"

    want = str(expect["value"]).strip()
    ok = want in vals
    return ok, "ตรง" if ok else f"ไม่พบค่า {want} (ได้ {sorted(vals)[:5]})"


def cmd_eval(args) -> None:
    conn = open_db(args.database, readonly=True)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    rows_out = []
    n_ok = n_sql_ok = n_cited = n_answerable = 0

    print(f"  ประเมิน {len(questions)} คำถาม")
    print("  " + "-" * 74)
    for i, q in enumerate(questions, 1):
        t0 = time.time()
        got = ask(conn, q["question"], verbose=False)
        ok, why = score_one(q["expect"], got)
        sql_ok = got["error"] is None
        n_ok += ok
        n_sql_ok += sql_ok
        rows_out.append({**q, "sql": got["sql"], "n_rows": len(got["rows"]),
                         "error": got["error"],
                         "sql_model_output": got["sql_model_output"],
                         "answer_model_output": got["answer_model_output"],
                         "answer": got["answer"],
                         "source_pages": got.get("source_pages") or [],
                         "page_warning": got.get("page_warning"),
                         "correct": ok, "why": why,
                         "seconds": round(time.time() - t0, 1)})
        n_cited += bool(got.get("source_pages"))
        n_answerable += bool(got.get("rows"))
        print(f"  {i:>2}. [{'ถูก ' if ok else 'ผิด'}] {q['question'][:44]:<46} {why[:26]}")
    conn.close()

    print("  " + "-" * 74)
    n = len(questions)
    print(f"  SQL รันผ่าน   {n_sql_ok}/{n}  ({n_sql_ok / n:.0%})")
    print(f"  ตอบถูก        {n_ok}/{n}  ({n_ok / n:.0%})")
    if n_answerable:
        print(f"  อ้างอิงหน้าได้ {n_cited}/{n_answerable}  "
              f"({n_cited / n_answerable:.0%} ของข้อที่มีข้อมูลตอบ)")
        if n_cited == 0:
            print("    ! ไม่มีข้อไหนอ้างอิงหน้าได้เลย — ฐานข้อมูลยังไม่มี source_page")
    print()
    print("  แยกสองตัวเลขนี้เสมอ เพราะมันบอกคนละเรื่อง")
    print("    SQL รันผ่านแต่ตอบผิด = โมเดลเข้าใจคำถามผิด (แก้ที่ prompt/ตัวอย่าง)")
    print("    SQL รันไม่ผ่าน       = โมเดลเขียน SQL ไม่เป็น (แก้ที่ schema/VIEW)")

    if args.output:
        Path(args.output).write_text(
            json.dumps(rows_out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  บันทึกผลที่ {args.output}")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 6.5 — เทียบผลสกัดกับเฉลย (ground truth) ทีละฟิลด์
# ═══════════════════════════════════════════════════════════════════════
#
#  ทำไมต้องมีส่วนนี้ และทำไมต้องทำก่อนแก้อย่างอื่น
#      ถ้าไม่มีตัวเลขวัด การ "ปรับ prompt แล้วรู้สึกว่าดีขึ้น" คือการเดา
#      ทุกครั้งที่แก้โค้ดโดยไม่มีตัวเลขเทียบ เรามีโอกาสครึ่งหนึ่งที่จะทำให้แย่ลง
#      แล้วไม่รู้ตัวจนถึงวันส่งงาน
#
#  ทำไมวัดทีละฟิลด์ ไม่วัดว่า "ทั้งวิชาถูกไหม"
#      ถ้าวัดทั้งวิชา วิชาที่ผิดแค่ชื่อภาษาอังกฤษจะถูกนับว่าผิดเท่ากับ
#      วิชาที่ผิดทั้งรหัสและหน่วยกิต ซึ่งบอกไม่ได้ว่าควรไปแก้ตรงไหน
#      การแยกเป็น Precision/Recall รายฟิลด์บอกตรง ๆ ว่า
#      "หน่วยกิตแม่น 98% แต่ prerequisite แม่น 40%" — แล้วเราจะรู้ว่าต้องแก้อะไร
#
#  นิยามที่ใช้ (ระดับฟิลด์ นับเฉพาะวิชาที่จับคู่รหัสกันได้)
#      TP = เราเติมค่ามา และตรงกับเฉลย
#      FP = เราเติมค่ามา แต่ไม่ตรงกับเฉลย (หรือวิชานั้นไม่มีในเฉลยเลย)
#      FN = เฉลยมีค่า แต่เราไม่ได้เติม หรือเติมผิด
#  Precision = TP/(TP+FP) "ที่ตอบมา ถูกกี่เปอร์เซ็นต์"
#  Recall    = TP/(TP+FN) "ที่ควรได้ ได้มากี่เปอร์เซ็นต์"
# ═══════════════════════════════════════════════════════════════════════

GT_FIELDS = ("code", "name_th","name_en", "credits", "year", "semester",
             "category", "type", "prerequisite")


def _norm_text(v: Any) -> str:
    """ตัดช่องว่างซ้ำและอักขระที่ต่างกันแต่ความหมายเดียวกันออก"""
    s = str(v if v is not None else "").strip()
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def _norm_credits(v: Any) -> str:
    """
    เทียบหน่วยกิตแบบยุติธรรม

    "3(2-2-5)" กับ " 3 (2-2-5) " ต้องนับว่าตรงกัน
    ส่วน "3(3-0-6) หรือ 3(2-2-5)" เก็บทั้งก้อนไว้เทียบตรง ๆ
    เพราะการตัดให้เหลือแบบแรกคือการตัดสินใจแทนเล่ม ซึ่งไม่ใช่หน้าที่ของตัววัด
    """
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", "", s)
    return s.casefold()


def _credits_match(want: str, got: str) -> bool:
    """
    ตัดสินว่าหน่วยกิตสองฝั่งตรงกันหรือไม่

    ฝั่งหนึ่งอาจเป็น "3(2-2-5)" (ข้อความจากเล่ม) อีกฝั่งอาจเป็น "3" (ตัวเลขในฐาน)
    ถ้าเทียบข้อความตรง ๆ จะได้ 0% ทั้งที่หน่วยกิตถูกทุกวิชา — เป็นการวัดที่หลอกตัวเอง
    กติกาคือ ถ้าทั้งสองฝั่งมีวงเล็บชั่วโมง ให้เทียบทั้งก้อน
    ถ้าฝั่งใดฝั่งหนึ่งมีแค่จำนวนหน่วยกิต ให้เทียบเฉพาะจำนวนหน่วยกิต
    """
    if want == got:
        return True
    if not want or not got:
        return False
    if "(" in want and "(" in got:
        return False
    a = re.match(r"\d+", want)
    b = re.match(r"\d+", got)
    return bool(a and b and a.group() == b.group())


def _norm_prereq(v: Any) -> str:
    """เทียบ prerequisite ที่ระดับ 'ชุดรหัสวิชา' ไม่ใช่ข้อความ"""
    codes = _lab7b_codes(v)
    if codes:
        return ",".join(sorted(set(codes)))
    s = _norm_text(v)
    # "ไม่มี" "-" "ไม่มีี" ฯลฯ ถือว่าไม่มีเงื่อนไข เทียบเท่าค่าว่าง
    if s in ("", "-", "ไม่มี", "none", "null", "n/a", "ไม่ระบุ"):
        return ""
    return s


def _norm_field(field: str, value: Any) -> str:
    if field == "credits":
        return _norm_credits(value)
    if field == "prerequisite":
        return _norm_prereq(value)
    if field in ("year", "semester"):
        # ปี/ภาค "0" (วิชาเลือกที่ไม่ผูกเทอม จากแคตตาล็อกที่ไม่มีตารางแผน) กับ null
        # ของเฉลย (GENED เก็บ None) สื่อความหมายเดียวกันคือ "ไม่ผูกปี/ภาค"
        # ต้อง normalize ให้เท่ากัน (ว่างทั้งคู่) เหมือนที่ lab7b_curriculum.py ทำใน
        # evaluate()/_ys() ไว้แล้ว ไม่งั้นแคตตาล็อกวิชาทุกตัวจะกลาย FP รัว ๆ
        # (ปี/ภาคจริงที่ระบุเป็น 0 ไม่มีในทางปฏิบัติ ปีเริ่มที่ 1 ภาคเริ่มที่ 1 เสมอ)
        s = str(value if value is not None else "").strip()
        m = re.search(r"-?\d+", s)
        got = m.group() if m else ""
        return "" if got == "0" else got
    return _norm_text(value)


def _gt_courses(obj: Any) -> list[dict]:
    """
    ดึงรายการวิชาออกจากไฟล์เฉลย โดยรับได้หลายรูปแบบ

    ไฟล์เฉลยของแต่ละรุ่นวางโครงไม่เหมือนกัน (บ้าง {"courses": [...]}
    บ้างเป็น list ตรง ๆ) การรับหลายรูปแบบถูกกว่าการบังคับให้คนแก้ไฟล์เฉลย
    """
    if isinstance(obj, list):
        return [c for c in obj if isinstance(c, dict)]
    if isinstance(obj, dict):
        for key in ("courses", "data", "items", "records", "rows"):
            v = obj.get(key)
            if isinstance(v, list):
                return [c for c in v if isinstance(c, dict)]
        # เผื่อกรณี {"06026240": {...}, ...}
        if all(isinstance(v, dict) for v in obj.values()) and obj:
            out = []
            for k, v in obj.items():
                out.append({**v, "code": v.get("code", k)})
            return out
    return []


def _norm_for_dup_check(c: dict) -> tuple:
    """ลายนิ้วมือคร่าวๆ ของวิชา ใช้แยก 'หน้าเดียวกันเจอซ้ำ' ออกจาก 'วิชาคนละตัวที่รหัส wildcard ชนกัน'"""
    return (str(c.get("name_th") or "").strip(), str(c.get("year") or ""),
            str(c.get("semester") or ""))


_TRAILING_NUM_RE = re.compile(r"(\d+)\s*$")
# วิชาเลือกแบบ "A หรือกลุ่มวิชาที่ 1-4" / "A OR COURSE GROUP 1-4" มีช่วงเลขบอกกลุ่ม
# (1-4) ต่อท้ายเป็นข้อความคงที่เหมือนกันทุก slot — ไม่ใช่เลขลำดับที่ต้องใช้แยก slot
# ตัดตั้งแต่ "หรือ"/"OR" ออกก่อนอ่านเลขลำดับจริงที่อยู่ก่อนหน้า (ดูคอมเมนต์ใน
# _slot_number)
_ALT_CLAUSE_RE = re.compile(r"หรือ|\bOR\b", re.IGNORECASE)
# key ที่ resolve เลขลำดับไปแล้วในรอบก่อนหน้า (ลงท้ายด้วย "_ตัวเลข") — wildcard code
# ดิบจากเล่มไม่มีทางลงท้ายแบบนี้เอง (_WILDCARD_RE บังคับให้ลงท้ายด้วย x/X เสมอ)
# ใช้แยกว่า "ยังไม่เคยตั้ง suffix" (ต้องคำนวณจาก _slot_number) กับ
# "ตั้งไปแล้วจากรอบก่อน" (เก็บไว้เฉย ๆ ไม่งั้นจะต่อ suffix ซ้อนกันไปเรื่อย ๆ
# ทุกครั้งที่ _index_by_code ถูกเรียกซ้ำในแต่ละขั้นของ pipeline)
_RESOLVED_SUFFIX_RE = re.compile(r"_\d+$")


def _slot_number(record: dict) -> int | None:
    """
    ดึงเลขลำดับที่ฝังอยู่ในชื่อวิชาเอง เช่น "วิชาเลือกเสรี 2" -> 2,
    "FREE ELECTIVE COURSE 1" -> 1

    ใช้แทนการนับ "ลำดับที่เจอในลิสต์ที่สกัดมา" ตอนตั้งชื่อ key ให้ช่องวิชา wildcard
    ที่ซ้ำกัน (PLACEHOLDER_XXXXXXXX, PLACEHOLDER_XXXXXXXX_2, ...) — บั๊กที่พบจริง:
    ถ้า LLM สกัดสองช่องออกมาไม่ตรงลำดับกับเล่ม (เช่น เจอ "วิชาเลือกเสรี 2" ก่อน
    "วิชาเลือกเสรี 1") key แบบนับลำดับเดิมจะสลับ slot 1/2 กัน ทำให้ name_th,
    name_en, year, semester ของทั้งคู่ผิดพร้อมกันหมด ทั้งที่แต่ละแถวสกัดถูกแล้ว
    เอาเลขจากเนื้อชื่อเองจึงกันการสลับนี้ได้ตรง ๆ โดยไม่ต้องพึ่งลำดับการสกัด

    ⚠️ บั๊กที่พบจริงกับข้อมูลจริง (แก้ตรงนี้): บางชื่อลงท้ายด้วยช่วงกลุ่มวิชาคงที่
    เช่น "...ธุรกิจ 1 หรือกลุ่มวิชาที่ 1-4" — ถ้าอ่านแค่ "เลขท้ายสุดของสตริง" จะได้
    เลขท้ายของช่วง (4) ซึ่งเหมือนกันทั้ง slot 1 และ slot 2 (ทั้งคู่ลงท้าย "...1-4")
    ทำให้สอง slot ชนกันเป็นเลขเดียว (_4) แล้วโดน fallback ต่อ suffix ซ้อนกัน
    (_4_4_4) เลขลำดับจริงคือเลขที่อยู่ *ก่อน* คำว่า "หรือ"/"OR" ต้องตัดส่วนนั้น
    ทิ้งก่อนอ่านเลขท้าย
    """
    for field in ("name_th", "name_en"):
        s = str(record.get(field) or "").strip()
        if not s:
            continue
        head = _ALT_CLAUSE_RE.split(s, maxsplit=1)[0]
        m = _TRAILING_NUM_RE.search(head)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 20:   # กันเลขหน่วยกิต/รหัสอื่นที่ดันมาลงท้ายชื่อโดยบังเอิญ
                return n
    return None


def _dedup_insert(out: dict, fingerprints: dict, base_key: str,
                   fp: tuple, record: dict) -> str:
    """
    แทรก record เข้า out โดยกัน wildcard code ชนกันข้ามหน้า/เทอม

    ใช้ร่วมกันทั้ง _index_by_code() (ตอน eval-gt) และ convert_lab7b()
    (ตอนแปลง Lab7B -> Lab8B) เดิมมีแค่ _index_by_code() ที่เช็ค fingerprint
    ส่วน convert_lab7b() ยังทำ dict merge ตรงๆ ทำให้รหัส wildcard เดียวกัน
    ที่จริงเป็นคนละวิชา (เช่น 90644xxx ที่ปี1/เทอม2 กับปี4/เทอม1) ทับกันเงียบๆ
    ตั้งแต่ขั้น convert ก่อนที่ eval-gt บนไฟล์ curriculum.json ที่แปลงแล้วจะได้เห็นด้วยซ้ำ

    ถือว่าเป็น "หน้าเดียวกันเจอซ้ำ" (รวมกัน) ก็ต่อเมื่อ fingerprint ตรงกันจริง
    ถ้าไม่ตรง (คนละวิชา) จะแยก key ด้วยส่วนต่อท้าย _2, _3, ... แทนการทับ/ทิ้ง
    คืนค่า key จริงที่ใช้เก็บ record นี้ (ผู้เรียกต้องใช้ค่านี้แทน base_key ต่อไป
    เช่นตอนสร้างแถว plan/prerequisite ที่อ้างถึงวิชาเดียวกัน)

    ⚠️ บั๊กที่พบจริง (แก้ตรงนี้): ถ้าชื่อวิชาเองมีเลขลำดับกำกับอยู่แล้ว
    (วิชาเลือกเสรี 1/2, FREE ELECTIVE COURSE 1/2 ฯลฯ) ให้ใช้เลขนั้นกำหนด key
    ตรง ๆ ผ่าน _slot_number() แทนการนับลำดับที่เจอ ไม่งั้นถ้าลำดับสกัดสลับกับเล่ม
    key (และข้อมูลทุกฟิลด์ที่ผูกกับ key นั้น) จะสลับตามไปด้วย

    ⚠️ บั๊กรอบสอง (แก้ตรงนี้เช่นกัน): ฟังก์ชันนี้ถูกเรียกซ้ำหลายรอบคนละขั้นของ
    pipeline (import-lab7b แปลงเป็น curriculum.json แล้ว eval-gt มาอ่าน courses
    ซ้ำอีกที) รอบแรกตั้ง key เป็น PLACEHOLDER_XXXXXXXX_2 แล้วเขียน "code" นี้กลับ
    เข้า record จริง ๆ ด้วย — พอรอบถัดไปเห็น base_key ที่ลงท้ายด้วย "_2" อยู่แล้ว
    (แปลว่า resolve ไปแล้วจากรอบก่อน) ต้อง "เก็บไว้เฉย ๆ" ห้ามไปคำนวณ slot จาก
    ชื่อแล้วต่อ suffix ซ้ำอีก ไม่งั้นจะกลายเป็น _2_2 แล้ว _2_2_2 ไปเรื่อย ๆ ทุกรอบ
    ที่ index ถูกเรียกซ้ำ — wildcard code ดิบจากเล่มไม่มีทางลงท้ายด้วยตัวเลขเอง
    (ดู _RESOLVED_SUFFIX_RE) จึงใช้สังเกตแยกสองกรณีนี้ได้
    """
    key = base_key
    if is_placeholder(base_key):
        if _RESOLVED_SUFFIX_RE.search(base_key):
            # resolve ไปแล้วจากรอบก่อนหน้า — ใช้ตามเดิม เผื่อชนกันจริง (ไม่ควรเกิด
            # ปกติ) ค่อย fallback ไปหาช่องว่างถัดไปแบบเดิม
            n = 1
            while key in out and fingerprints.get(key) not in (fp, None):
                n += 1
                key = f"{base_key}_{n}"
        else:
            slot_n = _slot_number(record)
            if slot_n is not None:
                candidate = base_key if slot_n == 1 else f"{base_key}_{slot_n}"
                n = slot_n
                key = candidate
                # ชนกับของเดิมที่ fingerprint ไม่ตรง (เลขลำดับซ้ำกันจริงจากคนละที่มา
                # ซึ่งไม่ควรเกิดขึ้นปกติ) — กันไม่ให้ทับข้อมูลกันเงียบๆ ด้วยการหาช่อง
                # ถัดไปแบบเดิม
                while key in out and fingerprints.get(key) not in (fp, None):
                    n += 1
                    key = f"{base_key}_{n}"
            else:
                # ไม่มีเลขลำดับในชื่อให้อิง — กลับไปใช้วิธีเดิม (หา key ที่ว่าง หรือ key
                # ที่ fingerprint ตรงกัน คือแถวเดิมเจอซ้ำหน้า)
                n = 1
                while key in out and fingerprints.get(key) not in (fp, None):
                    n += 1
                    key = f"{base_key}_{n}"
    if key in out:
        # วิชาเดียวกันปรากฏหลายหน้า — เติมช่องที่ยังว่างแทนการทับ
        for f, v in record.items():
            if f == "pages" and isinstance(v, list) and v:
                merged = list(out[key].get(f) or [])
                out[key][f] = merged + [pg for pg in v if pg not in merged]
            elif out[key].get(f) in (None, "") and v not in (None, ""):
                out[key][f] = v
    else:
        out[key] = dict(record, code=key)
        fingerprints[key] = fp
    return key


def _index_by_code(courses: list[dict]) -> dict[str, dict]:
    """
    จัดทำดัชนีตามรหัสวิชา

    รหัส wildcard (90644xxx) ถูก normalize ให้ตรงกับฝั่งที่เก็บเป็น
    PLACEHOLDER_90644XXX เพื่อให้เทียบกันได้ ไม่ใช่นับเป็นวิชาคนละตัว

    ⚠️ บั๊กที่พบจริง: เล่มที่มีช่องวิชาเลือก wildcard เดียวกันซ้ำหลายช่อง (เช่น
    "06026xxx" เจอ 4 ครั้ง = วิชาเลือกกลุ่มวิทยาการข้อมูล 1/2/3/4 คนละวิชากัน)
    โค้ดเดิม map ทุกตัวไปที่ key เดียวกันเสมอ (PLACEHOLDER_06026XXX) แล้ว "เติม
    เฉพาะฟิลด์ว่าง" ทำให้วิชาที่ 2/3/4 หายไปเงียบๆ เหลือวิชาเดียวในการเทียบผล
    ตอนนี้ใช้ _dedup_insert() ร่วมกับ convert_lab7b() (ดูคอมเมนต์ที่นั่น)
    """
    out: dict[str, dict] = {}
    fingerprints: dict[str, tuple] = {}
    for c in courses:
        raw = str(c.get("code") or "").strip()
        codes = _lab7b_codes(raw)
        if codes:
            keys = codes
        else:
            ph = _placeholder_code(raw)
            keys = [ph] if ph else ([raw] if raw else [])
        for k in keys:
            base_key = k.upper() if is_placeholder(k) else k
            fp = _norm_for_dup_check(c)
            _dedup_insert(out, fingerprints, base_key, fp, c)
    return out


def _prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def evaluate_against_ground_truth(pred: Any, gt: Any) -> dict:
    """
    เทียบผลสกัดกับเฉลย คืนคะแนนรายฟิลด์และคะแนนรวม

    pred รับได้ทั้ง JSON ของ Lab 7B (courses มี year/semester/category/type)
    และ JSON ของ Lab 8B (courses + plan + elective_slots) โดยจะรวมข้อมูล
    จาก plan/elective_slots กลับเข้าไปที่วิชาเดียวกันก่อนเทียบ
    """
    gt_index = _index_by_code(_gt_courses(gt))
    pred_index = _index_by_code(_flatten_pred(pred))

    # ── ฟิลด์ code วัดที่ระดับ "ชุดรหัสวิชา" ─────────────────────────
    gt_codes, pred_codes = set(gt_index), set(pred_index)
    per_field = {"code": _prf(len(gt_codes & pred_codes),
                              len(pred_codes - gt_codes),
                              len(gt_codes - pred_codes))}

    mismatch_examples: dict[str, list] = {f: [] for f in GT_FIELDS}
    for f in gt_codes - pred_codes:
        mismatch_examples["code"].append({"code": f, "gt": f, "pred": None})
    for f in pred_codes - gt_codes:
        mismatch_examples["code"].append({"code": f, "gt": None, "pred": f})

    for field in GT_FIELDS:
        if field == "code":
            continue
        tp = fp = fn = 0
        for code in pred_codes | gt_codes:
            want = _norm_field(field, (gt_index.get(code) or {}).get(field))
            got = _norm_field(field, (pred_index.get(code) or {}).get(field))
            if want and got:
                same = (_credits_match(want, got) if field == "credits"
                        else want == got)
                if same:
                    tp += 1
                else:
                    fp += 1
                    fn += 1
                    if len(mismatch_examples[field]) < 10:
                        mismatch_examples[field].append(
                            {"code": code,
                             "gt": (gt_index.get(code) or {}).get(field),
                             "pred": (pred_index.get(code) or {}).get(field)})
            elif want and not got:
                fn += 1
                if len(mismatch_examples[field]) < 10:
                    mismatch_examples[field].append(
                        {"code": code,
                         "gt": (gt_index.get(code) or {}).get(field),
                         "pred": None})
            elif got and not want:
                fp += 1
                if len(mismatch_examples[field]) < 10:
                    mismatch_examples[field].append(
                        {"code": code, "gt": None,
                         "pred": (pred_index.get(code) or {}).get(field)})
            # ทั้งสองฝั่งว่าง = ตรงกันโดยไม่มีอะไรให้วัด ไม่นับเข้า TP
        per_field[field] = _prf(tp, fp, fn)

    micro = _prf(sum(v["tp"] for v in per_field.values()),
                 sum(v["fp"] for v in per_field.values()),
                 sum(v["fn"] for v in per_field.values()))
    f1 = micro["f1"]
    band = ("ดีเยี่ยม (>91%)" if f1 > 0.91 else
            "ผ่านเกณฑ์กลาง (80–90%)" if f1 >= 0.80 else
            "ต่ำกว่าเกณฑ์ (<80%)")
    return {
        "n_gt_courses": len(gt_index),
        "n_pred_courses": len(pred_index),
        "per_field": per_field,
        "micro": micro,
        "band": band,
        "mismatch_examples": {k: v for k, v in mismatch_examples.items() if v},
    }


def _flatten_pred(pred: Any) -> list[dict]:
    """
    รวมผลสกัดให้อยู่ในรูป "หนึ่งวิชาหนึ่ง dict" ก่อนเทียบกับเฉลย

    JSON ของ Lab 8B แยกข้อมูลวิชาออกเป็นสามที่ (courses / plan / elective_slots)
    ถ้าเทียบเฉพาะ courses จะได้คะแนน year/semester เป็นศูนย์ทั้งที่ข้อมูลมีอยู่
    ฟังก์ชันนี้จึงดึงกลับมารวมกันตามรหัสวิชา
    """
    if isinstance(pred, list):
        return [c for c in pred if isinstance(c, dict)]
    if not isinstance(pred, dict):
        return []
    courses = _gt_courses(pred)
    by_code = _index_by_code(courses)

    # ฐานข้อมูล Lab 8B เก็บหน่วยกิตแยกเป็นตัวเลขสี่ช่อง ส่วนเฉลยเก็บเป็น "3(2-2-5)"
    # ประกอบกลับก่อนเทียบ จะได้วัด "ชั่วโมง ท-ป-อ" ได้ด้วย ไม่ใช่วัดแค่จำนวนหน่วยกิต
    #
    # ⚠️ บั๊กที่พบจริง (แก้ตรงนี้): เดิมถ้าช่องชั่วโมงช่องใดช่องหนึ่งไม่ครบ (None/หลุด)
    # เงื่อนไข all(...) จะไม่ผ่าน แล้ว rec["credits"] ถูกปล่อยเป็น int เปล่า (เช่น 1)
    # ไปเทียบกับเฉลยที่เป็น "3(3-0-6)" ตรงๆ ผ่าน _norm_credits()/_credits_match()
    # ซึ่งยังเทียบได้ผลถูกต้องถ้าเป็นตัวเลขล้วนอยู่แล้ว จึงไม่ใช่จุดพังจริง — แต่เพื่อความ
    # ชัดเจนและกันพังเงียบถ้า _credits_match() เปลี่ยนกติกาในอนาคต ให้แปลงเป็น string
    # เสมอไม่ว่าจะประกอบชั่วโมงได้ครบหรือไม่
    for rec in by_code.values():
        credits_val = rec.get("credits")
        if isinstance(credits_val, int):
            hours = tuple(rec.get(k) for k in ("lecture_h", "lab_h", "self_h"))
            if all(isinstance(h, int) for h in hours):
                rec["credits"] = f"{credits_val}({hours[0]}-{hours[1]}-{hours[2]})"
            else:
                rec["credits"] = str(credits_val)
    for rec in by_code.values():
        if rec.get("credits_text"):     # เล่มให้หลายแบบ — เทียบทั้งก้อนตามที่ _norm_credits ตั้งใจ
            rec["credits"] = rec["credits_text"]

    for p in pred.get("plan") or []:
        code = str(p.get("code") or "").strip()
        key = code.upper() if is_placeholder(code) else code
        rec = by_code.setdefault(key, {"code": key})
        for src_field, dst_field in (("year", "year"), ("semester", "semester"),
                                     ("category", "category"), ("type", "type")):
            if rec.get(dst_field) in (None, "") and p.get(src_field) not in (None, ""):
                rec[dst_field] = p[src_field]

    for s in pred.get("elective_slots") or []:
        code = str(s.get("code") or "").strip()
        key = code.upper() if is_placeholder(code) else code
        rec = by_code.setdefault(key, {"code": key})
        for field in ("category", "type", "name_th"):
            if rec.get(field) in (None, "") and s.get(field) not in (None, ""):
                rec[field] = s[field]
        # วิชาเลือกยืดหยุ่น: เฉลยเขียน year=0 semester=0 เราจึงเทียบด้วย 0
        rec.setdefault("year", 0)
        rec.setdefault("semester", 0)
        if s.get("allowed_terms") and not rec.get("flexible_year_semester"):
            rec["flexible_year_semester"] = s["allowed_terms"]

    for r in pred.get("prerequisites") or []:
        code = str(r.get("code") or "").strip()
        rec = by_code.setdefault(code, {"code": code})
        existing = _lab7b_codes(rec.get("prerequisite"))
        if r.get("requires") and r["requires"] not in existing:
            rec["prerequisite"] = ", ".join(existing + [r["requires"]])

    return list(by_code.values())


def _load_gt(path: Path) -> tuple[list[dict], list[str]]:
    """อ่านเฉลยจากไฟล์เดียวหรือทั้งโฟลเดอร์ (รวมทุกไฟล์เป็นชุดเดียว)"""
    files = (sorted(path.glob("*.json")) if path.is_dir() else [path])
    if not files:
        raise FileNotFoundError(f"ไม่พบไฟล์ .json ใน {path}")
    merged: list[dict] = []
    for f in files:
        merged += _gt_courses(json.loads(f.read_text(encoding="utf-8")))
    return merged, [f.name for f in files]


def cmd_eval_gt(args) -> None:
    pred = json.loads(Path(args.pred).read_text(encoding="utf-8"))
    gt_courses, files = _load_gt(Path(args.ground_truth))
    report = evaluate_against_ground_truth(pred, gt_courses)
    report["ground_truth_files"] = files

    print()
    print(f"  เทียบกับเฉลย {len(files)} ไฟล์: {', '.join(files)}")
    print(f"  วิชาในเฉลย {report['n_gt_courses']} · ที่สกัดได้ {report['n_pred_courses']}")
    print("  " + "-" * 74)
    print(f"  {'ฟิลด์':<16}{'P':>8}{'R':>8}{'F1':>8}{'TP':>7}{'FP':>7}{'FN':>7}")
    for field in GT_FIELDS:
        m = report["per_field"][field]
        print(f"  {field:<16}{m['precision']:>8.1%}{m['recall']:>8.1%}"
              f"{m['f1']:>8.1%}{m['tp']:>7}{m['fp']:>7}{m['fn']:>7}")
    print("  " + "-" * 74)
    m = report["micro"]
    print(f"  {'รวมทุกฟิลด์':<15}{m['precision']:>8.1%}{m['recall']:>8.1%}"
          f"{m['f1']:>8.1%}{m['tp']:>7}{m['fp']:>7}{m['fn']:>7}")
    print(f"  โซนคะแนน: {report['band']}")
    print()
    print("  อ่านตารางนี้อย่างไร")
    print("    Precision ต่ำ = เติมค่าผิดมาเยอะ  -> แก้ prompt ให้ใส่ null เมื่อไม่แน่ใจ")
    print("    Recall ต่ำ    = ข้อมูลหายไปเยอะ   -> ดูว่าโดนข้ามที่ขั้นตอนไหน")
    worst = min(GT_FIELDS, key=lambda f: report["per_field"][f]["f1"])
    print(f"    ฟิลด์ที่ควรแก้ก่อน: {worst} "
          f"(F1 {report['per_field'][worst]['f1']:.1%})")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n  บันทึกผลที่ {args.output} (มีตัวอย่างที่ผิดให้ดูรายข้อ)")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 7 — ข้อมูลตัวอย่างสำหรับทดลอง
# ═══════════════════════════════════════════════════════════════════════

DEMO_JSON = {
    "program": {
        "program_id": "IT2565",
        # หมายเหตุ: นี่คือหลักสูตร "ฉบับย่อ" ที่ตัดเหลือ 2 ปีเพื่อใช้ฝึกปฏิบัติ
        # ตัวเลขทุกตัวสอดคล้องกันเอง กฎตรวจทั้ง 7 ข้อจึงต้องผ่านหมด
        # ถ้ากฎข้อใดเตือนกับข้อมูลชุดนี้ แปลว่ากฎข้อนั้นเขียนผิด ไม่ใช่ข้อมูลผิด
        "name_th": "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชาเทคโนโลยีสารสนเทศ (ฉบับย่อสำหรับฝึกปฏิบัติ)",
        "name_en": "Bachelor of Science Program in Information Technology (abridged)",
        "degree": "วท.บ. (เทคโนโลยีสารสนเทศ)",
        "total_credits": 39,
        "years": 2,
    },
    "courses": [
        {"code": "06026101", "name_th": "คณิตศาสตร์สำหรับเทคโนโลยีสารสนเทศ",
         "name_en": "Mathematics for IT", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 41},
        {"code": "06026102", "name_th": "การเขียนโปรแกรมคอมพิวเตอร์",
         "name_en": "Computer Programming", "credits": 3,
         "lecture_h": 2, "lab_h": 3, "self_h": 5, "description_th": None,
         "source_page": 42},
        {"code": "06026103", "name_th": "โครงสร้างข้อมูลและอัลกอริทึม",
         "name_en": "Data Structures and Algorithms", "credits": 3,
         "lecture_h": 2, "lab_h": 3, "self_h": 5, "description_th": None,
         "source_page": 43},
        {"code": "06026104", "name_th": "ระบบฐานข้อมูล",
         "name_en": "Database Systems", "credits": 3,
         "lecture_h": 2, "lab_h": 3, "self_h": 5, "description_th": None,
         "source_page": 44},
        {"code": "06026240", "name_th": "การพัฒนาระบบอัจฉริยะ",
         "name_en": "Intelligent System Development", "credits": 3,
         "lecture_h": 2, "lab_h": 3, "self_h": 5, "description_th": None,
         "source_page": 45},
        {"code": "06026241", "name_th": "คอมพิวเตอร์วิทัศน์",
         "name_en": "Computer Vision", "credits": 3,
         "lecture_h": 2, "lab_h": 3, "self_h": 5, "description_th": None,
         "source_page": 46},
        {"code": "06026259", "name_th": "การประมวลผลภาษาธรรมชาติ",
         "name_en": "Natural Language Processing", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 47},
        {"code": "06026260", "name_th": "การเรียนรู้เชิงลึก",
         "name_en": "Deep Learning", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 48},
        # วิชานี้มีคำอธิบายในเล่ม แต่ไม่ถูกล็อกไว้ที่เทอมใดเทอมหนึ่ง
        # จึงไปอยู่ใน elective_slots แทน plan — เป็นเคสที่เคยหายไปทั้งกลุ่ม
        {"code": "06026261", "name_th": "การวิเคราะห์ข้อมูลขนาดใหญ่",
         "name_en": "Big Data Analytics", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 54},
        {"code": "06026390", "name_th": "สหกิจศึกษาทางเทคโนโลยีสารสนเทศ",
         "name_en": "Cooperative Education in IT", "credits": 6,
         "lecture_h": 0, "lab_h": 0, "self_h": 0, "description_th": None,
         "source_page": 49},
        {"code": "90130001", "name_th": "ภาษาอังกฤษเพื่อการสื่อสาร",
         "name_en": "English for Communication", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 50},
        {"code": "90130002", "name_th": "ภาษาอังกฤษเชิงวิชาการ",
         "name_en": "Academic English", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 51},
        {"code": "90230001", "name_th": "มนุษย์กับสังคม",
         "name_en": "Human and Society", "credits": 3,
         "lecture_h": 3, "lab_h": 0, "self_h": 6, "description_th": None,
         "source_page": 52},
        {"code": "90330001", "name_th": "กีฬาและนันทนาการ",
         "name_en": "Sports and Recreation", "credits": 3,
         "lecture_h": 1, "lab_h": 4, "self_h": 4, "description_th": None,
         "source_page": 53},
    ],
    "plan": [
        # category / type เป็นคอลัมน์จริง ไม่ยัดรวมใน note อีกต่อไป
        # note เหลือไว้สำหรับ "ข้อความที่เล่มเขียนเพิ่ม" เท่านั้น
        {"year": 1, "semester": 1, "code": "06026101", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 60},
        {"year": 1, "semester": 1, "code": "06026102", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 60},
        {"year": 1, "semester": 1, "code": "90130001", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
         "note": None, "source_page": 60},
        {"year": 1, "semester": 1, "code": "90230001", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
         "note": None, "source_page": 60},
        {"year": 1, "semester": 2, "code": "06026103", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 61},
        {"year": 1, "semester": 2, "code": "06026104", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 61},
        {"year": 1, "semester": 2, "code": "90130002", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
         "note": None, "source_page": 61},
        {"year": 1, "semester": 2, "code": "90330001", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
         "note": None, "source_page": 61},
        {"year": 2, "semester": 1, "code": "06026240", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 62},
        {"year": 2, "semester": 1, "code": "06026241", "credits": 3,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": None, "source_page": 62},
        # วิชาเลือกอย่างใดอย่างหนึ่ง — สองแถว alt_group เดียวกัน
        {"year": 2, "semester": 1, "code": "06026259", "credits": 3,
         "alt_group": "elect_y2s1", "category": "หมวดวิชาเฉพาะ", "type": "เลือก",
         "note": "เลือกอย่างใดอย่างหนึ่ง", "source_page": 62},
        {"year": 2, "semester": 1, "code": "06026260", "credits": 3,
         "alt_group": "elect_y2s1", "category": "หมวดวิชาเฉพาะ", "type": "เลือก",
         "note": "เลือกอย่างใดอย่างหนึ่ง", "source_page": 62},
        # ภาคสหกิจศึกษา — วิชาเดียว 6 หน่วยกิต (ทดสอบข้อยกเว้นของ CHK7)
        {"year": 2, "semester": 2, "code": "06026390", "credits": 6,
         "alt_group": None, "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
         "note": "ภาคสหกิจศึกษา", "source_page": 63},
    ],
    # วิชาที่เล่มไม่ล็อกเทอม แต่บอกว่าเรียนได้เทอมไหนบ้าง
    # ข้อมูลกลุ่มนี้คือกลุ่มที่เคยหายไปเงียบ ๆ ทั้งก้อน
    "elective_slots": [
        {"code": "06026261", "allowed_terms": "2/1, 2/2",
         "name_th": "การวิเคราะห์ข้อมูลขนาดใหญ่", "credits": 3,
         "category": "หมวดวิชาเฉพาะ", "type": "เลือก",
         "note": None, "source_page": 64},
    ],
    "prerequisites": [
        {"code": "06026103", "requires": "06026102", "kind": "pre"},
        {"code": "06026240", "requires": "06026103", "kind": "pre"},
        {"code": "06026259", "requires": "06026103", "kind": "pre"},
        # เรียนควบ (co) ไม่ถูกตรวจด้วย CHK5 เพราะอยู่ภาคเดียวกันได้ตามระเบียบ
        {"code": "06026241", "requires": "06026240", "kind": "co"},
        {"code": "06026390", "requires": "06026240", "kind": "pre"},
    ],
}

DEMO_QUESTIONS = [
    # คำถามถูกออกแบบให้ "ตรวจอัตโนมัติได้" คือคำตอบเป็นค่าเดียวหรือชุดรหัสวิชา
    # หลีกเลี่ยงคำถามที่ตอบได้หลายรูปแบบ เช่น "อธิบายหลักสูตรนี้"
    # เพราะจะให้คะแนนอัตโนมัติไม่ได้ และไม่บอกอะไรเกี่ยวกับคุณภาพ SQL
    {"question": "หลักสูตรนี้มีทั้งหมดกี่หน่วยกิต",
     "expect": {"type": "value", "value": 39}},
    {"question": "หลักสูตรนี้ใช้เวลาเรียนกี่ปี",
     "expect": {"type": "value", "value": 2}},
    {"question": "ปี 1 เทอม 1 เรียนกี่หน่วยกิต",
     "expect": {"type": "value", "value": 12}},
    {"question": "ปี 1 เทอม 1 เรียนวิชาอะไรบ้าง",
     "expect": {"type": "set",
                "value": ["06026101", "06026102", "90130001", "90230001"]}},
    {"question": "ปี 2 เทอม 1 เรียนกี่หน่วยกิต",
     "expect": {"type": "value", "value": 9}},
    {"question": "วิชาการพัฒนาระบบอัจฉริยะมีรหัสอะไร",
     "expect": {"type": "value", "value": "06026240"}},
    {"question": "วิชา 06026240 มีกี่หน่วยกิต",
     "expect": {"type": "value", "value": 3}},
    {"question": "วิชา 06026104 ชื่อภาษาอังกฤษว่าอะไร",
     "expect": {"type": "value", "value": "Database Systems"}},
    {"question": "ต้องเรียนวิชาอะไรมาก่อนจึงจะลงเรียน 06026240 ได้",
     "expect": {"type": "value", "value": "06026103"}},
    {"question": "วิชาไหนใช้ 06026240 เป็นวิชาบังคับก่อน",
     "expect": {"type": "value", "value": "06026390"}},
    {"question": "วิชาคอมพิวเตอร์วิทัศน์อยู่ชั้นปีที่เท่าไร",
     "expect": {"type": "value", "value": 2}},
    {"question": "วิชาสหกิจศึกษามีกี่หน่วยกิต",
     "expect": {"type": "value", "value": 6}},
    {"question": "วิชา 90330001 มีชั่วโมงปฏิบัติการกี่ชั่วโมง",
     "expect": {"type": "value", "value": 4}},
    {"question": "ปี 2 เทอม 1 มีวิชาเลือกอย่างใดอย่างหนึ่งคือวิชาอะไรบ้าง",
     "expect": {"type": "set", "value": ["06026259", "06026260"]}},
    # วิชาเลือกที่ไม่ได้ล็อกเทอม — ถ้าตารางนี้หายไป ระบบจะตอบว่า "ไม่พบข้อมูล"
    {"question": "วิชา 06026261 เรียนได้ตอนไหนบ้าง",
     "expect": {"type": "value", "value": "2/1, 2/2"}},
    {"question": "ปี 1 เทอม 1 มีวิชาบังคับกี่วิชา",
     "expect": {"type": "value", "value": 4}},
    # สองข้อสุดท้ายทดสอบสิ่งที่สำคัญที่สุด คือระบบต้องยอมรับได้ว่า "ไม่รู้"
    # ระบบที่ตอบทุกคำถามได้เสมอ คือระบบที่แต่งคำตอบเมื่อไม่มีข้อมูล
    {"question": "วิชา 06026999 ชื่ออะไร",
     "expect": {"type": "none", "value": None}},
    {"question": "ปี 7 เทอม 1 เรียนวิชาอะไรบ้าง",
     "expect": {"type": "none", "value": None}},
]


def markdown_from_demo(d: dict) -> str:
    """สร้าง Markdown เลียนแบบผลลัพธ์ของ Lab 7B เพื่อใช้ทดสอบคำสั่ง extract"""
    L = [f"# {d['program']['name_th']}", "",
         f"{d['program']['name_en']}", "",
         f"ชื่อปริญญา: {d['program']['degree']}",
         f"จำนวนหน่วยกิตรวมตลอดหลักสูตร: {d['program']['total_credits']} หน่วยกิต",
         f"ระยะเวลาการศึกษา: {d['program']['years']} ปี", "",
         "## คำอธิบายรายวิชา", "",
         "| รหัสวิชา | ชื่อวิชา | หน่วยกิต | ท-ป-อ |",
         "|---|---|---|---|"]
    for c in d["courses"]:
        L.append(f"| {c['code']} | {c['name_th']} ({c['name_en']}) | "
                 f"{c['credits']} | {c['lecture_h']}-{c['lab_h']}-{c['self_h']} |")
    L += ["", "## แผนการศึกษา", ""]
    names = {c["code"]: c["name_th"] for c in d["courses"]}
    seen = set()
    for p in d["plan"]:
        key = (p["year"], p["semester"])
        if key not in seen:
            seen.add(key)
            L += ["", f"### ปีที่ {p['year']} ภาคการศึกษาที่ {p['semester']}", "",
                  "| รหัสวิชา | ชื่อวิชา | หน่วยกิต |", "|---|---|---|"]
        L.append(f"| {p['code']} | {names.get(p['code'], '')} | {p['credits']} |"
                 + (f"  <!-- {p['note']} -->" if p.get("note") else ""))
    L += ["", "## เงื่อนไขรายวิชา", ""]
    for r in d["prerequisites"]:
        word = "วิชาบังคับก่อน" if r["kind"] == "pre" else "วิชาเรียนควบ"
        L.append(f"- {r['code']} : {word} {r['requires']}")
    return "\n".join(L)


def cmd_demo(args) -> None:
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "curriculum.md").write_text(markdown_from_demo(DEMO_JSON), encoding="utf-8")
    (out / "curriculum_demo.json").write_text(
        json.dumps(DEMO_JSON, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "gold_questions.json").write_text(
        json.dumps(DEMO_QUESTIONS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  เขียน {out}/curriculum.md          (ใช้ทดสอบคำสั่ง extract)")
    print(f"  เขียน {out}/curriculum_demo.json   (JSON ที่ถูกต้อง ใช้ข้าม extract ได้)")
    print(f"  เขียน {out}/gold_questions.json    ({len(DEMO_QUESTIONS)} คำถาม)")
    print()
    print("  ทดลองทั้งสายโดยไม่ต้องรอ LLM สกัด:")
    print(f"    python3 lab8b_curriculum_db.py load "
          f"-i {out}/curriculum_demo.json -d {out}/curriculum.db --replace")
    print(f"    python3 lab8b_curriculum_db.py verify -d {out}/curriculum.db")


# ═══════════════════════════════════════════════════════════════════════
#  ส่วนที่ 8 — selftest
# ═══════════════════════════════════════════════════════════════════════

def cmd_selftest(args=None) -> bool:
    print("=" * 68)
    print("  selftest — ตรวจ schema, กฎตรวจ, และด่านความปลอดภัย SQL")
    print("=" * 68)
    passed = failed = 0

    def ck(name, got, want):
        nonlocal passed, failed
        if got == want:
            print(f"  [ ok ] {name}")
            passed += 1
        else:
            print(f"  [FAIL] {name}: ได้ {got!r} ต้องการ {want!r}")
            failed += 1

    # ── 1. Pydantic schema ──────────────────────────────────────────
    try:
        from pydantic import ValidationError
        Curriculum = build_models()
        ok_obj = Curriculum.model_validate(DEMO_JSON)
        ck("ข้อมูลตัวอย่างผ่าน schema", ok_obj.program.total_credits, 39)

        bad = json.loads(json.dumps(DEMO_JSON))
        bad["courses"][0]["code"] = "0602610"          # 7 หลัก
        try:
            Curriculum.model_validate(bad)
            ck("จับรหัสวิชาผิดรูปแบบ", False, True)
        except ValidationError as e:
            ck("จับรหัสวิชาผิดรูปแบบ", "8 หลัก" in format_errors(e), True)

        bad2 = json.loads(json.dumps(DEMO_JSON))
        bad2["plan"][0]["semester"] = 5                # เทอมต้อง 1-3
        try:
            Curriculum.model_validate(bad2)
            ck("จับเทอมนอกช่วง", False, True)
        except ValidationError as e:
            ck("จับเทอมนอกช่วง", "plan -> 0 -> semester" in format_errors(e), True)

        # JSON จาก Lab 7B ต้องแปลได้โดยไม่เรียก LLM
        lab7b_sample = {
            "program": "TEST",
            "courses": [
                {"code": "06026240", "name_th": "วิชาหนึ่ง",
                 "credits": "3(2-2-5)", "year": 1, "semester": 1,
                 "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
                 "prerequisite": "ไม่มี", "source_page": 12},
                {"code": "06026241", "name_th": "วิชาสอง",
                 "credits": "3(3-0-6)", "year": 2, "semester": 1,
                 "category": "หมวดวิชาเฉพาะ", "type": "บังคับ",
                 "prerequisite": "06026240", "page": "หน้า 13"},
                # รหัส wildcard — ต้องกลายเป็นช่องวิชาที่ยังนับหน่วยกิตได้
                {"code": "90644xxx", "name_th": "ช่องวิชาภาษา",
                 "credits": "3(3-0-6)", "year": 2, "semester": 1,
                 "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
                 "prerequisite": "ไม่มี"},
                # ปี/เทอมยืดหยุ่น — ต้องไปอยู่ใน elective_slots ไม่ใช่หายไป
                {"code": "06026259", "name_th": "วิชาเลือกยืดหยุ่น",
                 "credits": "3(3-0-6)", "year": 0, "semester": 0,
                 "flexible_year_semester": "3/1, 3/2, 4/1",
                 "category": "หมวดวิชาเฉพาะ", "type": "เลือก",
                 "prerequisite": "ไม่มี", "source_page": 20},
            ],
        }
        converted, report = convert_lab7b(
            lab7b_sample, total_credits=30, years=4)
        by_code = {c["code"]: c for c in converted["courses"]}
        plan_by_code = {p["code"]: p for p in converted["plan"]}
        ck("import Lab 7B แยกหน่วยกิตและชั่วโมง",
           (by_code["06026240"]["credits"], by_code["06026240"]["lecture_h"],
            by_code["06026240"]["lab_h"], by_code["06026240"]["self_h"]),
           (3, 2, 2, 5))
        ck("import Lab 7B แยก prerequisite",
           converted["prerequisites"],
           [{"code": "06026241", "requires": "06026240", "kind": "pre"}])

        # ── รหัส wildcard ต้องไม่ทำให้หน่วยกิตหาย ─────────────────────
        ck("wildcard กลายเป็นช่องวิชา ไม่ถูกทิ้ง",
           report["wildcard_placeholders"], 1)
        ck("ช่องวิชายังอยู่ในแผนพร้อมหน่วยกิต",
           plan_by_code.get("PLACEHOLDER_90644XXX", {}).get("credits"), 3)
        ck("หน่วยกิตปี 2 เทอม 1 ครบ ไม่ขาดไป 3",
           sum(p["credits"] for p in converted["plan"]
               if p["year"] == 2 and p["semester"] == 1), 6)

        # ── วิชาปี/เทอมยืดหยุ่นต้องถูกเก็บ ไม่ใช่หายเงียบ ─────────────
        slots = {s["code"]: s for s in converted["elective_slots"]}
        ck("วิชา flexible ถูกเก็บเป็น elective_slot",
           slots.get("06026259", {}).get("allowed_terms"), "3/1, 3/2, 4/1")
        ck("วิชา flexible ไม่ถูกยัดลงแผน", "06026259" in plan_by_code, False)
        ck("นับวิชา flexible ที่กู้ไว้ได้", report["flexible_courses_kept"], 1)

        # ── citation และ category/type ─────────────────────────────────
        ck("เก็บเลขหน้าจาก source_page", by_code["06026240"]["pages"], [12])
        ck("เก็บเลขหน้าจากชื่อฟิลด์อื่น (page)",
           by_code["06026241"]["pages"], [13])
        ck("category แยกเป็นคอลัมน์จริง",
           plan_by_code["06026240"]["category"], "หมวดวิชาเฉพาะ")
        ck("type แยกเป็นคอลัมน์จริง",
           plan_by_code["06026240"]["type"], "บังคับ")
        ck("ไม่ยัด category/type ลง note",
           plan_by_code["06026240"]["note"], None)

        # ── ตัววัดเทียบเฉลย ────────────────────────────────────────────
        gt = [
            {"code": "06026240", "name_th": "วิชาหนึ่ง", "credits": "3(2-2-5)",
             "year": 1, "semester": 1, "category": "หมวดวิชาเฉพาะ",
             "type": "บังคับ", "prerequisite": "ไม่มี"},
            {"code": "06026241", "name_th": "วิชาสอง", "credits": "3(3-0-6)",
             "year": 2, "semester": 1, "category": "หมวดวิชาเฉพาะ",
             "type": "บังคับ", "prerequisite": "06026240"},
            {"code": "90644xxx", "name_th": "ช่องวิชาภาษา",
             "credits": "3(3-0-6)", "year": 2, "semester": 1,
             "category": "หมวดวิชาศึกษาทั่วไป", "type": "บังคับ",
             "prerequisite": "ไม่มี"},
            {"code": "06026259", "name_th": "วิชาเลือกยืดหยุ่น",
             "credits": "3(3-0-6)", "year": 0, "semester": 0,
             "flexible_year_semester": "3/1, 3/2, 4/1",
             "category": "หมวดวิชาเฉพาะ", "type": "เลือก",
             "prerequisite": "ไม่มี"},
        ]
        gt_report = evaluate_against_ground_truth(converted, gt)
        ck("เทียบเฉลยแล้วจับคู่รหัสได้ครบ",
           gt_report["per_field"]["code"]["recall"], 1.0)
        ck("เทียบเฉลย: แปลงถูกต้องได้ F1 เต็ม",
           gt_report["micro"]["f1"], 1.0)

        broken = json.loads(json.dumps(converted))
        broken["courses"][0]["name_th"] = "ชื่อผิด"
        worse = evaluate_against_ground_truth(broken, gt)
        ck("เทียบเฉลยจับความผิดได้",
           worse["per_field"]["name_th"]["f1"] < 1.0, True)
        ck("เฉลยที่หายไปนับเป็น recall ตก",
           evaluate_against_ground_truth(
               {"courses": converted["courses"][:1]}, gt
           )["per_field"]["code"]["recall"] < 1.0, True)
    except ImportError:
        print("  [skip] ไม่มี pydantic จึงข้ามการทดสอบ schema")

    # ── 2. ด่านความปลอดภัย SQL ──────────────────────────────────────
    ck("เติม LIMIT ให้อัตโนมัติ",
       "LIMIT" in guard_sql("SELECT * FROM course"), True)
    ck("ไม่เติม LIMIT ซ้ำ",
       guard_sql("SELECT 1 LIMIT 5").count("LIMIT"), 1)
    for bad_sql, why in [("DROP TABLE course", "DROP"),
                         ("SELECT 1; DELETE FROM course", "หลายคำสั่ง"),
                         ("UPDATE course SET credits=0", "UPDATE"),
                         ("PRAGMA table_info(course)", "PRAGMA")]:
        try:
            guard_sql(bad_sql)
            ck(f"ปฏิเสธ {why}", False, True)
        except ValueError:
            ck(f"ปฏิเสธ {why}", True, True)
    ck("ยอมรับ WITH", guard_sql("WITH x AS (SELECT 1) SELECT * FROM x")[:4], "WITH")

    # ── 3. clean_sql_output ─────────────────────────────────────────
    ck("ตัด think ออกจาก SQL",
       clean_sql_output("<think>คิด</think>```sql\nSELECT 1\n```"), "SELECT 1")

    # ── 4. กฎตรวจ 7 ข้อ บนข้อมูลที่ถูกต้อง — ต้องไม่เตือนผิดเลย ────
    db = Path(tempfile.gettempdir()) / "_lab8b_selftest.db"
    if db.exists():
        db.unlink()
    conn = open_db(db)
    conn.executescript(DDL)
    load_curriculum(conn, DEMO_JSON)
    res = verify_db(conn)
    fails = [r["id"] for r in res if not r["ok"]]
    ck("ข้อมูลถูกต้องไม่ทำให้กฎเตือนผิด (false alarm = 0)", fails, [])

    # หน่วยกิตรวมต้องนับ alt_group ครั้งเดียว
    rows = {(r["year"], r["semester"]): r["credits"] for r in _sem_credits(conn)}
    ck("นับวิชาเลือกอย่างใดอย่างหนึ่งครั้งเดียว", rows[(2, 1)], 9)
    ck("ภาคสหกิจนับได้ 6 หน่วยกิต", rows[(2, 2)], 6)

    # ── 4b. normalize_plan_alternatives (ต้นเหตุ CHK1 เกินของ DSBA) ─────
    _nm = {f"PLACEHOLDER_06026XXX_{k}": {"name_th": f"วิชาเลือกกลุ่ม{g} {n}"}
           for k, (g, n) in zip(range(7, 13), [("วิทยาการข้อมูล", 3), ("การวิเคราะห์เชิงสถิติ", 3),
                                               ("วิศวกรรมข้อมูล", 3), ("วิทยาการข้อมูล", 4),
                                               ("การวิเคราะห์เชิงสถิติ", 4), ("วิศวกรรมข้อมูล", 4)])}
    _pl = [{"year": 3, "semester": 2, "code": c, "credits": 3, "alt_group": None}
           for c in list(_nm)[:4]]
    _pl += [{"year": 3, "semester": 2, "code": c, "credits": 3,
             "alt_group": "raw_alt_recovered_06026XXX_10"} for c in list(_nm)[4:]]
    _pl += [{"year": 4, "semester": 2, "code": "06026259", "credits": 6, "alt_group": "alt_y4s2_1"},
            {"year": 4, "semester": 2, "code": "06026260", "credits": 6, "alt_group": "alt_y4s2_1"},
            {"year": 4, "semester": 2, "code": "06026259", "credits": 6,
             "alt_group": "raw_alt_recovered_06026259_12"}]
    normalize_plan_alternatives(_pl, _nm, group_slots=True)
    _units: dict[tuple, int] = {}
    for _i, _r in enumerate(_pl):
        _k = (_r["year"], _r["semester"], _r["alt_group"] or f"x{_i}")
        _units[_k] = min(_units.get(_k, 10 ** 6), _r["credits"])
    ck("ช่องวิชาเลือกกลุ่ม 2 ช่อง + สหกิจ นับเป็น 3+3+6", sum(_units.values()), 12)
    ck("ตัดแถวสหกิจซ้ำที่กู้คืนทิ้ง", sum(1 for r in _pl if r["code"] == "06026259"), 1)

    # ── 5. กฎต้องจับความผิดจริงได้ด้วย ──────────────────────────────
    conn.execute("UPDATE plan_item SET credits = 5 WHERE code = '06026240'")
    res2 = {r["id"]: r["ok"] for r in verify_db(conn)}
    ck("CHK4 จับหน่วยกิตไม่ตรงกัน", res2["CHK4"], False)
    conn.execute("UPDATE plan_item SET credits = 3 WHERE code = '06026240'")

    # FOREIGN KEY กันรหัสกำพร้าตั้งแต่ตอนโหลดแล้ว จึงต้องปิดชั่วคราว
    # เพื่อทดสอบว่า CHK2 ยังทำงาน (ใช้กับฐานที่โหลดด้วย --allow-orphan)
    try:
        conn.execute("INSERT INTO plan_item (program_id, year, semester, code,"
                     " credits) VALUES ('IT2565', 1, 1, '06026777', 3)")
        ck("FOREIGN KEY กันรหัสกำพร้าตอนโหลด", False, True)
        conn.execute("DELETE FROM plan_item WHERE code = '06026777'")
    except sqlite3.IntegrityError:
        ck("FOREIGN KEY กันรหัสกำพร้าตอนโหลด", True, True)

    conn.commit()          # PRAGMA foreign_keys ไม่มีผลถ้ายังอยู่ใน transaction
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO plan_item (program_id, year, semester, code,"
                 " credits) VALUES ('IT2565', 1, 1, '06026777', 3)")
    res3 = {r["id"]: r["ok"] for r in verify_db(conn)}
    ck("CHK2 จับรหัสที่ไม่มีคำอธิบาย", res3["CHK2"], False)
    conn.execute("DELETE FROM plan_item WHERE code = '06026777'")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")

    # สลับลำดับให้วิชาบังคับก่อนอยู่หลัง
    conn.execute("UPDATE plan_item SET year = 1, semester = 1 "
                 "WHERE code = '06026260'")
    conn.execute("INSERT INTO prerequisite VALUES ('06026260','06026240','pre')")
    res4 = {r["id"]: r["ok"] for r in verify_db(conn)}
    ck("CHK5 จับลำดับวิชาบังคับก่อนผิด", res4["CHK5"], False)

    conn.execute("DELETE FROM prerequisite WHERE code='06026260'")
    conn.execute("UPDATE plan_item SET year=2, semester=1 WHERE code='06026260'")

    # CHK1 — หน่วยกิตรวมไม่ตรงกับที่ประกาศ
    conn.execute("UPDATE program SET total_credits = 120")
    ck("CHK1 จับหน่วยกิตรวมไม่ตรง",
       {r["id"]: r["ok"] for r in verify_db(conn)}["CHK1"], False)
    conn.execute("UPDATE program SET total_credits = 39")

    # CHK6 — วิชาซ้ำในภาคเรียนเดียวกัน
    conn.execute("INSERT INTO plan_item (program_id, year, semester, code,"
                 " credits) VALUES ('IT2565', 1, 1, '06026101', 3)")
    ck("CHK6 จับวิชาซ้ำในภาคเดียวกัน",
       {r["id"]: r["ok"] for r in verify_db(conn)}["CHK6"], False)
    conn.execute("DELETE FROM plan_item WHERE id = (SELECT MAX(id) FROM plan_item)")

    # CHK7 — ภาระหน่วยกิตเกินเกณฑ์
    # ต้องเพิ่ม "จำนวนวิชา" ไม่ใช่เพิ่มหน่วยกิตของวิชาเดิมให้สูง
    # เพราะวิชา 6 หน่วยกิตขึ้นไปจะถูกมองว่าเป็นภาคบล็อกแล้วได้รับยกเว้น
    # (ดูข้อจำกัดที่บันทึกไว้ในฟังก์ชัน verify_db)
    for c in ("06026240", "06026241", "06026259", "06026260"):
        conn.execute("INSERT INTO plan_item (program_id, year, semester, code,"
                     " credits) VALUES ('IT2565', 1, 1, ?, 3)", (c,))
    ck("CHK7 จับหน่วยกิตต่อภาคเกินเกณฑ์",
       {r["id"]: r["ok"] for r in verify_db(conn)}["CHK7"], False)
    conn.execute("DELETE FROM plan_item WHERE year=1 AND semester=1 AND code IN"
                 " ('06026240','06026241','06026259','06026260')")

    # ยืนยันอีกครั้งว่ากลับสู่สภาพสะอาดแล้วไม่มีการเตือนผิด
    ck("คืนค่าแล้วไม่มีคำเตือนค้าง",
       [r["id"] for r in verify_db(conn) if not r["ok"]], [])

    # ── 6. citation, category/type และวิชาเลือกยืดหยุ่นในฐานข้อมูลจริง ──
    ck("v_plan มีเลขหน้าให้อ้างอิง",
       conn.execute("SELECT pages FROM v_plan WHERE code='06026240'"
                    ).fetchone()[0], "[62]")
    ck("นับวิชาบังคับด้วยคอลัมน์ type ได้ตรง ๆ",
       conn.execute("SELECT COUNT(*) FROM plan_item WHERE year=1 AND semester=1"
                    " AND type='บังคับ'").fetchone()[0], 4)
    ck("นับหน่วยกิตหมวดศึกษาทั่วไปด้วย category ได้",
       conn.execute("SELECT SUM(credits) FROM plan_item"
                    " WHERE category='หมวดวิชาศึกษาทั่วไป'").fetchone()[0], 12)
    ck("วิชาเลือกยืดหยุ่นตอบได้ว่าเรียนเทอมไหน",
       conn.execute("SELECT terms FROM v_course_terms WHERE code='06026261'"
                    ).fetchone()[0], "2/1, 2/2")
    ck("v_course_terms ตอบวิชาในแผนได้ด้วย",
       conn.execute("SELECT terms FROM v_course_terms WHERE code='06026240'"
                    ).fetchone()[0], "2/1")

    # ── 7. การต่อเลขหน้าท้ายคำตอบ ────────────────────────────────────
    ck("ดึงเลขหน้าจากผลลัพธ์ SQL",
       pages_of([{"code": "06026240", "source_page": 62},
                 {"code": "06026241", "c.source_page": 62},
                 {"code": "06026390", "source_page": None}]), [62])
    ck("ดึงเลขหน้าหลายหน้าจากคอลัมน์ pages (JSON)",
       pages_of([{"code": "06046400", "pages": "[23, 287]"},
                 {"code": "06046402", "p.pages": [23, 288]},
                 {"code": "06066000", "pages": None}]), [23, 287, 288])
    ck("ต่อเลขหน้าท้ายคำตอบ",
       with_citation("9 หน่วยกิต", [12]), "9 หน่วยกิต (อ้างอิงหน้า 12)")
    ck("ไม่มีเลขหน้าก็ไม่แต่งขึ้นมา",
       with_citation("9 หน่วยกิต", []), "9 หน่วยกิต")
    ck("ไม่ต่อซ้ำถ้าคำตอบอ้างหน้าอยู่แล้ว",
       with_citation("9 หน่วยกิต (อ้างอิงหน้า 12)", [12]),
       "9 หน่วยกิต (อ้างอิงหน้า 12)")
    ck("ANSWER_PROMPT format ได้โดยไม่ KeyError",
       "source_pages" in ANSWER_PROMPT.format(question="ถาม", rows="[]"), True)

    # ── 8. detect_sections() — จับป้ายหัวข้อภาษาไทย แทนตาราง PROGRAM_PAGE_RANGES ──
    # เอกสารจำลองด้วยตัวคั่น <!-- PDF_PAGE N --> (แบบ intermediate_vlm.md จริง) ครบทุก
    # เคสขอบที่เจอจริงตอนตรวจกับ BIT/IT/DSBA/AIT/GENED ทั้ง 5 โปรแกรม
    def _pg(n, body):
        return f"<!-- PDF_PAGE {n} -->\n{body}\n"

    two_plan_doc = "".join([
        _pg(10, "### 3.1.3 รายวิชา\nเนื้อหารายวิชา..."),
        _pg(11, "รายวิชาต่อ ๆ ไป"),
        # ประโยคแทรกแบบ DSBA — มีคำว่า "ร่วม" ต้องไม่ถูกจับเป็นหัวข้อแผนจริง
        _pg(12, "สำหรับแผนการศึกษาที่ไม่เข้าร่วมโครงการสหกิจศึกษา\nสำหรับแผนการศึกษาที่เข้าร่วมโครงการสหกิจศึกษา"),
        _pg(13, "3.1.4 แผนการศึกษา\n3.1.4.1 แผนการศึกษาที่ไม่เข้าโครงการสหกิจศึกษา\nปีที่ 1 ภาคการศึกษาที่ 1"),
        _pg(14, "ปีที่ 4 ภาคการศึกษาที่ 2\nรวมตลอดหลักสูตร 126 หน่วยกิต"),
        _pg(15, "3.1.4.2 แผนการศึกษาที่เข้าโครงการสหกิจศึกษา\nปีที่ 1 ภาคการศึกษาที่ 1"),
        _pg(16, "เนื้อหาสหกิจศึกษาต่อ"),
        _pg(17, "รวมตลอดหลักสูตร 126 หน่วยกิต"),
        _pg(18, "ความหมายของรหัสประจำรายวิชา — เนื้อหาอื่นที่ไม่ใช่ section ไหนเลย"),
        _pg(19, "เนื้อหาแทรกอื่น ๆ ก่อนถึงภาคผนวกคำอธิบายรายวิชา"),
        _pg(20, "# คำอธิบายรายวิชา\n06026200 แคลคูลัส 1\nวิชาบังคับก่อน : ไม่มี"),
    ])
    got = detect_sections(two_plan_doc)
    ck("detect_sections: course_list เริ่มที่หน้าแรกของ 'รายวิชา'", got.get("course_list"), (10, 12))
    ck("detect_sections: nocoop ไม่ติดกับดัก 'ไม่เข้าร่วม' (มีคำว่าร่วม)", got.get("nocoop"), (13, 14))
    ck("detect_sections: coop ไม่ติดกับดัก 'เข้าร่วม' (มีคำว่าร่วม)", got.get("coop"), (15, 17))
    ck("detect_sections: coop จบที่ 'รวมตลอดหลักสูตร' ไม่ใช่กินยาวไปจนถึง courses",
       got.get("coop"), (15, 17))
    ck("detect_sections: courses (คำอธิบายรายวิชา) เริ่มถูกหน้า ไม่ใช่หน้า 18/19 ที่เป็นแค่เนื้อหาคั่น",
       got.get("courses"), (20, 20))

    single_plan_doc = "".join([
        _pg(1, "3.2 รายวิชา\nเนื้อหารายวิชา"),
        _pg(2, "3.3 แผนการศึกษา\nปีที่ 1 ภาคการศึกษาที่ 1"),
        _pg(3, "รวมตลอดหลักสูตร 120 หน่วยกิต"),
        _pg(4, "องค์ประกอบภาคสนาม — เนื้อหาคั่นก่อนภาคผนวก"),
        _pg(5, "# คำอธิบายรายวิชา\n06046400 แคลคูลัส 1"),
    ])
    got2 = detect_sections(single_plan_doc)
    ck("detect_sections: เล่มแผนเดียว (ไม่แยกสหกิจ) ได้ key 'plan' ไม่ใช่ nocoop/coop",
       ("plan" in got2, "nocoop" in got2, "coop" in got2), (True, False, False))
    ck("detect_sections: 'plan' แผนเดียวก็ตัดจบที่ 'รวมตลอดหลักสูตร' เหมือนกัน",
       got2.get("plan"), (2, 3))

    no_plan_doc = "".join([
        _pg(1, "3.4 รายวิชาในหมวดวิชาศึกษาทั่วไป\nตารางวิชา..."),
        _pg(2, "ภาคผนวก ก คำอธิบายรายวิชา\n90641004 โครงงานกลุ่ม 1"),
    ])
    got3 = detect_sections(no_plan_doc)
    ck("detect_sections: เอกสารไม่มีแผนการศึกษาเลย (แบบ GENED) ไม่มี key แผนใด ๆ",
       any(k in got3 for k in ("nocoop", "coop", "plan")), False)
    ck("detect_sections: ยังจับ courses จากภาคผนวกที่ขึ้นต้น 'ภาคผนวก ก' ได้",
       got3.get("courses"), (2, 2))

    def _detect_raises_valueerror(text):
        try:
            detect_sections(text)
            return False
        except ValueError:
            return True
    ck("detect_sections: เอกสารไม่มีตัวคั่นหน้าเลย -> ValueError ชัดเจน (ไม่ใช่พังเงียบ)",
       _detect_raises_valueerror("ไม่มีตัวคั่นหน้าอยู่เลยในข้อความนี้"), True)

    sliced13 = slice_pages(two_plan_doc, 13, 13)
    ck("slice_pages: ใช้ได้กับตัวคั่นแบบ <!-- PDF_PAGE N --> ด้วย ไม่ใช่แค่ --- Page N ---",
       ("PDF_PAGE 13" in sliced13, "PDF_PAGE 14" in sliced13,
        "แผนการศึกษาที่ไม่เข้าโครงการสหกิจศึกษา" in sliced13),
       (True, False, True))

    conn.close()
    db.unlink(missing_ok=True)

    print("=" * 68)
    print(f"  ผ่าน {passed} · ไม่ผ่าน {failed}")
    print("=" * 68)
    return failed == 0


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Lab 8B — จากข้อความที่สกัดได้ สู่ฐานข้อมูลที่ตอบคำถามได้",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="ตรวจสภาพแวดล้อม")
    sub.add_parser("selftest", help="ทดสอบ schema กฎตรวจ และด่าน SQL")

    p = sub.add_parser("demo", help="สร้างข้อมูลตัวอย่างสำหรับทดลอง")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("schema", help="เขียน JSON Schema และ SQL DDL")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("extract", help="Markdown -> JSON พร้อมวงจรซ่อม")
    p.add_argument("-i", "--input", required=True, help="ไฟล์ Markdown จาก Lab 7B")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--rounds", type=int, default=MAX_REPAIR_ROUNDS)
    p.add_argument("--max-chars", type=int, default=40000)
    p.add_argument("--program", choices=sorted(PROGRAM_PAGE_RANGES),
                   help="ป้ายกำกับ (IT/DSBA/BIT/AIT/GENED) ใช้เป็น fallback ตาราง legacy "
                        "เฉพาะตอนที่จับป้ายหัวข้อในไฟล์ไม่ได้เลย ปกติไม่ต้องระบุ — ค่าเริ่มต้น "
                        "คือจับ section จากป้ายหัวข้อ 'รายวิชา'/'แผนการศึกษา'/'คำอธิบายรายวิชา' "
                        "ในไฟล์เอง (ดู detect_sections())")
    p.add_argument("--section",
                   help="section ที่ต้องการ เช่น course_list, nocoop, coop, plan, courses "
                        "(ไม่ระบุจะใช้ section แรกตามลำดับหน้าที่จับได้)")
    p.add_argument("--no-detect", action="store_true",
                   help="ปิดการจับ section อัตโนมัติ — ป้อนทั้งไฟล์เข้า LLM รวดเดียว "
                        "(เหมือนไม่ระบุ --program/--section/--start-page/--end-page เลยแบบเดิม)")
    p.add_argument("--start-page", type=int, help="override ช่วงหน้าเอง (ใช้แทนการจับอัตโนมัติ)")
    p.add_argument("--end-page", type=int)

    p = sub.add_parser("import-lab7b",
                       help="Lab 7B JSON -> Lab 8B JSON โดยไม่เรียก LLM ซ้ำ")
    p.add_argument("-i", "--input", required=True,
                   help="pred_vlm.json, pred_text.json หรือ pred_baseline.json จาก Lab 7B")
    p.add_argument("-o", "--output", default=None,
                   help="JSON schema ของ Lab 8B (โหมดไฟล์เดียว; ไม่ใช้คู่กับ --split-dir)")
    p.add_argument("--program", choices=sorted(PROGRAM_PAGE_RANGES), default=None,
                   help="โปรแกรมของ pred JSON นี้ — ใช้กับ --split-dir")
    p.add_argument("--split-dir", default=None,
                   help="แยกโปรแกรมที่มี nocoop+coop ออกเป็นสองโปรแกรม (AIT/GENED ที่มีแผนเดียว/"
                        "ไม่มีแผน -> 1) เขียน <dir>/<section>/curriculum.json + <dir>/manifest.json")
    p.add_argument("--source-md", default=None,
                   help="Markdown ต้นทางของโปรแกรมนี้ (intermediate_vlm.md หรือ curriculum.md) — "
                        "ใช้กับ --split-dir เพื่อจับช่วงหน้า nocoop/coop จากป้ายหัวข้อ "
                        "'แผนการศึกษา...' ในเนื้อหาเองแทนตาราง PROGRAM_PAGE_RANGES ที่ hardcode "
                        "ไว้ล่วงหน้า ไม่ระบุจะถอยไปใช้ตาราง legacy ตาม --program")
    p.add_argument("--program-meta", default=None,
                   help="JSON {program_id: {name, total_credits, years}} เช่น IT_nocoop — ใช้กับ --split-dir")
    p.add_argument("--program-id", default=None, help="ทับ program id จาก Lab 7B")
    p.add_argument("--program-name", default=None, help="ชื่อหลักสูตรภาษาไทย")
    p.add_argument("--total-credits", type=int, default=None,
                   help="หน่วยกิตรวมตามที่หลักสูตรประกาศ; ไม่ระบุจะคำนวณจากแผน")
    p.add_argument("--years", type=int, default=None,
                   help="จำนวนปีของหลักสูตร; ไม่ระบุจะใช้ปีสูงสุดในแผน")

    p = sub.add_parser("load", help="JSON -> SQLite")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-d", "--database", required=True)
    p.add_argument("--replace", action="store_true", help="ลบฐานข้อมูลเดิมก่อน")
    p.add_argument("--allow-orphan", action="store_true",
                   help="ปิด FOREIGN KEY ชั่วคราว เพื่อโหลดข้อมูลที่ยังไม่ครบ "
                        "แล้วให้ CHK2 รายงานรหัสที่ไม่มีคำอธิบาย")

    p = sub.add_parser("verify", help="ตรวจความสอดคล้อง 7 ข้อ")
    p.add_argument("-d", "--database", required=True)
    p.add_argument("-o", "--output", default="")

    p = sub.add_parser("ask", help="ถามหนึ่งคำถาม")
    p.add_argument("-d", "--database", required=True)
    p.add_argument("-q", "--question", required=True)

    p = sub.add_parser("eval", help="ประเมินด้วยชุดคำถามทอง")
    p.add_argument("-d", "--database", required=True)
    p.add_argument("-q", "--questions", required=True)
    p.add_argument("-o", "--output", default="")

    p = sub.add_parser("eval-gt",
                       help="เทียบผลสกัดกับเฉลย ทีละฟิลด์ (Precision/Recall/F1)")
    p.add_argument("-p", "--pred", required=True,
                   help="JSON ของ Lab 7B หรือ Lab 8B ที่ต้องการวัด")
    p.add_argument("-g", "--ground-truth", required=True,
                   help="ไฟล์เฉลยหนึ่งไฟล์ หรือโฟลเดอร์ เช่น data/ground_truth/")
    p.add_argument("-o", "--output", default="")

    args = ap.parse_args()
    if args.cmd == "check":
        sys.exit(0 if check_environment() else 1)
    if args.cmd == "selftest":
        sys.exit(0 if cmd_selftest(args) else 1)
    {"demo": cmd_demo, "schema": cmd_schema, "extract": cmd_extract,
     "import-lab7b": cmd_import_lab7b,
     "load": cmd_load, "verify": cmd_verify, "ask": cmd_ask,
     "eval": cmd_eval, "eval-gt": cmd_eval_gt}[args.cmd](args)


if __name__ == "__main__":
    main()