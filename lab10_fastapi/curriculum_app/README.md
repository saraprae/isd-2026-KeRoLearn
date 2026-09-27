# Curriculum Application

แอปนี้รับคำถาม → ให้ Qwen สร้าง SQL → อ่าน SQLite → ส่งกลับทั้งคำตอบ, SQL และ rows

## โครงสร้างและวิธีรัน

โครงสร้างโฟลเดอร์ปัจจุบัน:

```text
isd-2026-KeRoLearn-main/          ← โฟลเดอร์ workspace
├── .venv/
└── isd-2026-KeRoLearn-main/      ← PROJECT_ROOT
    ├── lab10_fastapi/lab10_fastapi/curriculum_app/
    │   ├── .env
    │   └── main.py
    ├── src/ocr_system/lab8b_curriculum_db.py
    └── work/lab8b_run/
        ├── DSBA/nocoop/curriculum.db
        └── ...                 ← ฐานข้อมูลหลักสูตรและแผนอื่น
```

เปิด PowerShell จากโฟลเดอร์ workspace ที่มี `.venv` แล้วรัน:

```powershell
& '.\.venv\Scripts\python.exe' -m pip install -r '.\isd-2026-KeRoLearn-main\lab10_fastapi\lab10_fastapi\curriculum_app\requirements.txt'
ollama pull qwen3:4b
& '.\.venv\Scripts\python.exe' -m uvicorn curriculum_app.main:app --app-dir '.\isd-2026-KeRoLearn-main\lab10_fastapi\lab10_fastapi' --host 127.0.0.1 --port 8000
```

เปิด <http://127.0.0.1:8000/> หรือ <http://127.0.0.1:8000/docs>

ตั้งค่าใน `curriculum_app/.env` ดังนี้:

```dotenv
CURRICULUM_DB_ROOT=work/lab8b_run
CURRICULUM_DB_PATH=work/lab8b_run/DSBA/nocoop/curriculum.db
```

path สัมพัทธ์ใน `.env` อ้างอิงจาก `PROJECT_ROOT` ชั้นใน ไม่ใช่โฟลเดอร์ที่เปิด Terminal ใช้ `/` ใน path เพื่อหลีกเลี่ยงการแปลง `\n` เป็นอักขระขึ้นบรรทัดใหม่ในค่าที่ครอบด้วยเครื่องหมายคำพูดคู่

ก่อนรันต้องมี Lab 8B และไฟล์ฐานข้อมูลตามโครงสร้างข้างต้น แอปเพิ่ม `src` สำหรับ import ให้อัตโนมัติ ไม่ต้องตั้ง `PYTHONPATH`

## โหลดหลักสูตรและแผนด้วย `GET /api/curricula`

อ่านรายชื่อหลักสูตรและแผนจาก `settings.db_paths` ใน `config.py` ไม่ต้องส่ง query parameters หรือ request body และไม่เรียกโมเดลหรือเปิดฐานข้อมูล

เปิด <http://127.0.0.1:8000/api/curricula> หรือทดลองใน Swagger ที่ `/docs` ตัวอย่าง response HTTP `200` ตาม config ปัจจุบัน:

```json
{
  "programs": [
    {"program": "IT", "tracks": ["coop", "nocoop"]},
    {"program": "DSBA", "tracks": ["coop", "nocoop"]},
    {"program": "BIT", "tracks": ["coop", "nocoop"]},
    {"program": "AIT", "tracks": ["default"]}
  ]
}
```

หน้าเว็บเรียก API นี้เมื่อเปิดหน้า เพื่อนำข้อมูลมาเติม dropdown หลักสูตรและแผน เมื่อเปลี่ยนหลักสูตรจะปรับรายการแผนให้ตรงกัน จากนั้นส่งค่าที่เลือกเป็น `program` และ `track` ไปยัง `POST /api/ask` ระหว่างโหลดตัวเลือกหรือโหลดไม่สำเร็จ ปุ่มถามจะถูกปิดไว้

เมื่อเพิ่มหรือเปลี่ยน mapping ใน `settings.db_paths` ให้รีสตาร์ต backend และรีเฟรชหน้าเว็บ รายการใหม่จะปรากฏโดยไม่ต้องแก้รายชื่อใน JavaScript ผลจาก API นี้แสดงรายการที่ตั้งค่าไว้ ไม่ได้ยืนยันว่าไฟล์ DB ของทุกแผนพร้อมใช้งาน

`GET /api/curricula` ส่งรายการหลักสูตร/แผนสำหรับเลือก ส่วน `GET /api/program` อ่านรายละเอียดหลักสูตรจากฐานข้อมูลค่าเริ่มต้น

