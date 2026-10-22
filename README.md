# Steganografia w obrazach

## CLI: ukrywanie i odczyt tekstu

Po instalacji `python -m pip install -e .` dostępne są komendy
`steganografia embed`, `steganografia extract` i `steganografia capacity`.
Te same komendy można uruchamiać przez `python -m steganografia`.

```sh
steganografia capacity oryginal.png
steganografia embed oryginal.png wiadomosc.png --text "Zażółć gęślą jaźń"
steganografia extract wiadomosc.png > odzyskany.txt
```

`odzyskany.txt` zawiera dokładny tekst UTF-8, bez dodanego końca wiersza.
`embed` i `extract` wypisują informacje o pojemności na stderr,
a `extract` wysyła na stdout wyłącznie odzyskany tekst. Pojemność jest
liczona w bajtach UTF-8, po odjęciu 13-bajtowego nagłówka ramki.
Istniejący PNG można nadpisać wyłącznie z flagą `--overwrite`.
Kod zakończenia: `0` — sukces, `1` — błąd danych lub pliku,
`2` — błędna składnia komendy.

Pełna [demonstracja CLI](docs/cli-demo.md) tworzy wejściowy PNG i prowadzi
przez zapis oraz ponowny odczyt. Zobacz też
[raport weryfikacji](docs/reports/cli-verification.md)
i [materiał do Sprint 1 Review](docs/sprint-1-review.md).

## API Pythona

Moduł [`lsb`](src/steganografia/lsb.py) udostępnia własne osadzanie i
odczyt sekwencji bitów oraz kompletnych ramek STEG v1 w najmłodszych bitach
próbek obrazu RGB/RGBA.

```python
from steganografia import (
    capacity_bytes,
    embed_frame,
    extract_frame,
    payload_capacity_bytes,
)
from steganografia.frame import pack, unpack

max_payload = payload_capacity_bytes(image)
frame_bytes = pack("Zażółć gęślą jaźń", capacity_bytes=capacity_bytes(image))
encoded_image = embed_frame(image, frame_bytes)
frame_bytes = extract_frame(encoded_image)
text = unpack(frame_bytes, capacity_bytes=capacity_bytes(image))
```

Ramka ma 13-bajtowy nagłówek; `payload_capacity_bytes` zwraca pojemność
netto po jego odjęciu. Szczegóły kolejności próbek i bitów opisano w
[dokumentacji formatu i LSB](docs/frame-v1.md).
`pack(text, *, capacity_bytes)` tworzy kompletną ramkę STEG v1 z tekstu
UTF-8 i sprawdza długość w bajtach względem pojemności obrazu.

## Pliki obrazów (Pillow)

Instalacja: `python -m pip install -e .`.
Moduł [`images`](src/steganografia/images.py) obsługuje **statyczne PNG**,
rozpoznawane po zawartości pliku. Inne formaty (w tym JPEG), animowane
PNG/APNG i głębia 16 bitów są odrzucane z `ImageError`.

`load_cover` normalizuje wejście **przed osadzaniem** do tablicy NumPy
`uint8` o układzie `(wysokość, szerokość, 3)`:

| Tryb PNG | Normalizacja |
| --- | --- |
| 1, L | Rozwinięcie skali szarości do R, G, B |
| P (także palety 1/2/4-bitowe) | Rozwinięcie palety do RGB |
| LA, RGBA | Pominięcie alfa bez mieszania z tłem; zachowanie kolorów także przezroczystych pikseli |
| RGB | Zachowanie wartości 8-bitowych kanałów |

Nie wykonujemy skalowania obrazu, korekcji gamma, zarządzania kolorem ICC
ani obrotu według EXIF. Metadane, paleta i przezroczystość nie są przenoszone
do wyniku. Dopuszczalne głębie wejściowego PNG to 1, 2, 4 i 8 bitów,
zgodnie z dozwolonymi kombinacjami PNG; inne tryby są odrzucane.

```python
from steganografia import (
    capacity_bytes, pack, load_cover, load_stego, save_png, embed_frame, extract_frame,
)

cover = load_cover("oryginal.png")
frame_bytes = pack("Zażółć gęślą jaźń", capacity_bytes=capacity_bytes(cover))
encoded = embed_frame(cover, frame_bytes)
save_png(encoded, "wiadomosc.png")
recovered_bytes = extract_frame(load_stego("wiadomosc.png"))
assert recovered_bytes == frame_bytes
```

