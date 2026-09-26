# Curriculum Application

แอปนี้รับคำถาม → ให้ Qwen สร้าง SQL → อ่าน SQLite → ส่งกลับทั้งคำตอบ, SQL และ rows

## เอาไฟล์ไปวางที่ไหน

วางโฟลเดอร์ `curriculum_app` ไว้ภายใน `ocr_system/lab10_fastapi/` และรักษาโครงสร้างนี้:

```text
ocr_system/
├── lab10_fastapi/
│   ├── __init__.py
│   └── curriculum_app/       ← ไฟล์ Lab 10 ของกลุ่มนี้
├── src/ocr_system/
│   └── lab8b_curriculum_db.py ← โค้ด Lab 8B
└── work/lab8b_run/
    └── curriculum.db            ← ฐานข้อมูล
```

ห้ามย้าย `main.py` ออกจาก `curriculum_app` และให้รันคำสั่งจากโฟลเดอร์ `ocr_system`

ให้รันจากรากโปรเจกต์ `ocr_system` ใน VS Code Terminal:

```bash
python -m pip install -r lab10_fastapi/curriculum_app/requirements.txt
ollama pull qwen3:4b
python -m uvicorn lab10_fastapi.curriculum_app.main:app --reload --port 8000
```

เปิด <http://127.0.0.1:8000/> หรือ <http://127.0.0.1:8000/docs>

ก่อนรันต้องมี:

- `lab10_fastapi/curriculum_app/.env`
- `work/lab8b_run/curriculum.db`
- `src/ocr_system/lab8b_curriculum_db.py`

ถ้าแจกเฉพาะกลุ่ม Curriculum ให้ก็อปโฟลเดอร์นี้ พร้อม Lab 8B และไฟล์ DB ตามตำแหน่งข้างต้น

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