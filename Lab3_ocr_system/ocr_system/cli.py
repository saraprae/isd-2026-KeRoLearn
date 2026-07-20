"""
CLI entry point that chains the two-step pipeline:
  1. run_easyocr.py       -> reads data/input/sample.pdf, writes
                              output_easyocr/sample_ocr.json (+ .txt)
  2. curriculum_extraction.py -> reads output_easyocr/sample_ocr.json, writes
                              output_easyocr/extracted_result.json

run_easyocr.py is a plain top-level script (not a set of importable
functions), so step 1 is run as a subprocess. Step 2 imports
extract_curriculum_from_file directly since curriculum_extraction.py
already exposes it as a function.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from curriculum_extraction import extract_curriculum_from_file

BASE_DIR = Path(__file__).resolve().parent
RUN_EASYOCR_SCRIPT = BASE_DIR / "run_easyocr.py"
OCR_OUTPUT_JSON = BASE_DIR / "output_easyocr" / "sample_ocr.json"
FINAL_OUTPUT_JSON = BASE_DIR / "output_easyocr" / "extracted_result.json"


def run_ocr_step() -> None:
    """Run run_easyocr.py so it produces output_easyocr/sample_ocr.json."""
    print(f"[1/2] Running OCR: {RUN_EASYOCR_SCRIPT}")
    result = subprocess.run([sys.executable, str(RUN_EASYOCR_SCRIPT)], cwd=BASE_DIR)
    if result.returncode != 0:
        raise RuntimeError(f"run_easyocr.py exited with code {result.returncode}")
    if not OCR_OUTPUT_JSON.exists():
        raise FileNotFoundError(
            f"run_easyocr.py finished but expected output was not found: {OCR_OUTPUT_JSON}"
        )
    print(f"    -> OCR output written to: {OCR_OUTPUT_JSON}")


def run_extraction_step() -> dict:
    """Run curriculum extraction against the OCR output json."""
    print(f"[2/2] Extracting curriculum from: {OCR_OUTPUT_JSON}")
    result = extract_curriculum_from_file(ocr_path=OCR_OUTPUT_JSON)

    FINAL_OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(FINAL_OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=4)

    print(f"    -> Extracted curriculum written to: {FINAL_OUTPUT_JSON}")
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run OCR (run_easyocr.py) then extract curriculum from its output."
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip the OCR step and reuse the existing output_easyocr/sample_ocr.json.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.skip_ocr:
        if not OCR_OUTPUT_JSON.exists():
            raise FileNotFoundError(
                f"--skip-ocr was set but {OCR_OUTPUT_JSON} does not exist. "
                "Run without --skip-ocr first."
            )
        print(f"Skipping OCR step, reusing existing file: {OCR_OUTPUT_JSON}")
    else:
        run_ocr_step()

    run_extraction_step()
    print("Done.")


if __name__ == "__main__":
    main()