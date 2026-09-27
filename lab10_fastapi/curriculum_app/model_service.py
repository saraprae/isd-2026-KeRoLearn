"""Qwen text-to-SQL adapter that reuses Lab 8B's Ollama helper."""

import json
import re
from types import ModuleType
from typing import Any

import requests

from .config import Settings
from .database import (
    CurriculumDatabase,
    SQL_SCHEMA_CONTEXT,
    UnsupportedGenedMetadata,
)


SQL_SCHEMA = {
    "type": "object",
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
    "additionalProperties": False,
}
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class QwenTextToSQL:
    def __init__(self, config: Settings, lab8b: ModuleType):
        self.config = config
        self.lab8b = lab8b

    def available(self) -> bool:
        try:
            return requests.get(
                f"{self.config.ollama_url}/api/tags", timeout=3
            ).ok
        except requests.RequestException:
            return False

    def _chat(self, prompt: str, schema: dict) -> dict:
        # MODEL INTEGRATION POINT: เปลี่ยนฟังก์ชันนี้หากไม่ใช้ Ollama/Qwen
        # เปลี่ยนเฉพาะบล็อกเรียกโมเดลด้านล่างเป็น inference จริง เช่น:
        # from .my_model_module import infer  # เปลี่ยนเป็นโมดูลจริงใน curriculum_app
        # result = infer(prompt=prompt, schema=schema)
        # หากรับแค่ prompt ให้ใช้ result = infer(prompt)
        # ค่าเริ่มต้นยังใช้ Ollama ของ Lab 8B; คงส่วนตรวจผลและ return data ไว้
        result = self.lab8b.ollama_generate(
            prompt, fmt=schema, timeout=self.config.request_timeout,
            model=self.config.ollama_model, num_ctx=4096, num_predict=256,
        )

        if isinstance(result, dict):
            data = result
        elif isinstance(result, str):
            data = self.lab8b.parse_json_loose(result)
        else:
            raise ValueError("ผลจากโมเดลต้องเป็น dict หรือข้อความ JSON")

        # JSON ที่ parse สำเร็จอาจเป็น list, null หรือตัวเลขแทน object
        if not isinstance(data, dict):
            raise ValueError("ผลจากโมเดลต้องเป็น JSON object (dict)")

        required_keys = schema.get("required", [])
        missing_keys = [key for key in required_keys if key not in data]
        if missing_keys:
            raise ValueError(f"ผลจากโมเดลไม่มี key ที่ต้องใช้: {missing_keys}")

        for key in required_keys:
            if schema.get("properties", {}).get(key, {}).get("type") == "string":
                if not isinstance(data[key], str) or not data[key].strip():
                    raise ValueError(f"ผลจากโมเดล key {key} ต้องเป็นข้อความที่ไม่ว่าง")

        return data

    def make_sql(
        self, question: str, *, program: str | None = None, track: str | None = None,
    ) -> str:
        normalized_question = question.strip().rstrip("?？").strip()

        total_credit_questions = {
            "หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไร",
            "หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไหร่",
            "หลักสูตรนี้มีกี่หน่วยกิต",
        }
        if normalized_question in total_credit_questions:
            return "SELECT total_credits FROM program"
        context = json.dumps(
            {"program": program, "track": track}, ensure_ascii=False,
        )
        prompt = f"""แปลงคำถามเป็น SQLite SQL จาก schema นี้
{SQL_SCHEMA_CONTEXT}

บริบทฐานข้อมูลที่ระบบเลือกแล้ว: {context}
ข้อมูลในตารางเป็นของฐานข้อมูลที่เลือกนี้เท่านั้น

กติกา:
- ใช้เฉพาะตารางและคอลัมน์ใน schema ที่ให้ไว้
- ตอบ SELECT หรือ WITH เพียงคำสั่งเดียว ห้ามแก้ไขฐานข้อมูล
- ระบบเลือกไฟล์ฐานข้อมูลตามหลักสูตรและแผนเรียบร้อยแล้ว
- track เป็นตัวเลือกไฟล์ฐานข้อมูล ไม่ใช่คอลัมน์ ห้ามอ้าง track เป็นคอลัมน์ใน SQL
- ไม่ต้องกรองชื่อหลักสูตรหรือแผนซ้ำเมื่อผู้ใช้กล่าวถึงฐานข้อมูลที่เลือก
- ห้ามนำชื่อหลักสูตรไปกรองเป็นชื่อรายวิชา
- ถามจำนวนหรือรายการรายวิชาทั้งหมด ให้ใช้ course
- ถามหน่วยกิตรายเทอม ให้ใช้ v_semester_credits
- ถามรายวิชาตามปีและเทอม ให้ใช้ v_plan
- ถามหน่วยกิตรวมของหลักสูตร ให้เลือก total_credits จาก program
- ถามระยะเวลาหลักสูตร ให้เลือก years จาก program
- กรองรหัสหรือชื่อรายวิชาเมื่อผู้ใช้ระบุรายวิชาที่ต้องการค้นหา
- ยึดฐานข้อมูลที่ระบบเลือก ไม่เปลี่ยนฐานข้อมูลตามข้อความคำถาม
- เมื่อถามหน่วยกิตรวมของหลักสูตรที่เลือก ให้ใช้ SELECT total_credits FROM program
- สำหรับคำถามนี้ไม่ต้องกรอง name_th, name_en หรือ program_id เพราะระบบเลือกฐานข้อมูลของหลักสูตรให้แล้ว

ตัวอย่าง:
คำถาม: หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไร
SQL: SELECT total_credits FROM program

คำถาม: มีรายวิชาทั้งหมดกี่วิชา
SQL: SELECT COUNT(*) AS n_courses FROM course

คำถาม: GENED มีรายวิชาทั้งหมดกี่วิชา
SQL: SELECT COUNT(*) AS n_courses FROM course

คำถาม: หลักสูตรนี้มีกี่หน่วยกิต
SQL: SELECT total_credits FROM program

คำถาม: หลักสูตร IT coop มีกี่หน่วยกิต
SQL: SELECT total_credits FROM program

คำถาม: หลักสูตร DSBA nocoop เรียนกี่ปี
SQL: SELECT years FROM program

คำถาม: ต้องเรียนวิชาอะไรมาก่อนจึงจะลงเรียน 06026215 ได้
SQL: SELECT requires FROM prerequisite WHERE code='06026215' AND kind='pre'

คำถาม: ปี 1 เทอม 1 เรียนกี่หน่วยกิต
SQL: SELECT credits, n_courses FROM v_semester_credits WHERE year=1 AND semester=1

คำถาม: ปี 2 เทอม 1 เรียนวิชาอะไรบ้าง
SQL: SELECT code, name_th, credits FROM v_plan WHERE year=2 AND semester=1 ORDER BY code

คำถาม: วิชาแคลคูลัส 1 มีกี่หน่วยกิต
SQL: SELECT credits FROM course WHERE name_th LIKE '%แคลคูลัส 1%'

คำถาม: หลักสูตรเรียนทั้งหมดกี่ปี
SQL: SELECT years FROM program

คำถาม: {question}
ตอบ JSON ที่มี key ชื่อ sql"""
        sql = self._chat(prompt, SQL_SCHEMA)["sql"].strip()
        return re.sub(r"^```(?:sql)?|```$", "", sql, flags=re.MULTILINE).strip()

    def ask(
        self, database: CurriculumDatabase, question: str, *,
        program: str | None = None, track: str | None = None,
    ) -> dict:
        program = program.strip().upper() if program is not None else None
        track = track.strip().lower() if track is not None else None
        if program is not None and track is None:
            tracks = self.config.db_paths.get(program, {})
            if len(tracks) == 1:
                track = next(iter(tracks))
        generated_sql = self.make_sql(
            question,
            program=program,
            track=track,
        )

        try:
            sql, rows = database.query_from_model(
                generated_sql,
                is_gened=(program == "GENED"),
            )
        except UnsupportedGenedMetadata as exc:
            return {
                "question": question,
                "sql": generated_sql,
                "rows": [],
                "answer": str(exc),
            }
        answer = self.summarize(question, rows) if rows else "ไม่พบข้อมูลนี้ในฐานข้อมูลหลักสูตร"
        return {"question": question, "sql": sql, "rows": rows, "answer": answer}

    def summarize(self, question: str, rows: list[dict[str, Any]]) -> str:
        shown_rows = rows[:40]
        prompt = f"""ตอบภาษาไทยจากผลฐานข้อมูลเท่านั้น
คำถาม: {question}
ผลฐานข้อมูลที่ส่งให้สรุป: {json.dumps(shown_rows, ensure_ascii=False)}
ส่งให้สรุป {len(shown_rows)} แถว จาก rows ที่ API คืน {len(rows)} แถว

กติกา:
- ตอบเป็นประโยคภาษาไทยที่อ่านเข้าใจง่าย
- ห้ามเพิ่มข้อมูลที่ไม่มีในผลฐานข้อมูล และห้ามตีความ NULL ว่าเป็นศูนย์
- ถ้ามีหลายรายการให้สรุปจากข้อมูลที่ได้รับ ไม่อ้างว่าแสดงรายวิชาทั้งหมด
- จำนวนแถวที่ได้รับอาจถูกจำกัด ไม่ใช่จำนวนรายวิชาทั้งฐานข้อมูล
- ถ้าเป็นค่าตัวเลขจาก query ให้ระบุหน่วยตามคำถาม เช่น หน่วยกิต วิชา หรือปี

ตอบ JSON ที่มี key ชื่อ answer"""
        answer = self._chat(prompt, ANSWER_SCHEMA)["answer"].strip()
        if len(rows) > len(shown_rows):
            answer += (
                f"\nหมายเหตุ: สรุปจาก {len(shown_rows)} แถวแรก "
                f"จากผลที่ API คืน {len(rows)} แถว ดูรายการที่เหลือใน rows"
            )
        return answer
