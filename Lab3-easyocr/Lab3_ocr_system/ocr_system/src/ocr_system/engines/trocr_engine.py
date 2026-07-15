import cv2
import numpy as np
from PIL import Image
from .base import BaseOCREngine
from ocr_system.schemas import OCRLine


class TrOCREngine(BaseOCREngine):
    name = "trocr"

    def __init__(self, model_name: str = "microsoft/trocr-base-printed", device: str = "cpu"):
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        self.torch = torch
        self.device = device
        self.processor = TrOCRProcessor.from_pretrained(model_name)
        self.model = VisionEncoderDecoderModel.from_pretrained(model_name).to(device)
        self.model.eval()

    def recognize(self, image: np.ndarray, page: int | None = None) -> list[OCRLine]:
        # TrOCR works best on cropped text lines. This fallback uses the whole page.
        # For production, pass detected line crops from Paddle/Tesseract boxes.
        if len(image.shape) == 2:
            rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        pixel_values = self.processor(images=pil, return_tensors="pt").pixel_values.to(self.device)
        with self.torch.no_grad():
            generated_ids = self.model.generate(pixel_values)
        text = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        return [OCRLine(text=text.strip(), confidence=None, box=None, engine=self.name, page=page)] if text.strip() else []
