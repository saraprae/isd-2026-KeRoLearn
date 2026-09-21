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

# ช่วงหน้าเริ่มต้นของแต่ละโปรแกรม อิงตัวคั่น --- Page N --- ที่ pipeline.py ฝังไว้แล้ว
# key ระดับในสุดคือชื่อ section: nocoop / coop / plan / courses
PROGRAM_PAGE_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "IT":    {"nocoop": (31, 37), "coop": (38, 44), "courses": (324, 360)},
    "DSBA":  {"nocoop": (23, 29), "coop": (30, 36), "courses": (314, 341)},
    "BIT":   {"nocoop": (26, 30), "coop": (31, 35), "courses": (238, 257)},
    "AIT":   {"plan": (23, 26), "courses": (287, 304)},
    "GENED": {"courses": (39, 117)},   # ไม่มีแผนของตัวเอง — courses อย่างเดียว
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
        description_th: str | None = None
        # เลขหน้าในเล่มหลักสูตรที่พบข้อมูลนี้ — ใช้อ้างอิงตอนตอบคำถาม
        source_page: int | None = None

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
        source_page: int | None = None
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
        category: str | None = None
        type: str | None = None
        note: str | None = None
        source_page: int | None = None

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
    source_page INTEGER
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
    source_page INTEGER
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
    source_page   INTEGER,
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
       COALESCE(p.source_page, c.source_page) AS source_page
FROM plan_item p
LEFT JOIN course c ON c.code = p.code;

-- ตอบคำถาม "วิชานี้เรียนได้ตอนไหน" ได้ทั้งวิชาที่ล็อกเทอมและวิชาเลือกยืดหยุ่น
-- ถ้าไม่มี VIEW นี้ LLM ต้องรู้เองว่าต้องไปดูสองตาราง ซึ่งมันจะลืม
CREATE VIEW IF NOT EXISTS v_course_terms AS
SELECT p.code AS code, c.name_th AS name_th,
       (p.year || '/' || p.semester) AS terms,
       p.credits AS credits, 'plan' AS source,
       COALESCE(p.source_page, c.source_page) AS source_page
FROM plan_item p LEFT JOIN course c ON c.code = p.code
UNION ALL
SELECT e.code, COALESCE(c.name_th, e.name_th),
       e.allowed_terms, COALESCE(e.credits, c.credits), 'elective_slot',
       COALESCE(e.source_page, c.source_page)
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

def slice_pages(text: str, start: int, end: int) -> str:
    """ตัด Markdown เหลือเฉพาะช่วงหน้า [start, end] จากตัวคั่น --- Page N ---"""
    parts = PAGE_MARKER_RE.split(text)   # [pre, "N1", chunk1, "N2", chunk2, ...]
    out = []
    for i in range(1, len(parts), 2):
        page_no = int(parts[i])
        if start <= page_no <= end:
            out.append(f"--- Page {page_no} ---{parts[i + 1]}")
    if not out:
        raise ValueError(f"ไม่พบตัวคั่นหน้าในช่วง {start}-{end} "
                         f"— ตรวจว่า pipeline.py ฝัง --- Page N --- มาจริงหรือไม่")
    return "\n".join(out)

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
    elif args.program:
        ranges = PROGRAM_PAGE_RANGES[args.program]
        section = args.section or next(iter(ranges))
        if section not in ranges:
            raise SystemExit(f"โปรแกรม {args.program} ไม่มี section '{section}' "
                             f"(มีแค่ {list(ranges)})")
        start, end = ranges[section]
        print(f"  ตัดเฉพาะหน้า {start}-{end} ({args.program}/{section})")
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

