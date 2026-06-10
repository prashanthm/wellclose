"""OCR adapter (Brief §7B, ADR-003). Laptop defaults: Tesseract (and optional docTR via extras).
Common output schema: list of word blocks {text, conf, bbox:[x0,y0,x1,y1]} per page + quality score."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from PIL import Image
from .config import settings

ENGLISH_HINTS = {"the", "and", "well", "casing", "cement", "feet", "depth", "no", "of", "to", "date"}


@dataclass
class OCRPage:
    text: str
    blocks: list[dict]
    quality: float  # 0..1 (§7B ocr_quality_score)


class OCRAdapter(Protocol):
    def run(self, image: Image.Image) -> OCRPage: ...


def _quality(blocks: list[dict], text: str) -> float:
    if not blocks:
        return 0.0
    confs = [b["conf"] for b in blocks if b["conf"] >= 0]
    conf_score = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    words = [w.lower().strip(".,:;") for w in text.split()]
    dict_score = (sum(1 for w in words if w in ENGLISH_HINTS or w.isdigit()) / len(words)) if words else 0.0
    return round(0.7 * conf_score + 0.3 * min(1.0, dict_score * 3), 3)


class TesseractAdapter:
    def run(self, image: Image.Image) -> OCRPage:
        import pytesseract
        from pytesseract import Output
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
        blocks, words = [], []
        for i, txt in enumerate(data["text"]):
            if not txt.strip():
                continue
            conf = float(data["conf"][i])
            x, y, w, h = (data[k][i] for k in ("left", "top", "width", "height"))
            blocks.append({"text": txt, "conf": conf, "bbox": [x, y, x + w, y + h]})
            words.append(txt)
        text = " ".join(words)
        return OCRPage(text=text, blocks=blocks, quality=_quality(blocks, text))


class DocTRAdapter:
    def __init__(self) -> None:
        from doctr.models import ocr_predictor  # extras: pip install 'wellclose[ocr-doctr]'
        self._model = ocr_predictor(pretrained=True)

    def run(self, image: Image.Image) -> OCRPage:
        import numpy as np
        result = self._model([np.array(image.convert("RGB"))])
        page = result.pages[0]
        w, h = image.size
        blocks, words = [], []
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    (x0, y0), (x1, y1) = word.geometry
                    blocks.append({"text": word.value, "conf": float(word.confidence) * 100,
                                   "bbox": [x0 * w, y0 * h, x1 * w, y1 * h]})
                    words.append(word.value)
        text = " ".join(words)
        return OCRPage(text=text, blocks=blocks, quality=_quality(blocks, text))


def get_adapter() -> OCRAdapter:
    eng = settings().ocr_engine
    if eng == "doctr":
        return DocTRAdapter()
    return TesseractAdapter()