## ถามคำถามด้วย `/api/ask`

ส่ง `POST /api/ask` ด้วย JSON body นี้:

```json
{
  "question": "ปี 1 เทอม 1 เรียนกี่หน่วยกิต",
  "program": "DSBA",
  "track": "nocoop"
}
```

ระบบเลือกฐานข้อมูลจาก `program` และ `track` ที่ส่งมาใน request ซึ่งหน้าเว็บส่งจากตัวเลือกหลักสูตรและแผนการเรียน โดยใช้ `settings.db_paths` ใน `config.py` (โฟลเดอร์ฐานข้อมูลกำหนดด้วย `CURRICULUM_DB_ROOT`)

| program | track | ไฟล์ภายใต้ DB_ROOT |
|---|---|---|
| `IT`, `DSBA`, `BIT` | `coop` หรือ `nocoop` | `<program>/<track>/curriculum.db` |
| `AIT` | `default` | `AIT/curriculum.db` |

ต้องระบุ `program` ทุกครั้ง ส่วน IT, DSBA และ BIT ต้องระบุ `track` ด้วย สำหรับ AIT สามารถส่ง `"track": "default"` หรือละ `track` เพื่อใช้แผนเดียวที่มีได้ หากไม่ส่งค่าที่จำเป็นหรือส่งหลักสูตร/แผนที่ไม่รองรับ ระบบตอบ HTTP `422`

ตัวอย่างข้างต้นใช้ DSBA แผน nocoop ถ้าเปลี่ยนเป็น `"program": "IT", "track": "coop"` จะค้นจาก IT แผน coop โดยค่าเริ่มต้น `settings.db_path` ไม่ทับตัวเลือกนี้ ข้อความใน `question` ไม่ได้เปลี่ยนฐานข้อมูลอัตโนมัติ เช่น เลือก IT แต่พิมพ์ถาม DSBA ระบบยังค้นจาก IT และปัจจุบันยังไม่ตรวจความขัดแย้งนี้

`/api/ask` คืน `question`, `sql`, `rows` และ `answer` เหมือนเดิม โดย SQL ยังผ่าน `guard_sql` และอ่านฐานข้อมูลแบบ read-only

## คำถามที่พบบ่อย

### เปิดเว็บแล้วขึ้น `ERR_CONNECTION_REFUSED`

FastAPI ยังไม่ได้รัน ให้รันคำสั่ง Uvicorn ด้านบนและเปิด Terminal ค้างไว้

### ขึ้น `No module named fastapi`

ยังไม่ได้ activate venv หรือยังไม่ได้ติดตั้ง `requirements.txt`

### ขึ้น `ไม่พบฐานข้อมูล`

ตรวจว่ามี `work/lab8b_run/curriculum.db` และค่า `CURRICULUM_DB_PATH` ใน `.env` ถูกต้อง

### เปิดหน้าเว็บได้แต่ถามไม่ได้

เปิด `/api/health` แล้วตรวจว่า `database_ready` และ `ollama_ready` เป็น `true`

<!-- Qwen สร้าง SQL จากคำถามที่ [model_service.py (line 50)](/E:/69/Lab3_ocr_system - Copy/ocr_system/lab10_fastapi/curriculum_app/model_service.py:50)
นำ SQL ไปอ่าน SQLite แบบ readonly=True ที่ [database.py (line 61)](/E:/69/Lab3_ocr_system - Copy/ocr_system/lab10_fastapi/curriculum_app/database.py:61)
ส่งเฉพาะ rows ที่ได้จากฐานข้อมูลให้ Qwen สรุปคำตอบที่ [model_service.py (line 71)](/E:/69/Lab3_ocr_system - Copy/ocr_system/lab10_fastapi/curriculum_app/model_service.py:71)
Endpoint /api/ask ไม่ได้เรียก OCR หรืออ่าน PDF เลย -->

<!-- ไม่ได้ส่งหนังสือหลักสูตรทั้งเล่มเข้า LLM ทุกครั้ง
OCR/ประมวลผลหนังสือจะเกิดเฉพาะตอนสร้างหรืออัปเดตฐานข้อมูล เช่น รัน:
python run_lab8b.py
ส่วน:
python run_lab8b.py --skip-lab7
จะไม่ OCR หนังสือใหม่ แต่จะนำผลเดิมมาสร้าง curriculum.db ใหม่ -->

## บันทึกเพิ่มเติม: การตรวจผลลัพธ์จากโมเดลใน `_chat()`

