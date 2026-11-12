"""Testy metod steganografii DCT (JSteg, JSteg-MF, F5), wspólnego API i regresji."""

from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from steganografia import (
    F5_DEFAULT_KEY,
    FrameError,
    HEADER_SIZE,
    ImageError,
    f5_capacity_from_jpeg,
    f5_capacity_from_png,
    f5_embed_jpeg,
    f5_extract_jpeg,
    jsteg_embed_jpeg,
    jsteg_extract_jpeg,
    jsteg_jpeg_capacity_bytes,
    jsteg_png_jpeg_capacity_bytes,
    load_cover,
    pack,
    read_jpeg,
    unpack,
    write_jpeg,
)
from steganografia.api import (
    METHOD_REGISTRY,
    MethodNotFoundError,
    load_png_from_bytes,
)
from steganografia.cli import main

TEKST_PL = "Zażółć gęślą jaźń — test steganografii DCT 123!"


@pytest.fixture
def textured_png(tmp_path) -> Path:
    """Obraz 128x128 o bogatej teksturze zapewniający dużo niezerowych współczynników AC."""
    sciezka = tmp_path / "textured.png"
    rng = np.random.default_rng(42)
    obraz = rng.integers(10, 245, size=(128, 128, 3), dtype=np.uint8)
    Image.fromarray(obraz).save(sciezka)
    return sciezka


# ---------------------------------------------------------------------------
# 1. Wspólna tabela testów dla wszystkich metod przez wspólne API (S2-03 / S2-04)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method_name", ["lsb", "jsteg", "jsteg-mf", "f5"])
@pytest.mark.parametrize(
    "wiadomosc",
    [
        "",
        "Krótki tekst ASCII",
        TEKST_PL,
    ],
)
def test_wspolne_api_roundtrip_wszystkie_metody(textured_png, method_name, wiadomosc):
    """Każda zarejestrowana metoda ukrywa i odzyskuje identyczny payload przez wspólne API."""
    method = METHOD_REGISTRY.get(method_name)
    cover_bytes = textured_png.read_bytes()

    stats = method.capacity_bytes(cover_bytes)
    assert stats["capacity_bytes"] >= HEADER_SIZE
    assert stats["payload_capacity_bytes"] == stats["capacity_bytes"] - HEADER_SIZE

    artifact = method.embed_bytes(cover_bytes, wiadomosc)
    assert artifact.data
    odzyskany = method.extract_bytes(artifact.data)
    assert odzyskany == wiadomosc


@pytest.mark.parametrize("method_name", ["lsb", "jsteg", "jsteg-mf", "f5"])
def test_wspolne_api_przekroczenie_pojemnosci_daje_blad(textured_png, method_name):
    """Przekroczenie pojemności netto o 1 bajt jest odrzucane dla każdej metody."""
    method = METHOD_REGISTRY.get(method_name)
    cover_bytes = textured_png.read_bytes()
    limit = method.capacity_bytes(cover_bytes)["payload_capacity_bytes"]

    za_dlugi = "x" * (limit + 1)
    with pytest.raises(FrameError, match="przekracza pojemność obrazu"):
        method.embed_bytes(cover_bytes, za_dlugi)


def test_rejestr_metod_zawiera_wszystkie_metody_i_zglasza_blad_dla_nieznanej():
    names = METHOD_REGISTRY.names()
    assert set(names) == {"lsb", "jsteg", "jsteg-mf", "f5"}
    meta = {m["name"]: m for m in METHOD_REGISTRY.metadata()}
    assert meta["lsb"]["output_format"] == "png"
    assert meta["jsteg"]["output_format"] == "jpeg"
    assert meta["f5"]["output_format"] == "jpeg"

    with pytest.raises(MethodNotFoundError):
        METHOD_REGISTRY.get("nieistniejaca-metoda")


def test_load_png_from_bytes_nieznany_tryb(textured_png):
    with pytest.raises(ValueError, match="Nieznany tryb wczytania PNG"):
        load_png_from_bytes(textured_png.read_bytes(), mode="nieznany")


# ---------------------------------------------------------------------------
# 2. Testy rdzenia JSteg i JSteg-MF (S2-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mf", [False, True])
def test_jsteg_pelny_zapis_i_odczyt_jpeg(textured_png, tmp_path, mf):
    wyjscie = tmp_path / ("wynik_mf.jpg" if mf else "wynik.jpg")
    obraz = load_cover(textured_png)
    pojemnosc = jsteg_png_jpeg_capacity_bytes(obraz, mf=mf)
    assert pojemnosc > HEADER_SIZE

    ramka = pack(TEKST_PL, capacity_bytes=pojemnosc)
    jsteg_embed_jpeg(str(textured_png), str(wyjscie), ramka, mf=mf)

    assert wyjscie.exists()
    odzyskana_ramka = jsteg_extract_jpeg(str(wyjscie), mf=mf)
    pojemnosc_jpg = jsteg_jpeg_capacity_bytes(str(wyjscie), mf=mf)
    assert unpack(odzyskana_ramka, capacity_bytes=pojemnosc_jpg) == TEKST_PL


