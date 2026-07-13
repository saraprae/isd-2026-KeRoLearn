from .config import OCRConfig
from .engines.base import BaseOCREngine
from .engines.paddle_engine import PaddleOCREngine
from .engines.tesseract_engine import TesseractOCREngine
from .engines.trocr_engine import TrOCREngine
from .engines.ensemble_engine import EnsembleOCREngine


def build_engine(config: OCRConfig) -> BaseOCREngine:
    if config.engine == "paddle":
        return PaddleOCREngine(lang=config.paddle_lang)
    if config.engine == "tesseract":
        return TesseractOCREngine(languages=config.languages)
    if config.engine == "trocr":
        return TrOCREngine(model_name=config.trocr_model_name, device=config.device)
    if config.engine == "ensemble":
        return EnsembleOCREngine(paddle_lang=config.paddle_lang, tesseract_languages=config.languages)
    raise ValueError(f"Unknown OCR engine: {config.engine}")
