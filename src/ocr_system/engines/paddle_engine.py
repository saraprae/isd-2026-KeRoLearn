import numpy as np
from .base import BaseOCREngine
from ocr_system.schemas import OCRLine


class PaddleOCREngine(BaseOCREngine):
    name = "paddle"

    def __init__(self, lang: str = "th"):
        from paddleocr import PaddleOCR
        self.model = PaddleOCR(use_angle_cls=True, lang=lang)

    def recognize(self, image: np.ndarray, page: int | None = None) -> list[OCRLine]:
        result = self.model.ocr(image, cls=True)
        lines: list[OCRLine] = []
        for block in result or []:
            for item in block or []:
                box = item[0]
                text = item[1][0]
                conf = float(item[1][1])
                lines.append(OCRLine(text=text, confidence=conf, box=box, engine=self.name, page=page))
        return lines
