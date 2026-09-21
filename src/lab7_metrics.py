#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 lab7_metrics.py  —  โมดูลวัดผล CER / WER สำหรับ Lab 7 (ทั้งกลุ่ม A และ B)
================================================================================

 วิชา 06026240 การพัฒนาระบบอัจฉริยะ (Intelligent System Development)

 ไฟล์นี้เป็น "โมดูลกลาง" ที่ทั้ง lab7a_transcript.py และ lab7b_curriculum.py
 เรียกใช้ร่วมกัน  นักศึกษาไม่ต้องแก้ไฟล์นี้ (แต่ควรอ่านให้เข้าใจ เพราะข้อสอบออก)

 --------------------------------------------------------------------------
 ทำไมต้องมีไฟล์นี้แยก?
 --------------------------------------------------------------------------
 เพราะ "การวัดผล" ต้องเหมือนกันทั้งสองกลุ่ม ไม่งั้นเอาตัวเลขมาเทียบกันไม่ได้
 ถ้ากลุ่ม A normalize ข้อความแบบหนึ่ง กลุ่ม B normalize อีกแบบหนึ่ง
 ค่า CER ที่ได้จะเทียบกันไม่ได้เลย  --> เป็นหลักการสำคัญของงาน benchmark

 --------------------------------------------------------------------------
 สารบัญ
 --------------------------------------------------------------------------
   ส่วนที่ 1  Levenshtein distance (แกนกลางของทั้ง CER และ WER)
   ส่วนที่ 2  การตัดคำ (tokenization) — และทำไมภาษาไทยถึงเป็นปัญหา
   ส่วนที่ 3  Normalization — ขั้นตอนที่คนมักลืม แล้วได้ค่า error ผิด
   ส่วนที่ 4  CER / WER
   ส่วนที่ 5  ตัวสะสมผล (Accumulator) สำหรับวัดแยกราย attribute
   ส่วนที่ 6  การจับคู่รายการ (list alignment) ก่อนวัดผล
   ส่วนที่ 7  พิมพ์ตารางรายงาน
================================================================================
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


# ==============================================================================
#  ส่วนที่ 1 — LEVENSHTEIN DISTANCE
# ==============================================================================
#
#  Levenshtein distance = จำนวนครั้งน้อยที่สุดของการ "แก้ไข" ที่ทำให้
#  ข้อความ A กลายเป็นข้อความ B  โดยการแก้ไขมี 3 แบบ:
#
#     S (Substitution) แทนที่ 1 ตัว     : "แมว" -> "แมล"
#     D (Deletion)     ลบ 1 ตัว         : "แมว" -> "แม"
#     I (Insertion)    แทรก 1 ตัว       : "แมว" -> "แมวๆ"
#
#  ทั้ง CER และ WER ใช้สูตรเดียวกันเป๊ะ ต่างกันแค่ "หน่วย" ที่นับ
#     CER --> หน่วยเป็น "ตัวอักษร" (character)
#     WER --> หน่วยเป็น "คำ"       (word)
#
#  สูตร:   ERROR RATE = (S + D + I) / N        เมื่อ N = ความยาวของ ground truth
#
#  ⚠️ ข้อควรระวัง: ค่านี้ "เกิน 1.0 ได้" ถ้าโมเดลพ่นข้อความยาวเกินจริงมาก
#     (I เยอะมาก) ซึ่งเป็นอาการ hallucination ทั่วไปของ LLM
#     ดังนั้นถ้าเห็น CER = 3.5 อย่าคิดว่าโค้ดพัง — ให้ไปดู output ดิบ
# ==============================================================================


