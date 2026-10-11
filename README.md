# KeRoLearn — ถามตอบเรื่องหลักสูตรด้วย OCR + ภาษาไทย

DSBA8 – LLM Course (isd-2026-KeRoLearn)
โปรเจกต์ P2: OCR เล่มหลักสูตร เพื่อตอบคำถามเกี่ยวกับการเรียน

**สมาชิก**
1. 67070048 (discord: orayaraaYAHH)
2. 67070188 (discord: rubii)
3. 67070219 (discord: y4ngqin)
4. 67070258 (discord: namjimgai)

---

## 1. โปรเจกต์นี้คืออะไร

เล่มหลักสูตรของมหาวิทยาลัยเป็นไฟล์ PDF ยาวหลายสิบหน้า การหาคำตอบอย่าง "วิชานี้กี่หน่วยกิต" หรือ "เทอม 2 ปี 1 ต้องเรียนอะไรบ้าง" ต้องเปิดอ่านเอง

โปรเจกต์นี้ทำให้ถามเป็นภาษาไทยได้เลย (ตัวอย่างจริงที่รันบนเครื่องนี้ กับฐาน `work/lab8b_run/IT/nocoop/curriculum.db`):

```
คำถาม: หลักสูตรนี้มีทั้งหมดกี่หน่วยกิต
SQL:    SELECT total_credits FROM program
คำตอบ: 129
```

ถ้าในเล่มไม่มีข้อมูลนั้น ระบบจะตอบว่า **"ไม่พบข้อมูลนี้ในเล่มหลักสูตร"** แทนการเดา

### ระบบทำงานอย่างไร (ภาพรวมสั้น ๆ)

1. **อ่าน PDF ด้วย OCR** — แปลงแต่ละหน้าเป็นภาพ แล้วให้โมเดลอ่านตัวอักษรออกมาเป็นข้อความ
2. **จัดข้อความให้เป็นข้อมูลมีโครงสร้าง** — ดึงรายวิชา รหัสวิชา หน่วยกิต เทอม และเลขหน้า
3. **เก็บลงฐานข้อมูล** — เพื่อให้ค้นหาได้แม่นยำ
4. **ตอบคำถาม** — โมเดลแปลงคำถามเป็นคำสั่งค้นฐานข้อมูล แล้วสรุปคำตอบจากแถวที่ค้นเจอจริง พร้อมเลขหน้า

ทุกอย่างรันบนเครื่องของคุณเอง ไม่ต้องใช้อินเทอร์เน็ตหลังติดตั้งโมเดลแล้ว

### ศัพท์ที่จะเจอในเอกสารนี้

| คำ | ความหมาย |
|---|---|
| **OCR** | เทคโนโลยีอ่านตัวอักษรจากภาพ |
| **Ollama** | โปรแกรมที่รันโมเดล AI บนเครื่องเรา |
| **Typhoon-OCR** | โมเดลที่ใช้อ่านภาษาไทยจากภาพ (ดาวน์โหลดผ่าน Ollama) |
| **qwen3:4b** | โมเดลที่ใช้เข้าใจคำถามและสรุปคำตอบ |
| **SQLite** | ฐานข้อมูลแบบไฟล์เดียว (`curriculum.db`) ไม่ต้องติดตั้งเซิร์ฟเวอร์ |
| **run_id** | ชื่อชุดข้อมูลหนึ่งชุด เช่น `IT`, `DSBA_2560` (ตรงกับชื่อไฟล์ PDF) |
| **coop / nocoop** | แผนการเรียนแบบมี / ไม่มีสหกิจศึกษา (บางหลักสูตรมีสองแผน) |
| **ground truth (เฉลย)** | ข้อมูลที่คนตรวจแล้วว่าถูก ใช้วัดว่าระบบอ่านผิดมากแค่ไหน |

---

## 2. ติดตั้งและเตรียมเครื่อง (ทำครั้งเดียว)

