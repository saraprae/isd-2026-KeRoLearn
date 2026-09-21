
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
