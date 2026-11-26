"""Testy Sprintu 4 (S5): nsF5, OutGuess, kontener STEGFILE, steganaliza, prymitywy DCT, disturb CLI i przypadki negatywne."""

import struct
import numpy as np
import pytest
from PIL import Image

import steganografia as steg
from steganografia import (
    FrameError,
    HEADER_SIZE,
    ImageError,
    LUMINANCE_QUANTIZATION,
    calibrate_dct_histogram_detector,
    chi_square_analysis,
    dct_block,
    dct_histogram_detection,
    dct_histogram_report,
    embed_frame,
    hellinger_distance,
    load_cover,
    nsf5_capacity_from_jpeg,
    nsf5_capacity_from_png,
    nsf5_embed_jpeg,
    nsf5_extract_jpeg,
    outguess_capacity_from_jpeg,
    outguess_capacity_from_png,
    outguess_embed_jpeg,
    outguess_extract_jpeg,
    pack,
    quantize_block,
    read_jpeg,
    zigzag_scan,
)
from steganografia.frame import pack_bytes, unpack_bytes
from steganografia.api import (
    METHOD_REGISTRY,
    decode_file_payload,
    encode_file_payload,
)
from steganografia.cli import main

TEKST_PL = "Zażółć gęślą jaźń — test metod S4 2026!"


@pytest.fixture
def cover_png(tmp_path):
    """Obraz 160x160 z bogatą teksturą (zapewnia wysoką pojemność także dla nsF5 i OutGuess)."""
    sciezka = tmp_path / "cover_s4.png"
    rng = np.random.default_rng(2026)
    obraz = rng.integers(15, 240, size=(160, 160, 3), dtype=np.uint8)
    Image.fromarray(obraz).save(sciezka)
    return sciezka


# ---------------------------------------------------------------------------
# 1. Testy nsF5 i OutGuess (roundtrip, zły klucz, granica pojemności, histogram)
# ---------------------------------------------------------------------------


def test_nsf5_roundtrip_zly_klucz_i_granica_pojemnosci(cover_png, tmp_path):
    wyjscie = tmp_path / "nsf5.jpg"
    obraz = load_cover(cover_png)
    pojemnosc = nsf5_capacity_from_png(obraz, key="sekret-nsf5")
    assert pojemnosc > HEADER_SIZE + 20

    method = METHOD_REGISTRY.get("nsf5")
    artifact = method.embed_bytes(cover_png.read_bytes(), TEKST_PL, key="sekret-nsf5")
    assert method.extract_bytes(artifact.data, key="sekret-nsf5") == TEKST_PL

    with pytest.raises(FrameError):
        method.extract_bytes(artifact.data, key="bledny-klucz")

    limit_netto = pojemnosc - HEADER_SIZE
    ramka_max = pack("a" * limit_netto, capacity_bytes=pojemnosc)
    nsf5_embed_jpeg(str(cover_png), str(wyjscie), ramka_max, key="sekret-nsf5")
    odzyskana = nsf5_extract_jpeg(str(wyjscie), key="sekret-nsf5")
    assert unpack_bytes(odzyskana, capacity_bytes=nsf5_capacity_from_jpeg(str(wyjscie))) == b"a" * limit_netto

    with pytest.raises(FrameError):
        pack("a" * (limit_netto + 1), capacity_bytes=pojemnosc)


def test_outguess_roundtrip_zly_klucz_i_zachowanie_histogramu(cover_png, tmp_path):
    wyjscie = tmp_path / "outguess.jpg"
    obraz = load_cover(cover_png)
    pojemnosc = outguess_capacity_from_png(obraz, key="sekret-og")
    assert pojemnosc > HEADER_SIZE + 20

    ramka = pack(TEKST_PL, capacity_bytes=pojemnosc)
    outguess_embed_jpeg(str(cover_png), str(wyjscie), ramka, key="sekret-og")

    odzyskana = outguess_extract_jpeg(str(wyjscie), key="sekret-og")
    assert unpack_bytes(odzyskana, capacity_bytes=outguess_capacity_from_jpeg(str(wyjscie))) == TEKST_PL.encode("utf-8")

    with pytest.raises(FrameError):
        outguess_extract_jpeg(str(wyjscie), key="zly-klucz-og")

    raport = dct_histogram_report(wyjscie)
    assert raport["components"]["Y"]["ac"]["nonzero_count"] > 0


