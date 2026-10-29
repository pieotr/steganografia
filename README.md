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

Możesz też wczytać wiadomość bezpośrednio z pliku TXT i zapisać odzyskany
tekst bez przekierowania powłoki:

```sh
steganografia embed oryginal.png wiadomosc.png --text-file wiadomosc.txt
steganografia extract wiadomosc.png --output odzyskany.txt
```

`--text` i `--text-file` są wzajemnie wykluczające; podaj dokładnie jedną
z tych opcji. Plik wejściowy musi zawierać poprawny UTF-8. Zachowywane są
wszystkie znaki, końce wierszy (również CRLF) i ewentualny BOM; nie jest
dodawany nowy BOM ani koniec wiersza. `--output` (skrót `-o`) zapisuje tekst
do wskazanego pliku i pozostawia stdout pusty. Istniejący plik tekstowy
jest chroniony; nadpisanie wymaga `extract --output odzyskany.txt --overwrite`.
Katalog docelowy musi istnieć. Błędna ramka nie tworzy ani nie nadpisuje TXT.

`odzyskany.txt` zawiera dokładny tekst UTF-8, bez dodanego końca wiersza.
`embed` i `extract` wypisują informacje o pojemności na stderr,
a `extract` bez `--output` wysyła na stdout wyłącznie odzyskany tekst. Pojemność jest
liczona w bajtach UTF-8, po odjęciu 13-bajtowego nagłówka ramki.
Istniejący PNG można nadpisać wyłącznie z flagą `--overwrite`.
Kod zakończenia: `0` — sukces, `1` — błąd danych lub pliku,
`2` — błędna składnia komendy.

## API Flask

Dla frontendowca w projekcie jest dostępny też serwer Flask z endpointami dla
LSB i z architekturą przygotowaną pod rozszerzenia o DCT.

Uruchomienie:

```sh
python -m pip install -e .
steganografia-api --host 0.0.0.0 --port 5000
```

Alternatywnie można uruchomić bez instalacji z katalogu projektu:

```sh
python -m steganografia.server --host 0.0.0.0 --port 5000
```

Frontend jest zintegrowany z pakietem aplikacji i znajduje się w `src/steganografia/static/`.
Jest hostowany w tym samym procesie Flask, więc strona główna jest dostępna pod
`http://localhost:5000/`, a API pozostaje pod `/api/v1/*`. Domyślny port to `5000`;
pod adresem `/api/v1/swagger` działa przeglądarka Swagger UI, a spec OpenAPI jest dostępna
pod `/api/v1/openapi.json`.

Najważniejsze endpointy:

- `GET /api/v1/health` — status serwera,
- `POST /api/v1/lsb/capacity` — pojemność obrazu PNG,
- `POST /api/v1/lsb/embed` — osadzenie tekstu w PNG,
- `POST /api/v1/lsb/extract` — odczyt tekstu z PNG.

Przykład `curl`:

```sh
curl -X POST http://localhost:5000/api/v1/lsb/capacity \
  -F "file=@oryginal.png"

curl -X POST http://localhost:5000/api/v1/lsb/embed \
  -F "file=@oryginal.png" \
  -F "text=Cześć od frontendowca!"

curl -X POST http://localhost:5000/api/v1/lsb/extract \
  -F "file=@stego.png"
```

Dokumentacja bardziej szczegółowa znajduje się w [docs/api.md](docs/api.md).

Pełna [demonstracja CLI](docs/cli-demo.md) tworzy wejściowy PNG i prowadzi
przez zapis oraz ponowny odczyt. Zobacz też
[raport weryfikacji](docs/reports/cli-verification.md)
i [materiał do Sprint 1 Review](docs/sprint-1-review.md).

## API Pythona

### Przygotowanie obrazu do DCT

Obraz można wczytać istniejącym `load_cover`, a następnie przekonwertować
z RGB do składowych JPEG: jasności `Y` oraz chrominancji `Cb` i `Cr`.
Konwersja zwraca wartości `float64`, bez zaokrąglania, aby nie utracić
dokładności przed kolejnym etapem DCT:

```python
from steganografia import load_cover, rgb_to_ycbcr

rgb = load_cover("oryginal.png")
ycbcr = rgb_to_ycbcr(rgb)
print(ycbcr[0, 0])  # [Y, Cb, Cr]
```

