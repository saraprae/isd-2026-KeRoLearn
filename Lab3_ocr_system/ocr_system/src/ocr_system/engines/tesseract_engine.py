import cv2
import numpy as np
from .base import BaseOCREngine
from ocr_system.schemas import OCRLine


class TesseractOCREngine(BaseOCREngine):
    name = "tesseract"

    def __init__(self, languages: str = "tha+eng", psm: int = 6):
        import pytesseract
        self.pytesseract = pytesseract
        self.languages = languages
        self.config = f"--oem 3 --psm {psm}"

    def recognize(self, image: np.ndarray, page: int | None = None) -> list[OCRLine]:
        if len(image.shape) == 2:
            rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        data = self.pytesseract.image_to_data(
            rgb,
            lang=self.languages,
            config=self.config,
            output_type=self.pytesseract.Output.DICT,
        )
        lines: list[OCRLine] = []
        n = len(data["text"])
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i]) / 100.0
            except ValueError:
                conf = None
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            lines.append(OCRLine(text=text, confidence=conf, box=box, engine=self.name, page=page))
        return lines
