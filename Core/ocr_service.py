"""Central OCR adapter with PaddleOCR backend."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

OCR_ENGINE_PADDLE = "paddle"
_VALID_ENGINES = {OCR_ENGINE_PADDLE}

_OCR_DATA_KEYS: Tuple[str, ...] = (
    "text",
    "conf",
    "left",
    "top",
    "width",
    "height",
    "block_num",
    "par_num",
    "line_num",
)

_PADDLE_INSTANCES: Dict[str, Any] = {}
_PADDLE_INIT_ERRORS: Dict[str, str] = {}
_LOGGED_EVENTS: set[str] = set()
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _log_ocr_once(event_key: str, message: str) -> None:
    key = str(event_key or "").strip()
    if not key:
        key = message
    if key in _LOGGED_EVENTS:
        return
    _LOGGED_EVENTS.add(key)
    print(f"[OCR] {message}")


def normalize_ocr_engine(engine: str) -> str:
    normalized = str(engine or "").strip().lower()
    if normalized and normalized not in _VALID_ENGINES:
        _log_ocr_once("engine-ignored", f"OCR engine '{normalized}' ignored; using PaddleOCR")
    return OCR_ENGINE_PADDLE


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _empty_ocr_data() -> Dict[str, List[Any]]:
    return {key: [] for key in _OCR_DATA_KEYS}


def _to_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _normalize_ocr_shape(data: Any) -> Dict[str, List[Any]]:
    if not isinstance(data, dict):
        return _empty_ocr_data()

    normalized: Dict[str, List[Any]] = {}
    max_len = 0
    for key in _OCR_DATA_KEYS:
        values = _to_list(data.get(key, []))
        normalized[key] = values
        max_len = max(max_len, len(values))

    defaults: Dict[str, Any] = {
        "text": "",
        "conf": "-1",
        "left": 0,
        "top": 0,
        "width": 0,
        "height": 0,
        "block_num": 0,
        "par_num": 0,
        "line_num": 0,
    }
    for key in _OCR_DATA_KEYS:
        values = normalized[key]
        if len(values) < max_len:
            values.extend([defaults[key]] * (max_len - len(values)))
    return normalized


def _has_meaningful_text(data: Dict[str, List[Any]]) -> bool:
    for raw in data.get("text", []):
        if _clean_text(raw):
            return True
    return False


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _paddle_lang_for(lang: str) -> str:
    text = str(lang or "").strip().lower()
    if text in {"eng", "en"}:
        return "en"
    if len(text) >= 2:
        return text[:2]
    return "en"


def _get_paddle_instance(lang: str) -> Any:
    paddle_lang = _paddle_lang_for(lang)
    existing = _PADDLE_INSTANCES.get(paddle_lang)
    if existing is not None:
        return existing

    cached_error = _PADDLE_INIT_ERRORS.get(paddle_lang)
    if cached_error:
        raise RuntimeError(cached_error)

    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        message = f"PaddleOCR import failed ({exc})"
        _PADDLE_INIT_ERRORS[paddle_lang] = message
        raise RuntimeError(message) from exc

    constructor_attempts = [
        {"use_angle_cls": True, "lang": paddle_lang, "show_log": False},
        {"use_angle_cls": True, "lang": paddle_lang},
    ]

    last_exc: Optional[Exception] = None
    for kwargs in constructor_attempts:
        try:
            instance = PaddleOCR(**kwargs)
        except TypeError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            if ("show_log" in kwargs) and ("show_log" in str(exc)):
                last_exc = exc
                continue
            message = f"PaddleOCR init failed ({exc})"
            _PADDLE_INIT_ERRORS[paddle_lang] = message
            raise RuntimeError(message) from exc
        _PADDLE_INSTANCES[paddle_lang] = instance
        return instance

    message = f"PaddleOCR init failed ({last_exc})"
    _PADDLE_INIT_ERRORS[paddle_lang] = message
    raise RuntimeError(message)


def _to_paddle_input(image: Any) -> Any:
    if isinstance(image, str):
        return image

    try:
        from PIL import Image as PILImage
    except Exception:
        PILImage = None  # type: ignore[assignment]

    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError(f"numpy import failed ({exc})") from exc

    if PILImage is not None and isinstance(image, PILImage.Image):
        return np.array(image.convert("RGB"))
    return np.array(image)


def _is_paddle_line_entry(value: Any) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return False
    box = value[0]
    meta = value[1]
    if not isinstance(box, (list, tuple)) or not box:
        return False
    first_point = box[0]
    if not isinstance(first_point, (list, tuple)) or len(first_point) < 2:
        return False
    if isinstance(meta, dict):
        return True
    if isinstance(meta, str):
        return True
    if isinstance(meta, (list, tuple)) and len(meta) > 0:
        return isinstance(meta[0], str)
    return False


def _flatten_paddle_entries(raw_result: Any) -> List[Any]:
    if raw_result is None:
        return []

    entries: List[Any] = []
    if _is_paddle_line_entry(raw_result):
        entries.append(raw_result)
        return entries

    if not isinstance(raw_result, (list, tuple)):
        return entries

    for item in raw_result:
        if _is_paddle_line_entry(item):
            entries.append(item)
            continue
        if not isinstance(item, (list, tuple)):
            continue
        for nested in item:
            if _is_paddle_line_entry(nested):
                entries.append(nested)
    return entries


def _normalize_paddle_to_ocr(raw_result: Any) -> Dict[str, List[Any]]:
    entries = _flatten_paddle_entries(raw_result)
    if not entries:
        return _empty_ocr_data()

    records: List[Dict[str, Any]] = []
    for entry in entries:
        box = entry[0] if len(entry) > 0 else None
        meta = entry[1] if len(entry) > 1 else None

        text = ""
        score = -1.0
        if isinstance(meta, (list, tuple)):
            text = _clean_text(meta[0] if len(meta) > 0 else "")
            score = _coerce_float(meta[1], -1.0) if len(meta) > 1 else -1.0
        elif isinstance(meta, dict):
            text = _clean_text(meta.get("text", ""))
            score = _coerce_float(meta.get("score", -1.0), -1.0)
        else:
            text = _clean_text(meta)

        if not text:
            continue

        if not isinstance(box, (list, tuple)):
            continue
        xs: List[float] = []
        ys: List[float] = []
        for point in box:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            xs.append(_coerce_float(point[0], 0.0))
            ys.append(_coerce_float(point[1], 0.0))
        if not xs or not ys:
            continue

        left = min(xs)
        top = min(ys)
        right = max(xs)
        bottom = max(ys)
        records.append(
            {
                "text": text,
                "conf": max(-1.0, min(100.0, score * 100.0)) if score >= 0 else -1.0,
                "left": max(0.0, left),
                "top": max(0.0, top),
                "width": max(0.0, right - left),
                "height": max(0.0, bottom - top),
            }
        )

    if not records:
        return _empty_ocr_data()

    records.sort(key=lambda row: (float(row["top"]), float(row["left"])))
    avg_height = sum(max(1.0, float(row["height"])) for row in records) / max(1, len(records))
    line_threshold = max(8.0, min(26.0, avg_height * 0.65))

    line_num = 0
    reference_y: Optional[float] = None
    output = _empty_ocr_data()
    for row in records:
        y = float(row["top"])
        if reference_y is None or abs(y - reference_y) > line_threshold:
            line_num += 1
            reference_y = y
        else:
            reference_y = (reference_y * 0.6) + (y * 0.4)

        output["text"].append(row["text"])
        output["conf"].append(row["conf"])
        output["left"].append(int(round(float(row["left"]))))
        output["top"].append(int(round(float(row["top"]))))
        output["width"].append(int(round(float(row["width"]))))
        output["height"].append(int(round(float(row["height"]))))
        output["block_num"].append(1)
        output["par_num"].append(1)
        output["line_num"].append(line_num)
    return output


def _run_paddle_ocr_raw(image: Any, lang: str) -> Any:
    ocr = _get_paddle_instance(lang)
    payload = _to_paddle_input(image)
    try:
        return ocr.ocr(payload, cls=True)
    except TypeError:
        return ocr.ocr(payload)


def _ocr_with_paddle(image: Any, lang: str) -> Dict[str, List[Any]]:
    raw = _run_paddle_ocr_raw(image, lang)
    return _normalize_ocr_shape(_normalize_paddle_to_ocr(raw))


def ocr_image_to_data(image: Any, *, lang: str = "eng", engine: str = OCR_ENGINE_PADDLE) -> Dict[str, List[Any]]:
    normalize_ocr_engine(engine)
    try:
        result = _ocr_with_paddle(image, lang)
    except Exception as exc:
        _log_ocr_once("paddle-failed", f"PaddleOCR failed ({exc})")
        return _empty_ocr_data()

    if _has_meaningful_text(result):
        return result
    _log_ocr_once("paddle-empty", "PaddleOCR returned empty output")
    return _empty_ocr_data()


def _iter_ocr_rows(data: Dict[str, List[Any]]) -> Iterable[Tuple[float, float, int, int, int, str]]:
    count = len(data.get("text", []) or [])
    if count <= 0:
        return []

    rows: List[Tuple[float, float, int, int, int, str]] = []
    for idx in range(count):
        text = _clean_text((data.get("text", []) or [""])[idx] if idx < len(data.get("text", [])) else "")
        if not text:
            continue
        top = _coerce_float((data.get("top", []) or [0])[idx] if idx < len(data.get("top", [])) else 0, 0.0)
        left = _coerce_float((data.get("left", []) or [0])[idx] if idx < len(data.get("left", [])) else 0, 0.0)
        block = _coerce_int((data.get("block_num", []) or [0])[idx] if idx < len(data.get("block_num", [])) else 0, 0)
        para = _coerce_int((data.get("par_num", []) or [0])[idx] if idx < len(data.get("par_num", [])) else 0, 0)
        line = _coerce_int((data.get("line_num", []) or [0])[idx] if idx < len(data.get("line_num", [])) else 0, 0)
        rows.append((top, left, block, para, line, text))
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def ocr_image_to_text(image: Any, *, lang: str = "eng", engine: str = OCR_ENGINE_PADDLE) -> str:
    data = ocr_image_to_data(image, lang=lang, engine=engine)
    rows = list(_iter_ocr_rows(data))
    if not rows:
        return ""

    grouped: Dict[Tuple[int, int, int], List[str]] = {}
    ordered_keys: List[Tuple[int, int, int]] = []
    for top, _left, block, para, line, text in rows:
        if line > 0:
            key = (block, para, line)
        else:
            key = (block, para, int(round(top / 10.0)))
        if key not in grouped:
            grouped[key] = []
            ordered_keys.append(key)
        grouped[key].append(text)

    return "\n".join(_clean_text(" ".join(grouped[key])) for key in ordered_keys if grouped[key]).strip()


def warmup_ocr_runtime(*, engine: str = OCR_ENGINE_PADDLE) -> None:
    normalize_ocr_engine(engine)
    try:
        from paddleocr import PaddleOCR as _PaddleOCR  # noqa: F401
    except Exception as exc:
        _log_ocr_once("paddle-warmup-failed", f"PaddleOCR warmup skipped ({exc})")
