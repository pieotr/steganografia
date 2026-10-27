"""Testy CLI: capacity, embed, extract (w tym polskie znaki i błędy)."""

import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from steganografia import load_stego, save_png
from steganografia.cli import main
from steganografia.frame import HEADER_SIZE

TEKST = "Zażółć gęślą jaźń — tajny komunikat"


@pytest.fixture
def cover(tmp_path):
    sciezka = tmp_path / "cover.png"
    losowy = np.random.default_rng(7).integers(0, 256, size=(60, 60, 3), dtype=np.uint8)
    Image.fromarray(losowy).save(sciezka)  # 60*60*3//8 = 1350 B
    return sciezka


def test_capacity_podaje_pojemnosc(cover, capsys):
    assert main(["capacity", str(cover)]) == 0
    out = capsys.readouterr().out
    assert "1350 B" in out
    assert f"{1350 - HEADER_SIZE} B" in out


def test_embed_extract_polskie_znaki(cover, tmp_path, capsys):
    stego = tmp_path / "stego.png"
    assert main(["embed", str(cover), str(stego), "--text", TEKST]) == 0
    capsys.readouterr()
    assert main(["extract", str(stego)]) == 0
    assert capsys.readouterr().out.strip() == TEKST


def test_embed_z_pliku_i_extract_do_pliku(cover, tmp_path, capsys):
    wejscie = tmp_path / "wiadomosc.txt"
    wejscie.write_text(TEKST, encoding="utf-8")
    stego = tmp_path / "stego.png"
    odzyskane = tmp_path / "odzyskane.txt"
    assert main(["embed", str(cover), str(stego), "--text-file", str(wejscie)]) == 0
    assert main(["extract", str(stego), "-o", str(odzyskane)]) == 0
    assert odzyskane.read_text(encoding="utf-8") == TEKST


def test_za_dluga_wiadomosc_czytelny_blad(cover, tmp_path, capsys):
    stego = tmp_path / "stego.png"
    za_dluga = "a" * (1350 - HEADER_SIZE + 1)  # o jeden bajt za dużo
    assert main(["embed", str(cover), str(stego), "--text", za_dluga]) == 1
    err = capsys.readouterr().err
    assert "za długa" in err and "1337 B" in err
    assert not stego.exists()


def test_na_granicy_pojemnosci_dziala(cover, tmp_path):
    stego = tmp_path / "stego.png"
    assert main(["embed", str(cover), str(stego), "--text", "a" * (1350 - HEADER_SIZE)]) == 0


def test_extract_z_obrazu_bez_wiadomosci(tmp_path, capsys):
    pusty = tmp_path / "pusty.png"
    Image.new("RGB", (40, 40)).save(pusty)
    assert main(["extract", str(pusty)]) == 1
    assert "niepoprawna ramka" in capsys.readouterr().err


def test_extract_uszkodzona_ramka_crc(cover, tmp_path, capsys):
    stego = tmp_path / "stego.png"
    main(["embed", str(cover), str(stego), "--text", TEKST])
    obraz = load_stego(stego).copy()
    probki = obraz.reshape(-1)
    probki[HEADER_SIZE * 8 + 3] ^= 1  # odwrócenie jednego bitu payloadu
    save_png(probki.reshape(obraz.shape), stego, overwrite=True)
    capsys.readouterr()
    assert main(["extract", str(stego)]) == 1
    assert "CRC32" in capsys.readouterr().err


def test_nie_nadpisuje_bez_force(cover, tmp_path, capsys):
    stego = tmp_path / "stego.png"
    assert main(["embed", str(cover), str(stego), "--text", "raz"]) == 0
    assert main(["embed", str(cover), str(stego), "--text", "dwa"]) == 1
    assert "już istnieje" in capsys.readouterr().err
    assert main(["embed", str(cover), str(stego), "--text", "dwa", "--force"]) == 0
    capsys.readouterr()
    main(["extract", str(stego)])
    assert capsys.readouterr().out.strip() == "dwa"


def test_wynik_nie_moze_byc_obrazem_wejsciowym(cover, capsys):
    assert main(["embed", str(cover), str(cover), "--text", "x", "--force"]) == 1
    assert "różnić się" in capsys.readouterr().err


def test_brak_pliku_wejsciowego(tmp_path, capsys):
    assert main(["capacity", str(tmp_path / "brak.png")]) == 1
    assert "Błąd:" in capsys.readouterr().err


def test_wymagany_dokladnie_jeden_zrodlowy_tekst(cover, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["embed", str(cover), str(tmp_path / "o.png")])
    assert exc.value.code == 2


def test_uruchomienie_jako_modul_w_osobnym_procesie(cover, tmp_path):
    """Sprawdza prawdziwe CLI (python -m steganografia) razem z kodowaniem UTF-8."""
    stego = tmp_path / "stego.png"
    korzen = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(korzen), "PYTHONIOENCODING": "utf-8"}

    def uruchom(*args):
        return subprocess.run(
            [sys.executable, "-m", "steganografia", *args],
            capture_output=True, env=env, cwd=tmp_path,
        )

    wynik = uruchom("embed", str(cover), str(stego), "--text", TEKST)
    assert wynik.returncode == 0, wynik.stderr.decode("utf-8")
    wynik = uruchom("extract", str(stego))
    assert wynik.returncode == 0
    assert wynik.stdout.decode("utf-8").strip() == TEKST
