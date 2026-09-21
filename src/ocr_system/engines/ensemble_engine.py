import numpy as np
from .base import BaseOCREngine
from .paddle_engine import PaddleOCREngine
from .tesseract_engine import TesseractOCREngine
from ocr_system.schemas import OCRLine


class EnsembleOCREngine(BaseOCREngine):
    name = "ensemble"

    def __init__(self, paddle_lang: str = "th", tesseract_languages: str = "tha+eng"):
        self.engines = [
            PaddleOCREngine(lang=paddle_lang),
            TesseractOCREngine(languages=tesseract_languages),
        ]

    def recognize(self, image: np.ndarray, page: int | None = None) -> list[OCRLine]:
        paddle_result = self.engines[0].recognize(image, page=page)
        tesseract_result = self.engines[1].recognize(image, page=page)

        return self.merge(
            paddle_result,
            tesseract_result=tesseract_result,
        )

    def merge(
        self,
        paddle_result: list[OCRLine],
        tesseract_result: list[OCRLine] | None = None,
        trocr_result: list[OCRLine] | None = None,
    ) -> list[OCRLine]:
        candidates: list[OCRLine] = []
        candidates.extend(paddle_result or [])
        candidates.extend(tesseract_result or [])
        candidates.extend(trocr_result or [])

        # Simple production-safe default: keep all lines, sorted top-to-bottom if boxes exist.
        # Dedup exact repeated text while preserving stronger confidence.
        best: dict[str, OCRLine] = {}
        for line in candidates:
            key = line.text.strip()
            if not key:
                continue
            if key not in best:
                best[key] = line
            else:
                old_conf = best[key].confidence or 0.0
                new_conf = line.confidence or 0.0
                if new_conf > old_conf:
                    best[key] = line

        lines = list(best.values())
        lines.sort(key=lambda x: _box_top(x.box))
        return lines


def _box_top(box) -> float:
    if not box:
        return 10**9
    try:
        return min(float(p[1]) for p in box)
    except Exception:
        return 10**9