def levenshtein(ref: Sequence, hyp: Sequence) -> tuple[int, int, int, int]:
    """
    คำนวณ Levenshtein distance แบบ dynamic programming
    และ "ย้อนรอย" (backtrace) เพื่อแยกว่าเป็น error ชนิดไหนบ้าง

    Parameters
    ----------
    ref : ลำดับอ้างอิง (ground truth)  — เป็น str หรือ list[str] ก็ได้
    hyp : ลำดับที่โมเดลทำนายมา (hypothesis)

    Returns
    -------
    (distance, n_sub, n_del, n_ins)

    หมายเหตุเรื่องความจำ:
      ตาราง DP มีขนาด (len(ref)+1) x (len(hyp)+1)
      ถ้าข้อความยาว 10,000 ตัวอักษร จะกินหน่วยความจำ ~800 MB --> เครื่องค้าง
      ในแล็บนี้เราวัดทีละ field (ยาวไม่เกิน ~200 ตัวอักษร) จึงปลอดภัย
      ถ้าจะเอาไปวัดทั้งหน้า ให้เปลี่ยนไปใช้ไลบรารี `rapidfuzz` หรือ `jiwer`
    """
    n, m = len(ref), len(hyp)

    # ---- กรณีพิเศษ: ฝั่งใดฝั่งหนึ่งว่าง ----------------------------------
    if n == 0 and m == 0:
        return 0, 0, 0, 0
    if n == 0:
        return m, 0, 0, m          # ไม่มีของจริงเลย แต่โมเดลพ่นมา = insertion ล้วน
    if m == 0:
        return n, 0, n, 0          # มีของจริง แต่โมเดลไม่พ่นอะไรเลย = deletion ล้วน

    # ---- สร้างตาราง DP --------------------------------------------------
    # d[i][j] = ระยะห่างระหว่าง ref[:i] กับ hyp[:j]
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i                # แปลง ref[:i] -> "" ต้องลบ i ครั้ง
    for j in range(m + 1):
        d[0][j] = j                # แปลง "" -> hyp[:j] ต้องแทรก j ครั้ง

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]          # ตรงกัน ไม่เสียค่าอะไร
            else:
                d[i][j] = 1 + min(
                    d[i - 1][j - 1],               # substitution
                    d[i - 1][j],                   # deletion
                    d[i][j - 1],                   # insertion
                )

    # ---- ย้อนรอยจากมุมขวาล่างกลับมามุมซ้ายบน เพื่อนับชนิด error ----------
    # ทำไมต้องย้อนรอย? เพราะเราอยากรู้ว่าโมเดล "อ่านผิด" (sub) หรือ
    # "อ่านตก" (del) หรือ "แต่งเพิ่ม" (ins) — สามอย่างนี้แก้คนละวิธี
    i, j = n, m
    n_sub = n_del = n_ins = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and d[i][j] == d[i - 1][j - 1]:
            i, j = i - 1, j - 1                    # เดินทแยง แบบไม่เสียค่า
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            n_sub += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            n_del += 1
            i -= 1
        else:
            n_ins += 1
            j -= 1

    return d[n][m], n_sub, n_del, n_ins


# ==============================================================================
#  ส่วนที่ 2 — TOKENIZATION (การตัดคำ)
# ==============================================================================
#
#  ⚠️ นี่คือประเด็นที่สำคัญที่สุดของแล็บนี้สำหรับภาษาไทย ⚠️
#
#  WER = Word Error Rate  ต้องรู้ว่า "คำ" คืออะไรก่อน
#  ภาษาอังกฤษง่าย: ตัดด้วยช่องว่าง  "MACHINE LEARNING" -> ["MACHINE","LEARNING"]
#  ภาษาไทย: ไม่มีช่องว่างระหว่างคำ!
#      "การเรียนรู้ของเครื่อง"  ถ้าตัดด้วยช่องว่างจะได้ 1 คำ
#      แต่จริง ๆ คือ ["การ","เรียนรู้","ของ","เครื่อง"] = 4 คำ
#
#  ผลที่ตามมา: ถ้าใช้ split() กับภาษาไทย
#      - WER จะกลายเป็น "ถูกทั้งประโยค หรือ ผิดทั้งประโยค" (0.0 หรือ 1.0)
#      - ไม่มีความละเอียดเลย เอาไปเปรียบเทียบโมเดลไม่ได้
#
#  ทางแก้: ใช้ pythainlp ตัดคำด้วยอัลกอริทึม newmm (dictionary-based maximal matching)
#      pip install pythainlp
#
#  ถ้าไม่ติดตั้ง โค้ดจะ fallback ไปใช้ split() และ "เตือน" ในรายงาน
#  --> ตอนเขียนรายงานต้องระบุด้วยว่าใช้ tokenizer อะไร ไม่งั้นตัวเลขไม่มีความหมาย
# ==============================================================================