# ---------------------------------------------------------------------------
# 2. Testy kontenera STEGFILE i payloadu plikowego (--payload-file)
# ---------------------------------------------------------------------------


def test_stegfile_kodowanie_dekodowanie_i_sanityzacja_sciezki():
    surowe_dane = b"\x89PNG\r\n\x1a\n\x00\x01\x02binarne-dane\xff\xfe"
    kontener = encode_file_payload("../../etc/passwd", "application/octet-stream", surowe_dane)
    nazwa, mime, odzyskane = decode_file_payload(kontener)

    assert nazwa == "passwd"
    assert "/" not in nazwa and "\\" not in nazwa
    assert mime == "application/octet-stream"
    assert odzyskane == surowe_dane


def test_stegfile_bledne_naglowki():
    with pytest.raises(ValueError, match="osadzonego pliku"):
        decode_file_payload(b"ZLY_NAGLOWEK_12345")
    with pytest.raises(ValueError, match="Niekompletne metadane"):
        decode_file_payload(b"STEGFILE\x01" + struct.pack(">I", 999) + b"{}")


@pytest.mark.parametrize("cmd_prefix", [[], ["jsteg"], ["nsf5"]])
def test_cli_payload_file_roundtrip(cover_png, tmp_path, cmd_prefix):
    plik_wej = tmp_path / "sekret.bin"
    dane_binarne = bytes(range(256)) + b"BIN_PAYLOAD_OK"
    plik_wej.write_bytes(dane_binarne)

    ext = ".png" if not cmd_prefix else ".jpg"
    obraz_stego = tmp_path / f"stego_bin{ext}"
    plik_wyj = tmp_path / "odzyskany.bin"

    assert main([*cmd_prefix, "embed", str(cover_png), str(obraz_stego), "--payload-file", str(plik_wej)]) == 0
    assert main([*cmd_prefix, "extract", str(obraz_stego), "--output-file", str(plik_wyj)]) == 0
    assert plik_wyj.read_bytes() == dane_binarne


# ---------------------------------------------------------------------------
# 3. Testy steganalizy (chi-kwadrat, histogramy DCT, odległość Hellingera)
# ---------------------------------------------------------------------------


