"""Testy zgodne z kryteriami odbioru kart Trello S1-01, S1-02, S1-03."""

import struct
import zlib

import numpy as np
import pytest
from PIL import Image

import steganografia.images as images_mod
from steganografia import (
    FrameError,
    ImageError,
    capacity_bytes,
    embed_bits,
    embed_frame,
    extract_bits,
    extract_frame,
    load_cover,
    load_stego,
    pack,
    payload_capacity_bytes,
    save_png,
)
from steganografia.frame import HEADER_SIZE, MAGIC, VERSION, parse_header, unpack


def zbuduj_ramke(payload: bytes) -> bytes:
    return struct.pack(">4sBII", MAGIC, VERSION, len(payload), zlib.crc32(payload)) + payload


# ======================= S1-01: ramka danych =======================

def test_s101_naglowek_ma_13_bajtow():
    assert HEADER_SIZE == 13


@pytest.mark.parametrize("payload", [b"", b"123456789", "Zażółć gęślą jaźń".encode("utf-8")])
def test_s101_crc_z_referencyjnym_algorytmem_bitowym(payload):
    crc = 0xFFFFFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    crc ^= 0xFFFFFFFF
    assert zlib.crc32(payload) == crc
    ramka = pack(payload.decode("utf-8"), capacity_bytes=HEADER_SIZE + len(payload))
    assert int.from_bytes(ramka[9:13], "big") == crc


def test_s101_staly_wektor_niezalezny_od_funkcji_pakujacej():
    # Ramka zapisana "na sztywno" (bajty), bez użycia struct/zlib.
    # CRC32("123456789") = 0xCBF43926 to standardowa wartość kontrolna CRC-32.
    ramka = (
        b"STEG"                  # MAGIC
        b"\x01"                  # VERSION
        b"\x00\x00\x00\x09"      # LENGTH = 9 (big-endian)
        b"\xCB\xF4\x39\x26"      # CRC32 (big-endian)
        b"123456789"             # PAYLOAD
    )
    assert zlib.crc32(b"123456789") == 0xCBF43926
    assert pack("123456789", capacity_bytes=len(ramka)) == ramka
    assert unpack(ramka, capacity_bytes=1000) == "123456789"


def test_s101_pusty_tekst():
    ramka = pack("", capacity_bytes=13)
    assert len(ramka) == 13
    assert ramka == bytes.fromhex("53 54 45 47 01 00 00 00 00 00 00 00 00")
    assert unpack(ramka, capacity_bytes=13) == ""


def test_s101_polskie_znaki_dlugosc_w_bajtach_utf8():
    tekst = "Zażółć gęślą jaźń"
    payload = tekst.encode("utf-8")
    assert len(payload) > len(tekst)  # bajty, nie znaki
    ramka = pack(tekst, capacity_bytes=HEADER_SIZE + len(payload))
    assert struct.unpack(">I", ramka[5:9])[0] == len(payload)
    assert unpack(ramka, capacity_bytes=1000) == tekst


def test_s101_pack_limit_liczony_w_bajtach():
    assert unpack(pack("ą", capacity_bytes=15), capacity_bytes=15) == "ą"
    with pytest.raises(FrameError, match="maksymalnie 1 B payloadu"):
        pack("ą", capacity_bytes=14)


@pytest.mark.parametrize("capacity", [0, 12, -1])
def test_s101_pack_nie_miesci_naglowka(capacity):
    with pytest.raises(FrameError, match="nie mieści nagłówka"):
        pack("", capacity_bytes=capacity)


@pytest.mark.parametrize("capacity", [True, 13.0, "13", None])
def test_s101_pack_nieprawidlowy_typ_pojemnosci(capacity):
    with pytest.raises(TypeError, match="capacity_bytes"):
        pack("", capacity_bytes=capacity)


def test_s101_pack_limit_pola_length(monkeypatch):
    import steganografia.frame as frame_mod

    monkeypatch.setattr(frame_mod, "MAX_PAYLOAD_SIZE", 2)
    assert len(pack("ab", capacity_bytes=100)) == HEADER_SIZE + 2
    with pytest.raises(FrameError, match="maksymalnie 2 B payloadu"):
        pack("abc", capacity_bytes=100)


def test_s101_pack_bledny_tekst():
    with pytest.raises(TypeError, match="str"):
        pack(b"abc", capacity_bytes=100)
    with pytest.raises(FrameError, match="UTF-8"):
        pack("\ud800", capacity_bytes=100)


def test_s101_bledny_magic():
    ramka = bytearray(zbuduj_ramke(b"abc"))
    ramka[0] = ord("X")
    with pytest.raises(FrameError, match="MAGIC"):
        unpack(bytes(ramka), capacity_bytes=1000)


def test_s101_bledna_wersja():
    ramka = bytearray(zbuduj_ramke(b"abc"))
    ramka[4] = 2
    with pytest.raises(FrameError, match="wersja"):
        unpack(bytes(ramka), capacity_bytes=1000)