ส่วนนี้เป็นเอกสารที่เพิ่มภายหลังจากต้นฉบับ README เพื่อบันทึกการเปลี่ยนแปลงใน `QwenTextToSQL._chat()` ของ `model_service.py` โดยยังใช้ Ollama/Qwen เดิมเป็นค่าเริ่มต้น และยังไม่ได้เชื่อมโมเดล inference ตัวใหม่

### ก่อนเพิ่มการตรวจผล

เดิม `_chat()` เรียก `lab8b.ollama_generate()` แล้วส่งผลลัพธ์เข้า `lab8b.parse_json_loose()` โดยตรง จึงตั้งสมมติฐานว่าผลจากโมเดลเป็นข้อความ JSON และไม่ได้ตรวจให้ชัดว่าผลหลัง parse เป็น object หรือมี key ที่ผู้เรียกต้องการครบหรือไม่

ก่อนแก้ `_chat()` เรียก Ollama แล้วส่งผลเข้า `parse_json_loose()` ทันที โดยสมมติว่าผลจากโมเดลเป็นข้อความ JSON ที่ถูกต้องเสมอ จุดที่ขาดคือ:

- ถ้า inference คืน Python `dict` มาโดยตรง ก็ไม่มีทางแยกมารับแบบนั้นอย่างถูกต้อง
- ไม่ตรวจว่าหลัง parse ได้ `dict` จริงหรือไม่ ผลเป็น array, `null` หรือ scalar อาจทำให้โค้ดส่วนถัดไปพัง
- ไม่ตรวจว่ามี key ที่จำเป็นหรือไม่ เช่น ไม่มี `sql` หรือ `answer` ทำให้ระบบได้ค่าไม่ครบและล้มเหลวในขั้นต่อไป
- ข้อความที่ parse ไม่ได้และกลายเป็น `{}` ไม่ถูกปฏิเสธ ณ จุดรับผล จึงปล่อยข้อมูลผิดรูปแบบไปถึงขั้นสร้าง SQL หรือสรุปคำตอบ

การแก้เพิ่มการรองรับ dict โดยตรง และตรวจชนิด object กับ required keys ก่อนส่งต่อ ส่วนการตรวจว่าค่า `sql` หรือ `answer` เป็น string ตาม schema ยังไม่ได้ทำ และอยู่นอกขอบเขตการตรวจนี้

### หลังเพิ่มการตรวจผล

ปัจจุบัน `_chat()` ยังคงเรียก `lab8b.ollama_generate()` ด้วย prompt, JSON output schema และพารามิเตอร์เดิม จากนั้นจัดการผลลัพธ์ดังนี้:

- รับ Python `dict` จาก inference ได้โดยตรง
- ถ้าผลเป็นข้อความ จะใช้ `lab8b.parse_json_loose()` แปลงข้อความ
- ปฏิเสธผลที่ไม่ใช่ `dict` เช่น JSON array, `null` และ scalar ด้วย `ValueError`
- ตรวจ key ที่จำเป็นจาก `schema.get("required", [])` และ raise `ValueError` เมื่อมี key ขาด
- เมื่อผ่านการตรวจ จะคืน `data` ให้ `make_sql()` หรือ `summarize()` ตามเดิม

ตัวอย่างเช่น ขั้นสร้าง SQL ต้องได้ object ที่มี key `sql` ส่วนขั้นสรุปคำตอบต้องได้ object ที่มี key `answer` ข้อความที่ parser เดิมแปลงเป็น `{}` จะถูกปฏิเสธเพราะไม่มี required key

การตรวจนี้ยืนยันเพียงว่าเป็น `dict` และมี required keys ไม่ใช่การตรวจ JSON Schema ครบทุกข้อ ผู้เขียน inference ต้องคืนค่า `sql` และ `answer` เป็น string ตาม schema ด้วย เมื่อเกิด `ValueError` ในเส้นทาง `/api/ask` แอปจะตอบ HTTP `422`

การเปลี่ยนแปลงนี้จำกัดอยู่ที่การตรวจรูปแบบผลลัพธ์ใน `_chat()` ไม่ได้เปลี่ยน FastAPI, SQLite, `guard_sql`, frontend, config, requirements หรือ `.env`

เมื่อผู้ใช้ส่งคำถาม ระบบจะทำงานดังนี้:

