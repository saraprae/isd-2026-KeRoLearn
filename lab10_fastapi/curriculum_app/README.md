# Curriculum Application

แอปนี้รับคำถาม → ตรวจ cache และกฎ → ให้ Qwen เลือก intent/คำค้นเมื่อจำเป็น → โค้ดสร้าง SQL → อ่าน SQLite → สร้างคำตอบภาษาไทยจาก rows

ดู [handoff หลักของ Lab 10 / Lab 11](HANDOFF.md) สำหรับหน้าที่ฟังก์ชันรายไฟล์ ตารางเปรียบเทียบ Model 1 / Model 2 โฟลว Prompt/cache หน่วยกิตบางส่วน เลขหน้าอ้างอิง เวลาแยกขั้น กฎไทย JSONL logging และผลตรวจล่าสุด

Handoff รวมไว้ไฟล์เดียวแล้ว พร้อมรายการไฟล์ชั่วคราวที่ลบ ระบบยังแสดงยอดหน่วยกิตที่ระบุพร้อมหมายเหตุข้อมูลขาด และส่ง `citations`, `processing_ms`, `performance` เพิ่มจากสี่ฟิลด์หลักเดิม

พิมพ์เปรียบเทียบ **2 หลักสูตร** ได้โดยตรง เช่น `เปรียบเทียบหน่วยกิตรวมและจำนวนปี IT กับ DSBA` ระบบใช้กฎและ SQL เดิม อ่าน `program` ฐานละหนึ่งครั้งโดยไม่เรียก Qwen และใช้ cache ที่ตรวจ revision ของทั้งสองฐาน ชื่อในคำถามกำหนดหลักสูตรที่เทียบ; แผนใช้จากคำถามหรือฟอร์ม และแผนเดียวเลือกให้อัตโนมัติพร้อมแสดงในคำตอบ

รหัสหลักสูตร/แผนมาจาก `Settings.db_paths` เช่นเดียวกับ `/api/curricula` ชื่อเต็มอ่านจาก metadata; ชื่อเรียกกำหนดรวมใน `PROGRAM_ALIASES` หรือ JSON `CURRICULUM_PROGRAM_ALIASES` ใน `.env` ตัวอย่างอยู่ใน `.env.example` ไม่รองรับการเทียบรายวิชา ค่าเทอม หรือยอดรายปี/เทอมข้ามหลักสูตรในรอบนี้

## เอาไฟล์ไปวางที่ไหน

วางโฟลเดอร์ `curriculum_app` ไว้ภายใน `lab10_fastapi/` ของรากโปรเจกต์ และรักษาโครงสร้างนี้:

```text
isd-2026-KeRoLearn/
├── lab10_fastapi/
│   ├── __init__.py
│   └── curriculum_app/       ← ไฟล์ Lab 10 ของกลุ่มนี้
├── src/ocr_system/
│   └── lab8b_curriculum_db.py ← โค้ด Lab 8B
└── work/lab8b_run/
    ├── DSBA/nocoop/curriculum.db ← ฐานเริ่มต้น
    └── ...                      ← ฐานหลักสูตร/แผนอื่นตาม Settings.db_paths
```

ห้ามย้าย `main.py` ออกจาก `curriculum_app` และให้รันคำสั่งจากรากโปรเจกต์

คัดลอก `.env.example` เป็น `.env` ในโฟลเดอร์เดียวกันแล้วปรับค่าเครื่องที่ใช้งาน ไฟล์ `.env` เป็นค่าของแต่ละเครื่องและไม่อยู่ใน Git จากนั้นรันจากรากโปรเจกต์ใน VS Code Terminal:

```bash
python -m pip install -r lab10_fastapi/curriculum_app/requirements.txt
ollama pull qwen3:4b
python -m uvicorn lab10_fastapi.curriculum_app.main:app --reload --port 8000
```

เปิด <http://127.0.0.1:8000/> หรือ <http://127.0.0.1:8000/docs>

ส่วนจับเวลาอยู่ใน `database.py` และทั้ง planner/SQLite ใช้ context เดียวกัน ส่วน `main.py` เปิด/ปิด JSONL logging ผ่าน lifespan โดยอ่าน Settings จาก `config.py`

หากต้องการบันทึก logs ข้าม restart ให้ตั้งค่าใน `lab10_fastapi/curriculum_app/.env` แล้วเริ่ม server ใหม่ด้วยคำสั่งเดิม:

```dotenv
CURRICULUM_LOG_ENABLED=true
CURRICULUM_LOG_DIR=work
```

ค่าเริ่มต้น `CURRICULUM_LOG_ENABLED=false` ปิดเฉพาะการเขียนไฟล์ เวลาแยกขั้นใน API และ snapshots ใน memory ยังทำงาน Relative path ของ log directory อิงรากโปรเจกต์; ใช้ absolute path ได้

ระบบบันทึก `lab10_planner.jsonl` และ `lab10_performance.jsonl` ใน log directory หมุนเมื่อถึง 1 MiB และเก็บย้อนหลังสองไฟล์ Logging config รวมใน Python แล้ว จึงใช้คำสั่ง Uvicorn ปกติตามด้านบน

ก่อนรันต้องมี:

- `lab10_fastapi/curriculum_app/.env`
- `work/lab8b_run/DSBA/nocoop/curriculum.db` และฐานอื่นตาม `Settings.db_paths`
- `src/ocr_system/lab8b_curriculum_db.py`

ถ้าแจกเฉพาะกลุ่ม Curriculum ให้ก็อปโฟลเดอร์นี้ พร้อม Lab 8B และไฟล์ DB ตามตำแหน่งข้างต้น

## คำถามที่พบบ่อย

### เปิดเว็บแล้วขึ้น `ERR_CONNECTION_REFUSED`

FastAPI ยังไม่ได้รัน ให้รันคำสั่ง Uvicorn ด้านบนและเปิด Terminal ค้างไว้

### ขึ้น `No module named fastapi`

ยังไม่ได้ activate venv หรือยังไม่ได้ติดตั้ง `requirements.txt`

### ขึ้น `ไม่พบฐานข้อมูล`

ตรวจว่ามี `work/lab8b_run/DSBA/nocoop/curriculum.db` หรือ path ที่ตั้งใน `CURRICULUM_DB_PATH` และตรวจ mapping ของหลักสูตร/แผนใน `Settings.db_paths`

### เปิดหน้าเว็บได้แต่ถามไม่ได้

เปิด `/api/health` แล้วตรวจว่า `database_ready` และ `ollama_ready` เป็น `true`

Endpoint `/api/ask` อ่านฐานข้อมูลที่ Lab 8B สร้างไว้ ไม่ได้ทำ OCR หรืออ่าน PDF ใหม่ทุกคำถาม การสร้างหรืออัปเดตฐานข้อมูลใช้ `python run_lab8b.py`; ใช้ `--skip-lab7` เมื่อต้องการนำผล OCR เดิมมาสร้างฐานข้อมูลใหม่
