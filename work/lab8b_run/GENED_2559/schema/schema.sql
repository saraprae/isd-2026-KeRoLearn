
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
DROP VIEW IF EXISTS v_plan;
CREATE VIEW v_plan AS
SELECT p.id, p.year, p.semester, p.code, c.name_th, c.name_en,
       p.credits, c.lecture_h, c.lab_h, c.self_h,
       p.alt_group, p.category, p.type, p.note,
       COALESCE(p.pages, c.pages) AS pages
FROM plan_item p
LEFT JOIN course c ON c.code = p.code;

-- ตอบคำถาม "วิชานี้เรียนได้ตอนไหน" ได้ทั้งวิชาที่ล็อกเทอมและวิชาเลือกยืดหยุ่น
-- ถ้าไม่มี VIEW นี้ LLM ต้องรู้เองว่าต้องไปดูสองตาราง ซึ่งมันจะลืม
DROP VIEW IF EXISTS v_course_terms;
CREATE VIEW v_course_terms AS
SELECT p.code AS code, c.name_th AS name_th,
       (p.year || '/' || p.semester) AS terms,
       p.year AS year, p.semester AS semester,
       p.credits AS credits,
       COALESCE(p.pages, c.pages) AS pages
FROM plan_item p LEFT JOIN course c ON c.code = p.code
UNION ALL
SELECT e.code, COALESCE(c.name_th, e.name_th),
       e.allowed_terms, NULL, NULL, COALESCE(e.credits, c.credits),
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

-- หน่วยกิตรายปี (โมเดลไม่ต้อง GROUP BY ซ้อนเอง)
CREATE VIEW IF NOT EXISTS v_year_credits AS
SELECT year, SUM(credits) AS credits FROM v_semester_credits GROUP BY year;

-- หน่วยกิตรวมรายหมวด/ประเภท โดยนับวิชา "A หรือ B" (alt_group เดียวกันในเทอมเดียวกัน) ครั้งเดียว
-- เหตุผลเดียวกับ v_semester_credits: SUM จาก plan_item ตรง ๆ จะนับสหกิจ 06036147/06036148 สองครั้ง
DROP VIEW IF EXISTS v_category_credits;
CREATE VIEW v_category_credits AS
SELECT category, type, SUM(credits) AS credits
FROM (
    SELECT year, semester, category, type,
           COALESCE(alt_group, 'x' || id) AS grp,
           MIN(credits) AS credits
    FROM plan_item
    GROUP BY year, semester, category, type, COALESCE(alt_group, 'x' || id)
)
GROUP BY category, type;

-- ข้อ prerequisite ที่มีชื่อวิชาทั้งสองฝั่ง และชื่อคอลัมน์ไม่ให้สับทิศ
CREATE VIEW IF NOT EXISTS v_prereq AS
SELECT p.code AS course_code,   c1.name_th AS course_name,
       p.requires AS prereq_code, c2.name_th AS prereq_name,
       p.kind
FROM prerequisite p
LEFT JOIN course c1 ON c1.code = p.code
LEFT JOIN course c2 ON c2.code = p.requires;

-- รหัสจริง (ตัดรหัส placeholder ออกให้เลย)
CREATE VIEW IF NOT EXISTS v_real_course AS
SELECT * FROM course
WHERE LENGTH(code) = 8 AND code NOT GLOB '*[^0-9]*';

CREATE VIEW IF NOT EXISTS v_unlocks AS
SELECT prereq_code AS base_code, prereq_name AS base_name,
       course_code AS unlocks_code, course_name AS unlocks_name, kind
FROM v_prereq;

-- สถิติ prerequisite รายวิชา: ตอบคำถามจัดอันดับ/นับ โดยโมเดลไม่ต้องเลือกทิศเอง
--   n_prereq  = จำนวนวิชาที่ต้องเรียนมาก่อนวิชานี้
--   n_unlocks = จำนวนวิชาอื่นที่ต้องเรียนวิชานี้มาก่อน
-- เหตุผล: GROUP BY course_code หรือ prereq_code ต่างกันแค่ทิศเดียว โมเดลขนาดเล็กลอกตัวอย่างผิดทิศ
--        ย้ายการเลือกทิศมาไว้ที่ชื่อคอลัมน์ จะผิดทิศไม่ได้ (หลักการ: อะไรต้องถูกเสมอ ให้เป็นโค้ด)
DROP VIEW IF EXISTS v_prereq_stats;
CREATE VIEW v_prereq_stats AS
SELECT c.code AS code, c.name_th AS name_th,
       (SELECT COUNT(DISTINCT p.requires) FROM prerequisite p
         WHERE p.code = c.code AND p.kind = 'pre') AS n_prereq,
       (SELECT COUNT(DISTINCT p.code) FROM prerequisite p
         WHERE p.requires = c.code AND p.kind = 'pre') AS n_unlocks
FROM course c;
