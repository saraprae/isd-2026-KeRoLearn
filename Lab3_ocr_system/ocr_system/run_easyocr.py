import os
import json
import pypdfium2 as pdfium
import easyocr
import numpy as np

# กำหนด Path ขาเข้าและขาออก
input_pdf = "data/input/sample.pdf"
output_folder = "output_easyocr"
output_json_path = os.path.join(output_folder, "sample_ocr.json")
output_txt_path = os.path.join(output_folder, "sample_ocr.txt")

# ตรวจสอบว่ามีโฟลเดอร์ output หรือยัง
os.makedirs(output_folder, exist_ok=True)

print("1. กำลังโหลดโมเดล EasyOCR (TH-EN)...")
reader = easyocr.Reader(['th', 'en'], gpu=False)

print(f"2. กำลังอ่านไฟล์ PDF: {input_pdf}")
pdf = pdfium.PdfDocument(input_pdf)

# เตรียมโครงสร้างสำหรับเก็บข้อมูลเพื่อทำ JSON
json_data = {
    "source_path": input_pdf,
    "engine": "easyocr",
    "text": "",
    "pages": []
}

all_pages_text_list = []

# วนลูปประมวลผลทีละหน้า
for page_index in range(len(pdf)):
    print(f"กำลังประมวลผลหน้า {page_index + 1}/{len(pdf)}...")
    page = pdf[page_index]
    
    # แปลง PDF เป็นรูปภาพความละเอียดสูง
    bitmap = page.render(scale=3.0)
    pil_image = bitmap.to_pil()
    image_np = np.array(pil_image)
    
    # ดึงค่าแบบละเอียด (ไม่ใส่ detail=0 เพื่อให้ได้พิกัดและค่าความมั่นใจมาด้วย)
    # results จะได้รูปแบบ: [([[x1,y1], [x2,y2], [x3,y3], [x4,y4]], "text", confidence), ...]
    results = reader.readtext(image_np)
    
    page_lines = []
    page_text_list = []
    
    for box, text, confidence in results:
        page_text_list.append(text)
        
        # แปลงพิกัด box จาก numpy float/int ให้เป็น python int ธรรมดาเพื่อให้แปลงเป็น JSON ได้
        formatted_box = [[int(coord[0]), int(coord[1])] for coord in box]
        
        page_lines.append({
            "text": text,
            "confidence": round(float(confidence), 2),
            "box": formatted_box
        })
        
    page_full_text = "\n".join(page_text_list)
    formatted_page_text = f"--- Page {page_index + 1} ---\n{page_full_text}"
    all_pages_text_list.append(formatted_page_text)
    
    # เพิ่มข้อมูลหน้านี้เข้าโครงสร้างข้อมูลหลัก
    json_data["pages"].append({
        "page": page_index + 1,
        "text": page_full_text,
        "lines": page_lines
    })

# รวมข้อความทั้งหมดทุกหน้าเก็บไว้ที่ root key "text"
json_data["text"] = "\n\n".join(all_pages_text_list)

# 3. บันทึกไฟล์ JSON แบบจัดรูปแบบสวยงาม (Indent=4)
print(f"3. กำลังบันทึกไฟล์ JSON ไปยัง {output_json_path}")
with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(json_data, f, ensure_ascii=False, indent=4)

# แถมบันทึกไฟล์ .txt ไปพร้อมกันด้วยเพื่อความสะดวกในการใช้งาน
with open(output_txt_path, "w", encoding="utf-8") as f:
    f.write(json_data["text"])

print("successfully")