def _credit_parts(value: Any) -> tuple[int | None, int | None, int | None, int | None]:
    """แปล 3(2-2-5) ของ Lab 7B เป็นคอลัมน์ตัวเลขของ Lab 8B"""
    text = str(value or "").strip()
    m = re.search(r"(\d+)\s*\(\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*\)", text)
    if m:
        parts = tuple(map(int, m.groups()))
        if parts[0] > 12:      # เกินขอบของ schema (credits <= 12) = อ่านผิด เช่น เลข "15 ชั่วโมง" ในคำอธิบายหลุดมา
            raise ValueError(f"หน่วยกิต {parts[0]} เกิน 12 (น่าจะอ่านผิด): {value!r}")
        return parts  # type: ignore[return-value]
    # หน่วยกิตเดี่ยวต้องเป็นเลข 1-2 หลักล้วน ๆ — เลข 6 หลักขึ้นไปคือรหัสวิชาที่หลุดเข้าช่องหน่วยกิต
    m = re.fullmatch(r"(\d{1,2})(?:\s*หน่วยกิต)?", text)
    if not m:
        raise ValueError(f"อ่านหน่วยกิตไม่ได้: {value!r}")
    return int(m.group(1)), None, None, None


def _lab7b_codes(value: Any) -> list[str]:
    """แตกรหัส `A หรือ B`; คืนเฉพาะรหัสตัวเลข 8 หลักที่โหลด DB ได้"""
    return re.findall(r"(?<!\d)\d{8}(?!\d)", str(value or ""))


def _placeholder_code(raw_code: str) -> str | None:
    """
    แปลงรหัส wildcard ของเล่ม (90644xxx) เป็นรหัสช่องวิชาที่เก็บลงฐานข้อมูลได้

    คืน None ถ้าไม่ใช่รูปแบบ wildcard — ผู้เรียกจะได้ข้ามอย่างมีเหตุผล
    """
    token = str(raw_code or "").strip().replace(" ", "")
    if _WILDCARD_RE.match(token):
        return PLACEHOLDER_PREFIX + token.upper()
    return None


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


