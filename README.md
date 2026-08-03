# Thai-English OCR System

โปรเจกต์นี้เป็น OCR pipeline สำหรับเอกสารภาพเดี่ยวและหลายหน้า เช่น `.jpg`, `.png`, `.tif`, `.pdf` โดยรองรับเอกสารภาษาไทยและอังกฤษปนกัน

OCR engines ที่มีให้:

- PaddleOCR: เหมาะกับภาษาไทยและเอกสารทั่วไป
- Tesseract OCR: ใช้ `tha+eng` ได้ดีเมื่อมีภาษาไทย/อังกฤษปนกัน
- TrOCR: OCR แบบ Transformer เหมาะกับ printed English เป็นหลัก
- Ensemble: ใช้ PaddleOCR + Tesseract แล้วรวมผลแบบง่าย

---

## Project Structure

```text
ocr_system/
├── README.md
├── requirements.txt
├── pyproject.toml
├── data/
│   ├── input/                 # ใส่ไฟล์ภาพหรือ PDF ที่ต้องการ OCR
│   └── ground_truth/          # ไฟล์เฉลยสำหรับ evaluate
├── outputs/                   # ผลลัพธ์ OCR และ evaluation
└── src/
    └── ocr_system/
        ├── cli.py             # command line interface
        ├── config.py          # config หลักของระบบ
        ├── document_loader.py # โหลดภาพ / แปลง PDF เป็นภาพ
        ├── preprocessing.py   # resize, denoise, contrast, deskew, threshold
        ├── pipeline.py        # OCR pipeline หลัก
        ├── evaluation.py      # CER, WER, exact match
        ├── field_extraction.py# ดึง field เช่น email, date, id, phone
        ├── schemas.py         # dataclass ของผลลัพธ์
        ├── engine_factory.py  # เลือก OCR engine
        ├── engines/
        │   ├── base.py
        │   ├── paddle_engine.py
        │   ├── tesseract_engine.py
        │   ├── trocr_engine.py
        │   └── ensemble_engine.py
        └── utils/
            └── io.py
```

---

## ใช้งานผ่าน VS Code 

แนะนำให้ใช้ **VS Code** เพราะเปิดดูโครงสร้างไฟล์ แก้โค้ด และรันคำสั่งใน Terminal ได้ในที่เดียว
---
## วิธีเปิดโปรเจกต์ใน VS Code
1. แตกไฟล์ `ocr_system.zip`
2. จะได้โฟลเดอร์ชื่อ `ocr_system`
3. เปิด VS Code
4. ไปที่เมนู
```text
File > Open Folder
```

5. เลือกโฟลเดอร์ `ocr_system`
6. เปิด Terminal ใน VS Code
```text
Terminal > New Terminal
```
หลังจากนี้ให้พิมพ์คำสั่งต่าง ๆ ใน Terminal ของ VS Code ได้เลย

---

## Installation
แนะนำใช้ Python 3.10 ขึ้นไป
เช็กเวอร์ชัน Python ก่อน:

```bash
python --version
```
หรือบางเครื่องอาจต้องใช้:
```bash
py --version
```
ถ้าเวอร์ชันเป็น Python 3.10, 3.11 หรือ 3.12 สามารถใช้ได้

---

## สร้าง Virtual Environment
Virtual Environment คือพื้นที่แยกสำหรับติดตั้ง package ของโปรเจกต์นี้โดยเฉพาะ เพื่อไม่ให้ชนกับโปรเจกต์อื่น
ให้เข้าไปในโฟลเดอร์โปรเจกต์ก่อน:
```bash
cd ocr_system
```
จากนั้นสร้าง environment:
```bash
python -m venv .venv
```

ถ้าใช้ Windows แล้วคำสั่ง `python` ไม่ได้ ให้ลองใช้:
```bash
py -m venv .venv
```

---

## เปิดใช้งาน Virtual Environment

### Windows CMD
```bash
.venv\Scripts\activate
```

### Windows PowerShell
```bash
.venv\Scripts\Activate.ps1
```

