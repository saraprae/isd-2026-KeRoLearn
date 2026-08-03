import json
import os
import pypdfium2 as pdfium
import pytesseract
from pytesseract import Output

# [สำหรับ Windows] หากไม่ได้ตั้ง PATH ให้ระบุตำแหน่งไฟล์ tesseract.exe ที่นี่
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

input_pdf = "data/input/sample.pdf"
output_folder = "output_tesseract"
output_json_path = os.path.join(output_folder, "ocr_result.json")
output_txt_path = os.path.join(output_folder, "ocr_result.txt")

os.makedirs(output_folder, exist_ok=True)

print(f"1. กำลังอ่านไฟล์ PDF: {input_pdf}")
pdf = pdfium.PdfDocument(input_pdf)

json_data = {
    "source_path": input_pdf,
    "engine": "tesseract",
    "text": "",
    "pages": [],
}

all_pages_text_list = []

for page_index in range(len(pdf)):
    print(f"กำลังประมวลผลหน้า {page_index + 1}/{len(pdf)}...")
    page = pdf[page_index]

    # แปลง PDF เป็นรูปภาพความละเอียดสูง
    bitmap = page.render(scale=3.0)
    pil_image = bitmap.to_pil()

    # ดึงข้อมูลแบบละเอียด (รัน OCR เพียงรอบเดียว)
    data = pytesseract.image_to_data(
        pil_image, lang="tha+eng", output_type=Output.DICT
    )

    page_words = []
    page_text_words = []
    n_boxes = len(data["text"])

    for i in range(n_boxes):
        text = data["text"][i].strip()
        conf = float(data["conf"][i])

        # conf >= 0 เพื่อกรองเอาเฉพาะระดับ Word ที่อ่านค่าได้
        if text and conf >= 0:
            x, y, w, h = (
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )

            formatted_box = [
                [int(x), int(y)],
                [int(x + w), int(y)],
                [int(x + w), int(y + h)],
                [int(x), int(y + h)],
            ]

            normalized_conf = round(conf / 100.0, 2)

            page_words.append(
                {
                    "text": text,
                    "confidence": normalized_conf,
                    "box": formatted_box,
                }
            )
            page_text_words.append(text)

    # รวมคำในหน้านั้นเป็น Text หยาบๆ
    page_full_text = " ".join(page_text_words)

    formatted_page_text = f"--- Page {page_index + 1} ---\n{page_full_text}"
    all_pages_text_list.append(formatted_page_text)

    json_data["pages"].append(
        {"page": page_index + 1, "text": page_full_text, "words": page_words}
    )

json_data["text"] = "\n\n".join(all_pages_text_list)

print(f"2. กำลังบันทึกไฟล์ไปที่ {output_folder}")
with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(json_data, f, ensure_ascii=False, indent=4)

with open(output_txt_path, "w", encoding="utf-8") as f:
    f.write(json_data["text"])

print("Successfully completed OCR processing!")