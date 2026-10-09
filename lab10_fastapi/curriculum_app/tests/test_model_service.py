"""Regression tests for the typed-query port; all writes use temporary SQLite files."""
import json
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from ocr_system import lab8b_curriculum_db as lab8b
from lab10_fastapi.curriculum_app.database import (
    CurriculumDatabase, UnsupportedGenedMetadata, request_budget,
)
from lab10_fastapi.curriculum_app.model_service import (
    CHOICE_SCHEMA, PLAN_PROMPT, InferenceResponseError, InferenceUnavailable,
    ModelOutputError, QueryExecutionError, QueryPlan, QwenTextToSQL,
    Term, collect_citations, compile_plan, question_hints, rule_plan, validate_plan,
)


class ModelServiceTests(unittest.TestCase):
    # รูปประโยคเก่าที่ถามยอดตามเกณฑ์จบเข้ากฎแล้ว; ใช้กรณีนี้ตรวจเส้นทาง Qwen ต่อ.
    fallback_question = "อยากสอบถามว่าข้อมูลยอดเครดิตในเกณฑ์สำเร็จการศึกษาของหลักสูตรนี้ระบุไว้เท่าใด"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "curriculum.db"
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE program(program_id TEXT,name_th TEXT,name_en TEXT,degree TEXT,
                                     total_credits INTEGER,years INTEGER);
                INSERT INTO program VALUES('IT','Test program','TEST','BSc',132,4);
                CREATE TABLE course(code TEXT PRIMARY KEY,name_th TEXT,name_en TEXT,credits INTEGER,
                    lecture_h INTEGER,lab_h INTEGER,self_h INTEGER,description_th TEXT);
                INSERT INTO course VALUES
                    ('00000001','Alpha','DATA SCIENCE',3,2,2,5,'Networks and data'),
                    ('00000002','Beta','DATABASE',3,3,0,6,'Databases'),
                    ('00000003','Gamma','UNKNOWN',NULL,NULL,NULL,NULL,NULL),
                    ('00000004','Delta','D A T A',2,2,0,4,'Networks'),
                    ('PLACEHOLDER_XX','Elective slot',NULL,3,NULL,NULL,NULL,NULL);
                CREATE TABLE plan_item(id INTEGER PRIMARY KEY,program_id TEXT,year INTEGER,
                    semester INTEGER,code TEXT,credits INTEGER,alt_group TEXT,note TEXT);
                INSERT INTO plan_item VALUES
                    (1,'IT',1,1,'00000001',3,NULL,NULL),
                    (2,'IT',1,1,'00000002',3,'choice','Choose one'),
                    (3,'IT',1,1,'PLACEHOLDER_XX',3,'choice','Choose one'),
                    (4,'IT',2,1,'00000003',NULL,NULL,NULL),
                    (5,'IT',2,2,'00000004',2,NULL,NULL);
                CREATE TABLE prerequisite(code TEXT,requires TEXT,kind TEXT);
                INSERT INTO prerequisite VALUES('00000001','00000002','pre');
                CREATE VIEW v_plan AS SELECT p.id,p.year,p.semester,p.code,c.name_th,c.name_en,
                    p.credits,p.alt_group,p.note FROM plan_item p LEFT JOIN course c ON c.code=p.code;
                CREATE VIEW v_semester_credits AS
                    SELECT year,semester,SUM(credits) AS credits,COUNT(*) AS n_courses FROM (
                        SELECT year,semester,MIN(credits) AS credits FROM plan_item
                        GROUP BY year,semester,COALESCE(alt_group,'x'||id)
                    ) GROUP BY year,semester;
            """)
        self.config = SimpleNamespace(
            ollama_url="http://127.0.0.1:11434",ollama_model="qwen3:4b",
            request_timeout=2,max_rows=100,
            db_paths={"IT":{"coop":self.path},"GENED":{"default":self.path}},
        )
        self.database = CurriculumDatabase(lab8b,self.path)
        self.model = QwenTextToSQL(self.config,lab8b)

    def ask(self,question,program="IT",track="coop"):
        return self.model.ask(self.database,question,program=program,track=track)

    def choice(self,intent="course_list",search_field="name_any",search_term=None):
        return dict(intent=intent,search_field=search_field,search_term=search_term)

    def response(self,content=None,reason="stop"):
        response = Mock()
        response.json.return_value = {"done_reason":reason,"message":{
            "content":json.dumps(self.choice()) if content is None else content}}
        return response

    def test_rules_answer_without_inference(self):
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            credits=self.ask("หลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไร")
            semester=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")
        self.assertEqual(credits["rows"],[{"total_credits":132}])
        self.assertEqual(semester["rows"][0]["credits"],6)
        self.assertEqual(semester["rows"][0]["n_courses"],2)
        self.assertIn("ช่องวิชา",semester["answer"])
        self.assertEqual(set(credits),{"question","sql","rows","answer","citations","performance"})

    def test_fallback_calls_model_once(self):
        with patch.object(self.model,"_chat",return_value=self.choice("program_credits")) as chat:
            answer=self.ask(self.fallback_question)
        self.assertEqual(chat.call_count,1)
        self.assertEqual(answer["rows"][0]["total_credits"],132)
        self.assertEqual(chat.call_args.args[1],CHOICE_SCHEMA)
        self.assertIn("selected_database",json.loads(chat.call_args.args[0]))

    def test_category_requests_never_query_an_unfiltered_catalog(self):
        questions = [
            "วิชาเสรีมีอะไรบ้าง", "รายวิชาเสรีมีอะไรบ้าง",
            "วิชาเลือกเสรีที่มี 3 หน่วยกิตมีวิชาไหนบ้าง",
            "วิชาแกนมีอะไรบ้าง", "วิชาเฉพาะด้านมีอะไรบ้าง",
            "วิชาบังคับมีอะไรบ้าง", "หมวดศึกษาทั่วไปต้องเก็บกี่หน่วยกิต",
            "กลุ่มวิชาเฉพาะเลือกเก็บกี่หน่วยกิต",
        ]
        with patch.object(self.model, "_chat", side_effect=AssertionError("No inference expected")), \
             patch.object(self.database, "query_from_model", side_effect=AssertionError("No query expected")):
            for question in questions:
                with self.subTest(question=question):
                    answer = self.ask(question)
                    self.assertEqual((answer["sql"], answer["rows"]), ("", []))
                    self.assertIn("หมวดวิชา", answer["answer"])
                    self.assertEqual(answer["performance"]["qwen_calls"], 0)

    def test_validator_rejects_category_as_name_or_unfiltered_list(self):
        for intent, term in [("course_list", None), ("course_list", "เสรี"), ("course_details", "เสรี")]:
            with self.subTest(intent=intent, term=term):
                with self.assertRaisesRegex(ValueError, "Category filters"):
                    validate_plan(QueryPlan(intent=intent, search_term=term), "วิชาเสรีมีอะไรบ้าง")

    def test_category_words_inside_quoted_course_names_are_literal(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'", ("วิชาเสรี",))
        question = 'ขอรายวิชาที่ชื่อภาษาไทยมีคำว่า "วิชาเสรี"'
        with patch.object(self.model, "_chat", return_value=self.choice("course_list", "name_th", "วิชาเสรี")):
            answer = self.ask(question)
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])

    def test_free_word_in_an_unquoted_name_predicate_is_not_a_category(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'", ("เสรีศึกษา",))
        with patch.object(self.model, "_chat", return_value=self.choice("course_list", "name_th", "เสรี")):
            answer = self.ask("ขอรายวิชาที่ชื่อภาษาไทยมีคำว่า เสรี")
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])

    def test_mandatory_prerequisite_word_is_not_a_course_category(self):
        with patch.object(self.model, "_chat", side_effect=AssertionError("No inference expected")):
            answer = self.ask("วิชา 00000001 มีวิชาบังคับก่อนอะไรบ้าง")
        self.assertEqual([r["requires"] for r in answer["rows"]], ["00000002"])

    def test_named_credit_lookup_strips_only_question_prefix_and_uses_rules(self):
        self.add_page_metadata()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000002'", ("วิชาชีพ",))
        for question, code in [("วิชาAlpha มีกี่หน่วยกิต", "00000001"),
                               ("รายวิชาAlphaมีกี่หน่วยกิต", "00000001"),
                               ("วิชาวิชาชีพมีกี่หน่วยกิต", "00000002")]:
            with self.subTest(question=question):
                answer = self.ask(question)
                self.assertEqual([(r["code"], r["credits"]) for r in answer["rows"]], [(code, 3)])
                self.assertEqual(answer["performance"]["qwen_calls"], 0)
                self.assertEqual(answer["citations"][0]["course_code"], code)

    def test_named_course_hint_repairs_prefix_in_qwen_choice(self):
        # บังคับ fallback เพื่อตรวจ hints ด้วย แม้ปกติคำถามนี้เข้ากฎเร็วแล้ว.
        with patch("lab10_fastapi.curriculum_app.model_service.rule_plan", return_value=None), \
             patch("lab10_fastapi.curriculum_app.model_service._structured_rule", return_value=None), \
             patch.object(self.model, "_chat", return_value=self.choice("course_details", "name_any", "วิชาAlpha")) as chat:
            answer = self.ask("วิชาAlphaมีกี่หน่วยกิต")
        self.assertEqual(chat.call_count, 1)
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])
        self.assertEqual(json.loads(chat.call_args.args[0])["verified_hints"]["term"], "Alpha")

    def test_named_course_lookup_does_not_discard_extra_conditions(self):
        question = "วิชาAlphaมีกี่หน่วยกิตและต้องผ่านวิชาอะไรก่อน"
        self.assertFalse(question_hints(question)["named_course"])
        self.assertIsNone(rule_plan(question))

    def test_multi_field_sort_cannot_silently_drop_bare_name(self):
        question = "ขอรายวิชาทั้งหมดเรียงตามชื่อและหน่วยกิต"
        self.assertTrue(question_hints(question)["ambiguous_sort"])
        with patch.object(self.model, "_chat", side_effect=AssertionError("No inference expected")):
            answer = self.ask(question)
        self.assertEqual((answer["sql"], answer["rows"]), ("", []))
        with self.assertRaises(ValueError):
            validate_plan(QueryPlan(intent="course_list", sort_by="credits"), question)
        self.assertEqual(question_hints("ขอรายวิชาทั้งหมดเรียงตามชื่อ")["sort_by"], "name_th")
        self.assertEqual(question_hints("ขอรายวิชาทั้งหมดเรียงตามชื่อภาษาอังกฤษ")["sort_by"], "name_en")

    def test_english_name_output_never_uses_code_as_a_name_predicate(self):
        question = "วิชา 00000001 ชื่อภาษาอังกฤษว่าอะไร"
        with patch.object(self.model, "_chat", return_value=self.choice("course_details", "name_en", "00000001")) as chat:
            answer = self.ask(question)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(answer["rows"][0]["name_en"], "DATA SCIENCE")
        with self.assertRaisesRegex(ValueError, "Course codes identify"):
            validate_plan(QueryPlan(intent="course_details", course_codes=["00000001"],
                                    search_field="name_en", search_term="00000001"), question)

    def test_literal_numeric_name_predicate_with_course_code_is_preserved(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET name_en='00000001 SCIENCE' WHERE code='00000001'")
        question = 'วิชา 00000001 ที่ชื่อภาษาอังกฤษมีคำว่า "00000001"'
        with patch.object(self.model, "_chat", return_value=self.choice("course_list", "name_en", "00000001")):
            answer = self.ask(question)
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])
        self.assertIn("LIKE", answer["sql"])

    def test_course_count_cannot_answer_an_individual_credit_question(self):
        with self.assertRaisesRegex(ValueError, "not a course count"):
            validate_plan(QueryPlan(intent="course_count", course_codes=["00000001"]),
                          "วิชา 00000001 มีกี่หน่วยกิต")


    def test_explicit_filters_preserve_operator(self):
        question="ปี 2 เทอม 2 ขอรายวิชาที่มีอย่างน้อย 2 หน่วยกิต"
        with patch.object(self.model,"_chat",return_value=self.choice()):
            plan=self.model._plan(question,program="IT",track="coop")
        self.assertEqual((plan.credits_op,plan.credits),("ge",2))
        sql,params=compile_plan(plan)
        _,rows=self.database.query_from_model(sql,params=params)
        self.assertEqual([row["code"] for row in rows],["00000004"])

    def test_term_pairs_do_not_create_cartesian_product(self):
        with patch.object(self.model,"_chat",return_value=self.choice()):
            answer=self.ask("ขอวิชา ปี 1 เทอม 1 และปี 2 เทอม 2")
        self.assertEqual({(r["year"],r["semester"]) for r in answer["rows"]},{(1,1),(2,2)})

    def test_comparison_uses_both_terms(self):
        answer=self.ask("ปี 1 เทอม 1 กับปี 2 เทอม 2 ต่างกันกี่หน่วยกิต")
        self.assertEqual(len(answer["rows"]),2)
        self.assertIn("ส่วนต่าง: 4 หน่วยกิต",answer["answer"])

    def test_null_totals_are_not_zero(self):
        answer=self.ask("ปี 2 เทอม 1 เรียนกี่หน่วยกิต")
        self.assertIsNone(answer["rows"][0]["credits"])
        self.assertIn("ไม่ครบ/ไม่ระบุ",answer["answer"])
        self.assertEqual(answer["rows"][0]["missing_credit_slots"],1)

    def test_partial_semester_shows_known_sum_and_missing_slots(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO plan_item VALUES(6,'IT',2,1,'00000001',3,NULL,NULL)")
        answer=self.ask("ปี 2 เทอม 1 เรียนกี่หน่วยกิต")
        row=answer["rows"][0]
        self.assertEqual((row["credits"],row["n_courses"],row["missing_credit_slots"]),(3,2,1))
        self.assertIn("รวมเฉพาะหน่วยกิตที่ระบุ 3 หน่วยกิต",answer["answer"])
        self.assertIn("มี 1 ช่องที่ไม่ระบุหน่วยกิต",answer["answer"])

    def test_known_alternative_is_counted_once_when_sibling_is_missing(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE plan_item SET credits=NULL WHERE id=3")
        answer=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")
        row=answer["rows"][0]
        self.assertEqual((row["credits"],row["n_courses"]),(6,2))
        self.assertEqual((row["missing_credit_slots"],row["incomplete_alt_slots"]),(0,1))
        self.assertIn("บางตัวเลือกไม่ระบุหน่วยกิต",answer["answer"])

    def test_all_unknown_alternatives_are_one_missing_slot_and_real_zero_is_kept(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript("""
                INSERT INTO plan_item VALUES(6,'IT',3,1,'00000001',NULL,'unknown',NULL);
                INSERT INTO plan_item VALUES(7,'IT',3,1,'00000002','TBC','unknown',NULL);
                INSERT INTO plan_item VALUES(8,'IT',3,1,'00000004',0,NULL,NULL);
            """)
        answer=self.ask("ปี 3 เทอม 1 เรียนกี่หน่วยกิต")
        row=answer["rows"][0]
        self.assertEqual((row["credits"],row["n_courses"],row["missing_credit_slots"]),(0,2,1))
        self.assertIn("รวมเฉพาะหน่วยกิตที่ระบุ 0 หน่วยกิต",answer["answer"])

    def test_text_credits_are_not_coerced_to_zero_or_summed(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE plan_item SET credits='not known' WHERE id=4")
            conn.execute("INSERT INTO plan_item VALUES(6,'IT',2,1,'00000001',4,NULL,NULL)")
        row=self.ask("ปี 2 เทอม 1 เรียนกี่หน่วยกิต")["rows"][0]
        self.assertEqual((row["credits"],row["missing_credit_slots"]),(4,1))

    def test_alternative_minimum_is_preserved_with_different_known_values(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE plan_item SET credits=6 WHERE id=3")
            conn.execute("INSERT INTO plan_item VALUES(6,'IT',1,1,'00000003',NULL,'choice',NULL)")
        row=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")["rows"][0]
        self.assertEqual((row["credits"],row["n_courses"],row["incomplete_alt_slots"]),(6,2,1))

    def test_year_keeps_partial_sum_across_known_and_unknown_terms(self):
        answer=self.ask("ช่วยสรุปปี 2 รวมกี่หน่วยกิตหน่อยครับ")
        row=answer["rows"][0]
        self.assertEqual((row["total_credits"],row["missing_credit_slots"]),(2,1))
        self.assertIn("รวมเฉพาะหน่วยกิตที่ระบุ 2 หน่วยกิต",answer["answer"])
        self.assertIn("เทอม 1 ไม่ระบุ",answer["answer"])

    def test_partial_comparison_shows_values_without_claiming_full_difference(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO plan_item VALUES(6,'IT',2,1,'00000001',1,NULL,NULL)")
        answer=self.ask("ปี 1 เทอม 1 กับปี 2 เทอม 1 ต่างกันกี่หน่วยกิต")
        self.assertIn("รวมเฉพาะหน่วยกิตที่ระบุ 1 หน่วยกิต",answer["answer"])
        self.assertIn("ยังคำนวณส่วนต่างของยอดเต็มไม่ได้",answer["answer"])
        self.assertNotIn("ส่วนต่าง: 5",answer["answer"])

    def test_partial_rankings_show_values_and_do_not_confirm_winner(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("INSERT INTO plan_item VALUES(6,'IT',2,1,'00000001',1,NULL,NULL)")
        for question in ["เทอมไหนมีหน่วยกิตรวมมากที่สุด","ปีไหนมีหน่วยกิตรวมมากที่สุด"]:
            with self.subTest(question=question):
                answer=self.ask(question)
                self.assertGreater(len(answer["rows"]),1)
                self.assertIn("ยังยืนยันอันดับ",answer["answer"])
                self.assertIn("รวมเฉพาะหน่วยกิตที่ระบุ",answer["answer"])

    def test_conversational_thai_questions_use_rules_without_inference(self):
        cases=[
            ("ช่วยบอกว่าหลักสูตรต้องเก็บหน่วยกิตรวมเท่าไร", "program_credits", [], []),
            ("อยากรู้หลักสูตรนี้ต้องเก็บกี่หน่วยกิตถึงจะจบ", "program_credits", [], []),
            ("รบกวนบอกทั้งหลักสูตรรวมกี่หน่วยกิตหน่อยค่ะ", "program_credits", [], []),
            ("ช่วยบอกหลักสูตรนี้มีหน่วยกิตรวมทั้งหมดเท่าไรหน่อยครับ", "program_credits", [], []),
            ("ต้องเรียนให้ครบกี่หน่วยกิตถึงจะจบ", "program_credits", [], []),
            ("เรียนจบต้องเก็บกี่หน่วยกิต", "program_credits", [], []),
            ("อยากทราบหลักสูตรนี้ใช้เวลาเรียนกี่ปีครับ", "program_years", [], []),
            ("เรียนกี่ปีถึงจะจบ", "program_years", [], []),
            ("หลักสูตรนี้เรียนกี่ปีและต้องเก็บกี่หน่วยกิต", "program_info", [], []),
            ("ช่วยบอกปีหนึ่งเทอมหนึ่งต้องเก็บกี่หน่วยกิตหน่อยครับ", "semester_summary", [1], [1]),
            ("อยากรู้หน่วยกิตรวมของปี 1 เทอม 1 เท่าไร", "semester_summary", [1], [1]),
            ("สำหรับชั้นปีที่หนึ่งภาคการศึกษาที่หนึ่งรวมกี่หน่วยกิต", "semester_summary", [1], [1]),
            ("ขอสรุปภาคเรียน 1 ของปี 1 มีหน่วยกิตรวมเท่าไหร่ค่ะ", "semester_summary", [1], [1]),
            ("ช่วยสรุปปี 2 รวมกี่หน่วยกิตหน่อยครับ", "year_summary", [2], []),
            ("ช่วยดูปี 1 เทอม 1 ต้องเรียนวิชาอะไรบ้างหน่อย", "course_list", [1], [1]),
        ]
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            for question,intent,years,semesters in cases:
                with self.subTest(question=question):
                    plan=self.model._plan(question,program="IT",track="coop")
                    self.assertEqual((plan.intent,plan.years,plan.semesters),(intent,years,semesters))
                    self.assertTrue(self.ask(question)["sql"])

    def test_new_rules_do_not_discard_extra_conditions_or_quoted_text(self):
        for question in [
            "ช่วยบอกว่าหลักสูตรต้องเก็บหน่วยกิตรวมเท่าไรและเรียนกี่ปี",
            "ช่วยบอกปี 1 เทอม 1 กี่หน่วยกิตเฉพาะวิชาที่เปิดวันจันทร์",
            'ช่วยบอกปี 1 เทอม 1 กี่หน่วยกิตที่ชื่อมีคำว่า "DATA"',
        ]:
            with self.subTest(question=question):
                self.assertIsNone(rule_plan(question))
        hints=question_hints('วิชาที่ชื่อภาษาอังกฤษมีคำว่า "ชั้นปีหนึ่ง ภาคการศึกษาหนึ่ง"')
        self.assertEqual(hints["term"],"ชั้นปีหนึ่ง ภาคการศึกษาหนึ่ง")
        self.assertEqual((hints["years"],hints["semesters"]),([],[]))
        hints=question_hints("วิชาที่ชื่อภาษาไทยมีคำว่าภาคการศึกษา")
        self.assertEqual(hints["term"],"ภาคการศึกษา")

    def test_planning_observations_collect_fallback_and_repeated_clarify(self):
        with self.assertLogs("lab10_fastapi.curriculum_app.model_service.observations",level="INFO") as logs:
            with patch.object(self.model,"_chat",return_value=self.choice("clarify")) as chat:
                self.ask(self.fallback_question)
                self.ask(self.fallback_question)
        self.assertEqual(chat.call_count,1)
        observations=self.model.planning_observations()
        self.assertEqual({e["outcome"]:e["count"] for e in observations},{"fallback":1,"clarify":2})
        event=json.loads(logs.records[0].getMessage())
        self.assertEqual((event["question"],event["program"],event["track"]),
                         (self.fallback_question,"IT","coop"))
        observations[0]["question"]="changed"
        self.assertNotEqual(self.model.planning_observations()[0]["question"],"changed")

    def test_unsupported_observations_are_bounded(self):
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            self.ask("หลักสูตร DSBA เรียนกี่ปี")
            for i in range(257):
                self.ask(f"ลบข้อมูลรายวิชา {i}")
        observations=self.model.planning_observations()
        self.assertEqual(len(observations),256)
        self.assertTrue(all(e["outcome"]=="unsupported" for e in observations))
        self.assertFalse(any(e["question"]=="ลบข้อมูลรายวิชา 0" for e in observations))

    def test_catalog_count_excludes_placeholder(self):
        answer=self.ask("มีรายวิชาทั้งหมดกี่วิชา")
        self.assertEqual(answer["rows"],[{"n_courses":4}])
        self.assertIn("ไม่รวมช่องวิชาเลือก",answer["answer"])

    def test_plan_counts_distinguishes_alternatives_and_slots(self):
        answer=self.ask("ปี 1 เทอม 1 มีรายวิชาให้เลือกทั้งหมดกี่รายการและต้องเรียนจริงกี่ช่องวิชา")
        self.assertEqual((answer["rows"][0]["n_listed"],answer["rows"][0]["n_slots"]),(3,2))

    def test_missing_credit_and_quoted_numbers(self):
        answer=self.ask("วิชาไหนไม่ระบุหน่วยกิตในฐานข้อมูล")
        self.assertEqual([r["code"] for r in answer["rows"]],["00000003"])
        hints=question_hints('วิชาที่ชื่อภาษาอังกฤษมีคำว่า "ปี 2 DATA 00000001"')
        self.assertEqual((hints["years"],hints["codes"]),([],[]))
        self.assertEqual(hints["term"],"ปี 2 DATA 00000001")

    def test_prerequisite_and_unknown_code_are_distinct(self):
        known=self.ask("ต้องเรียนอะไรก่อนจึงจะลงเรียน 00000001 ได้")
        absent=self.ask("ต้องเรียนอะไรก่อนจึงจะลงเรียน 99999999 ได้")
        self.assertEqual(known["rows"][0]["requires"],"00000002")
        self.assertIn("ไม่พบรหัสวิชา 99999999",absent["answer"])

    def test_whole_word_and_ocr_search(self):
        for question,expected in [
            ('วิชาที่ชื่อภาษาอังกฤษมีคำว่า "DATA" แบบคำเต็ม',["00000001"]),
            ('วิชาที่ชื่อภาษาอังกฤษมีคำว่า "DATA" ไม่สนใจช่องว่าง',
             ["00000001","00000002","00000004"]),
        ]:
            with self.subTest(question=question):
                with patch.object(self.model,"_chat",return_value=self.choice(search_field="name_en")):
                    answer=self.ask(question)
                self.assertEqual([r["code"] for r in answer["rows"]],expected)

    def test_search_is_bound_and_wildcards_are_literal(self):
        question='วิชาที่ชื่อภาษาอังกฤษมีคำว่า "x\' OR 1=1 --"'
        with patch.object(self.model,"_chat",return_value=self.choice(search_field="name_en")):
            answer=self.ask(question)
        self.assertEqual(answer["rows"],[])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM course").fetchone()[0],5)
        sql,params=compile_plan(QueryPlan(intent="course_list",search_term="%_"))
        self.assertEqual(self.database.query_from_model(sql,params=params)[1],[])

    def test_gened_and_wrong_program_do_not_call_model(self):
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            gened=self.ask("หลักสูตรนี้มีกี่หน่วยกิต",program="GENED",track="default")
            other=self.ask("หลักสูตร DSBA เรียนกี่ปี")
        self.assertEqual(gened["sql"],"")
        self.assertIn("GENED",gened["answer"])
        self.assertEqual(other["sql"],"")
        with self.assertRaises(UnsupportedGenedMetadata):
            self.database.query_from_model("SELECT total_credits FROM program",is_gened=True)

    def test_validation_rejects_dropped_filter_and_invented_term(self):
        with self.assertRaises(ValueError):
            validate_plan(QueryPlan(intent="course_list"),"ปี 2 เทอม 1 มีวิชา 3 หน่วยกิตอะไรบ้าง")
        with self.assertRaises(ValueError):
            validate_plan(QueryPlan(intent="course_list",search_term="invented"),"ขอรายวิชาทั้งหมด")

    def test_wrong_model_shape_is_bounded_and_not_cached(self):
        with patch.object(self.model,"_chat",return_value={"sql":"DROP TABLE course"}) as chat:
            with self.assertRaises(InferenceResponseError):
                self.ask(self.fallback_question)
        self.assertEqual(chat.call_count,2)
        self.assertEqual(len(self.model.answer_cache._entries),0)

    def test_strict_json_and_truncation_budget(self):
        session=Mock()
        self.model._sessions.http=session
        session.post.side_effect=[self.response('{"intent":',"length"),self.response()]
        self.assertEqual(self.model._chat("question",CHOICE_SCHEMA),self.choice())
        self.assertEqual(
            [c.kwargs["json"]["options"]["num_predict"] for c in session.post.call_args_list],[128,256])
        payload=session.post.call_args.kwargs["json"]
        self.assertEqual(payload["messages"][0]["content"],PLAN_PROMPT+"\n/no_think")
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"],"10m")
        session.post.side_effect=None
        session.post.return_value=self.response(chr(96)*3+"json\n{}\n"+chr(96)*3)
        with self.assertRaises(ModelOutputError):
            self.model._chat("question",CHOICE_SCHEMA)

    def test_network_failure_is_not_retried_or_cached(self):
        import requests
        session=Mock()
        session.post.side_effect=requests.ConnectionError("offline")
        self.model._sessions.http=session
        with self.assertRaises(InferenceUnavailable):
            self.ask(self.fallback_question)
        self.assertEqual(session.post.call_count,1)
        self.assertEqual(len(self.model.answer_cache._entries),0)

    def test_health_checks_model_presence(self):
        response=Mock()
        self.model._sessions.http=Mock()
        self.model._sessions.http.get.return_value=response
        response.json.return_value={"models":[{"name":"another:latest"}]}
        self.assertFalse(self.model.available())
        response.json.return_value={"models":[{"model":"qwen3:4b"}]}
        self.assertTrue(self.model.available())

    def test_cache_copy_and_database_invalidation(self):
        question="หลักสูตรนี้มีกี่หน่วยกิต"
        first=self.ask(question)
        first["rows"][0]["total_credits"]=-1
        self.assertEqual(self.ask(question)["rows"][0]["total_credits"],132)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE program SET total_credits=140")
        info=self.path.stat()
        os.utime(self.path,ns=(info.st_atime_ns,info.st_mtime_ns+1_000_000_000))
        self.assertEqual(self.ask(question)["rows"][0]["total_credits"],140)

    def test_identical_concurrent_requests_share_inference(self):
        def choose(*args,**kwargs):
            time.sleep(0.03)
            return self.choice("program_credits")
        with patch.object(self.model,"_chat",side_effect=choose) as chat:
            with ThreadPoolExecutor(max_workers=2) as pool:
                answers=list(pool.map(self.ask,[self.fallback_question]*2))
        self.assertEqual(chat.call_count,1)
        self.assertEqual({k:v for k,v in answers[0].items() if k!="performance"},
                         {k:v for k,v in answers[1].items() if k!="performance"})
        self.assertEqual(sum(a["performance"]["answer_cache_hit"] for a in answers),1)
        self.assertEqual(self.model._inflight,{})

    def test_expensive_sql_obeys_budget(self):
        sql="""WITH RECURSIVE n(x) AS (
            SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000
        ) SELECT SUM(x) AS total FROM n"""
        with self.assertRaises(TimeoutError):
            with request_budget(0.01):
                self.database.query_from_model(sql)

    def test_missing_db_detected_before_inference(self):
        self.path.unlink()
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            with self.assertRaises(FileNotFoundError):
                self.ask(self.fallback_question)

    def test_api_error_mapping_and_response_contract(self):
        from fastapi import HTTPException
        from lab10_fastapi.curriculum_app import main
        from lab10_fastapi.curriculum_app.schemas import AskRequest,AskResponse
        request=AskRequest(question="หลักสูตรนี้มีกี่หน่วยกิต",program="IT",track="coop")
        for error,status in [
            (InferenceResponseError("bad response"),502),(InferenceUnavailable("offline"),503),
            (QueryExecutionError("bad query"),500),(TimeoutError("deadline"),504),
        ]:
            with self.subTest(status=status):
                with patch.object(main,"select_database",return_value=self.database):
                    with patch.object(main.model,"ask",side_effect=error):
                        with self.assertRaises(HTTPException) as caught:
                            main.ask(request)
                self.assertEqual(caught.exception.status_code,status)
        result=AskResponse.model_validate(self.ask(request.question)).model_dump()
        self.assertEqual(set(result),{"question","sql","rows","answer","citations","processing_ms","performance"})
        self.assertEqual(result["citations"],[])
        self.assertIsNone(result["processing_ms"])

    def add_page_metadata(self):
        # ฐานทดสอบเดิมไม่มี pages: ทุก test เดิมจึงตรวจ compatibility ของ DB เก่าด้วย.
        no_inference=patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected"))
        no_inference.start()
        self.addCleanup(no_inference.stop)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript("""
                ALTER TABLE course ADD COLUMN pages TEXT;
                ALTER TABLE plan_item ADD COLUMN pages TEXT;
                UPDATE course SET pages=CASE code
                    WHEN '00000001' THEN '[101,101,102]'
                    WHEN '00000002' THEN '[201]'
                    WHEN '00000003' THEN 'broken-json'
                    WHEN '00000004' THEN '[401]'
                    ELSE '[999]' END;
                UPDATE plan_item SET pages=CASE id
                    WHEN 1 THEN '[11,11,12]' WHEN 2 THEN '[11,13]'
                    WHEN 3 THEN '[13,14]' WHEN 4 THEN '[21]' ELSE '[22]' END;
                DROP VIEW v_plan;
                CREATE VIEW v_plan AS SELECT p.id,p.year,p.semester,p.code,c.name_th,c.name_en,
                    p.credits,p.alt_group,p.note,COALESCE(p.pages,c.pages) AS pages
                    FROM plan_item p LEFT JOIN course c ON c.code=p.code;
            """)

    def test_citations_do_not_change_credit_totals_or_main_sql(self):
        before=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")
        self.add_page_metadata()
        after=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")
        self.assertEqual(before["rows"],after["rows"])
        self.assertEqual(before["sql"],after["sql"])
        self.assertEqual(before["answer"],after["answer"])
        self.assertEqual(after["rows"][0]["credits"],6)
        self.assertEqual(len(after["citations"]),1)
        self.assertEqual(after["citations"][0]["pages"],[11,12,13,14])
        self.assertEqual(after["citations"][0]["year"],1)
        self.assertEqual(after["citations"][0]["semester"],1)

    def test_citations_keep_exact_term_pairs(self):
        self.add_page_metadata()
        plan=QueryPlan(intent="compare_terms",terms=[Term(year=1,semester=1),Term(year=2,semester=2)])
        sql,params=compile_plan(plan)
        _,rows=self.database.query_from_model(sql,params=params)
        citations=collect_citations(self.database,plan,rows,program="IT",track="coop")
        self.assertEqual({(c["year"],c["semester"]) for c in citations},{(1,1),(2,2)})
        self.assertEqual(sorted({p for c in citations for p in c["pages"]}),[11,12,13,14,22])

    def test_ranked_citations_only_cover_returned_year(self):
        self.add_page_metadata()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE plan_item SET credits=3 WHERE id=4")
        plan=QueryPlan(intent="year_summary",ranking="max")
        sql,params=compile_plan(plan)
        _,rows=self.database.query_from_model(sql,params=params)
        self.assertEqual([r["year"] for r in rows],[1])
        citations=collect_citations(self.database,plan,rows)
        self.assertEqual(sorted({p for c in citations for p in c["pages"]}),[11,12,13,14])

    def test_course_citations_keep_filters_sort_and_display_limit(self):
        self.add_page_metadata()
        plan=QueryPlan(intent="course_list",credits=3,sort_by="name_en",sort_direction="desc")
        limited=CurriculumDatabase(lab8b,self.path,1)
        sql,params=compile_plan(plan)
        _,rows=limited.query_from_model(sql,params=params)
        citations=collect_citations(limited,plan,rows)
        self.assertEqual(rows[0]["code"],"00000002")
        self.assertEqual([c["course_code"] for c in citations],["00000002"])
        self.assertEqual(citations[0]["pages"],[201])

    def test_count_citations_preserve_missing_credit_filter(self):
        self.add_page_metadata()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET pages='[301]' WHERE code='00000003'")
        plan=QueryPlan(intent="course_count",missing_credits=True)
        sql,params=compile_plan(plan)
        _,rows=self.database.query_from_model(sql,params=params)
        self.assertEqual(rows[0]["n_courses"],1)
        self.assertEqual(collect_citations(self.database,plan,rows)[0]["pages"],[301])

    def test_aggregate_citations_are_not_cut_by_guard_limit(self):
        self.add_page_metadata()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executemany("INSERT INTO course(code,name_th,credits,pages) VALUES(?,?,?,?)",
                [(str(40000000+i),"Extra",3,json.dumps([1000+i])) for i in range(210)])
        answer=self.ask("มีรายวิชาทั้งหมดกี่วิชา")
        self.assertEqual(answer["rows"][0]["n_courses"],214)
        pages=answer["citations"][0]["pages"]
        self.assertTrue(all(1000+i in pages for i in range(210)))
        self.assertNotIn(999,pages)  # placeholder ไม่อยู่ใน COUNT จริง.

    def test_invalid_pages_are_ignored_without_breaking_answer(self):
        self.add_page_metadata()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE course SET pages=? WHERE code='00000001'",
                ('[101,101,0,-1,true,"102",103.5,null,102]',))
        answer=self.ask("ขอรายวิชาทั้งหมด")
        pages={c["course_code"]:c["pages"] for c in answer["citations"]}
        self.assertEqual(pages["00000001"],[101,102])
        self.assertNotIn("00000003",pages)
        self.assertEqual(len(answer["rows"]),5)

    def test_metadata_without_pages_is_not_assigned_course_pages(self):
        self.add_page_metadata()
        self.assertEqual(self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["citations"],[])
        self.assertEqual(self.ask("ต้องเรียนอะไรก่อนจึงจะลงเรียน 00000001 ได้")["citations"],[])

    def test_citations_are_omitted_if_database_changes_between_queries(self):
        self.add_page_metadata()
        original=self.database.query_citations
        def read_then_change(*args,**kwargs):
            citations=original(*args,**kwargs)
            with closing(sqlite3.connect(self.path)) as conn, conn:
                conn.execute("UPDATE plan_item SET pages='[77]' WHERE id=1")
            return citations
        with patch.object(self.database,"query_citations",side_effect=read_then_change):
            answer=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")
        self.assertEqual(answer["rows"][0]["credits"],6)
        self.assertEqual(answer["citations"],[])
        self.assertIn(77,self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")["citations"][0]["pages"])

    def test_description_citations_use_course_pages_with_year_filter(self):
        self.add_page_metadata()
        plan=QueryPlan(intent="course_details",years=[1],semesters=[1],course_codes=["00000001"])
        sql,params=compile_plan(plan)
        _,rows=self.database.query_from_model(sql,params=params)
        citations=collect_citations(self.database,plan,rows)
        self.assertEqual(citations[0]["source"],"course")
        self.assertEqual(citations[0]["pages"],[101,102])

    def test_citation_cache_copies_and_invalidates_with_database(self):
        self.add_page_metadata()
        question="ปี 1 เทอม 1 เรียนกี่หน่วยกิต"
        first=self.ask(question)
        first["citations"][0]["pages"].append(9999)
        self.assertNotIn(9999,self.ask(question)["citations"][0]["pages"])
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE plan_item SET pages='[15]' WHERE id=1")
        pages=self.ask(question)["citations"][0]["pages"]
        self.assertEqual(pages,[11,13,14,15])

    def test_api_processing_time_is_current_and_does_not_mutate_cached_payload(self):
        from lab10_fastapi.curriculum_app import main
        from lab10_fastapi.curriculum_app.schemas import AskRequest,AskResponse
        payload={"question":"test","sql":"SELECT 1","rows":[],"answer":"test","citations":[]}
        request=AskRequest(question="test",program="IT",track="coop")
        with patch.object(main,"select_database",return_value=self.database), \
             patch.object(main.model,"ask",return_value=payload), \
             patch.object(main.time,"perf_counter",side_effect=[10,10.125,20,20.001]):
            first=main.ask(request)
            second=main.ask(request)
        self.assertEqual(first["processing_ms"],125)
        self.assertEqual(second["processing_ms"],1)
        self.assertNotIn("processing_ms",payload)
        legacy=AskResponse.model_validate({k:v for k,v in payload.items() if k!="citations"})
        self.assertEqual(legacy.citations,[])
        self.assertIsNone(legacy.processing_ms)
        self.assertIsNone(legacy.performance)

    def test_new_thai_fallback_forms_answer_without_qwen(self):
        cases = [
            ("ถ้าจะวางแผนเรียน ช่วยบอกจำนวนหน่วยกิตรวมตามเกณฑ์จบของหลักสูตรนี้หน่อย", "program_credits", []),
            ("ขอทราบหน่วยกิตสำหรับจบหลักสูตรนี้เท่าไรครับ", "program_credits", []),
            ("ต้องเก็บหน่วยกิตเท่าไหร่ถึงจะจบ", "program_credits", []),
            ("ต้องเรียนกี่หน่วยกิตเพื่อจบหลักสูตรนี้", "program_credits", []),
            ("หลักสูตรนี้ใช้ระยะเวลาศึกษากี่ปี", "program_years", []),
            ("ขอทราบว่าหลักสูตรนี้มีรายวิชาทั้งหมดกี่วิชา", "course_count", []),
            ("หลักสูตรนี้มีทั้งหมดกี่วิชา", "course_count", []),
            ("ช่วยดูหลักสูตรนี้มีวิชาอะไรบ้างหน่อยครับ", "course_list", []),
            ("ปี 1 เทอม 1 รวมแล้วกี่หน่วยกิต", "semester_summary", [1]),
            ("ปีหนึ่งเทอมหนึ่งมีหน่วยกิตทั้งหมดเท่าไหร่", "semester_summary", [1]),
            ("ปี 1 มีหน่วยกิตทั้งหมดเท่าไร", "year_summary", [1]),
            ("ช่วยดูปี 1 เทอม 1 มีรายวิชาไหนบ้างหน่อย", "course_list", [1]),
            ("วิชา 00000001 ต้องเรียนวิชาอะไรก่อน", "prerequisites", []),
            ("ขอทราบวิชา 00000001 มีวิชาบังคับก่อนอะไรบ้างครับ", "prerequisites", []),
            ("ก่อนเรียนวิชา 00000001 ต้องผ่านวิชาอะไรบ้าง", "prerequisites", []),
        ]
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            for question,intent,years in cases:
                with self.subTest(question=question):
                    plan=self.model._plan(question,program="IT",track="coop")
                    self.assertEqual((plan.intent,plan.years),(intent,years))
                    answer=self.ask(question)
                    self.assertTrue(answer["sql"])
                    self.assertEqual(answer["performance"]["qwen_calls"],0)
                    if intent=="program_credits":
                        self.assertEqual(answer["rows"],[{"total_credits":132}])
                    if intent=="course_count":
                        self.assertEqual(answer["rows"],[{"n_courses":4}])
                    if intent=="prerequisites":
                        self.assertEqual(answer["rows"][0]["requires"],"00000002")

    def test_new_rules_preserve_scope_and_reject_extra_conditions(self):
        for question in [
            "ขอทราบหน่วยกิตสำหรับจบหลักสูตรนี้เท่าไรเฉพาะวิชาบังคับ",
            "ปี 1 เทอม 1 รวมแล้วกี่หน่วยกิตเฉพาะวิชาที่เปิดวันจันทร์",
            'หลักสูตรนี้มีวิชาอะไรบ้างที่ชื่อมีคำว่า "DATA"',
            "วิชา 00000001 มีวิชาบังคับก่อนอะไรบ้างและเกรดขั้นต่ำเท่าไร",
            "วิชา 00000001 มีวิชาบังคับก่อนอะไรบ้างในปี 2",
        ]:
            with self.subTest(question=question):
                self.assertIsNone(rule_plan(question))
        with patch.object(self.model,"_chat",side_effect=AssertionError("No inference expected")):
            plan=self.model._plan("ปี 1 เทอม 1 และปี 2 เทอม 2 มีรายวิชาไหนบ้าง",program="IT",track="coop")
            self.assertEqual([(term.year,term.semester) for term in plan.terms],[(1,1),(2,2)])
            answer=self.ask("ปี 1 เทอม 1 และปี 2 เทอม 2 มีรายวิชาไหนบ้าง")
        self.assertEqual({(r["year"],r["semester"]) for r in answer["rows"]},{(1,1),(2,2)})
        for question in ["ปี 99 เทอม 1 รวมแล้วกี่หน่วยกิต", "ปี 1 เทอม 9 มีรายวิชาไหนบ้าง"]:
            with patch.object(self.model,"_chat",return_value=self.choice("clarify")):
                self.assertEqual(self.ask(question)["rows"],[])

    def test_request_timings_distinguish_rules_plan_cache_and_answer_cache(self):
        question="ปี 1 เทอม 1 เรียนกี่หน่วยกิต"
        first=self.ask(question)["performance"]
        self.assertEqual(first["plan_source"],"rules")
        self.assertEqual(first["qwen_calls"],0)
        self.assertEqual(first["query_calls"],1)
        self.assertEqual(first["citation_query_calls"],1)
        self.model.answer_cache.clear()
        second=self.ask(question)["performance"]
        self.assertEqual(second["plan_source"],"plan_cache")
        self.assertTrue(second["plan_cache_hit"])
        third=self.ask(question)["performance"]
        self.assertEqual(third["plan_source"],"answer_cache")
        self.assertTrue(third["answer_cache_hit"])
        self.assertFalse(third["plan_cache_hit"])
        self.assertEqual((third["qwen_calls"],third["query_calls"],third["citation_query_calls"]),(0,0,0))
        for stage in ("planning","qwen","query","citations","compile","render"):
            self.assertEqual(third["stages_ms"][stage],0)
        for report in (first,second,third):
            self.assertTrue(all(value>=0 for value in report["stages_ms"].values()))
            self.assertAlmostEqual(sum(report["stages_ms"].values()),report["total_ms"],delta=.02)

    def test_citation_queries_are_not_counted_twice_in_query_stage(self):
        self.add_page_metadata()
        report=self.ask("ปี 1 เทอม 1 เรียนกี่หน่วยกิต")["performance"]
        self.assertEqual(report["query_calls"],1)
        self.assertEqual(report["citation_query_calls"],2)  # schema PRAGMA + evidence SQL.
        self.assertGreater(report["stages_ms"]["citations"],0)
        self.assertAlmostEqual(sum(report["stages_ms"].values()),report["total_ms"],delta=.02)

    def test_qwen_stage_counts_http_requests_and_ollama_durations(self):
        self.model._sessions.http=Mock()
        response=self.response(json.dumps(self.choice("program_credits")))
        response.json.return_value.update(total_duration=20_000_000,load_duration=2_000_000,
                                         prompt_eval_duration=3_000_000,eval_duration=15_000_000)
        def delayed_response(*args,**kwargs):
            time.sleep(.02)
            return response
        self.model._sessions.http.post.side_effect=delayed_response
        report=self.ask(self.fallback_question)["performance"]
        self.assertEqual(report["plan_source"],"qwen")
        self.assertEqual(report["qwen_calls"],1)
        self.assertGreaterEqual(report["stages_ms"]["qwen"],15)
        self.assertEqual(report["ollama_ms"],{"total":20,"load":2,"prompt":3,"generate":15})
        self.assertAlmostEqual(sum(report["stages_ms"].values()),report["total_ms"],delta=.02)

    def test_qwen_truncation_and_plan_repair_are_counted(self):
        for responses,calls in [
            ([self.response("",reason="length"),self.response(json.dumps(self.choice("program_credits")))],2),
            ([self.response('{"wrong":1}'),self.response(json.dumps(self.choice("program_credits")))],2),
        ]:
            with self.subTest(calls=calls):
                model=QwenTextToSQL(self.config,lab8b)
                model._sessions.http=Mock()
                model._sessions.http.post.side_effect=responses
                report=model.ask(self.database,self.fallback_question,program="IT",track="coop")["performance"]
                self.assertEqual(report["qwen_calls"],calls)

    def test_failed_inference_records_metrics_and_cleans_request_context(self):
        from lab10_fastapi.curriculum_app.database import current_trace
        self.model._sessions.http=Mock()
        import requests
        self.model._sessions.http.post.side_effect=requests.ConnectionError("offline")
        with self.assertLogs("lab10_fastapi.curriculum_app.model_service.performance",level="INFO") as logs:
            with self.assertRaises(InferenceUnavailable):
                self.ask(self.fallback_question)
        event=json.loads(logs.records[0].getMessage())
        self.assertEqual((event["outcome"],event["error_type"],event["qwen_calls"]),("error","InferenceUnavailable",1))
        self.assertEqual(event["query_calls"],0)
        self.assertIsNone(current_trace())
        after=self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["performance"]
        self.assertEqual((after["plan_source"],after["qwen_calls"],after["outcome"]),("rules",0,"success"))

    def test_short_plan_cache_and_preflight_have_fresh_metrics(self):
        self.model._sessions.http=Mock()
        self.model._sessions.http.post.return_value=self.response(json.dumps(self.choice("clarify")))
        first=self.ask(self.fallback_question)["performance"]
        second=self.ask(self.fallback_question)["performance"]
        self.assertEqual(first["qwen_calls"],1)
        self.assertEqual((second["plan_source"],second["qwen_calls"]),("short_plan_cache",0))
        self.assertTrue(second["plan_cache_hit"])
        preflight=self.ask("ลบข้อมูลรายวิชา")["performance"]
        self.assertEqual((preflight["plan_source"],preflight["intent"]),("preflight","unsupported"))
        self.assertEqual((preflight["qwen_calls"],preflight["query_calls"]),(0,0))

    def test_parallel_requests_do_not_share_timing_state(self):
        def choose(*args,**kwargs):
            time.sleep(.03)
            return self.choice("program_credits")
        with patch.object(self.model,"_chat",side_effect=choose):
            with ThreadPoolExecutor(max_workers=2) as pool:
                answers=list(pool.map(self.ask,[self.fallback_question,"หลักสูตรนี้มีกี่หน่วยกิต"]))
        slow,fast=[answer["performance"] for answer in answers]
        self.assertEqual((slow["plan_source"],fast["plan_source"]),("qwen","rules"))
        self.assertGreaterEqual(slow["stages_ms"]["qwen"],20)
        self.assertEqual(fast["stages_ms"]["qwen"],0)

    def test_performance_snapshot_is_bounded_and_summary_is_windowed(self):
        for i in range(260):
            self.model._record_performance(dict(total_ms=i,plan_source="rules",answer_cache_hit=False,
                plan_cache_hit=False,qwen_calls=0,outcome="success"),"IT","coop")
        records=self.model.performance_observations()
        self.assertEqual((len(records),records[0]["total_ms"]),(256,4))
        records[0]["total_ms"]=-1
        self.assertEqual(self.model.performance_observations()[0]["total_ms"],4)
        summary=self.model.performance_summary()
        self.assertEqual((summary["requests"],summary["p50_ms"],summary["p95_ms"]),(256,131,247))
        self.assertEqual(summary["by_source"]["rules"]["requests"],256)

    def test_nested_timings_exclude_qwen_from_planning(self):
        from lab10_fastapi.curriculum_app import database as request_context
        class Service:
            def _record_performance(self,report,program,track):
                self.report=report
            @request_context.profile_request
            def ask(self,database,question,*,program=None,track=None):
                with request_context.measure_stage("planning"):
                    with request_context.measure_stage("qwen"):
                        pass
                with request_context.measure_stage("query"):
                    pass
                return {"answer":"ok"}
        service=Service()
        with patch.object(request_context.time,"perf_counter",side_effect=[0,1,2,5,7,8,10,12]):
            report=service.ask(None,"test")["performance"]
        self.assertEqual(report["stages_ms"]["planning"],3000)
        self.assertEqual(report["stages_ms"]["qwen"],3000)
        self.assertEqual(report["stages_ms"]["query"],2000)
        self.assertEqual(report["stages_ms"]["other"],4000)
        self.assertEqual(sum(report["stages_ms"].values()),report["total_ms"])

    def test_performance_jsonl_logging_rotates_and_preserves_current_metrics(self):
        import logging
        from logging.handlers import RotatingFileHandler
        path=Path(self.temp.name)/"performance.jsonl"
        handler=RotatingFileHandler(path,maxBytes=512,backupCount=2,encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger=logging.getLogger("lab10_fastapi.curriculum_app.model_service.performance")
        previous_level=logger.level
        logger.setLevel(logging.INFO)  # ใช้ API ของ logging เพื่อ invalidate isEnabledFor cache.
        try:
            with patch.object(logger,"handlers",[handler]), \
                 patch.object(logger,"propagate",False):
                first=self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["performance"]
                second=self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["performance"]
            latest=json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
            previous=json.loads(path.with_name(path.name+".1").read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(latest["plan_source"],"answer_cache")
            self.assertEqual(latest["stages_ms"],second["stages_ms"])
            self.assertEqual(previous["stages_ms"],first["stages_ms"])
            self.assertEqual((latest["program"],latest["track"]),("IT","coop"))
            self.assertEqual(self.model.performance_summary()["answer_cache_misses"],1)
        finally:
            logger.setLevel(previous_level)
            handler.close()


    def test_logging_settings_read_flags_and_resolve_paths(self):
        from lab10_fastapi.curriculum_app.config import PROJECT_ROOT, Settings
        for value, enabled in [("true",True),("1",True),("YES",True),("on",True),
                               ("false",False),("0",False),("NO",False),("off",False)]:
            with self.subTest(value=value), patch.dict(os.environ, {
                "CURRICULUM_LOG_ENABLED":value, "CURRICULUM_LOG_DIR":"work/test-logs",
            }):
                config=Settings()
                self.assertEqual(config.log_enabled,enabled)
                self.assertEqual(config.log_dir,PROJECT_ROOT/"work/test-logs")
        with patch.dict(os.environ,{"CURRICULUM_LOG_DIR":self.temp.name}):
            self.assertEqual(Settings().log_dir,Path(self.temp.name))
        with patch.dict(os.environ,{"CURRICULUM_LOG_ENABLED":"maybe"}):
            with self.assertRaises(ValueError):
                Settings()
        with patch.dict(os.environ):
            os.environ.pop("CURRICULUM_LOG_ENABLED",None)
            self.assertFalse(Settings().log_enabled)

    def test_disabled_file_logging_keeps_request_metrics_without_creating_files(self):
        import logging
        from lab10_fastapi.curriculum_app import main
        config=SimpleNamespace(log_enabled=False,log_dir=Path(self.temp.name)/"not-created")
        logger=logging.getLogger("lab10_fastapi.curriculum_app.model_service.performance")
        previous=(list(logger.handlers),logger.level,logger.propagate)
        with main.configure_logging(config):
            first=self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["performance"]
            second=self.ask("หลักสูตรนี้มีกี่หน่วยกิต")["performance"]
        self.assertEqual((first["plan_source"],second["plan_source"]),("rules","answer_cache"))
        self.assertFalse(config.log_dir.exists())
        self.assertEqual((list(logger.handlers),logger.level,logger.propagate),previous)

    def test_lifespan_writes_rules_cache_and_errors_then_closes_log_files(self):
        import asyncio
        import logging
        import requests
        from dataclasses import replace
        from lab10_fastapi.curriculum_app import main
        from lab10_fastapi.curriculum_app.schemas import AskRequest
        log_dir=Path(self.temp.name)/"logs"
        config=replace(main.settings,log_enabled=True,log_dir=log_dir)
        request=AskRequest(question="หลักสูตรนี้มีกี่หน่วยกิต",program="IT",track="coop")
        error_request=AskRequest(question=self.fallback_question,program="IT",track="coop")
        loggers=[logging.getLogger("lab10_fastapi.curriculum_app.model_service."+suffix)
                 for suffix in ("observations","performance")]
        previous=[(list(logger.handlers),logger.level,logger.propagate) for logger in loggers]
        file_handlers=[]
        self.model._sessions.http=Mock()
        self.model._sessions.http.post.side_effect=requests.ConnectionError("offline")

        async def exercise():
            async with main.app.router.lifespan_context(main.app):
                for logger, state in zip(loggers,previous):
                    file_handlers.extend(handler for handler in logger.handlers if handler not in state[0])
                first=main.ask(request)
                second=main.ask(request)
                self.assertIn("processing_ms",first)
                self.assertEqual(first["rows"],second["rows"])
                self.assertEqual(first["performance"]["plan_source"],"rules")
                self.assertEqual(second["performance"]["plan_source"],"answer_cache")
                with self.assertRaises(main.HTTPException) as caught:
                    main.ask(error_request)
                self.assertEqual(caught.exception.status_code,503)
            # Starting the app again must append once, without retaining old handlers.
            async with main.app.router.lifespan_context(main.app):
                main.ask(request)

        with patch.object(main,"settings",config),patch.object(main,"model",self.model), \
             patch.object(main,"select_database",return_value=self.database):
            asyncio.run(exercise())
        events=[json.loads(line) for line in (log_dir/"lab10_performance.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([event["plan_source"] for event in events],["rules","answer_cache","qwen","answer_cache"])
        self.assertEqual((events[2]["outcome"],events[2]["error_type"]),("error","InferenceUnavailable"))
        self.assertEqual((events[1]["qwen_calls"],events[1]["query_calls"],events[1]["citation_query_calls"]),(0,0,0))
        planner=[json.loads(line) for line in (log_dir/"lab10_planner.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(event["question"],event["outcome"]) for event in planner],[(self.fallback_question,"fallback")])
        self.assertTrue(all(handler.stream is None for handler in file_handlers))
        for logger, state in zip(loggers,previous):
            self.assertEqual((list(logger.handlers),logger.level,logger.propagate),state)
        # Windows cannot rename a directory with open log files; shutdown releases them.
        log_dir.rename(log_dir.with_name("logs-closed"))

    def test_nested_logging_configuration_writes_each_event_once_and_preserves_other_handlers(self):
        import logging
        from lab10_fastapi.curriculum_app import main
        config=SimpleNamespace(log_enabled=True,log_dir=Path(self.temp.name)/"logs")
        logger=logging.getLogger("lab10_fastapi.curriculum_app.model_service.performance")
        external=Mock(spec=logging.Handler)
        external.level=logging.NOTSET
        with patch.object(logger,"handlers",[external]):
            previous=(logger.level,logger.propagate)
            with self.assertRaisesRegex(RuntimeError,"test shutdown"):
                with main.configure_logging(config):
                    with main.configure_logging(config):
                        logger.info(json.dumps({"event":"nested"}))
                    logger.info(json.dumps({"event":"outer"}))
                    raise RuntimeError("test shutdown")
            self.assertEqual(logger.handlers,[external])
            self.assertEqual((logger.level,logger.propagate),previous)
        external.close.assert_not_called()
        events=[json.loads(line) for line in (config.log_dir/"lab10_performance.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events,[{"event":"nested"},{"event":"outer"}])

    def test_configured_jsonl_logs_rotate_at_one_mib_with_two_backups(self):
        import logging
        from lab10_fastapi.curriculum_app import main
        config=SimpleNamespace(log_enabled=True,log_dir=Path(self.temp.name)/"logs")
        logger=logging.getLogger("lab10_fastapi.curriculum_app.model_service.performance")
        with main.configure_logging(config):
            for sequence in range(5):
                logger.info(json.dumps({"sequence":sequence,"payload":"x"*600_000}))
        latest=config.log_dir/"lab10_performance.jsonl"
        files=[latest,latest.with_name(latest.name+".1"),latest.with_name(latest.name+".2")]
        self.assertEqual(len(list(config.log_dir.glob("lab10_performance.jsonl*"))),3)
        self.assertTrue(all(path.stat().st_size<=1048576 for path in files))
        self.assertEqual([json.loads(path.read_text(encoding="utf-8"))["sequence"] for path in files],[4,3,2])

    def test_logging_setup_failure_releases_handlers_already_installed(self):
        import logging
        from logging.handlers import RotatingFileHandler
        from lab10_fastapi.curriculum_app import main
        config=SimpleNamespace(log_enabled=True,log_dir=Path(self.temp.name)/"logs")
        logger=logging.getLogger("lab10_fastapi.curriculum_app.model_service.observations")
        previous=(list(logger.handlers),logger.level,logger.propagate)
        handler=RotatingFileHandler(Path(self.temp.name)/"setup.jsonl",encoding="utf-8")
        with patch.object(main,"RotatingFileHandler",side_effect=[handler,OSError("cannot prepare log")]):
            with self.assertRaisesRegex(OSError,"cannot prepare log"):
                with main.configure_logging(config):
                    self.fail("Failed setup must not enter the application lifespan")
        self.assertIsNone(handler.stream)
        self.assertEqual((list(logger.handlers),logger.level,logger.propagate),previous)


    def test_term_comparisons_with_curriculum_suffix_keep_original_single_database_flow(self):
        for suffix in ("ของหลักสูตรนี้", "ของ IT"):
            question = "ปี 1 เทอม 1 กับ ปี 2 เทอม 2 ต่างกันกี่หน่วยกิต " + suffix
            with self.subTest(suffix=suffix), patch.object(
                self.model, "_chat", side_effect=AssertionError("Term comparison must retain its rules"),
            ):
                answer = self.ask(question)
                self.assertEqual(answer["performance"]["intent"], "compare_terms")
                self.assertEqual((answer["performance"]["qwen_calls"], answer["performance"]["query_calls"]), (0, 1))
                self.assertEqual([(row["year"], row["semester"], row["credits"]) for row in answer["rows"]],
                                 [(1, 1, 6), (2, 2, 2)])
                self.assertIn("ส่วนต่าง: 4 หน่วยกิต", answer["answer"])


class CompareProgramTests(unittest.TestCase):
    """Cross-program rules, reads and caches use disposable databases only."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        names = {
            "IT": ("เทคโนโลยีสารสนเทศ", "Information Technology"),
            "DSBA": ("วิทยาการข้อมูลและการวิเคราะห์ธุรกิจ", "Data Science and Business Analytics"),
            "BIT": ("เทคโนโลยีสารสนเทศทางธุรกิจ", "Business Information Technology"),
            "AIT": ("เทคโนโลยีสารสนเทศประยุกต์", "Applied Information Technology"),
            "GENED": ("ศึกษาทั่วไป", "General Education"),
        }
        credits = {"IT": 126, "DSBA": 132, "BIT": 129, "AIT": 130, "GENED": 30}
        self.paths = {}
        for program, (name_th, name_en) in names.items():
            path = self.root / f"{program}.db"
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE program(program_id TEXT, name_th TEXT, name_en TEXT,
                        degree TEXT, total_credits INTEGER, years INTEGER);
                    CREATE TABLE course(code TEXT PRIMARY KEY, name_th TEXT, name_en TEXT,
                        credits INTEGER, lecture_h INTEGER, lab_h INTEGER, self_h INTEGER,
                        description_th TEXT);
                """)
                conn.execute("INSERT INTO program VALUES(?,?,?,?,?,?)",
                             (program, name_th, name_en, "BSc", credits[program], 4 if program != "BIT" else 3))
                conn.execute("INSERT INTO course VALUES(?,?,?,?,?,?,?,?)",
                             ("00000001", "วิชา IT กับ DSBA", "IT and DSBA", 3, 3, 0, 6, "Example"))
            self.paths[program] = path
        self.config = SimpleNamespace(
            ollama_url="http://127.0.0.1:11434", ollama_model="qwen3:4b",
            request_timeout=2, max_rows=100,
            db_paths={program: {"nocoop": path} for program, path in self.paths.items()},
            program_aliases={"IT": ("ไอที",), "DSBA": ("ดีเอสบีเอ",)},
        )
        self.model = QwenTextToSQL(self.config, lab8b)
        self.database = CurriculumDatabase(lab8b, self.paths["DSBA"])
        self.prohibit_inference()

    def prohibit_inference(self):
        no_qwen = patch.object(self.model, "_chat", side_effect=AssertionError("Comparison must use rules"))
        no_qwen.start()
        self.addCleanup(no_qwen.stop)

    def reload_configuration(self):
        self.model = QwenTextToSQL(self.config, lab8b)
        self.prohibit_inference()

    def ask(self, question, *, program="DSBA", track="nocoop"):
        return self.model.ask(self.database, question, program=program, track=track)

    def update(self, program, column, value):
        if column not in {"total_credits", "years"}:
            raise AssertionError("Unexpected test column")
        with closing(sqlite3.connect(self.paths[program])) as conn, conn:
            conn.execute(f"UPDATE program SET {column}=?", (value,))

    def assert_rejected(self, question, intent):
        answer = self.ask(question)
        self.assertEqual(answer["rows"], [])
        self.assertEqual(answer["sql"], "")
        self.assertEqual(answer["performance"]["intent"], intent)
        self.assertEqual(answer["performance"]["qwen_calls"], 0)
        self.assertEqual(answer["performance"]["query_calls"], 0)
        self.assertFalse(answer["performance"]["answer_cache_hit"])
        return answer

    def test_program_credit_comparison_overrides_form_and_uses_two_queries(self):
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", program="BIT")
        self.assertEqual([(r["program"], r["track"], r["total_credits"]) for r in answer["rows"]],
                         [("IT", "nocoop", 126), ("DSBA", "nocoop", 132)])
        self.assertIn("ส่วนต่างหน่วยกิตรวม: 6 หน่วยกิต", answer["answer"])
        self.assertIn("IT", answer["answer"])
        self.assertIn("DSBA", answer["answer"])
        self.assertIn("nocoop", answer["answer"])
        metrics = answer["performance"]
        self.assertEqual((metrics["intent"], metrics["plan_source"], metrics["qwen_calls"], metrics["query_calls"]),
                         ("compare_programs", "rules", 0, 2))
        self.assertIn("total_credits", answer["sql"])
        self.assertIn("-- IT", answer["sql"])
        self.assertIn("-- DSBA", answer["sql"])

    def test_reversing_targets_preserves_values_and_absolute_difference(self):
        forward = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        reverse = self.ask("เปรียบเทียบหน่วยกิตรวม DSBA กับ IT")
        self.assertEqual({r["program"]: r["total_credits"] for r in forward["rows"]},
                         {r["program"]: r["total_credits"] for r in reverse["rows"]})
        self.assertEqual([r["program"] for r in reverse["rows"]], ["DSBA", "IT"])
        self.assertIn("ส่วนต่างหน่วยกิตรวม: 6 หน่วยกิต", reverse["answer"])

    def test_duration_comparison_uses_original_program_years_template(self):
        answer = self.ask("เปรียบเทียบจำนวนปี IT กับ BIT")
        self.assertEqual([(r["program"], r["years"]) for r in answer["rows"]], [("IT", 4), ("BIT", 3)])
        self.assertNotIn("total_credits", answer["rows"][0])
        self.assertIn("ส่วนต่างระยะเวลาหลักสูตร: 1 ปี", answer["answer"])
        self.assertEqual(answer["performance"]["query_calls"], 2)

    def test_both_metrics_need_only_one_read_per_target(self):
        answer = self.ask("เปรียบเทียบหน่วยกิตรวมและจำนวนปี IT กับ DSBA")
        self.assertEqual([(r["total_credits"], r["years"]) for r in answer["rows"]], [(126, 4), (132, 4)])
        self.assertEqual((answer["performance"]["qwen_calls"], answer["performance"]["query_calls"]), (0, 2))

    def test_thai_aliases_and_database_metadata_names_are_supported(self):
        for question in [
            "เปรียบเทียบหน่วยกิตรวม ไอที กับ ดีเอสบีเอ",
            "เปรียบเทียบหน่วยกิตรวม it กับ dsba",
            "เปรียบเทียบหน่วยกิตรวม เทคโนโลยีสารสนเทศ กับ วิทยาการข้อมูลและการวิเคราะห์ธุรกิจ",
            "เปรียบเทียบหน่วยกิตรวม Information Technology กับ Data Science and Business Analytics",
        ]:
            with self.subTest(question=question):
                self.assertEqual([r["program"] for r in self.ask(question)["rows"]], ["IT", "DSBA"])

    def test_natural_difference_question_is_compared_without_inference(self):
        answer = self.ask("IT กับ DSBA หน่วยกิตรวมต่างกันเท่าไหร่")
        self.assertEqual([r["program"] for r in answer["rows"]], ["IT", "DSBA"])
        self.assertIn("ส่วนต่างหน่วยกิตรวม: 6 หน่วยกิต", answer["answer"])
        self.assertEqual(answer["performance"]["qwen_calls"], 0)

    def test_longer_code_boundaries_do_not_accidentally_add_it(self):
        for program in ("BIT", "AIT"):
            with self.subTest(program=program):
                answer = self.ask(f"เปรียบเทียบหน่วยกิตรวม {program} กับ DSBA")
                self.assertEqual([r["program"] for r in answer["rows"]], [program, "DSBA"])

    def test_unknown_code_and_partial_code_cannot_fall_back_to_selected_form(self):
        for unknown in ("UNKNOWN", "ITX", "XIT"):
            with self.subTest(unknown=unknown):
                self.assert_rejected(f"เปรียบเทียบหน่วยกิตรวม IT กับ {unknown}", "clarify")

    def test_duplicate_canonical_target_is_clarify(self):
        for question in ("เปรียบเทียบหน่วยกิตรวม IT กับ IT", "เปรียบเทียบหน่วยกิตรวม IT กับ ไอที"):
            with self.subTest(question=question):
                self.assert_rejected(question, "clarify")

    def test_more_than_two_targets_is_unsupported(self):
        self.assert_rejected("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA กับ BIT", "unsupported")

    def test_gened_program_metadata_cannot_be_compared(self):
        self.assert_rejected("เปรียบเทียบหน่วยกิตรวม IT กับ GENED", "unsupported")

    def test_unsupported_topics_and_extra_filters_are_not_silently_dropped(self):
        for question in (
            "เปรียบเทียบรายวิชา IT กับ DSBA",
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA ปี 2 เทอม 1",
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA และค่าเทอม",
            'เปรียบเทียบหน่วยกิตรวม IT กับ DSBA และ "ค่าเทอม"',
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA เฉพาะวิชา 3 หน่วยกิต",
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA และลบข้อมูล",
        ):
            with self.subTest(question=question):
                self.assert_rejected(question, "unsupported")

    def test_alias_collision_requires_clarification_instead_of_selecting_first_program(self):
        self.config.program_aliases = {"IT": ("หลักสูตรร่วม",), "DSBA": ("หลักสูตรร่วม",)}
        self.reload_configuration()
        self.assert_rejected("เปรียบเทียบหน่วยกิตรวม หลักสูตรร่วม กับ BIT", "clarify")

    def test_metadata_aliases_refresh_when_database_program_name_changes(self):
        old_question = "เปรียบเทียบหน่วยกิตรวม เทคโนโลยีสารสนเทศ กับ DSBA"
        self.assertEqual([r["program"] for r in self.ask(old_question)["rows"]], ["IT", "DSBA"])
        with closing(sqlite3.connect(self.paths["IT"])) as conn, conn:
            conn.execute("UPDATE program SET name_th=?", ("หลักสูตรระบบสารสนเทศใหม่",))
        new_question = "เปรียบเทียบหน่วยกิตรวม หลักสูตรระบบสารสนเทศใหม่ กับ DSBA"
        self.assertEqual([r["program"] for r in self.ask(new_question)["rows"]], ["IT", "DSBA"])
        self.assert_rejected(old_question, "clarify")

    def test_missing_topic_is_clarify(self):
        self.assert_rejected("เปรียบเทียบ IT กับ DSBA", "clarify")

    def test_two_programs_with_two_term_filters_are_unsupported(self):
        for question in (
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA ปี 1 เทอม 1 กับ ปี 2 เทอม 2",
            "ปี 1 เทอม 1 ของ IT กับ ปี 2 เทอม 2 ของ DSBA ต่างกันกี่หน่วยกิต",
        ):
            with self.subTest(question=question):
                self.assert_rejected(question, "unsupported")

    def test_explicit_common_track_takes_precedence_over_form(self):
        for program in ("IT", "DSBA"):
            self.config.db_paths[program]["coop"] = self.paths[program]
        self.reload_configuration()
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA แผน coop", track="nocoop")
        self.assertEqual([r["track"] for r in answer["rows"]], ["coop", "coop"])

    def test_nocoop_word_does_not_get_misclassified_as_coop(self):
        for program in ("IT", "DSBA"):
            self.config.db_paths[program]["coop"] = self.paths[program]
        self.reload_configuration()
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA แผน nocoop", track="coop")
        self.assertEqual([r["track"] for r in answer["rows"]], ["nocoop", "nocoop"])

    def test_mixed_explicit_tracks_require_clarification(self):
        for program in ("IT", "DSBA"):
            self.config.db_paths[program]["coop"] = self.paths[program]
        self.reload_configuration()
        self.assert_rejected("เปรียบเทียบหน่วยกิตรวม IT แผน coop กับ DSBA แผน nocoop", "clarify")

    def test_missing_track_uses_single_available_track_per_target(self):
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", track=None)
        self.assertEqual([r["track"] for r in answer["rows"]], ["nocoop", "nocoop"])

    def test_missing_or_invalid_track_for_multiple_options_is_clarify(self):
        self.config.db_paths["IT"]["coop"] = self.paths["IT"]
        self.reload_configuration()
        for track in (None, "missing"):
            with self.subTest(track=track):
                answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", track=track)
                self.assertEqual((answer["rows"], answer["performance"]["intent"]), ([], "clarify"))
                self.assertEqual(answer["performance"]["query_calls"], 0)

    def test_missing_explicit_track_is_not_implicitly_replaced_by_sole_track(self):
        self.assert_rejected("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA แผน coop", "clarify")

    def test_null_credit_is_unknown_and_never_becomes_zero_difference(self):
        self.update("IT", "total_credits", None)
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        self.assertIsNone(answer["rows"][0]["total_credits"])
        self.assertEqual(answer["rows"][1]["total_credits"], 132)
        self.assertIn("ไม่ทราบ", answer["answer"])
        self.assertNotIn("ส่วนต่างหน่วยกิตรวม:", answer["answer"])

    def test_invalid_numeric_metadata_is_unknown_and_cannot_create_difference(self):
        self.update("IT", "total_credits", "TBC")
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        self.assertIn("ไม่ทราบ", answer["answer"])
        self.assertNotIn("ส่วนต่างหน่วยกิตรวม:", answer["answer"])

    def test_nonfinite_metadata_is_unknown_and_api_response_remains_valid_json(self):
        from fastapi.encoders import jsonable_encoder
        from starlette.responses import JSONResponse
        from lab10_fastapi.curriculum_app import main
        from lab10_fastapi.curriculum_app.schemas import AskRequest, AskResponse
        self.update("IT", "total_credits", float("inf"))
        request = AskRequest(question="เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", program="DSBA", track="nocoop")
        with patch.object(main, "model", self.model):
            answer = main.ask(request)
        response = JSONResponse(content=jsonable_encoder(AskResponse.model_validate(answer)))
        payload = json.loads(response.body)
        self.assertIsNone(payload["rows"][0]["total_credits"])
        self.assertEqual(payload["rows"][1]["total_credits"], 132)
        self.assertIn("ไม่ทราบ", payload["answer"])
        self.assertNotIn("ส่วนต่างหน่วยกิตรวม:", payload["answer"])

    def test_null_years_do_not_hide_valid_credit_comparison(self):
        self.update("IT", "years", None)
        answer = self.ask("เปรียบเทียบหน่วยกิตรวมและจำนวนปี IT กับ DSBA")
        self.assertIsNone(answer["rows"][0]["years"])
        self.assertIn("ไม่ทราบ", answer["answer"])
        self.assertIn("ส่วนต่างหน่วยกิตรวม: 6 หน่วยกิต", answer["answer"])
        self.assertNotIn("ส่วนต่างระยะเวลาหลักสูตร:", answer["answer"])

    def test_second_request_has_fresh_metrics_and_zero_queries(self):
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        first, second = self.ask(question), self.ask(question)
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual((second["performance"]["plan_source"], second["performance"]["intent"]),
                         ("answer_cache", "compare_programs"))
        self.assertTrue(second["performance"]["answer_cache_hit"])
        self.assertEqual((second["performance"]["qwen_calls"], second["performance"]["query_calls"],
                          second["performance"]["citation_query_calls"]), (0, 0, 0))
        second["rows"][0]["total_credits"] = -1
        self.assertEqual(self.ask(question)["rows"][0]["total_credits"], 126)

    def test_cache_invalidates_when_either_target_database_changes(self):
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        self.ask(question)
        self.update("IT", "total_credits", 120)
        first = self.ask(question)
        self.assertEqual([r["total_credits"] for r in first["rows"]], [120, 132])
        self.assertFalse(first["performance"]["answer_cache_hit"])
        self.update("DSBA", "total_credits", 136)
        second = self.ask(question)
        self.assertEqual([r["total_credits"] for r in second["rows"]], [120, 136])
        self.assertFalse(second["performance"]["answer_cache_hit"])

    def test_cache_ignores_unrelated_form_database_revision(self):
        self.database = CurriculumDatabase(lab8b, self.paths["BIT"])
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        self.ask(question, program="BIT")
        self.update("BIT", "total_credits", 140)
        answer = self.ask(question, program="BIT")
        self.assertTrue(answer["performance"]["answer_cache_hit"])
        self.assertEqual(answer["performance"]["query_calls"], 0)

    def test_same_explicit_targets_reuse_cache_across_form_programs(self):
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        self.ask(question, program="DSBA")
        self.database = CurriculumDatabase(lab8b, self.paths["BIT"])
        answer = self.ask(question, program="BIT")
        self.assertTrue(answer["performance"]["answer_cache_hit"])
        self.assertEqual(answer["performance"]["query_calls"], 0)

    def test_missing_unrelated_form_database_does_not_block_explicit_targets(self):
        self.database = CurriculumDatabase(lab8b, self.root / "missing-form.db")
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", program="BIT")
        self.assertEqual([r["program"] for r in answer["rows"]], ["IT", "DSBA"])
        self.assertEqual(answer["performance"]["query_calls"], 2)

    def test_api_route_resolves_explicit_targets_before_selected_form_database(self):
        from lab10_fastapi.curriculum_app import main
        from lab10_fastapi.curriculum_app.schemas import AskRequest, AskResponse
        request = AskRequest(question="เปรียบเทียบหน่วยกิตรวม IT กับ DSBA", program="UNKNOWN", track="nocoop")
        with patch.object(main, "model", self.model), \
             patch.object(main, "select_database", side_effect=AssertionError("Form DB must not select comparison targets")):
            answer = main.ask(request)
        self.assertEqual([r["program"] for r in answer["rows"]], ["IT", "DSBA"])
        self.assertGreaterEqual(answer["processing_ms"], 0)
        AskResponse.model_validate(answer)

    def test_unselected_target_wal_change_invalidates_answer_cache(self):
        with closing(sqlite3.connect(self.paths["IT"])) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.commit()
            question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
            self.ask(question)
            before = self.paths["IT"].stat()
            writer.execute("UPDATE program SET total_credits=121")
            writer.commit()
            after = self.paths["IT"].stat()
            self.assertEqual((before.st_mtime_ns, before.st_size), (after.st_mtime_ns, after.st_size))
            answer = self.ask(question)
            self.assertEqual(answer["rows"][0]["total_credits"], 121)
            self.assertFalse(answer["performance"]["answer_cache_hit"])

    def test_revision_change_during_reads_retries_whole_comparison_once(self):
        original = CurriculumDatabase.query_from_model
        calls = []
        def query(database, sql, **kwargs):
            result = original(database, sql, **kwargs)
            calls.append(database.path)
            if len(calls) == 1:
                self.update("IT", "total_credits", 119)
            return result
        with patch.object(CurriculumDatabase, "query_from_model", query):
            answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        self.assertEqual([r["total_credits"] for r in answer["rows"]], [119, 132])
        self.assertEqual(answer["performance"]["query_calls"], 4)
        self.assertEqual(calls, [self.paths["IT"], self.paths["DSBA"], self.paths["IT"], self.paths["DSBA"]])

    def test_repeated_revision_change_fails_without_caching_inconsistent_rows(self):
        original = CurriculumDatabase.query_from_model
        calls = []
        def query(database, sql, **kwargs):
            result = original(database, sql, **kwargs)
            calls.append(database.path)
            if len(calls) in {1, 3}:
                self.update("IT", "total_credits", 126 + len(calls))
            return result
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        with patch.object(CurriculumDatabase, "query_from_model", query):
            with self.assertRaises(QueryExecutionError):
                self.ask(question)
        self.assertEqual(len(calls), 4)
        answer = self.ask(question)
        self.assertFalse(answer["performance"]["answer_cache_hit"])
        self.assertEqual(answer["performance"]["query_calls"], 2)

    def test_parallel_identical_questions_share_one_two_database_read(self):
        original = CurriculumDatabase.query_from_model
        def query(database, sql, **kwargs):
            time.sleep(.02)
            return original(database, sql, **kwargs)
        question = "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"
        with patch.object(CurriculumDatabase, "query_from_model", query):
            with ThreadPoolExecutor(max_workers=2) as pool:
                answers = list(pool.map(self.ask, [question, question]))
        self.assertEqual(answers[0]["rows"], answers[1]["rows"])
        self.assertEqual(sorted(answer["performance"]["query_calls"] for answer in answers), [0, 2])
        self.assertEqual(sum(answer["performance"]["qwen_calls"] for answer in answers), 0)

    def test_comparison_targets_share_one_request_deadline(self):
        from lab10_fastapi.curriculum_app.database import remaining_seconds
        original = CurriculumDatabase.query_from_model
        budgets = []
        def query(database, sql, **kwargs):
            budgets.append(remaining_seconds())
            time.sleep(.015)
            return original(database, sql, **kwargs)
        with patch.object(CurriculumDatabase, "query_from_model", query):
            self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        self.assertEqual(len(budgets), 2)
        self.assertGreater(budgets[0] - budgets[1], .01)

    def test_catalog_lock_wait_respects_deadline_and_next_request_recovers(self):
        from threading import Event
        from lab10_fastapi.curriculum_app.database import current_trace
        locked, release = Event(), Event()
        def hold_catalog_lock():
            with self.model.catalog._lock:
                locked.set()
                release.wait(timeout=2)
        self.config.request_timeout = .04
        with ThreadPoolExecutor(max_workers=1) as pool:
            holder = pool.submit(hold_catalog_lock)
            try:
                self.assertTrue(locked.wait(timeout=1), "The other thread must acquire the catalog lock")
                started = time.perf_counter()
                with self.assertRaises(TimeoutError):
                    self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
                self.assertLess(time.perf_counter() - started, .5)
                failed = self.model.performance_observations()[-1]
                self.assertEqual((failed["qwen_calls"], failed["query_calls"], failed["error_type"]),
                                 (0, 0, "TimeoutError"))
                self.assertIsNone(current_trace())
            finally:
                release.set()
            holder.result(timeout=1)
        self.config.request_timeout = 2
        answer = self.ask("เปรียบเทียบหน่วยกิตรวม IT กับ DSBA")
        self.assertEqual([r["program"] for r in answer["rows"]], ["IT", "DSBA"])
        self.assertEqual((answer["performance"]["qwen_calls"], answer["performance"]["query_calls"]), (0, 2))
        self.assertIsNone(current_trace())

    def test_quoted_course_search_is_not_treated_as_cross_program_comparison(self):
        # Ordinary course searches retain their existing Qwen fallback when needed.
        with patch.object(self.model, "_chat", return_value={
            "intent": "course_list", "search_field": "name_any", "search_term": None,
        }):
            answer = self.ask('ขอรายวิชาที่ชื่อมีคำว่า "IT กับ DSBA"')
        self.assertEqual(answer["performance"]["intent"], "course_list")
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])

    def comparison_plan(self, metrics=("total_credits",), track="nocoop"):
        return QueryPlan(intent="compare_programs", targets=[
            {"program": "IT", "track": track}, {"program": "DSBA", "track": track},
        ], metrics=list(metrics))

    def test_validate_plan_rejects_missing_or_duplicate_comparison_metrics(self):
        for metrics in ((), ("total_credits", "total_credits")):
            with self.subTest(metrics=metrics), self.assertRaises(ValueError):
                validate_plan(self.comparison_plan(metrics), "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA",
                              catalog=self.model.catalog)

    def test_validate_plan_cannot_omit_or_invent_requested_metrics(self):
        for metrics, question in (
            (("total_credits",), "เปรียบเทียบหน่วยกิตรวมและจำนวนปี IT กับ DSBA"),
            (("total_credits", "years"), "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"),
            (("years",), "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA"),
        ):
            with self.subTest(metrics=metrics, question=question), self.assertRaises(ValueError):
                validate_plan(self.comparison_plan(metrics), question, catalog=self.model.catalog)

    def test_validate_plan_preserves_explicit_common_track(self):
        for program in ("IT", "DSBA"):
            self.config.db_paths[program]["coop"] = self.paths[program]
        self.reload_configuration()
        with self.assertRaises(ValueError):
            validate_plan(self.comparison_plan(track="nocoop"),
                          "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA แผน coop", catalog=self.model.catalog)

    def test_validate_plan_accepts_multi_track_program_and_sole_default_track(self):
        self.config.db_paths["IT"]["coop"] = self.paths["IT"]
        self.config.db_paths["AIT"] = {"default": self.paths["AIT"]}
        self.reload_configuration()
        plan = QueryPlan(intent="compare_programs", targets=[
            {"program": "IT", "track": "nocoop"}, {"program": "AIT", "track": "default"},
        ], metrics=["total_credits"])
        validate_plan(plan, "เปรียบเทียบหน่วยกิตรวม IT กับ AIT", catalog=self.model.catalog)

    def test_validate_plan_rejects_hidden_unsupported_conditions(self):
        for question in (
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA ปี 2 เทอม 1",
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA และค่าเทอม",
            "เปรียบเทียบหน่วยกิตรวม IT กับ DSBA เฉพาะวิชา 3 หน่วยกิต",
        ):
            with self.subTest(question=question), self.assertRaises(ValueError):
                # An externally prepared plan must not bypass the rule's full-text check.
                validate_plan(self.comparison_plan(), question, catalog=self.model.catalog)


class StructuralPlannerTests(unittest.TestCase):
    """คำถามจริง: หมวด/ประเภท ปีต้นทาง-ปลายทาง และเงื่อนไขที่ห้ามทิ้ง."""
    ask = ModelServiceTests.ask
    choice = ModelServiceTests.choice

    def setUp(self):
        ModelServiceTests.setUp(self)
        no_inference = patch.object(self.model,"_chat",side_effect=AssertionError("Unexpected inference"))
        no_inference.start()
        self.addCleanup(no_inference.stop)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.executescript("""
                ALTER TABLE plan_item ADD COLUMN category TEXT;
                ALTER TABLE plan_item ADD COLUMN type TEXT;
                ALTER TABLE plan_item ADD COLUMN pages TEXT;
                ALTER TABLE course ADD COLUMN pages TEXT;
                ALTER TABLE prerequisite ADD COLUMN pages TEXT;
                UPDATE plan_item SET category='หมวดวิชาเฉพาะ',type='บังคับ',pages='[10]';
                UPDATE plan_item SET category='หมวดวิชาศึกษาทั่วไป',type='เลือก' WHERE id IN (2,3);
                UPDATE plan_item SET category='หมวดวิชาเลือกเสรี',type='เลือก',pages='[20]' WHERE id=4;
                UPDATE plan_item SET type='เลือก',pages='[22]' WHERE id=5;
                UPDATE course SET pages='[100]';
                UPDATE prerequisite SET pages='[200]';
                INSERT INTO prerequisite VALUES('00000003','00000001','pre','[201]');
                INSERT INTO prerequisite VALUES('00000003','00000002','pre','[202]');
                INSERT INTO prerequisite VALUES('00000004','00000001','co','[203]');
                DROP VIEW v_plan;
                CREATE VIEW v_plan AS SELECT p.*,c.name_th,c.name_en FROM plan_item p
                    LEFT JOIN course c ON c.code=p.code;
            """)

    def test_free_elective_filter_keeps_year_and_does_not_become_name_search(self):
        with patch.object(self.model, "_chat", side_effect=AssertionError("Use rules")):
            answer = self.ask("ในปี 2 มีเสรีอะไรบ้าง")
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000003"])
        self.assertIn("หมวดวิชาเลือกเสรี", answer["sql"])
        self.assertEqual(answer["citations"][0]["pages"], [20])

    def test_empty_free_electives_have_scope_evidence(self):
        answer = self.ask("ในปี 1 มีเสรีอะไรบ้าง")
        self.assertEqual(answer["rows"], [])
        self.assertIn("ไม่พบช่องวิชาเลือกเสรี", answer["answer"])
        self.assertTrue(answer["citations"])
        self.assertEqual(answer["citations"][0]["pages"], [10])

    def test_elective_type_is_not_free_elective_category(self):
        answer = self.ask("ปี 1 มีวิชาเลือกอะไรบ้าง")
        self.assertEqual({r["code"] for r in answer["rows"]}, {"00000002", "PLACEHOLDER_XX"})
        self.assertTrue(all(r["category"] == "หมวดวิชาศึกษาทั่วไป" for r in answer["rows"]))

    def test_required_courses_accept_first_semester_alias(self):
        answer = self.ask("วิชาบังคับชั้นปี 1 ภาคต้นมีอะไรบ้าง")
        self.assertEqual([r["code"] for r in answer["rows"]], ["00000001"])

    def test_category_requirements_do_not_sum_plan_slots_as_official_requirements(self):
        answer = self.ask("หมวดวิชาเลือกเสรีต้องเก็บกี่หน่วยกิต")
        self.assertFalse(answer["sql"])
        self.assertIn("เกณฑ์", answer["answer"])

    def test_progression_pairs_are_directed_and_exclude_corequisites(self):
        with patch.object(self.model, "_chat", side_effect=AssertionError("Use rules")):
            answer = self.ask("วิชาปี 2 อะไรบ้างที่ต้องผ่านวิชาปี 1 ก่อน")
        self.assertEqual({(r["source_code"],r["target_code"]) for r in answer["rows"]},
                         {("00000001","00000003"),("00000002","00000003")})
        self.assertNotIn("00000004", {r["target_code"] for r in answer["rows"]})
        self.assertIn("เงื่อนไข", answer["answer"])
        self.assertTrue(any(c["source"] == "prerequisite" for c in answer["citations"]))
        self.assertTrue(any(c["source"] == "study_plan" for c in answer["citations"]))

    def test_reverse_wording_keeps_same_progression_direction(self):
        first = self.ask("วิชาปี 1 มีตัวต่อในปี 2 อะไรบ้าง")
        second = self.ask("วิชาปี 2 อะไรบ้างที่ต้องผ่านวิชาปี 1 ก่อน")
        self.assertEqual(first["rows"],second["rows"])

    def test_ambiguous_progression_year_is_a_specific_clarification(self):
        with patch.object(self.model, "_chat", side_effect=AssertionError("Ambiguous scope")):
            answer = self.ask("มีรายวิชาไหนบ้างมีตัวต่อ ปี 1")
        self.assertFalse(answer["sql"])
        self.assertIn("ปีปลายทาง",answer["answer"])

    def test_unsupported_condition_cannot_be_hidden_in_qwen_search_term(self):
        question = "ปี 1 มีวิชาอะไรบ้างเฉพาะที่เปิดวันจันทร์"
        with patch.object(self.model,"_chat",return_value=self.choice("course_list","name_any","เฉพาะที่เปิดวันจันทร์")):
            answer=self.ask(question)
        self.assertFalse(answer["sql"])
        self.assertIn("วันจันทร์",answer["answer"])

    def test_unknown_phrase_has_actionable_coverage_diagnostics(self):
        with patch.object(self.model,"_chat",return_value=self.choice()):
            answer=self.ask("ปี 1 มีวิชาอะไรบ้างพร้อมอาหารกลางวัน")
        self.assertFalse(answer["sql"])
        self.assertIn("อาหารกลางวัน",answer["answer"])
        self.assertTrue(answer["performance"]["planning_diagnostics"]["uncovered"])

    def test_lexicon_finds_unquoted_name_and_refreshes_after_database_edit(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'",("สหกิจศึกษา",))
        with patch.object(self.model,"_chat",side_effect=AssertionError("Known database name")):
            answer=self.ask("สหกิจศึกษาต้องเรียนกี่หน่วยกิต")
        self.assertEqual(answer["rows"][0]["code"],"00000001")
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'",("ฝึกงานวิชาชีพ",))
        with patch.object(self.model,"_chat",side_effect=AssertionError("Refreshed name")):
            answer=self.ask("ฝึกงานวิชาชีพต้องเรียนกี่หน่วยกิต")
        self.assertEqual(answer["rows"][0]["code"],"00000001")

    def test_lexicon_does_not_treat_a_course_title_as_a_category(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'",("วิชาเสรีสร้างสรรค์",))
        answer=self.ask("วิชาวิชาเสรีสร้างสรรค์มีกี่หน่วยกิต")
        self.assertEqual([r["code"] for r in answer["rows"]],["00000001"])

    def test_missing_categories_and_missing_plan_are_not_empty_matches(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE plan_item SET category=NULL WHERE year=1")
        answer=self.ask("ปี 1 มีเสรีอะไรบ้าง")
        self.assertFalse(answer["sql"])
        self.assertIn("ข้อมูลหมวด",answer["answer"])
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("DELETE FROM plan_item")
        answer=self.ask("ปี 1 มีเสรีอะไรบ้าง",program="GENED",track="default")
        self.assertFalse(answer["sql"])
        self.assertIn("ไม่มีแผนรายปี",answer["answer"])

    def test_coverage_diagnostics_survive_answer_cache_with_zero_queries(self):
        first=self.ask("ปี 2 มีเสรีอะไรบ้าง")
        second=self.ask("ปี 2 มีเสรีอะไรบ้าง")
        self.assertEqual(first["performance"]["planning_diagnostics"],second["performance"]["planning_diagnostics"])
        self.assertEqual(second["performance"]["query_calls"],0)

    def test_supported_details_grammar_and_hour_outputs_remain_covered(self):
        first=self.ask("วิชา 00000001 มีรายละเอียดอย่างไร")
        self.assertEqual(first["performance"]["intent"],"course_details")
        with patch.object(self.model,"_chat",return_value=self.choice("course_details")):
            second=self.ask("วิชา 00000001 มีชั่วโมงบรรยาย ปฏิบัติ ศึกษาด้วยตนเองกี่ชั่วโมง")
        self.assertEqual(second["rows"],first["rows"])
        self.assertTrue(second["performance"]["planning_diagnostics"]["complete"])

    def test_year_minimum_is_computed_without_qwen(self):
        result=self.ask("ปีไหนมีหน่วยกิตรวมน้อยที่สุด")
        self.assertEqual(result["performance"]["intent"],"year_summary")
        self.assertTrue(result["sql"])
        self.assertIn("น้อยที่สุด",result["answer"])

    def test_unquoted_literal_course_prefix_is_not_required(self):
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("UPDATE course SET name_th=? WHERE code='00000001'",("การเตรียมความพร้อมสหกิจศึกษา",))
        # ค้นข้อความย่อยตามคำถาม ไม่อ้างว่าเป็นชื่อเต็ม/รหัสที่ตรงแน่นอน.
        result=self.ask("สหกิจศึกษาต้องเรียนกี่หน่วยกิต")
        self.assertEqual([r["code"] for r in result["rows"]],["00000001"])
        self.assertIn("ข้อความย่อย",result["answer"])

    def test_relation_cannot_be_replaced_with_plain_list_when_words_are_covered(self):
        question="วิชา 00000003 ต้องผ่านวิชาอะไรก่อน"
        with self.assertRaises(ValueError):
            validate_plan(QueryPlan(intent="course_list",course_codes=["00000003"]),question)
        result=self.ask("ปี 1 มีวิชาอะไรบ้างที่ต้องผ่านวิชา 00000001 ก่อน")
        self.assertFalse(result["sql"])
        self.assertIn("ปีต้นทาง",result["answer"])

    def test_negation_and_quantifiers_cannot_disappear_from_progression(self):
        for question in ("วิชาปี 1 มีตัวต่อในปี 2 ที่ไม่ต้องผ่านอะไรบ้าง",
                         "วิชาปี 2 อะไรบ้างที่ต้องผ่านทุกวิชาในปี 1 ก่อน"):
            with self.subTest(question=question):
                result=self.ask(question)
                self.assertFalse(result["sql"])
                self.assertTrue(result["performance"]["planning_diagnostics"]["uncovered"])

    def test_specialized_electives_are_distinct_from_free_electives(self):
        result=self.ask("ปี 2 มีวิชาเฉพาะเลือกอะไรบ้าง")
        self.assertEqual([r["code"] for r in result["rows"]],["00000004"])
        self.assertTrue(all(r["category"]=="หมวดวิชาเฉพาะ" and r["type"]=="เลือก" for r in result["rows"]))

    def test_semester_plan_credit_summary_does_not_depend_on_qwen(self):
        result=self.ask("สรุปแผนการเรียนตลอดหลักสูตรเป็นรายเทอม พร้อมหน่วยกิตรวมแต่ละเทอม")
        self.assertEqual(result["performance"]["intent"],"semester_summary")
        self.assertEqual({(r["year"],r["semester"]) for r in result["rows"]},{(1,1),(2,1),(2,2)})


if __name__=="__main__":
    unittest.main()