def test_jsteg_na_granicy_pojemnosci_i_przekroczenie(textured_png, tmp_path):
    obraz = load_cover(textured_png)
    pojemnosc = jsteg_png_jpeg_capacity_bytes(obraz, mf=False)
    limit_netto = pojemnosc - HEADER_SIZE

    pelny_tekst = "a" * limit_netto
    ramka = pack(pelny_tekst, capacity_bytes=pojemnosc)
    wyjscie = tmp_path / "styk.jpg"
    jsteg_embed_jpeg(str(textured_png), str(wyjscie), ramka, mf=False)
    odzyskana = jsteg_extract_jpeg(str(wyjscie), mf=False)
    assert unpack(odzyskana, capacity_bytes=pojemnosc) == pelny_tekst

    with pytest.raises(FrameError):
        pack("a" * (limit_netto + 1), capacity_bytes=pojemnosc)


def test_jsteg_uszkodzenie_wspolczynnika_wykryte_przez_crc(textured_png, tmp_path):
    wyjscie = tmp_path / "uszkodzony.jpg"
    obraz = load_cover(textured_png)
    pojemnosc = jsteg_png_jpeg_capacity_bytes(obraz)
    ramka = pack(TEKST_PL, capacity_bytes=pojemnosc)
    jsteg_embed_jpeg(str(textured_png), str(wyjscie), ramka)

    coeffs = read_jpeg(wyjscie)
    zmieniono = 0
    licznik_niezerowych = 0
    for block in coeffs.y_blocks:
        for pos in range(1, 64):
            if block[pos] != 0:
                licznik_niezerowych += 1
                if licznik_niezerowych == HEADER_SIZE * 8 + 5:
                    block[pos] = block[pos] + (1 if block[pos] > 0 else -1)
                    zmieniono += 1
                    break
        if zmieniono:
            break

    uszkodzony_plik = tmp_path / "uszkodzony_crc.jpg"
    write_jpeg(
        uszkodzony_plik,
        width=coeffs.width,
        height=coeffs.height,
        y_blocks=coeffs.y_blocks,
        cb_blocks=coeffs.cb_blocks,
        cr_blocks=coeffs.cr_blocks,
    )
    with pytest.raises(FrameError, match="CRC32"):
        jsteg_extract_jpeg(str(uszkodzony_plik))


# ---------------------------------------------------------------------------
# 3. Testy rdzenia F5 (S2-02)
# ---------------------------------------------------------------------------


def test_f5_pelny_zapis_odczyt_i_klucz(textured_png, tmp_path):
    wyjscie = tmp_path / "f5.jpg"
    obraz = load_cover(textured_png)
    pojemnosc = f5_capacity_from_png(obraz)
    assert pojemnosc > HEADER_SIZE

    ramka = pack(TEKST_PL, capacity_bytes=pojemnosc)
    f5_embed_jpeg(str(textured_png), str(wyjscie), ramka, key="tajne-haslo")

    odzyskana = f5_extract_jpeg(str(wyjscie), key="tajne-haslo")
    pojemnosc_jpg = f5_capacity_from_jpeg(str(wyjscie))
    assert unpack(odzyskana, capacity_bytes=pojemnosc_jpg) == TEKST_PL

    with pytest.raises(FrameError):
        f5_extract_jpeg(str(wyjscie), key="inny-klucz")


def test_f5_ochrona_przed_nadpisaniem(textured_png, tmp_path):
    wyjscie = tmp_path / "f5_overwrite.jpg"
    obraz = load_cover(textured_png)
    ramka = pack("test", capacity_bytes=f5_capacity_from_png(obraz))
    f5_embed_jpeg(str(textured_png), str(wyjscie), ramka)

    with pytest.raises(ImageError, match="już istnieje"):
        f5_embed_jpeg(str(textured_png), str(wyjscie), ramka, overwrite=False)

    f5_embed_jpeg(str(textured_png), str(wyjscie), ramka, overwrite=True)