def test_s101_bledny_rozmiar_naglowka():
    with pytest.raises(FrameError, match="13 bajtów"):
        parse_header(b"STEG\x01", capacity_bytes=1000)


def test_s101_length_wiekszy_niz_pojemnosc_odrzucony_przed_odczytem():
    # LENGTH = 4 GB, a pojemność obrazu tylko 100 B: błąd na samym nagłówku.
    naglowek = struct.pack(">4sBII", MAGIC, VERSION, 0xFFFFFFFF, 0)
    with pytest.raises(FrameError, match="przekracza pojemność"):
        parse_header(naglowek, capacity_bytes=100)


def test_s101_ucieta_ramka():
    ramka = zbuduj_ramke(b"abcdef")
    with pytest.raises(FrameError, match="Ucięty payload"):
        unpack(ramka[:-2], capacity_bytes=1000)
    with pytest.raises(FrameError, match="Ucięty nagłówek"):
        unpack(ramka[:5], capacity_bytes=1000)


def test_s101_nadmiarowe_bajty():
    with pytest.raises(FrameError, match="Nadmiarowe"):
        unpack(zbuduj_ramke(b"abc") + b"x", capacity_bytes=1000)


def test_s101_zmiana_danych_wykryta_przez_crc():
    ramka = bytearray(zbuduj_ramke(b"abcdef"))
    ramka[HEADER_SIZE] ^= 0x01
    with pytest.raises(FrameError, match="CRC32"):
        unpack(bytes(ramka), capacity_bytes=1000)


def test_s101_niepoprawny_utf8():
    ramka = zbuduj_ramke(b"\xff\xfe")  # CRC poprawne, ale to nie jest UTF-8
    with pytest.raises(FrameError, match="UTF-8"):
        unpack(ramka, capacity_bytes=1000)


# ======================= S1-02: rdzeń LSB =======================

def _obraz_losowy(h=8, w=8, seed=0):
    return np.random.default_rng(seed).integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def test_s102_same_zera_i_same_jedynki():
    obraz = _obraz_losowy()
    for bity in (np.zeros(40, dtype=np.uint8), np.ones(40, dtype=np.uint8)):
        wynik = embed_bits(obraz, bity)
        assert np.array_equal(extract_bits(wynik, 40), bity)


def test_s102_reczny_test_wartosci_zmienionych_bajtow():
    # Obraz 2x2, próbki w kolejności C: R,G,B piksela (0,0), potem (0,1), ...
    probki = [255, 254, 1, 0, 170, 171, 85, 84, 200, 201, 10, 11]
    obraz = np.array(probki, dtype=np.uint8).reshape(2, 2, 3)
    bity = [1, 0, 1, 1, 0, 0, 1, 0]
    wynik = embed_bits(obraz, bity)
    oczekiwane = [255, 254, 1, 1, 170, 170, 85, 84, 200, 201, 10, 11]
    assert wynik.reshape(-1).tolist() == oczekiwane
    # Ekstrakcja ze stałych próbek, niezależnie od wyniku osadzania.
    assert extract_bits(np.array(oczekiwane, dtype=np.uint8).reshape(2, 2, 3), 8).tolist() == bity


def test_s102_pojemnosc_netto_uwzglednia_naglowek():
    obraz = _obraz_losowy(8, 8)  # 8*8*3 = 192 bity = 24 B
    assert capacity_bytes(obraz) == 24
    assert payload_capacity_bytes(obraz) == 24 - HEADER_SIZE == 11


def test_s102_dokladnie_na_granicy_pojemnosci_dziala():
    obraz = _obraz_losowy(8, 8)
    ramka = zbuduj_ramke(b"a" * 11)
    assert len(ramka) == 24
    assert extract_frame(embed_frame(obraz, ramka)) == ramka


def test_s102_ramka_zapisuje_bajty_msb_first():
    obraz = np.zeros((8, 8, 3), dtype=np.uint8)
    wynik = embed_frame(obraz, pack("", capacity_bytes=24))
    # MAGIC zaczyna się od ASCII S = 0x53, czyli 01010011.
    assert wynik.reshape(-1)[:8].tolist() == [0, 1, 0, 1, 0, 0, 1, 1]


def test_s102_przekroczenie_o_jeden_bajt_daje_blad():
    obraz = _obraz_losowy(8, 8)
    with pytest.raises(FrameError, match="maksymalnie 11 B payloadu"):
        embed_frame(obraz, zbuduj_ramke(b"a" * 12))


def test_s102_obraz_za_maly_na_naglowek():
    obraz = _obraz_losowy(4, 4)  # 48 bitów = 6 B < 13 B
    with pytest.raises(FrameError):
        payload_capacity_bytes(obraz)


def test_s102_za_duzo_bitow():
    obraz = _obraz_losowy(2, 2)  # 12 próbek
    with pytest.raises(FrameError):
        embed_bits(obraz, np.ones(13, dtype=np.uint8))