ถ้า PowerShell ขึ้น error เรื่อง policy ให้รัน:
```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

แล้วลอง activate ใหม่อีกครั้ง

### macOS / Linux
```bash
source .venv/bin/activate
```
ถ้าสำเร็จ จะเห็นชื่อ environment ขึ้นต้นบรรทัดประมาณนี้:
```text
(.venv) C:\...\ocr_system>
```

---

## ติดตั้ง Python Packages
หลังจาก activate `.venv` แล้ว ให้ติดตั้ง package ทั้งหมด:
```bash
pip install -r requirements.txt
```

จากนั้นติดตั้งโปรเจกต์แบบ editable:
```bash
pip install -e .
```

คำสั่งนี้ทำให้สามารถเรียกใช้งานโปรเจกต์ด้วยรูปแบบนี้ได้:
```bash
python -m ocr_system.cli
```

---

## Install Tesseract Engine
ในโปรเจกต์นี้มี OCR หลายตัว เช่น PaddleOCR, Tesseract และ TrOCR
แต่สำหรับ Tesseract ต้องติดตั้งโปรแกรม Tesseract OCR แยกต่างหาก เพราะ `pytesseract` เป็นแค่ Python package ที่ใช้เรียกโปรแกรม Tesseract เท่านั้น

---

## ติดตั้ง Tesseract บน Windows
ให้ติดตั้ง Tesseract OCR จาก UB Mannheim build
ระหว่างติดตั้ง ให้เลือกภาษา:
```text
English
Thai
```

หลังติดตั้งเสร็จ ให้เปิด CMD หรือ VS Code Terminal ใหม่ แล้วตรวจสอบ:
```bash
tesseract --version
```

จากนั้นตรวจสอบภาษาที่ติดตั้ง:
```bash
tesseract --list-langs
```
ควรเห็นอย่างน้อย:
```text
eng
tha
```
ถ้าไม่เห็น `tha` แปลว่ายังไม่ได้ติดตั้งภาษาไทย

---

## ติดตั้ง Tesseract บน Ubuntu / Debian
```bash
sudo apt update
sudo apt install tesseract-ocr tesseract-ocr-tha poppler-utils
```
---

## ติดตั้ง Tesseract บน macOS
```bash
brew install tesseract poppler
brew install tesseract-lang
```
หมายเหตุ: `poppler` จำเป็นสำหรับแปลง PDF เป็นภาพผ่าน `pdf2image`

---

## เตรียมไฟล์สำหรับทดสอบ OCR
นำไฟล์เอกสารไปวางในโฟลเดอร์นี้:
```text
data/input/
```

ตัวอย่าง:
```text
data/input/sample.pdf
data/input/sample.jpg
data/input/sample.png
```

รองรับทั้ง:
```text
PDF หลายหน้า
JPG
PNG
TIFF
BMP
```

---

## Usage
### 1. OCR ด้วย Ensemble
Ensemble คือการใช้หลาย OCR engine ช่วยกัน แล้วเลือกผลลัพธ์ที่เหมาะสมที่สุด
เหมาะสำหรับเอกสารที่มีทั้งภาษาไทยและอังกฤษปนกัน

```bash
python -m ocr_system.cli ocr data/input/sample.pdf --engine ensemble
```

หลังรันเสร็จ ผลลัพธ์จะอยู่ในโฟลเดอร์:
```text
outputs/
```

จะได้ไฟล์ประมาณนี้:
```text
outputs/sample_ocr.json
outputs/sample_ocr.txt
outputs/sample_fields.json
outputs/pages/
```

ความหมายของไฟล์:
```text
sample_ocr.json     ผล OCR แบบละเอียด เช่น text, confidence, page
sample_ocr.txt      ข้อความ OCR รวมทั้งหมด อ่านง่าย
sample_fields.json  field ที่ระบบพยายาม extract เช่น วันที่ ชื่อ รหัส
outputs/pages/      ภาพแต่ละหน้าที่แปลงจาก PDF
```

---

## 2. OCR ด้วย PaddleOCR
เหมาะกับเอกสารทั่วไป โดยเฉพาะภาษาไทยและอังกฤษปนกัน
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine paddle --paddle-lang th
```
ถ้าเอกสารเป็นอังกฤษล้วน อาจลองใช้:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine paddle --paddle-lang en
```
---
## 3. OCR ด้วย Tesseract ไทย + อังกฤษ
เหมาะกับเอกสาร scan ที่ตัวหนังสือชัด หรือเอกสารราชการ/ฟอร์มที่ layout ไม่ซับซ้อนมาก
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine tesseract --languages tha+eng
```

