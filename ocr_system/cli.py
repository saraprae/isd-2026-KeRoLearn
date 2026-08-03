"""CLI entry point: OCR (Tesseract) -> Curriculum Extraction -> Evaluation."""

import argparse
import json
import sys
from pathlib import Path

# ปรับระบบ Import ให้รองรับทั้งการรันแบบ python -m และการรันไฟล์ตรงๆ
try:
    from .config import OCRConfig
    from .pipeline import run_ocr
    from .curriculum_extraction import extract_curriculum_from_file
    from .evaluation import evaluate_from_files
except (ImportError, ValueError):
    from .config import OCRConfig
    from .pipeline import run_ocr
    from .curriculum_extraction import extract_curriculum_from_file
    from .evaluation import evaluate_from_files

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent if BASE_DIR.name == "ocr_system" else BASE_DIR

# Path กำหนดตำแหน่งไฟล์
DEFAULT_INPUT_DOC = PROJECT_ROOT / "data" / "input" / "sample.pdf"
OUTPUT_DIR = PROJECT_ROOT / "output_tesseract"
OCR_OUTPUT_JSON = OUTPUT_DIR / "ocr_result.json"
FINAL_OUTPUT_JSON = OUTPUT_DIR / "extracted_result.json"
DEFAULT_GROUND_TRUTH = PROJECT_ROOT / "data" / "ground_truth" / "ground_truth_sample.json"


def run_ocr_step(input_path: Path) -> None:
    """ขั้นตอนที่ 1: ทำ OCR ผ่าน pipeline.py"""
    print(f"[1/3] Running Tesseract OCR via Pipeline on: {input_path.name}")
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input document not found at: {input_path}")

    config = OCRConfig(
        input_path=str(input_path),
        output_dir=str(OUTPUT_DIR),
        engine="tesseract",
        dpi=300,
        preprocess=True
    )

    run_ocr(config)
    print(f"    -> OCR output written to: {OUTPUT_DIR}")


def run_extraction_step() -> dict:
    """ขั้นตอนที่ 2: สกัดข้อมูลหลักสูตร"""
    print(f"[2/3] Extracting curriculum from OCR output...")
    
    target_ocr_file = OCR_OUTPUT_JSON
    if not target_ocr_file.exists():
        json_files = list(OUTPUT_DIR.glob("*_ocr.json"))
        if json_files:
            target_ocr_file = json_files[0]
        else:
            raise FileNotFoundError(f"Could not find any OCR JSON output in {OUTPUT_DIR}")

    result = extract_curriculum_from_file(ocr_path=str(target_ocr_file))

    FINAL_OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(FINAL_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"    -> Extracted curriculum written to: {FINAL_OUTPUT_JSON}")
    return result


def run_evaluation_step(gt_path: Path) -> dict:
    """ขั้นตอนที่ 3: ประเมินผลเทียบกับ Ground Truth"""
    print(f"[3/3] Evaluating extraction against: {gt_path.name}")
    if not gt_path.exists():
        print(
            f"    [Warning] Ground truth file not found at {gt_path}. Skipping evaluation."
        )
        return {}

    eval_result = evaluate_from_files(
        ground_truth_json=gt_path, prediction_json=FINAL_OUTPUT_JSON
    )

    print("\n================ EVALUATION RESULT ================")
    print(json.dumps(eval_result, ensure_ascii=False, indent=2))
    print("===================================================\n")
    return eval_result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run OCR, Extract Curriculum, and Evaluate against Ground Truth."
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_INPUT_DOC),
        help="Path to input PDF/Image document for OCR",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip OCR and use existing OCR output JSON",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip extraction and use existing extracted_result.json",
    )
    parser.add_argument(
        "--gt",
        type=str,
        default=str(DEFAULT_GROUND_TRUTH),
        help="Path to ground truth JSON file for evaluation",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 1. OCR Step
    if args.skip_ocr:
        print(f"Skipping OCR step, using existing output in: {OUTPUT_DIR}")
    else:
        input_doc = Path(args.input)
        run_ocr_step(input_doc)

    # 2. Extraction Step
    if args.skip_extraction:
        if not FINAL_OUTPUT_JSON.exists():
            raise FileNotFoundError(
                f"--skip-extraction was set but {FINAL_OUTPUT_JSON} does not exist."
            )
        print(f"Skipping Extraction step, reusing: {FINAL_OUTPUT_JSON}")
    else:
        run_extraction_step()

    # 3. Evaluation Step
    gt_file_path = Path(args.gt)
    run_evaluation_step(gt_file_path)

    print("Pipeline completed successfully.")


if __name__ == "__main__":
    main()