ทำตามลำดับตั้งแต่ 2.1 ถึง 2.6 ทุกคำสั่งพิมพ์ใน Terminal (Windows: PowerShell, macOS/Linux: Terminal, หรือ Terminal ใน VS Code ผ่านเมนู `Terminal > New Terminal`)

### 2.0 เปิดคอมใหม่ทุกครั้ง ต้องทำอะไรบ้าง (เช็กลิสต์)

ติดตั้งครั้งแรกทำ 2.1–2.6 ให้ครบก่อน หลังจากนั้นทุกครั้งที่ปิดคอมแล้วเปิดใหม่ แค่ 4 ขั้นนี้:

1. เปิด Terminal ในโฟลเดอร์โปรเจกต์ (root ที่มีไฟล์ `run_lab8b.py` กับ `requirements.txt`)
2. เปิด venv ใหม่ (ดู 2.3 — สร้างแค่ครั้งแรก แต่ **activate ใหม่ทุกครั้ง**) แล้วเช็กว่าเห็น `(venv)` นำหน้า
3. เปิด Ollama ค้างไว้ แล้วรัน `ollama list` ต้องเห็น `qwen3:4b` กับ `scb10x/typhoon-ocr1.5-3b` (ดู 2.5)
4. เลือกทางใดทางหนึ่ง:
   - ถามเลยจากผลเดิม → หัวข้อ 3 (ไม่ต้องมี PDF)
   - รันใหม่ตั้งแต่ PDF → หัวข้อ 4 (ต้องมี PDF ใน `data/input/`, ดู 2.6)

> Windows: ถ้าโปรแกรมพิมพ์ภาษาไทยแล้ว error เรื่อง encoding (เช่นตอนรัน `--help`) ให้รัน `$env:PYTHONUTF8=1` ใน Terminal นั้นก่อน แล้วรันคำสั่งใหม่

### 2.1 ตรวจว่ามี Python 3.12

```bash
python --version
```

- ควรขึ้น `Python 3.12.x` (เครื่องนี้ใช้ `Python 3.12.8`)
- ถ้า Windows ขึ้น error ให้ลอง `py --version`
- ถ้า macOS/Linux ขึ้น error ให้ลอง `python3 --version`
- ถ้ายังไม่มี ให้ติดตั้งจาก https://www.python.org/downloads/ (Windows: ติ๊ก **Add python.exe to PATH** ตอนติดตั้ง) แล้วเปิด Terminal ใหม่

> จากนี้ไป ถ้าเครื่องคุณต้องใช้ `py` หรือ `python3` แทน `python` ให้แทนที่ทุกคำสั่ง

### 2.2 ดาวน์โหลดโปรเจกต์

```bash
git clone <TODO: ใส่ URL ของ repo>
cd isd-2026-KeRoLearn
```

ถ้าไม่มี git ให้กดปุ่ม **Code > Download ZIP** บน GitHub แล้วแตกไฟล์ จากนั้นเปิด Terminal ในโฟลเดอร์ที่แตกออกมา

เช็กว่าอยู่ถูกที่ โฟลเดอร์ปัจจุบันต้องมีไฟล์ `run_lab8b.py` และ `requirements.txt`:

```bash
ls              # macOS / Linux
dir             # Windows
```

> **ทุกคำสั่งต่อจากนี้ต้องรันจากโฟลเดอร์นี้ (root ของโปรเจกต์)**

### 2.3 สร้างและเปิดใช้ Virtual Environment (venv)

**venv คืออะไร:** พื้นที่แยกสำหรับติดตั้ง package ของโปรเจกต์นี้โดยเฉพาะ เพื่อไม่ให้ไปชนกับโปรเจกต์อื่นหรือ Python หลักของเครื่อง

**สร้าง** (ทำครั้งเดียว จะได้โฟลเดอร์ใหม่ชื่อ `venv`):

```bash
python -m venv venv
```

**เปิดใช้งาน (activate):**

| ระบบ | คำสั่ง |
|---|---|
| Windows PowerShell | `.\venv\Scripts\Activate.ps1` |
| Windows CMD | `venv\Scripts\activate.bat` |
| macOS / Linux | `source venv/bin/activate` |