def convert_lab7b(data: dict, *, program_id: str | None = None,
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
    plan: list[dict] = []
    prerequisites: list[dict] = []
    slot_by_code: dict[str, dict] = {}
    seen_plan: set[tuple] = set()
    seen_pre: set[tuple] = set()
    wildcard_placeholders = 0
    flexible_slots = 0

    for index, src in enumerate(data.get("courses") or []):
        raw_code = str(src.get("code") or "").strip()
        codes = _lab7b_codes(raw_code)
        page = _lab7b_page(src)
        category = (str(src.get("category")).strip()
                    if src.get("category") else None)
        ctype = str(src.get("type")).strip() if src.get("type") else None
        note = str(src.get("note")).strip() if src.get("note") else None

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

        try:
            credit, lecture, lab, self_h = _credit_parts(src.get("credits"))
        except ValueError as exc:
            try:
                y0, s0 = int(src.get("year")), int(src.get("semester"))
            except (TypeError, ValueError):
                y0 = s0 = 0
            if 1 <= y0 <= 8 and 1 <= s0 <= 3:
                # แถวในแผนต้องมีหน่วยกิตเพื่อนับยอดรวม — ข้ามพร้อมเตือนเหมือนเดิม
                warnings.append(f"courses[{index}] {exc}; ข้ามรายการ")
                continue
            # วิชาเลือกที่ไม่ผูกปี/เทอม (รวมวิชาที่มีแต่ในหน้าคำอธิบาย) ไม่กระทบยอดหน่วยกิตของแผน
            # เก็บไว้โดยไม่มีหน่วยกิต เพื่อให้ตอบ "วิชานี้คืออะไร/บังคับก่อนอะไร" ได้ (ห้ามทำข้อมูลหายเงียบ)
            credit = lecture = lab = self_h = None
            warnings.append(f"{raw_code}: {exc}; เก็บวิชาไว้โดยไม่มีหน่วยกิต")
        if "หรือ" in str(src.get("credits") or ""):
            warnings.append(f"{raw_code}: หน่วยกิตมีหลายแบบ; ใช้แบบแรก")

        for code in codes:
            candidate = {
                "code": code,
                "name_th": str(src.get("name_th") or raw_code or code).strip(),
                "name_en": (str(src["name_en"]).replace("\n", " ").strip()
                            if src.get("name_en") else None),
                "credits": credit,
                "lecture_h": lecture,
                "lab_h": lab,
                "self_h": self_h,
                "description_th": src.get("description_th"),
                "source_page": page,
            }
            old = course_by_code.get(code)
            if old is None:
                course_by_code[code] = candidate
            else:
                for key, value in candidate.items():
                    if old.get(key) in (None, "") and value not in (None, ""):
                        old[key] = value

        try:
            year = int(src.get("year"))
            semester = int(src.get("semester"))
        except (TypeError, ValueError):
            year = semester = 0

        flexible = str(src.get("flexible_year_semester") or "").strip() or None

        if not (1 <= year <= 8 and 1 <= semester <= 3):
            # ── ปี/เทอมไม่ชัดเจน — เก็บเป็น elective_slot แทนการทิ้ง ──────
            #    เดิมโค้ดนับ skipped_flexible แล้วปล่อยผ่าน ทำให้วิชาเลือกกว่า
            #    30 วิชาหายไปทั้งกลุ่ม พอมีคนถาม "06026240 เรียนได้ตอนไหน"
            #    ระบบตอบว่าไม่พบ ทั้งที่เล่มเขียนไว้ว่า 3/1, 3/2 หรือ 4/1
            flexible_slots += 1
            for code in codes:
                slot = {
                    "code": code,
                    "allowed_terms": flexible,
                    "name_th": str(src.get("name_th") or "").strip() or None,
                    "credits": credit,
                    "category": category,
                    "type": ctype,
                    "note": note,
                    "source_page": page,
                }
                old_slot = slot_by_code.get(code)
                if old_slot is None:
                    slot_by_code[code] = slot
                else:
                    for key, value in slot.items():
                        if old_slot.get(key) in (None, "") and value not in (None, ""):
                            old_slot[key] = value
            if not flexible:
                warnings.append(
                    f"{raw_code}: ปี/เทอม={year}/{semester} และไม่มี "
                    f"flexible_year_semester; เก็บเป็นวิชาเลือกที่ไม่ระบุเทอม")
        else:
            # alt_group จาก Lab 7B (สหกิจ "A หรือ B" ที่แยกเป็นสองแถวแล้ว) มาก่อน
            # ถ้าไม่มีค่อยใช้กฎเดิม: แถวเดียวที่มีหลายรหัส "A หรือ B"
            alt_group = (str(src["alt_group"]).strip() if src.get("alt_group")
                         else (f"lab7b_alt_{index}" if len(codes) > 1 else None))
            for code in codes:
                key = (year, semester, code, alt_group)
                if key not in seen_plan:
                    plan.append({"year": year, "semester": semester,
                                 "code": code, "credits": credit,
                                 "alt_group": alt_group,
                                 "category": category, "type": ctype,
                                 "note": note, "source_page": page})
                    seen_plan.add(key)
                elif is_slot:
                    # ช่องวิชาเดียวกันปรากฏซ้ำในภาคเดียวกัน (เช่น วิชาภาษา 2 ช่อง)
                    # ต้องแยกรหัสไม่ให้ชนกัน ไม่งั้น CHK6 จะเตือนว่าวิชาซ้ำ
                    n = 2
                    while (year, semester, f"{code}_{n}", alt_group) in seen_plan:
                        n += 1
                    dup_code = f"{code}_{n}"
                    course_by_code[dup_code] = dict(course_by_code[code],
                                                    code=dup_code)
                    plan.append({"year": year, "semester": semester,
                                 "code": dup_code, "credits": credit,
                                 "alt_group": alt_group,
                                 "category": category, "type": ctype,
                                 "note": note, "source_page": page})
                    seen_plan.add((year, semester, dup_code, alt_group))

        pre_codes = _lab7b_codes(src.get("prerequisite"))
        for code in codes:
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
        total_credits = sum(groups.values())
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
    with_page = sum(1 for c in result["courses"] if c.get("source_page"))
    report = {
        "source_courses": len(data.get("courses") or []),
        "converted_courses": len(result["courses"]),
        "plan_items": len(result["plan"]),
        "prerequisites": len(result["prerequisites"]),
        "elective_slots": len(result["elective_slots"]),
        # เดิมสองตัวนี้คือ "จำนวนข้อมูลที่ทิ้ง" ตอนนี้คือ "จำนวนข้อมูลที่กู้ไว้ได้"
        "wildcard_placeholders": wildcard_placeholders,
        "flexible_courses_kept": flexible_slots,
        "courses_with_source_page": with_page,
        "courses_without_source_page": len(result["courses"]) - with_page,
        "warnings": warnings,
    }
    if with_page == 0 and result["courses"]:
        report["warnings"].append(
            "ไม่มีวิชาใดมี source_page/pages เลย — pred JSON นี้สร้างจาก Lab 7B เวอร์ชันเก่า "
            "(ก่อนแนบเลขหน้า) ให้รัน lab7b_curriculum.py ใหม่ด้วย --pipeline vlm")
    return result, report


def plan_sections(program: str | None) -> dict[str, tuple[int, int]]:
    """section แผนการศึกษา (nocoop/coop) ของโปรแกรมนี้ — ว่างถ้าโปรแกรมมีแผนเดียว"""
    ranges = PROGRAM_PAGE_RANGES.get(program or "", {})
    return {k: v for k, v in ranges.items() if k in ("nocoop", "coop")}


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


def split_lab7b_by_plan(data: dict, program: str
                        ) -> tuple[dict[str, dict], dict[str, int], list[str]]:
    """
    แยกผล Lab 7B ที่รวมสองแผนไว้ในรอบเดียว ออกเป็นทีละ section จากเลขหน้า PDF

    กติกา (ไม่เรียก LLM และไม่ทิ้งข้อมูล):
      - แถวที่มีหน้าอยู่ในช่วง section ใด -> ไปอยู่ section นั้น
      - แถวที่เจอทั้งสองช่วง (วิชาเดียวกัน ปี/ภาคเดียวกัน ทั้งสองแผน) -> อยู่ทั้งสองฝั่ง
      - แถวที่จำแนกไม่ได้ (ไม่มีเลขหน้า หรืออยู่นอกช่วงแผน เช่นหน้าคำอธิบายรายวิชา)
        -> เก็บไว้ทั้งสองฝั่ง
    """
    sections = plan_sections(program)
    warnings: list[str] = []
    stats = {"rows": 0, "only_one_plan": 0, "in_both_plans": 0,
             "unclassified_kept_in_both": 0, "no_page_info": 0}
    parts = {s: {**{k: v for k, v in data.items() if k != "courses"}, "courses": []}
             for s in sections}

    chunk = int((data.get("_meta") or {}).get("pages_per_chunk") or 1)
    if chunk > 1:
        warnings.append(
            f"Lab 7B รันด้วย pages_per_chunk={chunk}: หนึ่งก้อนมีหลายหน้า วิชาทุกตัวในก้อนถูกแนบ "
            f"เลขหน้าทุกหน้าของก้อน ก้อนที่คร่อมรอยต่อ nocoop/coop จะทำให้วิชาไปอยู่สองฝั่งเกินจริง "
            f"(ตั้ง LAB7_CHUNK=1 เพื่อให้แยกได้แม่น)")

    for src in data.get("courses") or []:
        stats["rows"] += 1
        pages = _row_pages(src)
        hit = {name for name, (a, b) in sections.items()
               if any(a <= pg <= b for pg in pages)}
        if not pages:
            stats["no_page_info"] += 1
        if not hit:
            stats["unclassified_kept_in_both"] += 1
        elif len(hit) > 1:
            stats["in_both_plans"] += 1
        else:
            stats["only_one_plan"] += 1
        for name in (hit or set(sections)):
            a, b = sections[name]
            own = [pg for pg in pages if a <= pg <= b]
            row = dict(src)
            row["pages"] = own or pages
            row["source_page"] = (own or pages or [None])[0]
            parts[name]["courses"].append(row)

    failed = (data.get("_meta") or {}).get("ocr_failed_pages") or []
    if failed:
        warnings.append(f"Lab 7B OCR หน้า PDF {failed} ไม่สำเร็จ — วิชาในหน้าเหล่านั้นไม่อยู่ในข้อมูล")
    if stats["no_page_info"]:
        warnings.append(f"{stats['no_page_info']} แถวไม่มีเลขหน้า (pred JSON เก่า?) — เก็บไว้ทั้งสองฝั่ง")
    return parts, stats, warnings


def _write_converted(part: dict, pid: str, meta: dict, fallback: dict, outdir: Path
                     ) -> tuple[dict, dict]:
    converted, report = convert_lab7b(
        part,
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
    sections = plan_sections(args.program)

    manifest: dict[str, Any] = {
        "program": args.program, "source": str(args.input),
        "split_by_plan": bool(sections), "split_stats": None,
        "warnings": [], "programs": [],
    }
    if sections:
        parts, stats, warns = split_lab7b_by_plan(data, args.program)
        manifest["split_stats"], manifest["warnings"] = stats, warns
        jobs = [(f"{args.program}_{name}", name, parts[name], Path(name))
                for name in sections]
        fallback: dict = {}       # ค่า CLI ตัวเดียวใช้กับสองโปรแกรมไม่ได้ — ใช้ --program-meta แทน
        print(f"  แยก {args.program} ตามเลขหน้า: {stats['only_one_plan']} วิชาอยู่แผนเดียว · "
              f"{stats['in_both_plans']} ทั้งสองแผน · "
              f"{stats['unclassified_kept_in_both']} จำแนกไม่ได้ (เก็บทั้งสองฝั่ง)")
        for w in warns:
            print(f"    ⚠ {w}")
    else:
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
                                         root / rel)
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

    converted, report = convert_lab7b(
        data,
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
            " lecture_h, lab_h, self_h, description_th, source_page)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (c["code"], c["name_th"], c.get("name_en"), c["credits"],
             c.get("lecture_h"), c.get("lab_h"), c.get("self_h"),
             c.get("description_th"), c.get("source_page")))

    conn.execute("DELETE FROM plan_item WHERE program_id = ?", (pid,))
    for p in data.get("plan", []):
        conn.execute(
            "INSERT INTO plan_item (program_id, year, semester, code, credits,"
            " alt_group, category, type, note, source_page)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, p["year"], p["semester"], p["code"], p["credits"],
             p.get("alt_group"), p.get("category"), p.get("type"),
             p.get("note"), p.get("source_page")))

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
            " source_page) VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, s["code"], s.get("allowed_terms"), s.get("name_th"),
             s.get("credits"), s.get("category"), s.get("type"),
             s.get("note"), s.get("source_page")))
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
        "SELECT COUNT(*) FROM course WHERE source_page IS NOT NULL").fetchone()[0]
    conn.close()
    print(f"  โหลดเข้า {db} แล้ว")
    for t, c in n.items():
        print(f"    {t:<14} {c:>5} แถว")
    print(f"    course ที่มีเลขหน้าอ้างอิง {pages}/{n['course']}")
    if n["course"] and pages == 0:
        print("    ! ไม่มีเลขหน้าเลย — คำตอบจะอ้างอิงหน้าไม่ได้ "
              "ตรวจว่า Lab 7B แนบ source_page มาหรือยัง")


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
- ให้เลือกคอลัมน์ source_page ติดมาด้วยเสมอถ้าตารางหรือวิวนั้นมีคอลัมน์นี้
  เพราะคำตอบต้องอ้างอิงเลขหน้าในเล่มหลักสูตรได้
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
- ถ้าผลลัพธ์มีคอลัมน์ source_page ให้ใส่เลขหน้าเหล่านั้นลงใน source_pages
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

    รับทุกคอลัมน์ที่ลงท้ายด้วย source_page เพราะ JOIN มักเปลี่ยนชื่อคอลัมน์
    เป็น c.source_page หรือ p.source_page ตามที่ LLM เขียน SQL มา
    """
    pages: set[int] = set()
    for r in rows:
        for key, value in r.items():
            if not str(key).lower().endswith("source_page"):
                continue
            if value is None:
                continue
            m = re.search(r"\d+", str(value))
            if m:
                pages.add(int(m.group()))
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


def _index_by_code(courses: list[dict]) -> dict[str, dict]:
    """
    จัดทำดัชนีตามรหัสวิชา

    รหัส wildcard (90644xxx) ถูก normalize ให้ตรงกับฝั่งที่เก็บเป็น
    PLACEHOLDER_90644XXX เพื่อให้เทียบกันได้ ไม่ใช่นับเป็นวิชาคนละตัว

    ⚠️ บั๊กที่พบจริง: เล่มที่มีช่องวิชาเลือก wildcard เดียวกันซ้ำหลายช่อง (เช่น
    "06026xxx" เจอ 4 ครั้ง = วิชาเลือกกลุ่มวิทยาการข้อมูล 1/2/3/4 คนละวิชากัน)
    โค้ดเดิม map ทุกตัวไปที่ key เดียวกันเสมอ (PLACEHOLDER_06026XXX) แล้ว "เติม
    เฉพาะฟิลด์ว่าง" ทำให้วิชาที่ 2/3/4 หายไปเงียบๆ เหลือวิชาเดียวในการเทียบผล
    ตอนนี้: ถือว่าเป็น "หน้าเดียวกันเจอซ้ำ" (รวมกัน) ก็ต่อเมื่อชื่อ/ปี/เทอมตรงกันจริง
    ถ้าไม่ตรง (คนละวิชา) จะแยก key ด้วยส่วนต่อท้าย _2, _3, ... แทนการทับ/ทิ้ง
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
            key = base_key
            if is_placeholder(base_key):
                # หา key ที่ว่าง หรือ key ที่ fingerprint ตรงกัน (แถวเดิมเจอซ้ำหน้า) เท่านั้น
                n = 1
                while key in out and fingerprints.get(key) not in (fp, None):
                    n += 1
                    key = f"{base_key}_{n}"
            if key in out:
                # วิชาเดียวกันปรากฏหลายหน้า — เติมช่องที่ยังว่างแทนการทับ
                for f, v in c.items():
                    if out[key].get(f) in (None, "") and v not in (None, ""):
                        out[key][f] = v
            else:
                out[key] = dict(c, code=key)
                fingerprints[key] = fp
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
    for rec in by_code.values():
        if isinstance(rec.get("credits"), int) and all(
                isinstance(rec.get(k), int)
                for k in ("lecture_h", "lab_h", "self_h")):
            rec["credits"] = (f"{rec['credits']}({rec['lecture_h']}-"
                              f"{rec['lab_h']}-{rec['self_h']})")

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
        ck("เก็บเลขหน้าจาก source_page", by_code["06026240"]["source_page"], 12)
        ck("เก็บเลขหน้าจากชื่อฟิลด์อื่น (page)",
           by_code["06026241"]["source_page"], 13)
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
       conn.execute("SELECT source_page FROM v_plan WHERE code='06026240'"
                    ).fetchone()[0], 62)
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
    ck("ต่อเลขหน้าท้ายคำตอบ",
       with_citation("9 หน่วยกิต", [12]), "9 หน่วยกิต (อ้างอิงหน้า 12)")
    ck("ไม่มีเลขหน้าก็ไม่แต่งขึ้นมา",
       with_citation("9 หน่วยกิต", []), "9 หน่วยกิต")
    ck("ไม่ต่อซ้ำถ้าคำตอบอ้างหน้าอยู่แล้ว",
       with_citation("9 หน่วยกิต (อ้างอิงหน้า 12)", [12]),
       "9 หน่วยกิต (อ้างอิงหน้า 12)")
    ck("ANSWER_PROMPT format ได้โดยไม่ KeyError",
       "source_pages" in ANSWER_PROMPT.format(question="ถาม", rows="[]"), True)

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
                   help="ใช้ช่วงหน้า default ของโปรแกรมนี้ (IT/DSBA/BIT/AIT/GENED)")
    p.add_argument("--section",
                   help="section ในโปรแกรมนั้น เช่น nocoop, coop, plan, courses "
                        "(ไม่ระบุจะใช้ section แรกของโปรแกรมนั้น)")
    p.add_argument("--start-page", type=int, help="override ช่วงหน้าเอง (ใช้แทน --program)")
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
                   help="แยกโปรแกรมที่มี nocoop+coop ตามเลขหน้าอัตโนมัติ (IT/DSBA/BIT -> 2 โปรแกรม, "
                        "AIT/GENED -> 1) เขียน <dir>/<section>/curriculum.json + <dir>/manifest.json")
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