Subsampling 4:2:0 można wykonać jako kolejny krok. `Y` pozostaje w pełnej
rozdzielczości, a `Cb` i `Cr` są uśredniane w blokach 2×2:

```python
from steganografia import load_cover, rgb_to_ycbcr, subsample_420

ycbcr = rgb_to_ycbcr(load_cover("oryginal.png"))
y, cb, cr = subsample_420(ycbcr)
print(y.shape, cb.shape, cr.shape)
```

To przygotowuje komponenty do dalszego kodowania JPEG, ale nie zapisuje
jeszcze pliku i nie wykonuje dopełnienia do bloków 8×8.

Pojedynczy blok 8×8 można pobrać po indeksie liczonym w kolejności
wierszami (od zera):

```python
from steganografia import get_block

block = get_block(y, index=0)
print(block)
```

Jeśli rozmiar komponentu nie jest wielokrotnością 8, brakujące wartości są
uzupełniane przez powielenie ostatniego wiersza lub kolumny.

Na pojedynczym bloku można teraz wykonać DCT:

```python
from steganografia import dct_block, get_block

block = get_block(y, index=0)
coefficients = dct_block(block)
print(coefficients)
```

Przed transformacją domyślnie odejmowane jest 128 (`level shift`), ponieważ
próbki obrazu mają zakres 0–255, a DCT wygodniej analizuje wartości skupione
wokół zera. Współczynnik `coefficients[0, 0]` (DC) opisuje średnią jasność
bloku, a pozostałe współczynniki (AC) opisują coraz szybsze zmiany jasności
w poziomie i pionie. DCT nie kompresuje jeszcze danych i nie zaokrągla
współczynników — robi to dopiero późniejsza kwantyzacja.

Kwantyzację wykonujemy osobno dla luminancji i chrominancji:

```python
from steganografia import (
    CHROMINANCE_QUANTIZATION,
    LUMINANCE_QUANTIZATION,
    dct_block,
    get_block,
    quantize_block,
)

dct = dct_block(get_block(y, index=0))
quantized = quantize_block(dct, LUMINANCE_QUANTIZATION)
```

Współczynnik jest dzielony przez odpowiadającą mu wartość macierzy, a wynik
zaokrąglany. Duże wartości macierzy, szczególnie przy wysokich
częstotliwościach, powodują wyzerowanie wielu szczegółów. To właśnie tutaj
pojawia się główna utrata jakości JPEG. Dla `Cb` i `Cr` używamy
`CHROMINANCE_QUANTIZATION`.

Po kwantyzacji współczynniki odczytujemy po zygzaku:

```python
from steganografia import quantize_block, zigzag_scan

quantized = quantize_block(dct, LUMINANCE_QUANTIZATION)
ordered = zigzag_scan(quantized)
print(ordered)
```

Pierwszy element to współczynnik DC. Następne elementy to współczynniki AC,
uporządkowane od niskich do wysokich częstotliwości. W praktycznym obrazie
końcowa część tablicy często składa się z zer, dlatego taki układ jest
korzystny dla następnego etapu, czyli kodowania długości serii (RLE).

Gotowe, zmodyfikowane współczynniki można zapisać bez ponownego wykonywania
DCT przez własny enkoder JPEG:

```python
from steganografia import write_jpeg

write_jpeg(
    "wynik.jpg",
    width=128,
    height=128,
    y_blocks=y_blocks,
    cb_blocks=cb_blocks,
    cr_blocks=cr_blocks,
)
```

`y_blocks`, `cb_blocks` i `cr_blocks` zawierają skwantyzowane bloki po
`zigzag_scan`, w kolejności raster-scan komponentu. Dla kolorowego JPEG
enkoder zapisuje układ 4:2:0: cztery bloki `Y`, jeden `Cb` i jeden `Cr` na
każdą jednostkę MCU. Własny zapis wykonuje kodowanie DC, RLE AC, Huffmana,
byte stuffing i nagłówki baseline JPEG.

Cały pipeline dla PNG jest dostępny również w CLI:

```sh
steganografia jpeg oryginal.png wynik.jpg
```

Komenda wykonuje RGB→YCbCr, subsampling 4:2:0, DCT, kwantyzację,
odczyt zygzakowy i zapis własnego JPEG. Istniejący plik wynikowy jest
chroniony; jawne nadpisanie wymaga:

```sh
steganografia jpeg oryginal.png wynik.jpg --overwrite
```

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