def test_s102_brak_modyfikacji_niewykorzystanych_probek_i_wyzszych_bitow():
    obraz = _obraz_losowy(8, 8, seed=1)
    ramka = zbuduj_ramke(b"abc")
    uzyte = len(ramka) * 8
    wynik = embed_frame(obraz, ramka)

    a = obraz.reshape(-1)
    b = wynik.reshape(-1)
    # niewykorzystane próbki identyczne
    assert np.array_equal(a[uzyte:], b[uzyte:])
    # w wykorzystanych zmienia się wyłącznie bit 0
    assert np.array_equal(a[:uzyte] >> 1, b[:uzyte] >> 1)
    # oryginał nie został zmodyfikowany (zwracana jest kopia)
    assert not np.shares_memory(obraz, wynik)
    assert np.array_equal(obraz, _obraz_losowy(8, 8, seed=1))


# ======================= S1-03: PNG i przepływ plikowy =======================

def test_s103_integracja_na_prawdziwym_pliku_png(tmp_path):
    cover_path = tmp_path / "cover.png"
    stego_path = tmp_path / "stego.png"
    Image.fromarray(_obraz_losowy(40, 40, seed=2)).save(cover_path)
    oryginal_bajty = cover_path.read_bytes()

    payload = "Zażółć gęślą jaźń".encode("utf-8")
    ramka = pack(payload.decode("utf-8"), capacity_bytes=capacity_bytes(load_cover(cover_path)))
    save_png(embed_frame(load_cover(cover_path), ramka), stego_path)

    # oryginał nie został nadpisany
    assert cover_path.read_bytes() == oryginal_bajty
    # po zamknięciu i ponownym otwarciu: identyczne bajty wiadomości
    stego = load_stego(stego_path)
    assert extract_frame(stego) == ramka
    assert unpack(extract_frame(stego), capacity_bytes=capacity_bytes(stego)) == "Zażółć gęślą jaźń"


def test_s103_zapis_bez_overwrite_nie_nadpisuje(tmp_path):
    sciezka = tmp_path / "a.png"
    save_png(np.zeros((5, 5, 3), dtype=np.uint8), sciezka)
    przed = sciezka.read_bytes()
    with pytest.raises(ImageError, match="już istnieje"):
        save_png(np.full((5, 5, 3), 255, dtype=np.uint8), sciezka)
    assert sciezka.read_bytes() == przed


def test_s103_plik_nie_istnieje(tmp_path):
    with pytest.raises(ImageError, match="Nie można odczytać"):
        load_cover(tmp_path / "brak.png")


def test_s103_uszkodzony_plik(tmp_path):
    sciezka = tmp_path / "zepsuty.png"
    sciezka.write_bytes(b"to nie jest obraz")
    with pytest.raises(ImageError):
        load_cover(sciezka)


def test_s103_jpeg_odrzucony(tmp_path):
    sciezka = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(sciezka, "JPEG")
    with pytest.raises(ImageError, match="Nieobsługiwany format"):
        load_cover(sciezka)


def test_s103_nieobslugiwany_tryb_16_bit(tmp_path):
    sciezka = tmp_path / "16bit.png"
    Image.fromarray(np.zeros((10, 10), dtype=np.uint16)).save(sciezka)
    with pytest.raises(ImageError):
        load_cover(sciezka)


@pytest.mark.parametrize("limit", ["MAX_PIXELS", "MAX_DIMENSION", "MAX_FILE_BYTES"])
def test_s103_przekroczenie_limitu_rozmiaru(tmp_path, monkeypatch, limit):
    sciezka = tmp_path / "duzy.png"
    Image.new("RGB", (20, 20)).save(sciezka)
    monkeypatch.setattr(images_mod, limit, 10)
    with pytest.raises(ImageError, match="przekracza limit"):
        load_cover(sciezka)


def test_s103_normalizacja_wejscia_do_rgb(tmp_path):
    for tryb, nazwa in (("L", "szary"), ("RGBA", "rgba"), ("P", "paleta")):
        sciezka = tmp_path / f"{nazwa}.png"
        Image.new(tryb, (12, 7)).save(sciezka)
        obraz = load_cover(sciezka)
        assert obraz.shape == (7, 12, 3)
        assert obraz.dtype == np.uint8


def test_s103_ekstrakcja_nie_normalizuje_obrazu_wynikowego(tmp_path):
    sciezka = tmp_path / "rgba.png"
    Image.new("RGBA", (12, 12)).save(sciezka)
    with pytest.raises(ImageError, match="8-bitowego RGB"):
        load_stego(sciezka)


def test_s103_zapis_tylko_do_png(tmp_path):
    with pytest.raises(ImageError, match=".png"):
        save_png(np.zeros((5, 5, 3), dtype=np.uint8), tmp_path / "a.jpg")
