import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from jiwer import wer
import Levenshtein


@dataclass
class EvaluationResult:
    file: str
    cer: float
    wer: float
    exact_match: bool
    reference_chars: int
    prediction_chars: int


def normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def char_error_rate(reference: str, prediction: str) -> float:
    ref = normalize_text(reference).replace(" ", "")
    hyp = normalize_text(prediction).replace(" ", "")
    if not ref:
        return 0.0 if not hyp else 1.0
    return Levenshtein.distance(ref, hyp) / len(ref)


def evaluate_text(reference: str, prediction: str, file_name: str = "") -> EvaluationResult:
    ref = normalize_text(reference)
    hyp = normalize_text(prediction)
    return EvaluationResult(
        file=file_name,
        cer=char_error_rate(ref, hyp),
        wer=wer(ref, hyp) if ref else (0.0 if not hyp else 1.0),
        exact_match=ref == hyp,
        reference_chars=len(ref),
        prediction_chars=len(hyp),
    )


def evaluate_from_files(ground_truth_json: str | Path, prediction_json: str | Path) -> dict:
    with Path(ground_truth_json).open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)
    with Path(prediction_json).open("r", encoding="utf-8") as f:
        prediction = json.load(f)

    source_name = Path(prediction["source_path"]).name
    reference = ground_truth.get(source_name) or ground_truth.get(Path(source_name).stem)
    if reference is None:
        raise KeyError(f"No ground truth found for {source_name}")

    result = evaluate_text(reference, prediction["text"], file_name=source_name)
    return asdict(result)
