# Lab 10 — FastAPI + Qwen text-to-SQL + SQLite + Frontend

Lab นี้มีสอง application แยก `main.py` และ `index.html` ออกจากกัน

```text
Curriculum App                 Transcript App
คำถาม → SQL → SQLite          Upload PDF/Image
       → rows → คำตอบ          → preprocess → OCR → postprocess → JSON
```

> ระบบนี้ยังไม่ใช่ vector RAG: ไม่มี embedding หรือ vector database โมเดลทำหน้าที่แปลงคำถามเป็น SQL และสรุปผลจาก SQLite

## 1. ไฟล์สำคัญ

```text
lab10_fastapi/
├── curriculum_app/
│   ├── main.py         Curriculum API
│   ├── config.py / .env.example
│   ├── database.py / model_service.py / schemas.py
│   ├── requirements.txt
│   ├── README.md
│   └── static/index.html
├── transcript_app/
│   ├── main.py         Transcript upload API
│   ├── config.py / .env.example
│   ├── pipeline_service.py / schemas.py
│   ├── requirements.txt
│   ├── README.md
│   └── static/index.html
└── README.md
```

แต่ละกลุ่มสามารถก็อปเฉพาะโฟลเดอร์ application ของตนเองได้ แต่ต้องมีโฟลเดอร์ `src/ocr_system` ที่เก็บ Lab 8 อยู่ในโปรเจกต์เดียวกัน

## 2. สิ่งที่ต้องมีก่อนเริ่ม

- Python 3.10 ขึ้นไป
- VS Code
- Ollama
- โมเดล `qwen3:4b`
- ฝั่ง Transcript ต้องมีโมเดล `scb10x/typhoon-ocr1.5-3b` ด้วย
- ฐานข้อมูล `work/lab8b_run/curriculum.db` จาก Lab 8B

ถ้ายังไม่มีฐานข้อมูล ให้กลับไปรันจากรากโปรเจกต์:

```bash
python run_lab8b.py --skip-lab7
```

หากยังไม่มีผล Lab 7B ให้รันโดยไม่ใส่ `--skip-lab7`:

```bash
python run_lab8b.py
```

## 3. เปิดโปรเจกต์และ Terminal

เปิดโฟลเดอร์ `ocr_system` ใน VS Code แล้วเลือก:

```text
Terminal > New Terminal
```

ทุกคำสั่งต่อจากนี้ให้รันใน Terminal ของ VS Code และต้องอยู่ที่รากโปรเจกต์ ซึ่งเป็นตำแหน่งเดียวกับ `pyproject.toml`

## 4. สร้าง virtual environment

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

หาก PowerShell ปฏิเสธการ activate ให้รันหนึ่งครั้ง:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

เมื่อ activate สำเร็จ จะเห็น `(.venv)` ด้านหน้าบรรทัดคำสั่ง

## 5. ติดตั้ง package

ใช้คำสั่งเดียวกันทุกระบบหลัง activate env:

```bash
python -m pip install --upgrade pip
python -m pip install -r lab10_fastapi/curriculum_app/requirements.txt
python -m pip install -r lab10_fastapi/transcript_app/requirements.txt
```

ตรวจว่า FastAPI และ Uvicorn พร้อม:

```bash
python -c "import fastapi, uvicorn; print('Lab 10 packages OK')"
```

## 6. เตรียมไฟล์ `.env`

ห้ามใส่รหัสผ่านหรือ config จริงลง source code และห้าม commit `.env`

### Windows PowerShell

```powershell
Copy-Item lab10_fastapi\curriculum_app\.env.example lab10_fastapi\curriculum_app\.env
Copy-Item lab10_fastapi\transcript_app\.env.example lab10_fastapi\transcript_app\.env
```

### macOS/Linux

```bash
cp lab10_fastapi/curriculum_app/.env.example lab10_fastapi/curriculum_app/.env
cp lab10_fastapi/transcript_app/.env.example lab10_fastapi/transcript_app/.env
```

Curriculum App ใช้ค่า:

```dotenv
CURRICULUM_DB_PATH=work/lab8b_run/curriculum.db
CURRICULUM_OLLAMA_URL=http://127.0.0.1:11434
CURRICULUM_OLLAMA_MODEL=qwen3:4b
```

Transcript App ใช้ `TRANSCRIPT_OLLAMA_URL`, `TRANSCRIPT_OCR_MODEL` และ `TRANSCRIPT_TEXT_MODEL` ใน `.env` ของตนเอง

