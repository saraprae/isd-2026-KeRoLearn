import json
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class ExtractionEvaluationResult:
    file: str
    total_ground_truths: int
    recall: str              # สัดส่วนรายวิชาที่หาเจอ (%)
    name_en_agreement: str   # ความถูกต้องของชื่อภาษาอังกฤษ (%)
    credit_agreement: str    # ความถูกต้องของหน่วยกิต (%)

def evaluate_extraction(reference_list: list[dict], prediction_list: list[dict], file_name: str = "") -> ExtractionEvaluationResult:
    total_refs = len(reference_list)
    
    if total_refs == 0:
        return ExtractionEvaluationResult(file_name, 0, "0.00%", "0.00%", "0.00%")

    found_count = 0
    name_en_correct = 0
    credits_correct = 0

    # เทียบเฉลย (Reference) ทีละรายการกับผลลัพธ์ (Prediction)
    for ref in reference_list:
        ref_code = str(ref.get("code", "")).strip()
        ref_name_th = str(ref.get("name_th", "")).strip()
        
        # ปรับ format เพื่อให้เทียบได้ยืดหยุ่นขึ้น
        ref_name_en = str(ref.get("name_en", "")).strip().lower()
        ref_credits = str(ref.get("credits", "")).strip().replace(" ", "")

        matched_pred = None
        
        # 1. ค้นหาวิชาที่ตรงกันใน Prediction (เกณฑ์คือ รหัสวิชา หรือ ชื่อวิชาภาษาไทย)
        for pred in prediction_list:
            pred_code = str(pred.get("code", "")).strip()
            pred_name_th = str(pred.get("name_th", "")).strip()
            
            if (ref_code and ref_code == pred_code) or (ref_name_th and ref_name_th == pred_name_th):
                matched_pred = pred
                break
        
        # 2. ถ้าหาเจอ ให้นำฟิลด์ย่อยๆ มาเทียบ agreement
        if matched_pred:
            found_count += 1
            
            pred_name_en = str(matched_pred.get("name_en", "")).strip().lower()
            pred_credits = str(matched_pred.get("credits", "")).strip().replace(" ", "")

            is_name_en_match = (ref_name_en == pred_name_en)
            is_credit_match = (ref_credits == pred_credits)

            if is_name_en_match:
                name_en_correct += 1
            if is_credit_match:
                credits_correct += 1

    # 3. คำนวณ Metrics ทั้ง 3 ตัว และแปลงเป็น %
    recall_val = (found_count / total_refs) * 100
    name_en_val = (name_en_correct / found_count * 100) if found_count > 0 else 0.0
    credit_val = (credits_correct / found_count * 100) if found_count > 0 else 0.0

    return ExtractionEvaluationResult(
        file=file_name,
        total_ground_truths=total_refs,
        recall=f"{recall_val:.2f}%",
        name_en_agreement=f"{name_en_val:.2f}%",
        credit_agreement=f"{credit_val:.2f}%"
    )

def evaluate_from_files(ground_truth_json: str | Path, prediction_json: str | Path) -> dict:
    with Path(ground_truth_json).open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)
    with Path(prediction_json).open("r", encoding="utf-8") as f:
        prediction = json.load(f)

    # 1. จัดการชื่อไฟล์สำหรับใช้รายงานผล
    source_path = prediction.get("source_path") or prediction.get("source") or "sample_ocr.json"
    source_name = Path(source_path).name

    # 2. ดึงข้อมูลเฉลย (Ground Truth) ตามโครงสร้างไฟล์
    if "courses" in ground_truth:
        reference = ground_truth["courses"]
    elif isinstance(ground_truth, list):
        reference = ground_truth
    else:
        reference = ground_truth.get(source_name) or ground_truth.get(Path(source_name).stem, [])

    if not reference:
        print(f"Warning: Could not find valid reference data in {ground_truth_json}")
        reference = []

    if isinstance(reference, dict):
        reference = [reference]

    # 3. ดึงข้อมูลที่สกัดได้ (Prediction)
    pred_data = prediction.get("extracted_data") or prediction.get("courses") or []
    if isinstance(pred_data, dict):
        pred_data = [pred_data]

    # 4. ส่งข้อมูลเข้าไปประเมินผล
    result = evaluate_extraction(
        reference_list=reference, 
        prediction_list=pred_data, 
        file_name=source_name
    )
    
    return asdict(result)