1. สร้าง prompt เพื่อให้ Qwen แปลงคำถามเป็น SQL แล้วเรียก `lab8b.ollama_generate()` ด้วยค่าเดิม
2. ตรวจผลลัพธ์จากโมเดล ถ้าเป็น `dict` ก็ใช้ได้เลย ถ้าเป็นข้อความจะส่งให้ `lab8b.parse_json_loose()` แปลงเป็น dict
3. ปฏิเสธผลที่ไม่ใช่ JSON object เช่น array, `null` หรือ scalar รวมถึงกรณีที่ไม่มี key ที่ schema ระบุว่าจำเป็น เช่น `sql`
4. ส่ง SQL ไปตรวจความปลอดภัยและค้นฐานข้อมูลแบบ read-only จากนั้นให้โมเดลสรุปผล โดยรอบนี้ต้องมี key `answer`
5. ตอบกลับผู้ใช้เป็น JSON ที่มี `question`, `sql`, `rows` และ `answer` ถ้าไม่พบแถวข้อมูล ระบบใช้ข้อความ “ไม่พบข้อมูลนี้ในฐานข้อมูลหลักสูตร”

ถ้าผลโมเดลผิดรูปแบบหรือขาด required key `_chat()` จะ raise `ValueError` และ handler ปัจจุบันแปลงเป็น HTTP `422` ส่วนการติดต่อ Ollama ไม่ได้จะได้ HTTP `503` การตรวจนี้ยืนยันเฉพาะว่าเป็น dict และมี key ที่จำเป็น ไม่ได้ตรวจชนิดของค่าเต็มตาม JSON Schema ดังนั้น inference ควรคืน `sql` และ `answer` เป็น string

การทดสอบผ่านกรณีรับ dict, รับข้อความ JSON, และปฏิเสธ array, `null`, scalar, ข้อความที่ parse แล้วไม่มี key และผลที่ขาด required key แล้ว ทั้งนี้เป็นการทดสอบด้วย mock ไม่ได้เรียก Ollama จริง

---

## 📋 สรุปหน้าที่ API ทั้งหมด

| Method | Endpoint | หน้าที่ |
|---|---|---|
| `GET` | `/` | แสดงหน้าเว็บหลัก (index.html) |
| `GET` | `/api/health` | ตรวจสอบว่าระบบทั้งหมดพร้อมใช้งานหรือเปล่า |
| `GET` | `/api/curricula` | ดูรายชื่อหลักสูตรและแผนเรียนที่มีทั้งหมด |
| `GET` | `/api/program` | ดูข้อมูลหลักสูตร (ชื่อหลักสูตร, จำนวนหน่วยกิตรวม, จำนวนปี) |
| `GET` | `/api/courses` | ดูรายวิชาทั้งหมด หรือค้นหาวิชาของหลักสูตรที่เลือก |
| `POST` | `/api/courses` | เพิ่มวิชาใหม่เข้าไปในฐานข้อมูล |
| `GET` | `/api/descriptions` | ดูคำอธิบายรายละเอียดของวิชา (จากรหัสวิชา) |
| `GET` | `/api/study-plan` | ดูแผนการเรียนรายเทอม (ปีที่เท่าไหร่ เทอมอะไร เรียนวิชาอะไรบ้าง) |
| `POST` | `/api/ask` | ส่งคำถามภาษาไทยให้ AI แปลงเป็น SQL ค้นฐานข้อมูล แล้วตอบกลับเป็นภาษาไทย |

---

## 🔍 อธิบายละเอียด

### 🔵 `/api/health`
> ตรวจสุขภาพระบบ — ใช้ **เช็คก่อนเสมอ** ว่า DB และ Ollama พร้อมไหม

### 🔵 `/api/curricula`
> บอกว่าระบบรองรับหลักสูตรอะไรบ้าง เช่น DSBA มี coop/nocoop, AIT มีแค่ default

### 🔵 `/api/program`
> ดูข้อมูลพื้นฐานของหลักสูตร เช่น ชื่อ, **132 หน่วยกิต**, เรียน **4 ปี**

### 🔵 `/api/courses`
> ดูรายวิชาทั้งหมดของหลักสูตรนั้น หรือค้นหาวิชาที่ต้องการ

### 🟩 `POST /api/courses`
> เพิ่มวิชาใหม่เข้า DB (ใช้ตอนทดสอบหรือเพิ่มข้อมูล)

### 🔵 `/api/descriptions`
> ดูคำอธิบายวิชาแบบละเอียด เช่น เนื้อหาวิชา, ชั่วโมงบรรยาย, ชั่วโมง lab

### 🔵 `/api/study-plan`
> ดูว่า **ปีที่ X เทอม Y** ต้องเรียนวิชาอะไรบ้าง — มีประโยชน์มากสำหรับวางแผนการเรียน

### 🟩 `POST /api/ask`
> **ฟีเจอร์หลักของ Lab นี้!** — พิมพ์คำถามภาษาไทยเข้าไป AI จะ:
> 1. แปลงคำถาม → SQL
> 2. ค้นหาในฐานข้อมูล
> 3. สรุปคำตอบเป็นภาษาไทยกลับมา