_THAI_TOKENIZER = None
TOKENIZER_NAME = "whitespace (fallback)"

try:
    from pythainlp.tokenize import word_tokenize as _pythainlp_tokenize  # type: ignore

    _THAI_TOKENIZER = _pythainlp_tokenize
    TOKENIZER_NAME = "pythainlp/newmm"
except ImportError:
    pass


# ตรวจว่ามีอักขระไทยอยู่ในสตริงหรือไม่ (ช่วง Unicode ของไทยคือ U+0E00–U+0E7F)
_THAI_RE = re.compile(r"[\u0E00-\u0E7F]")


def tokenize(text: str) -> list[str]:
    """
    ตัดคำแบบ 'ผสม' — เลือกวิธีตัดตามภาษาของข้อความ

    - มีอักขระไทย + ติดตั้ง pythainlp แล้ว  -> ใช้ newmm
    - นอกนั้น                              -> ตัดด้วยช่องว่าง

    ตัวอย่าง:
        tokenize("MACHINE LEARNING")        -> ['MACHINE', 'LEARNING']
        tokenize("การเรียนรู้ของเครื่อง")   -> ['การ','เรียนรู้','ของ','เครื่อง']  (ถ้ามี pythainlp)
    """
    if not text:
        return []

    if _THAI_TOKENIZER is not None and _THAI_RE.search(text):
        # keep_whitespace=False เพื่อไม่ให้ช่องว่างกลายเป็น token
        toks = _THAI_TOKENIZER(text, engine="newmm", keep_whitespace=False)
        return [t for t in toks if t.strip()]

    return [t for t in text.split() if t]


# ==============================================================================
#  ส่วนที่ 3 — NORMALIZATION
# ==============================================================================
#
#  💡 บทเรียนสำคัญ: ค่า CER ที่สูง ส่วนใหญ่ไม่ได้แปลว่าโมเดลแย่
#     แต่แปลว่า "เราลืม normalize"
#
#  ตัวอย่างจริงจากไฟล์ ground truth ของแล็บนี้:
#     GT เก็บว่า  : "programmingformanagement"        (ไม่มีช่องว่าง ตัวพิมพ์เล็ก)
#     LLM พ่นออกมา : "Programming for Management"      (มีช่องว่าง ตัวพิมพ์ใหญ่)
#
#     ถ้าไม่ normalize  -> CER ≈ 0.30  (ดูเหมือนโมเดลอ่านผิด 30%)
#     ถ้า normalize     -> CER = 0.00  (โมเดลอ่านถูกทุกตัวอักษร!)
#
#  --> เราต้องวัด "ความสามารถในการอ่านตัวอักษร" ไม่ใช่ "รูปแบบการจัดหน้า"
#
#  ระดับของ normalization ที่ใช้ในแล็บนี้ (เลือกได้ตาม field):
#     NONE   ไม่ทำอะไร               — ใช้เมื่อรูปแบบสำคัญ (เช่น "3(3-0-6)")
#     BASIC  NFC + ตัดช่องว่างหัวท้าย + ยุบช่องว่างซ้ำ
#     STRICT BASIC + ตัวพิมพ์เล็ก + ลบช่องว่างทั้งหมด + แปลงเลขไทยเป็นอารบิก
# ==============================================================================