ถ้าเป็นอังกฤษอย่างเดียว:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine tesseract --languages eng
```

ถ้าเป็นไทยอย่างเดียว:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine tesseract --languages tha
```

---

## 4. OCR ด้วย TrOCR
TrOCR เป็นโมเดล OCR จาก Transformer
ในโปรเจกต์นี้ใช้เป็น fallback สำหรับข้อความสั้น ๆ หรือภาพที่ crop เป็นบรรทัดแล้ว
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine trocr --device cpu
```
ถ้ามี GPU และติดตั้ง PyTorch แบบ CUDA แล้ว สามารถใช้:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine trocr --device cuda
```
หมายเหตุ: TrOCR ในโปรเจกต์นี้ยังไม่เหมาะกับเอกสารยาวทั้งหน้า แนะนำใช้ PaddleOCR หรือ Tesseract เป็นหลัก

---
## Evaluation
Evaluation คือการวัดว่า OCR อ่านถูกแค่ไหน โดยเทียบกับข้อความจริง หรือ Ground Truth
สร้างไฟล์ ground truth เช่น:
```text
data/ground_truth/example_ground_truth.json
```

ตัวอย่างเนื้อหา:
```json
{
  "sample.pdf": "ข้อความจริงทั้งหมดในเอกสาร sample.pdf",
  "sample.jpg": "ข้อความจริงในเอกสาร sample.jpg"
}
```

จากนั้นรัน OCR ก่อน:
```bash
python -m ocr_system.cli ocr data/input/sample.pdf --engine ensemble
```
แล้ว evaluate:
```bash
python -m ocr_system.cli evaluate data/ground_truth/example_ground_truth.json outputs/sample_ocr.json
```

Metric ที่ได้:

```text
cer           Character Error Rate ยิ่งต่ำยิ่งดี
wer           Word Error Rate ยิ่งต่ำยิ่งดี
exact_match   ข้อความตรงทั้งหมดหรือไม่
```

ตัวอย่างการอ่านผล:
```text
CER = 0.05 หมายถึงผิดประมาณ 5% ระดับตัวอักษร
WER = 0.12 หมายถึงผิดประมาณ 12% ระดับคำ
exact_match = false หมายถึงยังไม่ตรง 100%
```
---

## คำสั่งที่ใช้บ่อย
OCR ไฟล์ PDF ด้วยระบบรวม:
```bash
python -m ocr_system.cli ocr data/input/sample.pdf --engine ensemble
```

OCR รูปภาพด้วย PaddleOCR:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine paddle --paddle-lang th
```

OCR รูปภาพด้วย Tesseract:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine tesseract --languages tha+eng
```

Evaluate ผล OCR:
```bash
python -m ocr_system.cli evaluate data/ground_truth/example_ground_truth.json outputs/sample_ocr.json
```

---

## Recommended Engine

สำหรับเอกสารไทย+อังกฤษปนกัน แนะนำเริ่มจาก:
```bash
python -m ocr_system.cli ocr data/input/sample.pdf --engine ensemble --languages tha+eng --paddle-lang th --save-debug-images
```

ถ้าเอกสารเป็นอังกฤษเกือบทั้งหมด:
```bash
python -m ocr_system.cli ocr data/input/sample.pdf --engine paddle --paddle-lang en
```

ถ้า Tesseract อ่านไทยเพี้ยน ให้ลอง OCR แบบไม่ preprocess:
```bash
python -m ocr_system.cli ocr data/input/sample.jpg --engine tesseract --no-preprocess
```

---

## Output JSON Format
```json
{
  "source_path": "data/input/sample.pdf",
  "engine": "ensemble",
  "text": "--- Page 1 ---\n...",
  "pages": [
    {
      "page": 1,
      "text": "...",
      "lines": [
        {
          "text": "ข้อความที่ OCR อ่านได้",
          "confidence": 0.95,
          "box": [[0, 0], [100, 0], [100, 30], [0, 30]],
          "engine": "paddle",
          "page": 1
        }
      ],
      "image_path": "outputs/pages/sample_page_001.jpg"
    }
  ]
}
```

---