**วิธีเช็กว่าสำเร็จ:** จะเห็น `(venv)` นำหน้าบรรทัดใน Terminal เช่น

```
(venv) C:\...\isd-2026-KeRoLearn>
```

**ข้อควรจำ**
- ต้อง activate ใหม่ **ทุกครั้งที่เปิด Terminal ใหม่** (สร้างแค่ครั้งเดียว แต่ activate ทุกครั้ง)
- ถ้าไม่ได้ activate แล้วรันโปรเจกต์ จะเจอ `ModuleNotFoundError` ทั้งที่ติดตั้ง package ไปแล้ว
- ถ้า PowerShell ขึ้น error เรื่อง policy ให้รันคำสั่งนี้ครั้งเดียว แล้ว activate ใหม่:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```
- ออกจาก venv: พิมพ์ `deactivate`

### 2.4 ติดตั้ง Python packages ด้วย pip

ตรวจก่อนว่า `(venv)` ขึ้นอยู่ (ถ้าไม่ขึ้น กลับไปทำ 2.3) แล้วรัน:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

- ชื่อไฟล์ที่ถูกต้องคือ **`requirements.txt`** (มีตัว s ท้าย requirements)
- `-r` แปลว่า "อ่านรายชื่อ package จากไฟล์นี้" ใช้เวลาสักครู่ เพราะต้องดาวน์โหลดหลายตัว
- ในไฟล์มีครบทุกขั้นแล้ว: ของขั้น OCR (`pymupdf`, `pillow`, `pdfplumber`, `numpy`, `opencv-python`, `pytesseract`), ของขั้นวัดผลภาษาไทย (`pythainlp` ใช้ตัดคำแบบ newmm ให้ค่า WER แม่นขึ้น), และของขั้นฐานข้อมูล/ถามตอบ (`requests`, `pydantic>=2`) — ติดตั้งรอบเดียวใช้ได้ทุกขั้น ไม่ต้องติดตั้งอะไรเพิ่ม

**วิธีเช็กว่าติดตั้งสำเร็จ:**

```bash
python -c "import fitz, PIL, requests, pydantic, pdfplumber, pythainlp, numpy, cv2, pytesseract; print('OK', pydantic.VERSION)"
```

ควรขึ้น `OK 2.x.x` (เลขต้นต้องเป็น 2 ขึ้นไป)

**โปรแกรม Tesseract OCR (ไม่บังคับ):** จำเป็นเฉพาะ pipeline baseline เปรียบเทียบ ขั้นหลัก (`-p vlm`) ไม่ใช้ ถ้าไม่มีเครื่องจะข้าม baseline ไปเอง เครื่องนี้มี `tesseract v5.5.3` อยู่แล้ว

**ถ้าติดตั้งไม่ผ่าน**
- `pip is not recognized` / `pip: command not found` → ใช้ `python -m pip install -r requirements.txt` แทน
- ขึ้น error เรื่อง `No such file or directory: 'requirements.txt'` → ยังไม่ได้อยู่ใน root ของโปรเจกต์ (กลับไปเช็ก 2.2)
- ขึ้น error ตอน build package → ตรวจว่าใช้ Python 3.12 (ดู 2.1) เพราะ package บางตัวอาจยังไม่รองรับ Python เวอร์ชันใหม่กว่านั้น

### 2.5 ติดตั้ง Ollama และดาวน์โหลดโมเดล

1. ติดตั้ง Ollama จาก https://ollama.com แล้วเปิดโปรแกรมค้างไว้ตลอดเวลาที่ใช้งาน
2. ดาวน์โหลดโมเดล:

```bash
ollama pull qwen3:4b                        # โมเดลถามตอบ (จำเป็นทุกกรณี)
ollama pull scb10x/typhoon-ocr1.5-3b        # โมเดล OCR (จำเป็นเมื่อรัน OCR จาก PDF)
```

3. เช็กว่าโมเดลมาครบ:

```bash
ollama list
```

ควรเห็นทั้ง `qwen3:4b` และ `scb10x/typhoon-ocr1.5-3b` (ไฟล์โมเดลมีขนาดหลาย GB ควรเชื่อมเน็ตให้เสถียร — เครื่องนี้มีขนาด 2.5 GB กับ 3.2 GB ตามลำดับ)

ถ้าคำสั่ง `ollama` ต่อไม่ติด (connection refused) แปลว่าโปรแกรม Ollama ยังไม่เปิด: เปิดโปรแกรม Ollama (หรือรัน `ollama serve` ในอีกหน้าต่างหนึ่ง) ค้างไว้ก่อน แล้วรัน `ollama list` ใหม่

ตัวแปรสภาพแวดล้อม (ตั้งเฉพาะเมื่อ Ollama ไม่ได้อยู่ที่ค่าเริ่มต้น):
- `OLLAMA_HOST` — ฝั่ง 7B บังคับให้เป็น localhost เท่านั้น (ทำงานออฟไลน์)
- `LAB8_OLLAMA_URL` — ที่อยู่ Ollama ที่ฝั่ง 8B ใช้

### 2.6 วางไฟล์ PDF (เฉพาะเมื่อจะรัน OCR เอง)

ไฟล์ PDF เล่มหลักสูตร **ไม่ได้อยู่ใน repo** (ถูกตั้งเป็น ignore) ดาวน์โหลดได้จาก `<TODO: ใส่ลิงก์ Google Drive ที่มี PDF>` แล้ววางที่ `data/input/` โดยตั้งชื่อตาม run_id:

```
data/input/
  IT.pdf  DSBA.pdf  BIT.pdf  AIT.pdf  GENED.pdf
  IT_2560.pdf  DSBA_2560.pdf  BIT_2560.pdf  GENED_2559.pdf  GENED_2564.pdf