# ตารางแปลงเลขไทย ๐๑๒๓๔๕๖๗๘๙ -> 0123456789
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def normalize(text: Any, level: str = "strict") -> str:
    """
    ทำให้ข้อความอยู่ในรูปมาตรฐานก่อนนำไปเทียบ

    Parameters
    ----------
    text  : ข้อความ (หรือ None / ตัวเลข — จะแปลงเป็น str ให้)
    level : "none" | "basic" | "word" | "strict"

              none    ไม่แตะต้องเลย
              basic   NFC + ยุบช่องว่าง + ตัดหัวท้าย
              word    basic + ตัวพิมพ์เล็ก + เลขไทย->อารบิก   (ยัง "คง" ช่องว่างไว้)
                      ใช้กับ WER เพราะถ้าลบช่องว่างจะตัดคำอังกฤษไม่ได้
              strict  word + ลบช่องว่างทั้งหมด
                      ใช้กับ CER เพราะ ground truth ของเราไม่มีช่องว่าง

    ทำไมต้อง NFC?
        ภาษาไทยมีสระและวรรณยุกต์ที่ "ลอย" อยู่บนพยัญชนะ
        คำเดียวกันอาจเข้ารหัสได้หลายแบบ (ลำดับ combining marks ต่างกัน)
        NFC = Normalization Form Canonical Composition บังคับให้เป็นรูปเดียว
        ถ้าไม่ทำ  "ที่" สองตัวที่ดูเหมือนกันอาจถูกนับว่าต่างกัน --> CER ผิดฟรี ๆ
    """
    if text is None:
        return ""
    s = str(text)

    if level == "none":
        return s

    # --- BASIC ---------------------------------------------------------
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\u200b", "")            # zero-width space (พบบ่อยใน PDF ไทย)
    s = s.replace("\xa0", " ")             # non-breaking space
    s = re.sub(r"\s+", " ", s).strip()     # ยุบช่องว่าง/ขึ้นบรรทัดใหม่ให้เหลือช่องเดียว

    if level == "basic":
        return s

    # --- WORD ----------------------------------------------------------
    s = s.translate(_THAI_DIGITS)          # ๓ -> 3
    s = s.lower()                          # "B+" -> "b+"  (GT ของเราเก็บเป็นตัวเล็ก)

    if level == "word":
        return s

    # --- STRICT --------------------------------------------------------
    s = re.sub(r"\s+", "", s)              # ลบช่องว่างทั้งหมด (GT ของเราไม่มีช่องว่าง)
    return s


# ==============================================================================
#  ส่วนที่ 4 — CER / WER
# ==============================================================================


def cer(ref: str, hyp: str, level: str = "strict") -> tuple[float, int, int, int, int]:
    """
    Character Error Rate

    Returns
    -------
    (cer, n_sub, n_del, n_ins, n_ref_chars)

    ถ้า ground truth ว่าง:
        - hypothesis ว่างด้วย -> CER = 0.0  (ถูกต้อง: ไม่มีก็คือไม่มี)
        - hypothesis ไม่ว่าง  -> CER = 1.0  (โมเดลแต่งขึ้นมาเอง = ผิด 100%)
    """
    r, h = normalize(ref, level), normalize(hyp, level)
    if len(r) == 0:
        return (0.0 if len(h) == 0 else 1.0), 0, 0, len(h), 0
    dist, s, d, i = levenshtein(r, h)
    return dist / len(r), s, d, i, len(r)


def wer(ref: str, hyp: str, level: str = "word") -> tuple[float, int, int, int, int]:
    """
    Word Error Rate

    ⚠️ สังเกตว่า default level = "word" ไม่ใช่ "strict"
       เพราะ strict ลบช่องว่างทิ้งหมด --> ตัดคำภาษาอังกฤษไม่ได้เลย
       (จะเหลือ 1 คำยาว ๆ)  นี่คือกับดักที่นักศึกษาพลาดกันบ่อย
    """
    r_toks = tokenize(normalize(ref, level))
    h_toks = tokenize(normalize(hyp, level))
    if len(r_toks) == 0:
        return (0.0 if len(h_toks) == 0 else 1.0), 0, 0, len(h_toks), 0
    dist, s, d, i = levenshtein(r_toks, h_toks)
    return dist / len(r_toks), s, d, i, len(r_toks)


