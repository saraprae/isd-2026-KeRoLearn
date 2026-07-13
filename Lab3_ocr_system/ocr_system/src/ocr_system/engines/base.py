from abc import ABC, abstractmethod
import numpy as np
from ocr_system.schemas import OCRLine


class BaseOCREngine(ABC):
    name: str

    @abstractmethod
    def recognize(self, image: np.ndarray, page: int | None = None) -> list[OCRLine]:
        raise NotImplementedError
