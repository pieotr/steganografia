"""Testy integracyjne Sprintu 3: wspólne API (LSB, DCT, JSteg-MF, F5), restart i zakłócenia."""

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from steganografia.api import (
    METHOD_REGISTRY,
    SteganographyRegistry,
    LSBMethod,
    DCTMethod,
    JStegMethod,
    JStegMFMethod,
    F5Method,
    read_jpeg_bytes,
)

TEKST_PL = "Zażółć gęślą jaźń — test API Sprint 3!"


@pytest.fixture
def cover_png(tmp_path) -> Path:
    sciezka = tmp_path / "cover_s3.png"
    rng = np.random.default_rng(99)
    obraz = rng.integers(15, 240, size=(128, 128, 3), dtype=np.uint8)
    Image.fromarray(obraz).save(sciezka)
    return sciezka


def _fresh_registry() -> SteganographyRegistry:
    """Symuluje czystą instancję aplikacji po restarcie (brak stanu poprzedniej sesji)."""
    reg = SteganographyRegistry()
    reg.register(LSBMethod())
    reg.register(DCTMethod())
    reg.register(JStegMethod())
    reg.register(JStegMFMethod())
    reg.register(F5Method())
    return reg


def test_metoda_dct_w_rejestrze_i_read_jpeg_bytes(cover_png):
    assert "dct" in METHOD_REGISTRY.names()
    dct = METHOD_REGISTRY.get("dct")
    artifact = dct.embed_bytes(cover_png.read_bytes(), TEKST_PL)
    assert artifact.extension == ".jpg"
    assert dct.extract_bytes(artifact.data) == TEKST_PL

    stream = io.BytesIO(artifact.data)
    assert read_jpeg_bytes(stream) == artifact.data
    with pytest.raises(ValueError, match="JPEG"):
        read_jpeg_bytes(io.BytesIO(cover_png.read_bytes()))


@pytest.mark.parametrize("method_name", ["lsb", "dct", "jsteg-mf", "f5"])
def test_s3_pelny_scenariusz_restart_i_zaklocenia(cover_png, tmp_path, method_name):
    """Weryfikacja kryteriów S3-01 i S3-04:
    wczytaj -> osadź -> zapisz -> otwórz po restarcie -> odczytaj -> zakłóć -> sprawdź.
    """
    method = METHOD_REGISTRY.get(method_name)

    # 1. Sprawdzenie pojemności netto
    stats = method.capacity_bytes(cover_png.read_bytes())
    assert stats["payload_capacity_bytes"] >= len(TEKST_PL.encode("utf-8"))

    # 2. Osadzenie wiadomości i zapis pliku wynikowego na dysk
    artifact = method.embed_bytes(cover_png.read_bytes(), TEKST_PL)
    saved_file = tmp_path / f"wynik_{method_name}{artifact.extension}"
    saved_file.write_bytes(artifact.data)

    # 3. Restart aplikacji (nowy rejestr bez stanu sesji) i odczyt z samego pliku
    fresh_method = _fresh_registry().get(method_name)
    assert fresh_method.extract_bytes(saved_file.read_bytes()) == TEKST_PL

    # 4. Zakłócenie obrazu przez stratną rekompresję JPEG (niszczy LSB i zmienia współczynniki DCT)
    jpg_buf = io.BytesIO()
    Image.open(io.BytesIO(artifact.data)).save(jpg_buf, format="JPEG", quality=50)
    if method_name == "lsb":
        corrupted_png = io.BytesIO()
        Image.open(io.BytesIO(jpg_buf.getvalue())).save(corrupted_png, format="PNG")
        corrupted_bytes = corrupted_png.getvalue()
    else:
        corrupted_bytes = jpg_buf.getvalue()

    with pytest.raises(Exception):
        fresh_method.extract_bytes(corrupted_bytes)


def test_http_endpoints_jesli_flask_dostepny(cover_png, tmp_path):
    """Opcjonalny test endpointów Flask, uruchamiany gdy zainstalowany jest Flask."""
    pytest.importorskip("flask")
    import base64
    from steganografia.server import create_app

    client = create_app(frontend_dir=tmp_path).test_client()
    assert client.get("/api/v1/health").status_code == 200

    res_emb = client.post(
        "/api/v1/dct/embed",
        data={
            "file": (io.BytesIO(cover_png.read_bytes()), "cover.png"),
            "text": TEKST_PL,
        },
        content_type="multipart/form-data",
    )
    assert res_emb.status_code == 200
    encoded = base64.b64decode(res_emb.get_json()["image_base64"])

    res_ext = client.post(
        "/api/v1/dct/extract",
        data={"file": (io.BytesIO(encoded), "wynik.jpg")},
        content_type="multipart/form-data",
    )
    assert res_ext.status_code == 200
    assert res_ext.get_json()["text"] == TEKST_PL