#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_stream.py — ดูเนื้อหาที่ Typhoon-OCR พิมพ์ออกมาสดๆ (stream) ก่อนโดน
Ollama ตัดด้วย "token repeat limit reached" เพื่อดูว่ามันวนซ้ำคำ/วลีอะไร

ใช้:
    python probe_stream.py data/input/IT.pdf 30      # index 0-based (หน้า 31)
"""
import base64
import io
import json
import sys
import requests
import pymupdf as fitz
from PIL import Image

WATERMARK_THRESHOLD = 195


def suppress_faint_background(png_bytes: bytes, threshold: int = WATERMARK_THRESHOLD) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    img = img.point(lambda p: 255 if p > threshold else p)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG")
    return out.getvalue()

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL_OCR = "scb10x/typhoon-ocr1.5-3b"

TYPHOON_PROMPT = """Extract all text from the image.

Instructions:
- Only return the clean Markdown.
- Do not include any explanation or extra text.
- You must include all information on the page.

Formatting Rules:
- Tables: Render tables using <table>...</table> in clean HTML format.
- Equations: Render equations using LaTeX syntax with inline ($...$) and block ($$...$$).
- Watermarks, background seals, stamps, or faint institutional logos printed across the page are page decoration, not content. Ignore them completely.
- Images/Charts/Diagrams: Wrap only clearly defined, intentional visual content in <figure>...</figure> tags, described in Thai.
- Page Numbers: Wrap page numbers in <page_number>...</page_number>.
- Checkboxes: Use ☐ for unchecked and ☑ for checked boxes."""


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "data/input/IT.pdf"
    page_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    zoom = 150 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    png_bytes = pix.tobytes("png")
    doc.close()
    clean_bytes = suppress_faint_background(png_bytes)
    with open("probe_clean.png", "wb") as f:
        f.write(clean_bytes)
    print(f"หน้า index={page_idx} (PDF หน้า {page_idx + 1}), ภาพ {pix.width}x{pix.height}px, "
          f"{len(png_bytes):,} bytes -> ลบลายน้ำแล้วบันทึกเป็น probe_clean.png "
          f"({len(clean_bytes):,} bytes)\n")

    payload = {
        "model": MODEL_OCR,
        "messages": [{
            "role": "user",
            "content": TYPHOON_PROMPT,
            "images": [base64.b64encode(clean_bytes).decode()],
        }],
        "stream": True,
        "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 1200},
    }

    print("=" * 70)
    print("  เนื้อหาที่โมเดลพิมพ์ออกมาสดๆ (จะหยุดเองถ้าโดน abort):")
    print("=" * 70)
    full = []
    try:
        with requests.post(f"{OLLAMA_HOST}/api/chat", json=payload,
                            stream=True, timeout=900) as r:
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    print(f"\n[ไม่ใช่ JSON บรรทัดนี้]: {line[:300]}")
                    continue
                if "error" in chunk:
                    print(f"\n\n❌ ERROR จาก Ollama: {chunk['error']}")
                    break
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    full.append(piece)
                    print(piece, end="", flush=True)
                if chunk.get("done"):
                    print(f"\n\n[จบปกติ, done_reason={chunk.get('done_reason')}]")
                    break
    except requests.exceptions.HTTPError as e:
        print(f"\n\n❌ HTTP error: {e}")
    except Exception as e:
        print(f"\n\n❌ Exception: {e}")

    text = "".join(full)
    print("\n\n" + "=" * 70)
    print(f"  รวมได้ {len(text):,} ตัวอักษรก่อนหยุด")
    print("=" * 70)
    if len(text) > 200:
        print("\n--- 300 ตัวอักษรสุดท้ายก่อนหยุด ---")
        print(text[-300:])


if __name__ == "__main__":
    main()