# ==============================================================================
#  ส่วนที่ 5 — ACCUMULATOR (ตัวสะสมผลราย attribute)
# ==============================================================================
#
#  ⚠️ กับดักทางสถิติที่สำคัญมาก:
#
#     "ค่าเฉลี่ยของ CER รายช่อง"  ≠  "CER รวมของทุกช่อง"
#
#     สมมติมี 2 ช่อง:
#        ช่อง A: ref ยาว 2 ตัว  ผิด 1 ตัว  -> CER = 0.50
#        ช่อง B: ref ยาว 98 ตัว ผิด 1 ตัว  -> CER = 0.01
#
#     ค่าเฉลี่ยแบบ macro  = (0.50 + 0.01)/2 = 0.255   <-- ช่องสั้นมีน้ำหนักเท่าช่องยาว
#     ค่าแบบ micro (รวม)  = (1+1)/(2+98)   = 0.020   <-- ถ่วงน้ำหนักตามความยาว
#
#  ในรายงาน OCR มาตรฐาน "CER" หมายถึงแบบ micro เสมอ
#  แต่แบบ macro ก็มีประโยชน์: มันบอกว่า "ช่องสั้น ๆ อย่างเกรดพังไหม"
#  --> เราจึงรายงานทั้งสองค่า และให้นักศึกษาอภิปรายว่าทำไมต่างกัน
# ==============================================================================


@dataclass
class FieldStat:
    """สะสมสถิติของ attribute หนึ่ง ๆ (เช่น 'ชื่อวิชา' หรือ 'เกรด')"""

    label: str
    # --- ตัวนับสำหรับ CER แบบ micro ---
    c_err: int = 0          # ผลรวม S+D+I ระดับตัวอักษร
    c_ref: int = 0          # ผลรวมความยาว ground truth ระดับตัวอักษร
    c_sub: int = 0
    c_del: int = 0
    c_ins: int = 0
    # --- ตัวนับสำหรับ WER แบบ micro ---
    w_err: int = 0
    w_ref: int = 0
    # --- ตัวนับสำหรับ exact match ---
    n_items: int = 0        # จำนวนช่องที่วัดทั้งหมด
    n_exact: int = 0        # จำนวนช่องที่ตรงเป๊ะหลัง normalize
    n_missing: int = 0      # ช่องที่ GT มีค่า แต่โมเดลไม่ตอบ (ตอบ null/ว่าง)
    n_hallucinated: int = 0 # ช่องที่ GT ว่าง แต่โมเดลแต่งมา
    # --- เก็บตัวอย่างที่ผิดไว้ให้ดู (สูงสุด 5 รายการ) ---
    samples: list[dict] = field(default_factory=list)

    def add(self, ref: Any, hyp: Any, key: str = "", cer_level: str = "strict",
            wer_level: str = "word", track_wer: bool = True) -> None:
        """เพิ่มผลการเทียบ 1 ช่องเข้าไปในสถิติ"""
        self.n_items += 1

        r_norm = normalize(ref, cer_level)
        h_norm = normalize(hyp, cer_level)

        if r_norm and not h_norm:
            self.n_missing += 1
        if not r_norm and h_norm:
            self.n_hallucinated += 1

        # ---- CER ----
        _, s, d, i, n = cer(ref, hyp, cer_level)
        self.c_err += s + d + i
        self.c_ref += n
        self.c_sub += s
        self.c_del += d
        self.c_ins += i

        # ---- WER (ข้ามได้สำหรับ field ที่ไม่ใช่ข้อความ เช่น เกรด/หน่วยกิต) ----
        if track_wer:
            _, ws, wd, wi, wn = wer(ref, hyp, wer_level)
            self.w_err += ws + wd + wi
            self.w_ref += wn

        # ---- Exact match ----
        if r_norm == h_norm:
            self.n_exact += 1
        elif len(self.samples) < 5:
            self.samples.append({"key": key, "gt": str(ref), "pred": str(hyp)})

    # ---- ค่าที่คำนวณออกมา ----
    @property
    def cer(self) -> float:
        return self.c_err / self.c_ref if self.c_ref else 0.0

    @property
    def wer(self) -> float:
        return self.w_err / self.w_ref if self.w_ref else 0.0

    @property
    def acc(self) -> float:
        """Exact-match accuracy: สัดส่วนช่องที่ตรงเป๊ะ"""
        return self.n_exact / self.n_items if self.n_items else 0.0