Path ของฐานข้อมูลแบบ relative จะเริ่มจากรากโปรเจกต์

## 7. เตรียม Ollama และ Qwen

เปิด Ollama และตรวจโมเดล:

```bash
ollama list
```

หากยังไม่มี Qwen:

```bash
ollama pull qwen3:4b
ollama pull scb10x/typhoon-ocr1.5-3b
```

ทดสอบ:

```bash
ollama run qwen3:4b "ตอบคำว่า พร้อม"
```

กด `Ctrl+D` หรือพิมพ์ `/bye` เพื่อออกจากหน้าสนทนา

## 8. รัน FastAPI

### Curriculum Application

```bash
python -m uvicorn lab10_fastapi.curriculum_app.main:app --reload --host 127.0.0.1 --port 8000
```

เปิดเบราว์เซอร์:

- หน้าเว็บ: <http://127.0.0.1:8000/>
- Swagger API: <http://127.0.0.1:8000/docs>
- ตรวจสถานะ: <http://127.0.0.1:8000/api/health>

### Transcript Application

เปิด Terminal ของ VS Code อีกหน้าหนึ่ง activate `.venv` แล้วรัน:

```bash
python -m uvicorn lab10_fastapi.transcript_app.main:app --reload --host 127.0.0.1 --port 8001
```

- หน้า upload: <http://127.0.0.1:8001/>
- Swagger API: <http://127.0.0.1:8001/docs>
- ตรวจสถานะ: <http://127.0.0.1:8001/api/health>

หยุด server ด้วย `Ctrl+C`

## 9. API ที่มีให้

### Curriculum API

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/api/health` | ตรวจความพร้อมของฐานข้อมูลและ Ollama พร้อมแสดงชื่อโมเดลที่ตั้งค่าไว้ |
| GET | `/api/curricula` | อ่านรายชื่อหลักสูตรและแผนจาก config เพื่อเติมตัวเลือกหน้าเว็บ |
| GET | `/api/program` | อ่านข้อมูลหลักสูตรจากฐานข้อมูลค่าเริ่มต้น |
| GET | `/api/courses` | อ่าน/ค้นหารายวิชาด้วย `search` โดยต้องระบุ `program` และระบุ `track` สำหรับ IT, DSBA, BIT |
| GET | `/api/descriptions` | อ่านคำอธิบายรายวิชาจากรหัสวิชา 8 หลัก โดยต้องระบุ `courseid` |
| GET | `/api/study-plan` | อ่านรายวิชาตามแผนการเรียน โดยต้องระบุ `program`, `track`, `year` (1–4) และ `semester` (1–3) |
| POST | `/api/courses` | เพิ่มรายวิชาลงฐานข้อมูล SQLite ค่าเริ่มต้น โดยส่งข้อมูลรายวิชาเป็น JSON body |
| POST | `/api/ask` | รับ `question`, `program`, `track` ให้โมเดลสร้าง SQL อ่านฐานข้อมูลตามหลักสูตร/แผนที่เลือกแบบ read-only และคืน `question`, `sql`, `rows`, `answer` |

`program` รองรับ `IT`, `DSBA`, `BIT`, `AIT`; `track` ใช้ `coop` หรือ `nocoop` ตามหลักสูตร และใช้ `default` สำหรับ AIT `/api/courses` ต้องระบุ `program` เสมอ และต้องระบุ `track` สำหรับ IT, DSBA, BIT

### `GET /api/curricula` — รายการหลักสูตรและแผน

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

### Transcript API

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/api/health` | ตรวจ config ของ Transcript App |
| POST | `/api/transcript/extract` | อัปโหลดและสกัด Transcript |

ทดลอง GET:

```text
http://127.0.0.1:8000/api/courses?program=IT&track=nocoop&search=06026200
```

ทดลอง POST แนะนำให้เปิด `/docs`, เลือก endpoint แล้วกด **Try it out**

ตัวอย่าง body ของ `/api/ask`:

```json
{
  "question": "ปี 1 เทอม 1 เรียนกี่หน่วยกิต",
  "program": "DSBA",
  "track": "nocoop"
}
```

### การเลือกฐานข้อมูลของ `/api/ask`

ระบบเลือกฐานข้อมูลจาก `program` และ `track` ที่ส่งมาใน request ซึ่งหน้าเว็บส่งจากตัวเลือกหลักสูตรและแผนการเรียน โดยใช้ `settings.db_paths` ใน `config.py` (โฟลเดอร์ฐานข้อมูลกำหนดด้วย `CURRICULUM_DB_ROOT`)

