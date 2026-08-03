# check_diff.py
import json
from pathlib import Path

# กำหนด Path ไฟล์ Ground Truth และไฟล์ผลลัพธ์
gt_path = Path("data/ground_truth/ground_truth_sample.json")
pred_path = Path("output_tesseract/extracted_result.json")

if not gt_path.exists() or not pred_path.exists():
    print("❌ ไม่พบไฟล์ JSON สำหรับเปรียบเทียบ กรุณาเช็ก Path อีกครั้ง")
    exit()

with open(gt_path, encoding="utf-8") as f:
    gt_data = json.load(f)

with open(pred_path, encoding="utf-8") as f:
    pred_data = json.load(f)

# สมมติโครงสร้าง JSON เก็บรายวิชาไว้ใน Key 'courses' หรือเป็น List
gt_courses = gt_data.get("courses", gt_data) if isinstance(gt_data, dict) else gt_data
pred_courses = pred_data.get("courses", pred_data) if isinstance(pred_data, dict) else pred_data

# แปลงเป็น Dict โดยใช้รหัสวิชา (code) หรือ ชื่อภาษาอังกฤษ เป็น Key
gt_map = {item.get("code", item.get("name_en")): item for item in gt_courses if isinstance(item, dict)}
pred_map = {item.get("code", item.get("name_en")): item for item in pred_courses if isinstance(item, dict)}

print("================ 🔍 สรุปผลการตรวจสอบ ================\n")

# 1. หาวิชาที่ตกหล่น (Missing Courses)
missing = [code for code in gt_map if code not in pred_map]
print(f"❌ วิชาที่สกัดไม่เจอ/ตกหล่น ({len(missing)} วิชา):")
for code in missing:
    gt_item = gt_map[code]
    print(f"  - [{code}] {gt_item.get('name_en', '')} / {gt_item.get('name_th', '')}")

print("\n---------------------------------------------------")

# 2. หาวิศัยที่สกัดมาได้ แต่ข้อมูลไม่ตรงกัน (Mismatch)
print("⚠️ วิชาที่สกัดได้ แต่ข้อมูลไม่ตรงกับ Ground Truth:")
mismatch_count = 0
for code, gt_item in gt_map.items():
    if code in pred_map:
        pred_item = pred_map[code]
        diffs = []
        
        # เช็กชื่อภาษาอังกฤษ
        if gt_item.get("name_en") != pred_item.get("name_en"):
            diffs.append(f"Name EN -> เฉลย: '{gt_item.get('name_en')}' | สกัดได้: '{pred_item.get('name_en')}'")
        
        # เช็กหน่วยกิต
        if str(gt_item.get("credit")) != str(pred_item.get("credit")):
            diffs.append(f"Credit  -> เฉลย: '{gt_item.get('credit')}' | สกัดได้: '{pred_item.get('credit')}'")

        if diffs:
            mismatch_count += 1
            print(f"\n📌 วิชา [{code}]:")
            for d in diffs:
                print(f"    • {d}")

if mismatch_count == 0:
    print("  (ไม่มีวิชาที่มีข้อมูลขัดแย้งกัน)")

print("\n===================================================")