# ==============================================================================
#  ส่วนที่ 6 — LIST ALIGNMENT (การจับคู่รายการ)
# ==============================================================================
#
#  ปัญหา: ก่อนจะวัด CER ของ "ชื่อวิชา" เราต้องรู้ก่อนว่า
#         วิชาไหนใน output ของโมเดล คู่กับ วิชาไหนใน ground truth
#
#  วิธีที่ผิด (แต่คนทำกันเยอะ): จับคู่ตามลำดับ index
#         gt[0] <-> pred[0], gt[1] <-> pred[1], ...
#         ถ้าโมเดล "อ่านตก" ไป 1 แถว ทุกแถวหลังจากนั้นจะเลื่อนหมด
#         --> CER พุ่งเป็น 0.9 ทั้งที่โมเดลอ่านถูกเกือบหมด
#
#  วิธีที่ถูก: จับคู่ด้วย "กุญแจ" ที่เสถียร เช่น รหัสวิชา
#         แล้วรายงานแยกว่า
#            matched  = จับคู่ได้     -> เอาไปวัด CER/WER
#            missed   = GT มี แต่โมเดลไม่มี  (อ่านตกแถว)
#            spurious = โมเดลมี แต่ GT ไม่มี (แต่งแถวขึ้นมา)
#
#  ตัวชี้วัดของการจับคู่คือ Precision / Recall / F1 ระดับ "แถว"
#  ซึ่งเป็นคนละเรื่องกับ CER ระดับ "ตัวอักษร" — ต้องรายงานทั้งคู่
# ==============================================================================


@dataclass
class AlignResult:
    matched: list[tuple[dict, dict]] = field(default_factory=list)   # (gt_item, pred_item)
    missed: list[dict] = field(default_factory=list)                 # GT มี pred ไม่มี
    spurious: list[dict] = field(default_factory=list)               # pred มี GT ไม่มี

    @property
    def recall(self) -> float:
        denom = len(self.matched) + len(self.missed)
        return len(self.matched) / denom if denom else 0.0

    @property
    def precision(self) -> float:
        denom = len(self.matched) + len(self.spurious)
        return len(self.matched) / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def align_by_key(gt_items: Iterable[dict], pred_items: Iterable[dict],
                 key_fn: Callable[[dict], str]) -> AlignResult:
    """
    จับคู่รายการสองชุดด้วยฟังก์ชันสร้างกุญแจ

    key_fn ควรคืนค่าที่ normalize แล้ว เช่น รหัสวิชาที่ตัดช่องว่างออก

    หมายเหตุ: ใช้ dict ของ list เพราะกุญแจอาจซ้ำได้
    (ในไฟล์หลักสูตร DSBA รหัส 06026259 ปรากฏ 2 แถวจริง ๆ)
    """
    res = AlignResult()

    # สร้างดัชนีของฝั่ง prediction
    pool: dict[str, list[dict]] = {}
    for it in pred_items:
        pool.setdefault(key_fn(it), []).append(it)

    for g in gt_items:
        k = key_fn(g)
        bucket = pool.get(k)
        if bucket:
            res.matched.append((g, bucket.pop(0)))   # หยิบตัวแรกออกมาใช้
        else:
            res.missed.append(g)

    # อะไรที่เหลือใน pool = โมเดลแต่งเกินมา
    for leftover in pool.values():
        res.spurious.extend(leftover)

    return res