```

ไฟล์ PDF **ไม่ได้อยู่ใน repo** (ถูก ignore ไว้ใน `.gitignore` ด้วยกฎ `data/input/*.pdf`) เช็กของจริงบนเครื่องด้วย `dir data\input` (Windows) หรือ `ls data/input` (macOS/Linux) — รอบไหนไม่มี PDF รอบนั้นจะถูกข้ามและนับเป็นล้มเหลวในสรุปท้าย (ดูหัวข้อ 4)

ไฟล์เฉลย (ไม่บังคับ) อยู่ใน `data/ground_truth/` แล้ว เช่น `IT_academic_plan_no_coop.json`

> ถ้าแค่อยากลองถามตอบ ไม่ต้องทำข้อ 2.6 ไปที่หัวข้อ 3 ได้เลย

---

## 3. ลองถามคำถาม (ใช้ผลที่รันไว้แล้ว ไม่ต้อง OCR ใหม่)

โฟลเดอร์ `work/` **ไม่อยู่ใน repo** เป็นผลที่สร้างบนเครื่องตอนรันตามหัวข้อ 4 (บนเครื่องนี้มีอยู่แล้วเพราะรันไว้ก่อน) ถ้าโคลนใหม่แล้ว `work/` ยังว่าง ให้ทำหัวข้อ 4 ก่อน แล้วค่อยกลับมาข้อนี้

เมื่อมี `work/` แล้ว (ทำ 2.1–2.5 เปิด Ollama ค้างไว้ และ activate venv แล้ว) ก็ลองถามได้ทันทีโดยไม่ต้อง OCR ใหม่:

```bash
python src/ocr_system/lab8b_curriculum_db.py ask -d work/lab8b_run/IT/nocoop/curriculum.db -q "<คำถามภาษาไทย>"
```

ตัวอย่างที่รันได้จริงบนเครื่องนี้:

```bash
python src/ocr_system/lab8b_curriculum_db.py ask -d work/lab8b_run/IT/nocoop/curriculum.db -q "หลักสูตรนี้มีทั้งหมดกี่หน่วยกิต"
```

> Windows: ถ้าข้อความไทยแสดงผลเพี้ยนหรือ error เรื่อง encoding ให้รัน `$env:PYTHONUTF8=1` ก่อน แล้วรันคำสั่งใหม่

ระบบจะสร้างคำสั่ง SQL แบบอ่านอย่างเดียว แล้วสรุปคำตอบพร้อมเลขหน้าอ้างอิงจากแถวที่ค้นเจอจริง ถ้าไม่พบแถวใดจะตอบว่า **"ไม่พบข้อมูลนี้ในเล่มหลักสูตร"** โดยไม่ให้โมเดลเดาคำตอบ

หลักสูตรอื่นเปลี่ยนที่ `-d` เช่น `work/lab8b_run/<run_id>/<nocoop|coop>/curriculum.db` (AIT และ GENED ไม่แยกแผน ใช้ `work/lab8b_run/<run_id>/curriculum.db`)

---

## 4. รันทั้งระบบตั้งแต่ PDF (OCR เอง)

ต้องทำ 2.1–2.6 ครบ เปิด Ollama ค้างไว้ และ activate venv แล้ว รันจาก root ของโปรเจกต์:

**ขั้นที่ 1 — ดูก่อนว่าจะรันอะไรบ้าง (ยังไม่ทำจริง)**
```bash
python run_lab8b.py --all-runs --gt-dir data/ground_truth --dry-run
```

**ขั้นที่ 2 — ทดลองรันหลักสูตรเดียวก่อน**
```bash
python run_lab8b.py --run IT --gt-dir data/ground_truth
```

**ขั้นที่ 3 — รันครบทั้ง 10 ชุด**
```bash
python run_lab8b.py --all-runs --gt-dir data/ground_truth
```

**ขั้นที่ 4 — เปิดดูผลจริง** (ดูหัวข้อ 5) อย่าดูแค่เครื่องหมาย ✓ ท้ายโปรแกรม

ตัวเลือกที่ควรรู้:

| ตัวเลือก | ความหมาย |
|---|---|
| `--gt-dir data/ground_truth` | **ควรใส่เสมอ** ถ้าไม่ใส่ จะไม่มีผลเทียบกับเฉลย |
| `--run <run_id>` | รันเฉพาะหลักสูตรเดียว |
| `--all-runs` | รันครบ 10 ชุด (ชุดที่ไม่มี PDF จะถูกข้ามและนับเป็นล้มเหลวในสรุปท้าย) |
| `--skip-lab7` | ข้ามขั้น OCR ใช้ผล OCR เดิมที่มีอยู่แล้ว |
| `--dry-run` | แสดงคำสั่งโดยไม่รันจริง |

OCR ทำทีละหน้าด้วยโมเดลในเครื่อง จึงใช้เวลานาน (ดูตารางเวลาในหัวข้อ 6) แนะนำให้ลองหลักสูตรเดียวก่อน

### ลองกับเล่มเวอร์ชันอื่นโดยทำเฉลยเอง

เฉลยมีไว้เทียบคะแนนเท่านั้น — **ไม่มีเฉลยก็รันได้** ขั้น 7B จะข้ามการเทียบเฉลย ขั้น 8B จะข้าม eval-gt แต่ยังได้ DB, verify และถามตอบตามปกติ ถ้าจะทำเฉลยเองสำหรับเล่มเวอร์ชันอื่น:

1. สร้างไฟล์ JSON ใน `data/ground_truth/` ตั้งชื่อตามโปรแกรม เช่น `IT_academic_plan_coop.json` กับ `IT_academic_plan_no_coop.json` (โปรแกรมแผนเดียว เช่น AIT ใช้ `AIT_academic_plan.json`) — โปรแกรมจับคู่จากต้นชื่อไฟล์เอง ไม่สนตัวพิมพ์เล็ก-ใหญ่
2. โครงไฟล์ (ตัวอย่าง 1 วิชา ค่า `plan` ใช้ `coop` / `no_coop`):
```json
{
  "program": "IT",
  "plan": "coop",
  "courses": [
    {"code": "06016401", "name_th": "...", "name_en": "...",
     "credits": "3(3-0-6)", "year": "1", "semester": "1",
     "category": "หมวดวิชาเฉพาะ", "type": "บังคับ", "prerequisite": "ไม่มี"}
  ]
}
```
3. รันตามปกติพร้อม `--gt-dir data/ground_truth` — ขั้น 7B จะรวมเฉลย coop+nocoop ให้ตอนเทียบ ส่วนขั้น 8B จะแยกเทียบทีละแผนให้เอง

### ภายในการรันทำอะไรบ้าง

คำสั่ง `run_lab8b.py` ควบคุมสองขั้นต่อเนื่องกัน:

```
PDF ──► ขั้น 7B  (src/ocr_system/lab7b_curriculum.py)
        เรนเดอร์ภาพ 150 DPI → ลบลายน้ำจาง → Typhoon-OCR ทีละหน้า
        → intermediate_vlm.md → สกัดตารางด้วยกฎ → pred_vlm.json
        → เทียบเฉลย (ถ้ามี): Precision/Recall/F1, CER, WER
   │
   ▼
        ขั้น 8B  (src/ocr_system/lab8b_curriculum_db.py)
        import-lab7b → curriculum.json → load (SQLite)
        → verify (CHK1-7) → eval-gt → eval (ถามตอบ)
```

- **import-lab7b** หาช่วงหน้าของแผนสหกิจ/ไม่สหกิจจากหัวข้อภาษาไทยใน OCR แล้วจัดแต่ละวิชาเข้าแผนตามเลขหน้า
- **CER / WER** คืออัตราผิดระดับตัวอักษร / ระดับคำ ยิ่งต่ำยิ่งดี

## 5. ผลลัพธ์อยู่ที่ไหน และอ่านอย่างไร

```
work/lab7b_run/<run_id>/
    intermediate_vlm.md       ผล OCR เป็น Markdown (มีเครื่องหมาย <!-- PDF_PAGE N -->)
    pred_vlm.json             ข้อมูลหลักสูตรที่สกัดได้ พร้อมเลขหน้าของแต่ละวิชา
    evaluation.json           ผลเทียบเฉลย (เมื่อใส่ --gt-dir)
    comparison.csv            ตารางเทียบ (เมื่อใส่ --gt-dir)

work/lab8b_run/<run_id>/{nocoop,coop}/
    curriculum.json           ข้อมูลหลักสูตรของแผนนั้น
    curriculum.db             ฐานข้อมูล SQLite
    verify.json               ผลตรวจความสอดคล้อง CHK1-7
    eval_gt.json              ผลเทียบเฉลย (เมื่อมีเฉลย)
    eval_result.json          ผลถามตอบจากชุดคำถาม (เมื่อมีคำถามครบ 30 ข้อ)
```

AIT และ GENED ไม่แยกแผน ไฟล์อยู่ใน `work/lab8b_run/<run_id>/` โดยตรง

**ถ้าอยากรู้ว่าผลรันดีหรือไม่ ให้เปิดดู `verify.json` และ `eval_result.json`** อย่าดูแค่เครื่องหมาย ✓ ในสรุปท้ายของ `run_lab8b.py` (ดูหัวข้อข้อจำกัด)

### verify (CHK1-7) ตรวจอะไร

1. หน่วยกิตรวมตรงกับที่ประกาศในเล่ม
2. ทุกรหัสในแผนมีคำอธิบายวิชา
3. รหัสวิชามี 8 หลัก
4. หน่วยกิตในแผนตรงกับในรายวิชา
5. วิชาบังคับก่อนอยู่ในเทอมก่อนหน้า
6. ไม่มีวิชาซ้ำในเทอมเดียวกัน
7. หน่วยกิตต่อเทอมอยู่ในช่วง 9–22

### eval (ถามตอบ) ให้คะแนนอย่างไร

ชุดคำถามอยู่ใน `work/lab8b_run/<run_id>/<nocoop|coop>/` รูปแบบ:
```json
{"question": "...", "expect": {"type": "value | set | count | none", "value": "..."}}
```
`run_lab8b.py` จะรัน eval เมื่อมีคำถามอย่างน้อย 30 ข้อ คะแนนดูจากผลลัพธ์ของ SQL ไม่ใช่ข้อความคำตอบ:

| type | ผ่านเมื่อ |
|---|---|
| `value` | ค่าที่คาดอยู่ในเซลล์ใดก็ได้ของผลลัพธ์ |
| `set` | ค่าที่คาดทุกตัวอยู่ในผลลัพธ์ (แถวเกินไม่ถือว่าผิด) |
| `count` | จำนวนแถวเท่ากัน |
| `none` | ต้องไม่มีแถวเลย |

---

## 6. ระยะเวลาในการรันของแต่ละขั้นตอน

เวลาขึ้นกับเครื่อง (CPU/GPU, RAM) และจำนวนหน้าของเล่ม ตารางนี้วัดจากเครื่อง: `<TODO: ระบุสเปกเครื่อง>` ด้วยหลักสูตร `<TODO: เช่น IT>` จำนวน `<TODO>` หน้า

| ขั้นตอน | เครื่องมือ / โมเดล | เวลา |
|---|---|---|
| เรนเดอร์ PDF เป็นภาพ 150 DPI | PyMuPDF | `<TODO>` |
| ลบลายน้ำ | Pillow | `<TODO>` |
| OCR ทีละหน้า | Typhoon-OCR (Ollama) | `<TODO>` (ต่อหน้า: `<TODO>`) |
| สกัดตารางด้วยกฎ → `pred_vlm.json` | Python (rules) | `<TODO>` |
| เทียบเฉลย (Precision/Recall/F1, CER, WER) | Python (+ pythainlp) | `<TODO>` |
| import-lab7b → `curriculum.json` | Python | `<TODO>` |
| load → SQLite | sqlite3 | `<TODO>` |
| verify (CHK1-7) | Python | `<TODO>` |
| eval-gt | Python | `<TODO>` |
| eval ถามตอบ (30 ข้อ) | qwen3:4b (Ollama) | `<TODO>` (ต่อข้อ: `<TODO>`) |
| ถามตอบ 1 คำถาม (`ask`) | qwen3:4b (Ollama) | `<TODO>` |

**วิธีวัดเวลา**

รวมทั้งหมดของหลักสูตรเดียว:
```powershell
# Windows PowerShell
Measure-Command { python run_lab8b.py --run IT --gt-dir data/ground_truth }
```
```bash
# macOS / Linux
time python run_lab8b.py --run IT --gt-dir data/ground_truth
```

แยกเวลาขั้น 7B กับ 8B: รันอีกครั้งด้วย `--skip-lab7` จะได้เวลาของขั้น 8B อย่างเดียว เวลาขั้น 7B = เวลารวม − เวลาขั้น 8B

เวลาแต่ละขั้นย่อย (เรนเดอร์ ลบลายน้ำ OCR ฯลฯ) ให้ดูจาก log ที่โปรแกรมพิมพ์ หรือเพิ่มการจับเวลาในโค้ดถ้าต้องการละเอียดกว่านี้

## 7. แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุที่เป็นไปได้ | วิธีแก้ |
|---|---|---|
| เชื่อมต่อ Ollama ไม่ได้ / connection refused | Ollama ยังไม่เปิด | เปิดโปรแกรม Ollama ค้างไว้ แล้วลองใหม่ |
| ขึ้นว่า model not found | ยังไม่ได้ `ollama pull` | รันคำสั่ง pull ตามหัวข้อ 2.5 |
| Ollama อยู่คนละที่กับค่าเริ่มต้น | — | ตั้ง `LAB8_OLLAMA_URL` (ฝั่ง 8B) หรือ `OLLAMA_HOST` (ฝั่ง 7B ต้องเป็น localhost เท่านั้น) |
| รอบหนึ่งถูกนับว่าล้มเหลวทันที | ไม่มี PDF ใน `data/input/` | วางไฟล์ให้ชื่อตรงกับ run_id |
| รัน `--help` แล้ว error เรื่อง encoding (Windows) | Terminal ใช้ cp1252 อ่านข้อความไทยใน help ไม่ได้ | รัน `$env:PYTHONUTF8=1` ก่อน แล้วรันคำสั่งใหม่ |
| PowerShell activate venv ไม่ได้ (policy error) | ติดนโยบายการรันสคริปต์ | รัน `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` แล้วลองใหม่ |
| `ModuleNotFoundError` ทั้งที่ติดตั้งแล้ว | ลืม activate venv (ต้อง activate ใหม่ทุกครั้งที่เปิด Terminal ใหม่) | ทำตาม 2.3 แล้วรันใหม่ |
| ผลดูเหมือนของเก่า | มี `pred_vlm.json` ค้างจากรอบก่อน | ลบโฟลเดอร์ `work/lab7b_run/<run_id>/` แล้วรันใหม่ |

---

## 8. ข้อจำกัดที่ควรรู้

- **คะแนน eval (เช่น 30/30) ไม่ใช่ความแม่นยำโดยรวม** วัดแบบผ่อนปรน (ยอมให้มีข้อมูลเกิน) และใช้ได้เฉพาะชุดคำถามนี้
- **✓ ในสรุปท้ายของ `run_lab8b.py` แปลว่าโปรแกรมไม่ crash เท่านั้น** ไม่ได้แปลว่า verify หรือ eval ผ่าน
- **ผลเก่าอาจถูกหยิบมาใช้โดยไม่รู้ตัว** ถ้าขั้น OCR ล้มแต่มี `pred_vlm.json` เก่าค้างอยู่ ขั้นถัดไปจะใช้ไฟล์เก่า ให้ตรวจเวลาแก้ไขไฟล์หรือลบโฟลเดอร์ของรอบนั้นก่อนรันใหม่
- **ลบลายน้ำได้เฉพาะสีจาง** ใช้ threshold เดียวทุกหน้า (ค่าเริ่มต้น 195 ปรับได้ด้วยตัวแปร `LAB7_WATERMARK_THRESHOLD`)
- **ไม่มีการรัน baseline Tesseract** ในขั้นตอนหลัก ถ้าต้องการเส้นฐานเปรียบเทียบ ให้รัน `lab7b_curriculum.py -p all` แยก
- **เล่มรุ่น 2560 ได้รับการซ่อมข้อมูลหลังสกัดน้อยกว่าเล่มหลัก** คุณภาพผลอาจต่างกัน
- **กฎซ่อมข้อมูลของ BIT ระบุรหัสวิชาตรง ๆ** (`06036145`, `06036146` ให้อยู่ทั้งสองแผน) ตรวจด้วยมือแล้วเฉพาะ BIT

---

## 9. โครงสร้างโปรเจกต์ (สรุป)

```
run_lab8b.py                     จุดเริ่มต้น: รันทั้งสองขั้นต่อเนื่อง
requirements.txt                 package ทั้งหมด (ติดตั้งครั้งเดียวด้วย pip install -r)
src/ocr_system/
    lab7b_curriculum.py          ขั้น 7B: PDF → OCR → ข้อมูลหลักสูตร
    lab8b_curriculum_db.py       ขั้น 8B: ข้อมูล → SQLite → ตรวจสอบ → ถามตอบ
src/lab7_metrics.py              ตัววัดผลเทียบเฉลย (Precision/Recall/F1, CER, WER)
src/ocr_system/utils/            ฟังก์ชันช่วย (io ฯลฯ)
data/input/                      วาง PDF เอง (ไม่อยู่ใน repo, ถูก ignore)
data/ground_truth/               ไฟล์เฉลย
work/                            ผลที่รัน (lab7b_run/, lab8b_run/)
```