`save_png` przyjmuje wyłącznie gotowe `uint8 RGB` i zapisuje **bezstratny
PNG**, z rozszerzeniem `.png`. JPEG nie jest ścieżką zapisu, ponieważ
stratna kompresja niszczy LSB. `load_stego` wymaga 8-bitowego RGB PNG
i odczytuje próbki bez ponownej normalizacji; inne tryby odrzuca.

Istniejący plik, w tym oryginał, jest domyślnie chroniony przed nadpisaniem.
Należy wybrać nową nazwę; nadpisanie wymaga jawnego
`save_png(encoded, "oryginal.png", overwrite=True)`. Zapis jest publikowany
atomowo po zakończeniu kodowania.

Limity: plik do **64 MiB**, do **16 000 000 pikseli**, każdy wymiar do
**16 384 pikseli**. Limity wejścia są sprawdzane przed dekodowaniem pikseli;
zapis również sprawdza wymiary i rozmiar pliku wynikowego. Błędne,
nieobsługiwane i zbyt duże pliki oraz błędy zapisu zgłaszają `ImageError`
z opisem przyczyny. Limit wiadomości pozostaje zależny od pojemności LSB
i jest zgłaszany jako `FrameError`.

## Jak uruchomić wszystkie testy

Wymagania: **Python 3.10 lub nowszy** z modułami `venv` i `pip`.
Wszystkie poniższe komendy wykonuj z głównego katalogu repozytorium
`steganografia` — tego, który zawiera `pyproject.toml`.

**1. Przygotuj środowisko wirtualne** (jednorazowo):

```sh
python -m venv .venv
```

Jeżeli Python jest dostępny jako `python3`, użyj `python3 -m venv .venv`.

**2. Aktywuj środowisko** w bieżącym terminalu.

Linux/macOS (Bash/Zsh):

```sh
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

**3. Zainstaluj projekt wraz z zależnościami testowymi**, w tym pytest:

```sh
python -m pip install -e ".[test]"
```

Samo `pip install -e .` nie instaluje pytest. Jeśli pojawi się
`No module named pytest`, wykonaj powyższą instalację w aktywnym środowisku.

**4. Uruchom cały zestaw testów**:

```sh
python -m pytest -q
```

Ta komenda automatycznie zbiera wszystkie testy z `tests/`, zgodnie
z konfiguracją w `pyproject.toml`. Nie trzeba podawać nazw plików.
Przy kolejnych uruchomieniach wystarczy aktywować środowisko i wykonać
`python -m pytest -q` z głównego katalogu repozytorium.

Wynik `46 passed` oznacza, że obecne 46 testów przeszło; liczba wzrośnie
po dodaniu kolejnych testów. `FAILED` lub `ERROR` oznacza problem wymagający
sprawdzenia. Sukces kończy proces kodem `0`.

Aby zobaczyć nazwy wszystkich testów i ich wyniki:

```sh
python -m pytest -v
```

Aby uruchomić wszystkie testy i jednocześnie zapisać raport JUnit:

```sh
python -m pytest -q --junitxml=reports/pytest.xml
```

Raport powstanie w `reports/pytest.xml`; pytest utworzy katalog raportu,
jeśli jeszcze nie istnieje. To ten sam format raportu, który zapisuje CI.

Obecne testy sprawdzają ramkę i CRC32, reguły LSB oraz pełny zapis
i ponowny odczyt rzeczywistego PNG. Plik testów znajduje się w
`tests/test_karty_s1.py` (został przeniesiony z `src/steganografia/`).

Workflow [Testy pytest](.github/workflows/pytest.yml) uruchamia istniejący
zestaw po pushu, w pull requestach i ręcznie. Zapisuje raport JUnit jako
artefakt `raport-pytest`, także przy błędzie testów. Nie wdraża aplikacji.
Nowe testy CLI pozostają zadaniem członka zespołu odpowiedzialnego za testy;
lokalny raport istniejących testów nie potwierdza jeszcze wykonania workflow.