def align_multipass(gt_items: Iterable[dict], pred_items: Iterable[dict],
                    key_fns: Sequence[Callable[[dict], str]]) -> AlignResult:
    """
    จับคู่หลายรอบ: ใช้กุญแจที่ 'เข้มที่สุด' ก่อน แล้วค่อยผ่อนลงเรื่อย ๆ

    ทำไมต้องทำแบบนี้?
      บางครั้งกุญแจเดียวไม่พอ  เช่นในตารางหลักสูตร:
        - รหัส "06026xxx" (ช่องวิชาเลือก) ปรากฏ 2 แถวในภาคเดียวกัน
          ต่างกันแค่ชื่อ ("วิชาเลือกกลุ่มวิทยาการข้อมูล 1" กับ "... 2")
          --> ต้องใช้ชื่อมาช่วยแยก
        - แต่ถ้าโมเดลอ่านชื่อผิดนิดเดียว การบังคับให้ชื่อตรงจะทำให้จับคู่ไม่ได้เลย
          แล้วถูกนับเป็น "ตกแถว + แต่งเกิน" ทั้งที่จริงโมเดลอ่านเจอ

      ทางออก: รอบแรกใช้ (รหัส+ปี+ภาค+ชื่อ) จับคู่ที่ชัวร์ ๆ ก่อน
              รอบสองใช้ (รหัส+ปี+ภาค) เก็บตกที่เหลือ
      เทคนิคนี้เรียกว่า cascading / progressive matching
      ใช้กันทั่วไปในงาน entity resolution และ record linkage

    key_fns : เรียงจากเข้มไปหลวม เช่น [key_strict, key_loose]
    """
    res = AlignResult()
    remaining_gt = list(gt_items)
    remaining_pred = list(pred_items)

    for fn in key_fns:
        pool: dict[str, list[dict]] = {}
        for it in remaining_pred:
            pool.setdefault(fn(it), []).append(it)

        still_missing: list[dict] = []
        for g in remaining_gt:
            bucket = pool.get(fn(g))
            if bucket:
                res.matched.append((g, bucket.pop(0)))
            else:
                still_missing.append(g)

        remaining_gt = still_missing
        remaining_pred = [p for lst in pool.values() for p in lst]

    res.missed = remaining_gt
    res.spurious = remaining_pred
    return res


# ==============================================================================
#  ส่วนที่ 7 — รายงานผล
# ==============================================================================


def print_table(stats: dict[str, FieldStat], title: str = "ผลการประเมิน") -> None:
    """พิมพ์ตารางสรุปลง console"""
    print()
    print("=" * 96)
    print(f"  {title}")
    print(f"  tokenizer สำหรับ WER: {TOKENIZER_NAME}")
    print("=" * 96)
    hdr = (f"{'Attribute':<26} {'N':>5} {'CER':>8} {'WER':>8} {'Exact':>8} "
           f"{'Sub':>6} {'Del':>6} {'Ins':>6} {'Miss':>6}")
    print(hdr)
    print("-" * 96)

    for st in stats.values():
        if st.n_items == 0:
            continue
        wer_txt = f"{st.wer:.4f}" if st.w_ref else "   —  "
        print(f"{st.label:<26} {st.n_items:>5} {st.cer:>8.4f} {wer_txt:>8} "
              f"{st.acc:>7.1%} {st.c_sub:>6} {st.c_del:>6} {st.c_ins:>6} {st.n_missing:>6}")

    # ---- แถวรวม (micro) ----
    tot_err = sum(s.c_err for s in stats.values())
    tot_ref = sum(s.c_ref for s in stats.values())
    tot_werr = sum(s.w_err for s in stats.values())
    tot_wref = sum(s.w_ref for s in stats.values())
    tot_n = sum(s.n_items for s in stats.values())
    tot_ex = sum(s.n_exact for s in stats.values())

    print("-" * 96)
    micro_cer = tot_err / tot_ref if tot_ref else 0.0
    micro_wer = tot_werr / tot_wref if tot_wref else 0.0
    micro_acc = tot_ex / tot_n if tot_n else 0.0
    print(f"{'รวม (micro)':<26} {tot_n:>5} {micro_cer:>8.4f} {micro_wer:>8.4f} {micro_acc:>7.1%}")

    # ---- แถวรวม (macro) : เฉลี่ยแบบให้ทุก attribute น้ำหนักเท่ากัน ----
    active = [s for s in stats.values() if s.n_items > 0]
    if active:
        macro_cer = sum(s.cer for s in active) / len(active)
        macro_wer = sum(s.wer for s in active) / len(active)
        macro_acc = sum(s.acc for s in active) / len(active)
        print(f"{'รวม (macro)':<26} {'':>5} {macro_cer:>8.4f} {macro_wer:>8.4f} {macro_acc:>7.1%}")
    print("=" * 96)


