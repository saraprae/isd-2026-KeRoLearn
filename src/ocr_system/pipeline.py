from pathlib import Path
import cv2
from .config import OCRConfig
from .document_loader import load_document_pages
from .engine_factory import build_engine
from .preprocessing import read_image, preprocess_image, save_debug_image
from .schemas import OCRDocumentResult, OCRPageResult
from .utils.io import ensure_dir, save_json, save_text


def run_ocr(config: OCRConfig) -> OCRDocumentResult:
    output_dir = ensure_dir(config.output_dir)
    page_dir = ensure_dir(config.page_image_dir)
    pages = load_document_pages(config.input_path, page_dir, dpi=config.dpi)
    engine = build_engine(config)

    page_results: list[OCRPageResult] = []
    for page_no, image_path in enumerate(pages, start=1):
        image = read_image(image_path)
        if config.preprocess:
            image_for_ocr = preprocess_image(image, deskew=config.deskew)
            if config.save_debug_images:
                debug_path = output_dir / "debug" / f"page_{page_no:03d}_preprocessed.png"
                save_debug_image(image_for_ocr, debug_path)
        else:
            image_for_ocr = image

        lines = engine.recognize(image_for_ocr, page=page_no)
        if config.min_confidence > 0:
            lines = [x for x in lines if x.confidence is None or x.confidence >= config.min_confidence]

        text = "\n".join(line.text for line in lines if line.text.strip())
        page_results.append(OCRPageResult(page=page_no, text=text, lines=lines, image_path=str(image_path)))

    full_text = "\n\n".join(f"--- Page {p.page} ---\n{p.text}" for p in page_results)
    result = OCRDocumentResult(
        source_path=str(config.input_path),
        engine=engine.name,
        text=full_text,
        pages=page_results,
    )

    stem = Path(config.input_path).stem
    save_json(result.to_dict(), output_dir / f"{stem}_ocr.json")
    save_text(result.text, output_dir / f"{stem}_ocr.txt")
    return result
