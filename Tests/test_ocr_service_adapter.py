from Core import ocr_service


def _sample_ocr_payload(text: str = "sample") -> dict[str, list[object]]:
    return {
        "text": [text],
        "conf": [92.0],
        "left": [10],
        "top": [20],
        "width": [30],
        "height": [12],
        "block_num": [1],
        "par_num": [1],
        "line_num": [1],
    }


def test_ocr_returns_empty_when_paddle_raises(monkeypatch):
    def _raise_paddle(_image, _lang):
        raise RuntimeError("paddle failed")

    monkeypatch.setattr(ocr_service, "_ocr_with_paddle", _raise_paddle)

    data = ocr_service.ocr_image_to_data(object(), engine="paddle")
    assert data["text"] == []


def test_ocr_returns_empty_when_paddle_returns_empty(monkeypatch):
    monkeypatch.setattr(ocr_service, "_ocr_with_paddle", lambda _image, _lang: ocr_service._empty_ocr_data())

    data = ocr_service.ocr_image_to_data(object(), engine="paddle")
    assert data["text"] == []


def test_paddle_normalization_returns_ocr_shape_and_reading_order():
    raw = [
        [
            [[[40, 80], [180, 80], [180, 110], [40, 110]], ("Second line", 0.91)],
            [[[20, 25], [130, 25], [130, 55], [20, 55]], ("First line", 0.96)],
        ]
    ]

    normalized = ocr_service._normalize_paddle_to_ocr(raw)

    assert set(normalized.keys()) == {
        "text",
        "conf",
        "left",
        "top",
        "width",
        "height",
        "block_num",
        "par_num",
        "line_num",
    }
    assert normalized["text"] == ["First line", "Second line"]
    assert normalized["line_num"] == [1, 2]
    assert normalized["top"][0] < normalized["top"][1]


def test_legacy_engine_values_still_use_paddle(monkeypatch):
    calls: list[str] = []

    def _paddle(_image, _lang):
        calls.append("paddle")
        return _sample_ocr_payload("paddle only")

    monkeypatch.setattr(ocr_service, "_ocr_with_paddle", _paddle)

    data = ocr_service.ocr_image_to_data(object(), engine="auto")
    assert calls == ["paddle"]
    assert data["text"] == ["paddle only"]