| program | track | ไฟล์ภายใต้ DB_ROOT |
|---|---|---|
| `IT`, `DSBA`, `BIT` | `coop` หรือ `nocoop` | `<program>/<track>/curriculum.db` |
| `AIT` | `default` | `AIT/curriculum.db` |

ต้องระบุ `program` ทุกครั้ง ส่วน IT, DSBA และ BIT ต้องระบุ `track` ด้วย สำหรับ AIT สามารถส่ง `"track": "default"` หรือละ `track` เพื่อใช้แผนเดียวที่มีได้ หากไม่ส่งค่าที่จำเป็นหรือส่งหลักสูตร/แผนที่ไม่รองรับ ระบบตอบ HTTP `422`

ตัวอย่างข้างต้นใช้ DSBA แผน nocoop ถ้าเปลี่ยนเป็น `"program": "IT", "track": "coop"` จะค้นจาก IT แผน coop โดยค่าเริ่มต้น `settings.db_path` ไม่ทับตัวเลือกนี้ ข้อความใน `question` ไม่ได้เปลี่ยนฐานข้อมูลอัตโนมัติ เช่น เลือก IT แต่พิมพ์ถาม DSBA ระบบยังค้นจาก IT และปัจจุบันยังไม่ตรวจความขัดแย้งนี้

`/api/ask` คืน `question`, `sql`, `rows` และ `answer` เหมือนเดิม โดย SQL ยังผ่าน `guard_sql` และอ่านฐานข้อมูลแบบ read-only

ตัวอย่าง body ของ `/api/courses`:

```json
{
  "code": "99999999",
  "name_th": "วิชาทดลอง API",
  "name_en": "API TEST COURSE",
  "credits": 3,
  "lecture_h": 3,
  "lab_h": 0,
  "self_h": 6,
  "description_th": "ข้อมูลตัวอย่างสำหรับทดสอบ POST"
}
```

> POST `/api/courses` เขียนลง DB จริง ควรใช้รหัสทดลองที่ลบออกภายหลัง หรือใช้สำเนา DB สำหรับการสาธิต

## 10. จุดเปลี่ยนโมเดลของนักศึกษา

เปิด `curriculum_app/model_service.py` แล้วค้นหา:

```text
MODEL INTEGRATION POINT
```

ฟังก์ชันที่ต้องเปลี่ยนคือ:

```python
QwenTextToSQL._chat()
```

จากนั้นแก้ `_chat()` ให้เรียกฟังก์ชัน inference ของโมเดลและคืน Python `dict` รูปแบบเดิม ส่วน FastAPI, SQLite และ frontend ไม่ต้องแก้ ส่วน Transcript App ใช้โมเดลผ่าน `lab8a_denoise.py` และ `lab7a_transcript.py` โดยตรง

## 11. ลำดับการทำงานของ `/api/ask`

1. `index.html` ส่ง `POST /api/ask` พร้อม `question`, `program` และ `track`
2. FastAPI ตรวจ request ด้วย Pydantic และเลือกฐานข้อมูลด้วย `select_database(program, track)`
3. Qwen สร้าง `SELECT` SQL
4. `database.py` ปฏิเสธ SQL ที่แก้ข้อมูล
5. เปิด SQLite แบบ read-only แล้วรัน query
6. Qwen สรุป rows เป็นคำตอบภาษาไทย
7. FastAPI ส่ง JSON กลับหน้าเว็บ

## 12. ปัญหาที่พบบ่อย

### `No module named fastapi`

ยังไม่ได้ activate env หรือติดตั้ง requirements:

```bash
python -m pip install -r lab10_fastapi/curriculum_app/requirements.txt
python -m pip install -r lab10_fastapi/transcript_app/requirements.txt
```

### `ไม่พบฐานข้อมูล`

ตรวจ `CURRICULUM_DB_PATH` ใน `curriculum_app/.env` และสร้าง DB จาก Lab 8B ก่อน

### `ติดต่อ Ollama ไม่ได้`

เปิด Ollama แล้วตรวจ:

```bash
ollama list
```

### เปิดหน้าเว็บได้แต่ถามไม่ได้

เปิด `/api/health` แล้วดูว่า `database_ready` และ `ollama_ready` เป็น `true` หรือไม่