def test_steganalysis_chi_square_czysty_vs_pelny_lsb():
    rng = np.random.default_rng(10)
    czysty = np.tile(np.arange(0, 256, 2, dtype=np.uint8), (64, 3))[:, :192].reshape(64, 64, 3)
    raport_czysty = chi_square_analysis(czysty, window_size=1024)
    assert raport_czysty["channels"]["R"]["global"]["status"] == "ok"
    assert len(raport_czysty["channels"]["R"]["windows"]) == 4

    losowy_payload = rng.integers(0, 256, size=64 * 64 * 3 // 8 - HEADER_SIZE, dtype=np.uint8).tobytes()
    ramka = pack_bytes(losowy_payload, capacity_bytes=64 * 64 * 3 // 8)
    stego = embed_frame(czysty, ramka)
    raport_stego = chi_square_analysis(stego)
    assert raport_stego["channels"]["R"]["global"]["p_value"] > 0.05


def test_steganalysis_hellinger_i_detektor_dct(tmp_path):
    h1 = {"values": [-2, -1, 1, 2], "counts": [10, 40, 40, 10]}
    h2 = {"values": [-2, -1, 1, 2], "counts": [25, 25, 25, 25]}
    assert hellinger_distance(h1, h1) == 0.0
    d = hellinger_distance(h1, h2)
    assert 0.0 < d <= 1.0

    czyste_pliki = []
    for seed in range(6):
        rng = np.random.default_rng(100 + seed)
        arr = rng.integers(20, 235, size=(64, 64, 3), dtype=np.uint8)
        png_p = tmp_path / f"clean_{seed}.png"
        jpg_p = tmp_path / f"clean_{seed}.jpg"
        Image.fromarray(arr).save(png_p)
        assert main(["jpeg", str(png_p), str(jpg_p)]) == 0
        czyste_pliki.append(jpg_p)

    model = calibrate_dct_histogram_detector(czyste_pliki[:3], czyste_pliki[3:], component="Y", quantile=0.95)
    assert model["method"] == "dct_histogram_hellinger"
    wynik = dct_histogram_detection(czyste_pliki[0], model)
    assert "distance" in wynik and "alarm" in wynik


# ---------------------------------------------------------------------------
# 4. Testy prymitywów DCT oraz negatywne testy formatów JPEG (progresywny, 4:4:4)
# ---------------------------------------------------------------------------


def test_prymitywy_dct_na_wektorach_kontrolnych():
    blok_128 = np.full((8, 8), 128, dtype=np.uint8)
    dct_zero = dct_block(blok_128, level_shift=True)
    assert np.allclose(dct_zero, 0.0, atol=1e-12)

    macierz = np.arange(64, dtype=np.int32).reshape(8, 8)
    zz = zigzag_scan(macierz)
    assert zz.shape == (64,)
    assert list(zz[:6]) == [0, 1, 8, 16, 9, 2]

    q = quantize_block(np.full((8, 8), 32.0), LUMINANCE_QUANTIZATION)
    assert q[0, 0] == 2


def test_jpeg_nie_baseline_odrzucony_czytelnym_bledem(tmp_path):
    obraz = Image.fromarray(np.random.default_rng(5).integers(0, 255, size=(32, 32, 3), dtype=np.uint8))

    prog_jpg = tmp_path / "progressive.jpg"
    obraz.save(prog_jpg, format="JPEG", progressive=True)
    with pytest.raises(ImageError, match="Nieobsługiwany"):
        read_jpeg(prog_jpg)

    full_jpg = tmp_path / "444.jpg"
    obraz.save(full_jpg, format="JPEG", subsampling=0)
    with pytest.raises(ImageError, match="4:2:0"):
        read_jpeg(full_jpg)


# ---------------------------------------------------------------------------
# 5. Test symulatora zakłóceń (S3-03): komenda CLI steganografia disturb + CSV
# ---------------------------------------------------------------------------


def test_cli_disturb_eksperymenty_dla_6_metod_i_raport_csv(cover_png, tmp_path):
    katalog_wynikow = tmp_path / "wyniki_disturb"
    kod = main(["disturb", str(cover_png), str(katalog_wynikow), "--seed", "123"])
    assert kod == 0

    raport_csv = katalog_wynikow / "disturb_report.csv"
    assert raport_csv.exists()

    wiersze = raport_csv.read_text(encoding="utf-8").splitlines()
    # Nagłówek + 6 metod * 7 scenariuszy (none, jpeg 90/70/50, noise 2.0/5.0, scale 0.75) = 43 wiersze
    assert len(wiersze) == 1 + 6 * 7
    assert wiersze[0] == (
        "id_obrazu,metoda,rozmiar_payloadu_B,parametry_zaklocenia,"
        "plik_wynikowy,status_ramki,wynik_odzyskania"
    )

    # Kontrola bez zakłóceń ('none:0:seed=123') musi dawać OK / IDENTICAL dla wszystkich 6 metod
    wiersze_kontrolne = [w for w in wiersze[1:] if ",none:0:seed=123," in w]
    assert len(wiersze_kontrolne) == 6
    assert all(w.endswith(",OK,IDENTICAL") for w in wiersze_kontrolne)


# ---------------------------------------------------------------------------
# 6. Regresja BUG-01: eksport rs_analysis w __all__
# ---------------------------------------------------------------------------


def test_bug01_import_gwiazdkowy_i_brak_martwego_rs_analysis():
    ns = {}
    exec('from steganografia import *', ns)
    assert 'rs_analysis' not in steg.__all__
    assert 'rs_analysis' not in ns