# ---------------------------------------------------------------------------
# 4. Przypadki brzegowe obrazów: wymiary niepodzielne przez 8, wartości 0/255, niski kontrast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rozmiar", [(83, 91), (95, 77), (100, 100)])
@pytest.mark.parametrize("method_name", ["jsteg", "f5"])
def test_dct_wymiary_niepodzielne_przez_8_oraz_blisko_0_255(tmp_path, rozmiar, method_name):
    """Testy dla wymiarów niepodzielnych przez 8 oraz pikseli blisko granic 0 i 255."""
    wys, szer = rozmiar
    rng = np.random.default_rng(123)
    baza = rng.choice([0, 255], size=(wys, szer, 3)).astype(np.int16)
    szum = rng.integers(-12, 13, size=(wys, szer, 3), dtype=np.int16)
    obraz = np.clip(baza + szum, 0, 255).astype(np.uint8)

    sciezka = tmp_path / f"brzeg_{wys}x{szer}.png"
    Image.fromarray(obraz).save(sciezka)

    method = METHOD_REGISTRY.get(method_name)
    artifact = method.embed_bytes(sciezka.read_bytes(), "Test wymiarów niepodzielnych przez 8")
    assert method.extract_bytes(artifact.data) == "Test wymiarów niepodzielnych przez 8"


def test_dct_obraz_jednolity_niski_kontrast_jawnie_odrzucany(tmp_path):
    """Jednolity obraz o zerowych współczynnikach AC ma pojemność 0 B i jest jawnie odrzucany."""
    jednolity = tmp_path / "plaski.png"
    Image.fromarray(np.full((64, 64, 3), 128, dtype=np.uint8)).save(jednolity)

    obraz = load_cover(jednolity)
    assert jsteg_png_jpeg_capacity_bytes(obraz) == 0
    assert f5_capacity_from_png(obraz) == 0

    with pytest.raises(FrameError, match="nie mieści nagłówka"):
        METHOD_REGISTRY.get("jsteg").embed_bytes(jednolity.read_bytes(), "tekst")


# ---------------------------------------------------------------------------
# 5. Testy CLI dla podkomend jsteg, jsteg-mf, f5 oraz lsb (S2-03)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcmd", ["jsteg", "jsteg-mf", "f5"])
def test_cli_dct_capacity_embed_extract(textured_png, tmp_path, capsys, subcmd):
    wyjscie_jpg = tmp_path / f"wynik_{subcmd}.jpg"
    wyjscie_txt = tmp_path / f"odzyskany_{subcmd}.txt"

    # 1. Capacity
    assert main([subcmd, "capacity", str(textured_png)]) == 0
    out = capsys.readouterr().out
    assert "B ramki" in out

    # 2. Embed z --text
    assert main([subcmd, "embed", str(textured_png), str(wyjscie_jpg), "--text", TEKST_PL]) == 0
    capsys.readouterr()
    assert wyjscie_jpg.exists()

    # 3. Ochrona przed nadpisaniem obrazu wynikowego bez --overwrite
    assert main([subcmd, "embed", str(textured_png), str(wyjscie_jpg), "--text", "inny"]) == 1
    assert "już istnieje" in capsys.readouterr().err

    # 4. Extract na stdout
    assert main([subcmd, "extract", str(wyjscie_jpg)]) == 0
    assert capsys.readouterr().out.strip() == TEKST_PL

    # 5. Extract do pliku i blokada nadpisania bez --overwrite
    assert main([subcmd, "extract", str(wyjscie_jpg), "--output", str(wyjscie_txt)]) == 0
    assert wyjscie_txt.read_text(encoding="utf-8") == TEKST_PL
    assert main([subcmd, "extract", str(wyjscie_jpg), "--output", str(wyjscie_txt)]) == 1
    assert "już istnieje" in capsys.readouterr().err
    assert main([subcmd, "extract", str(wyjscie_jpg), "--output", str(wyjscie_txt), "--overwrite"]) == 0


def test_cli_f5_z_wlasnym_kluczem(textured_png, tmp_path, capsys):
    wyjscie_jpg = tmp_path / "f5_klucz.jpg"
    assert main([
        "f5", "embed", str(textured_png), str(wyjscie_jpg),
        "--text", "Sekret F5", "--key", "moje-haslo-123"
    ]) == 0
    capsys.readouterr()

    # Błędny klucz daje kod wyjścia 1
    assert main(["f5", "extract", str(wyjscie_jpg), "--key", "zle-haslo"]) == 1
    assert "niepoprawna ramka STEG" in capsys.readouterr().err

    # Poprawny klucz odzyskuje wiadomość
    assert main(["f5", "extract", str(wyjscie_jpg), "--key", "moje-haslo-123"]) == 0
    assert capsys.readouterr().out.strip() == "Sekret F5"