def print_errors(stats: dict[str, FieldStat], limit: int = 3) -> None:
    """แสดงตัวอย่างที่ทำนายผิด — ส่วนที่มีค่าที่สุดสำหรับการวิเคราะห์"""
    print()
    print("ตัวอย่างที่ทำนายผิด (ใช้ตอบคำถามท้ายบท)")
    print("-" * 96)
    shown = 0
    for st in stats.values():
        for s in st.samples[:limit]:
            print(f"  [{st.label}] {s['key']}")
            print(f"      GT   : {s['gt']!r}")
            print(f"      PRED : {s['pred']!r}")
            shown += 1
    if shown == 0:
        print("  (ไม่มี — ตรงทุกช่อง)")
    print("-" * 96)


def stats_to_dict(stats: dict[str, FieldStat]) -> dict:
    """แปลงเป็น dict เพื่อบันทึกเป็น JSON / เอาไปทำกราฟต่อ"""
    out = {"tokenizer": TOKENIZER_NAME, "attributes": {}}
    for k, st in stats.items():
        if st.n_items == 0:
            continue
        out["attributes"][k] = {
            "label": st.label,
            "n_items": st.n_items,
            "cer": round(st.cer, 6),
            "wer": round(st.wer, 6) if st.w_ref else None,
            "exact_match_acc": round(st.acc, 6),
            "n_sub": st.c_sub, "n_del": st.c_del, "n_ins": st.c_ins,
            "n_missing": st.n_missing, "n_hallucinated": st.n_hallucinated,
            "n_ref_chars": st.c_ref,
            "error_samples": st.samples,
        }
    tot_err = sum(s.c_err for s in stats.values())
    tot_ref = sum(s.c_ref for s in stats.values())
    out["overall_micro_cer"] = round(tot_err / tot_ref, 6) if tot_ref else 0.0
    return out


def save_csv(stats: dict[str, FieldStat], path: str, extra: dict | None = None) -> None:
    """
    บันทึกเป็น CSV เพื่อเอาไปเปิดใน Excel ทำกราฟเปรียบเทียบระหว่าง pipeline
    extra = คอลัมน์เพิ่ม เช่น {"pipeline": "typhoon-ocr", "model": "qwen3:4b"}
    """
    import csv

    extra = extra or {}
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig = Excel เปิดไทยได้
        cols = list(extra.keys()) + [
            "attribute", "n_items", "cer", "wer", "exact_match_acc",
            "n_sub", "n_del", "n_ins", "n_missing", "n_ref_chars",
        ]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for st in stats.values():
            if st.n_items == 0:
                continue
            row = dict(extra)
            row.update({
                "attribute": st.label,
                "n_items": st.n_items,
                "cer": round(st.cer, 6),
                "wer": round(st.wer, 6) if st.w_ref else "",
                "exact_match_acc": round(st.acc, 6),
                "n_sub": st.c_sub, "n_del": st.c_del, "n_ins": st.c_ins,
                "n_missing": st.n_missing, "n_ref_chars": st.c_ref,
            })
            w.writerow(row)


# ==============================================================================
#  ทดสอบตัวเองอย่างรวดเร็ว:  python3 lab7_metrics.py
# ==============================================================================

if __name__ == "__main__":
    print(f"Tokenizer ที่ใช้ได้: {TOKENIZER_NAME}")
    print()

    tests = [
        ("แคลคูลัส 1", "แคลคูลัส 1", "ตรงเป๊ะ"),
        ("แคลคูลัส1", "Calculus 1", "อ่านเป็นอังกฤษ"),
        ("programmingformanagement", "Programming for Management",
         "ต่างแค่ช่องว่าง/ตัวพิมพ์ -> strict ต้องได้ 0"),
        ("b+", "B+", "ตัวพิมพ์ใหญ่/เล็ก"),
        ("3(3-0-6)", "3(3-0-6)", "หน่วยกิต"),
        ("06026240", "0602624O", "เลข 0 กับตัว O — error คลาสสิกของ OCR"),
    ]
    for ref, hyp, note in tests:
        c, s, d, i, n = cer(ref, hyp)
        w, *_ = wer(ref, hyp)
        print(f"  {note}")
        print(f"    GT={ref!r}  PRED={hyp!r}")
        print(f"    CER={c:.4f} (S={s} D={d} I={i} N={n})   WER={w:.4f}")
        print()
