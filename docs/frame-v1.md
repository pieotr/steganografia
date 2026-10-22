# Specyfikacja formatu ramki — Sprint 1, zadanie 1 (LSB)

**Status: zaimplementowano pakowanie i parser ramki, rdzeń LSB oraz obsługę PNG. Testy odbioru znajdują się w `tests/test_karty_s1.py`.**

**Właściciel:** S1 | **Sprawdza:** S5 | **Etap:** Sprint 1, tygodnie 2–3  
**Priorytet:** MUST | **Rozmiar:** M | **Zależność:** S0-08

Dokument określa format ramki wiadomości dla steganografii LSB w obrazach.
Zaimplementowano pakowanie tekstu, parser oraz testy pytest opisane poniżej.
Prace implementacyjne dotyczą Sprintu 1 i wymagają zakończenia S0-08.

## Cel i zakres

Należy opracować ramkę umożliwiającą zapis tekstu jako bajtów, rozpoznanie
formatu, ustalenie długości wiadomości i wykrywanie przypadkowych uszkodzeń.
Tekst ma być kodowany w UTF-8, bez dodawania BOM i terminatora NUL.
Należy dopuścić pustą wiadomość. Nie przewiduje się kompresji, szyfrowania
ani normalizacji Unicode w ramach tego zadania.

Osadzanie ramki w pikselach obrazu jest osobnym krokiem i jest zaimplementowane
w `src/steganografia/lsb.py`.

## Budowa ramki

```text
MAGIC(4 B) | VERSION(1 B) | LENGTH(4 B) | CRC32(4 B) | PAYLOAD
```

| Offset (bajty) | Pole | Rozmiar | Znaczenie |
| --- | --- | --- | --- |
| 0 | MAGIC | 4 B | Stała ASCII `STEG`, hex `53 54 45 47`, identyfikująca format |
| 4 | VERSION | 1 B | Wersja formatu; dla pierwszej wersji należy przyjąć `01` |
| 5 | LENGTH | 4 B | Bezznakowa liczba bajtów payloadu zakodowanego w UTF-8 |
| 9 | CRC32 | 4 B | Bezznakowa suma kontrolna samego payloadu |
| 13 | PAYLOAD | LENGTH B | Właściwa wiadomość w UTF-8 |

Nagłówek ma zajmować dokładnie **13 bajtów**, bez wyrównania i dodatkowych
bajtów pomiędzy polami. LENGTH ma oznaczać **bajty UTF-8, a nie znaki**.
Przykładowo `ą` zajmuje jeden znak, ale dwa bajty UTF-8.

## Kolejność bajtów i bitów

Pola LENGTH i CRC32 należy zapisywać w kolejności **big-endian**,
czyli od najstarszego bajtu do najmłodszego.

Bajty ramki należy przekazywać od początku nagłówka do końca payloadu.
W każdym bajcie należy przyjąć kolejność **MSB-first**: od bitu b7 do b0.
Przykładowo bajt `53` ma być przekazywany jako `0 1 0 1 0 0 1 1`.

Każdy kolejny bit ramki zajmuje najmłodszy bit kolejnej wybranej próbki obrazu.
Implementacja przyjmuje tablicę NumPy `uint8` o układzie
`(wysokość, szerokość, 3)` (RGB) lub `(wysokość, szerokość, 4)` (RGBA).
Próbki są wybierane w kolejności C: wiersze od góry, piksele od lewej,
a w każdym pikselu kanały R, G, B. Kanał alfa jest pomijany i niezmieniany.
Każdy kanał RGB przenosi jeden bit. Bajty ramki są zapisywane MSB-first,
zgodnie z sekcją „Kolejność bajtów i bitów”. Zapis i odczyt stosują tę samą
kolejność; obraz wejściowy nie jest modyfikowany.

## Limit długości zależny od pojemności

Dla `N` dostępnych próbek obrazu pojemność należy obliczać jako
`C = floor(N / 8)` bajtów. Niepełną końcówkę bajtu należy pominąć.
W wariancie RGB z jednym LSB na kanał należy przyjąć
`N = szerokość × wysokość × 3`.

Implementacja stosuje następujące ograniczenia:

- Dla `C < 13` należy odrzucić zapis, ponieważ nie zmieści się nagłówek.
- Dla `C >= 13` długość payloadu ma spełniać
  `0 <= LENGTH <= min(2**32 - 1, C - 13)`.
- Limit samego pola LENGTH ma wynosić 4 294 967 295 bajtów.
- Pusta wiadomość ma wymagać 13 bajtów, czyli 104 próbek obrazu.
- Wiadomość `ą` ma wymagać 15 bajtów, czyli 120 próbek obrazu.

`capacity_bytes(image)` zwraca pojemność całej ramki, natomiast
`payload_capacity_bytes(image)` zwraca pojemność payloadu po odjęciu
13-bajtowego nagłówka. Pojemność parsera pochodzi z rozmiaru obrazu, nigdy
z niezaufanego pola LENGTH.

Moduł udostępnia też niskopoziomowe `embed_bits(image, bits)` i
`extract_bits(image, bit_count)`. Przyjmują i zwracają sekwencję bitów wprost,
co pozwala przenosić inne strumienie; ich pojemność to liczba próbek RGB.
Przy przenoszeniu ramki należy użyć `embed_frame`/`extract_frame`, które
walidują 13-bajtowy nagłówek i uwzględniają go w pojemności payloadu.

## Kontrola CRC32

Należy zastosować **CRC-32/ISO-HDLC**, zgodne z `zlib.crc32`,
z następującymi parametrami:

| Parametr | Wartość |
| --- | --- |
| Szerokość | 32 bity |
| Wielomian | `0x04C11DB7` (postać reflected: `0xEDB88320`) |
| Init | `0xFFFFFFFF` |
| RefIn / RefOut | `true` / `true` |
| XorOut | `0xFFFFFFFF` |

CRC ma obejmować wyłącznie payload. Wynik należy umieścić w nagłówku
jako czterobajtową liczbę big-endian. Wariant reflected algorytmu CRC
nie ma zmieniać ustalonej kolejności przesyłania bitów ramki.

Testy porównują CRC tekstu ASCII `123456789` z wartością kontrolną
`0xCBF43926`. Dla pustego payloadu sprawdzana jest wartość `0x00000000`.
Źródło parametrów i wartości kontrolnej:
[CRC catalogue, CRC-32/ISO-HDLC](https://reveng.sourceforge.io/crc-catalogue/17plus.htm#crc.cat.crc-32-iso-hdlc).

CRC ma służyć do wykrywania przypadkowych uszkodzeń.
**Nie jest uwierzytelnieniem wiadomości** — osoba zmieniająca dane
może obliczyć dla nich nową, pasującą sumę kontrolną.

## Wymagania modułu i parsera

Funkcja `pack` koduje tekst do UTF-8, sprawdza limit długości, oblicza
CRC32 i łączy nagłówek z payloadem. Funkcja `unpack` odczytuje tekst z ramki.

Parser ma sprawdzać kolejno:

1. Czy dostępne jest co najmniej 13 bajtów nagłówka, zanim odczyta jego pola.
2. Czy MAGIC ma oczekiwaną wartość `STEG`.
3. Czy wersja formatu jest obsługiwana.
4. Czy LENGTH mieści się w limicie wynikającym z pojemności obrazu.
5. Czy dostępne dane mają dokładnie `13 + LENGTH` bajtów.
6. Czy CRC32 payloadu zgadza się z wartością z nagłówka.
7. Czy payload jest poprawnym tekstem UTF-8.

Sprawdzenie nagłówka i długości ma nastąpić **przed odczytem payloadu
lub alokacją bufora zależnego od LENGTH**. Niepoprawna ramka ma powodować
zgłoszenie błędu, bez zwracania częściowej wiadomości.

Parser ma przyjmować jedną kompletną ramkę i odrzucać nadmiarowe bajty.
Czytnik LSB najpierw pobiera nagłówek, weryfikuje MAGIC,
wersję i długość względem pojemności, a dopiero potem pobiera payload.
Niewykorzystane próbki obrazu mają pozostawać poza ramką.

## Zaimplementowany moduł ramki

Moduł `src/steganografia/frame.py` udostępnia:

- `pack(text, *, capacity_bytes)` — przyjmuje `str`, koduje UTF-8 bez BOM,
  terminatora i normalizacji Unicode, sprawdza limit bajtów payloadu
  oraz zwraca kompletną ramkę `bytes` z CRC32. Obsługuje pusty tekst.
  Tekst niemożliwy do zakodowania jako UTF-8 zgłasza `FrameError`.
- `parse_header(header, *, capacity_bytes)` — sprawdza dokładnie 13 bajtów
  nagłówka, MAGIC, wersję i LENGTH względem pojemności obrazu. Zwraca
  `FrameHeader` z polami `length`, `crc32` i właściwością `frame_size`.
  Nie pobiera payloadu i nie przydziela dla niego pamięci.
- `unpack(frame, *, capacity_bytes)` — sprawdza nagłówek oraz rzeczywisty
  rozmiar kompletnej ramki przed dostępem do payloadu. Następnie weryfikuje
  CRC32 i dekoduje tekst UTF-8. Odrzuca także nadmiarowe bajty.

`parse_header` i `unpack` przyjmują dane typu `bytes`.
Parametr `capacity_bytes` oznacza pojemność całej ramki w bajtach
i musi być liczbą całkowitą inną niż `bool`.
Błędy ramki i pojemności zgłaszają `FrameError` (podklasa `ValueError`),
a niewłaściwe typy argumentów — `TypeError`.

`extract_frame` odczytuje najpierw stałe 13 bajtów nagłówka i wywołuje
`parse_header` z pojemnością obliczoną z obrazu. Dopiero po sprawdzeniu
MAGIC, wersji i LENGTH odczytuje pozostałe bajty ramki; na koniec `unpack`
weryfikuje CRC32, dokładny rozmiar i UTF-8. `embed_frame` odrzuca niepełną,
nadmiarową lub niepoprawną ramkę. Zapis tworzy kopię obrazu i zmienia
wyłącznie LSB wykorzystanych próbek RGB; wyższe bity, alfa i niewykorzystane
próbki pozostają bez zmian.

## Testy pytest

Testy w `tests/test_karty_s1.py` obejmują:

- Pakowanie i odczyt pustego tekstu.
- Obsługę polskich znaków, np. `Zażółć gęślą jaźń`, oraz długość w bajtach UTF-8.
- Odrzucanie niepełnego nagłówka, błędnego MAGIC i nieobsługiwanej wersji.
- Odrzucanie długości przekraczającej pojemność obrazu lub dostępne dane.
- Odrzucanie uciętego payloadu i nadmiarowych bajtów po ramce.
- Wykrywanie zmiany danych lub sumy kontrolnej.
- Odrzucanie błędnego UTF-8, nawet gdy CRC jest poprawne.
- Przyjęcie ramki mieszczącej się dokładnie w limicie i odrzucenie większej.

Test parsera korzysta ze stałej ramki zapisanej bez wywoływania funkcji
pakującej. Wynik `pack` jest także porównywany ze stałymi wektorami:

```text
Tekst: ""
53 54 45 47 01 00 00 00 00 00 00 00 00

Tekst: "123456789"
53 54 45 47 01 00 00 00 09 CB F4 39 26 31 32 33 34 35 36 37 38 39
```

CRC jest dodatkowo sprawdzane niezależnie od funkcji pakującej za pomocą
referencyjnego algorytmu bitowego i wartości kontrolnej podanej w źródle.
Nie są to „wektory NIST dla LSB”, lecz wektory ramki projektu i przykład
kontrolny CRC.

## Weryfikacja odbioru

Po zainstalowaniu zależności testowych uruchom z katalogu projektu:

```sh
python -m pip install -e ".[test]"
python -m pytest -q
```

Konfiguracja pytest wykrywa testy w `tests/`. Zestaw obejmuje kryteria
ramki (S1-01), LSB (S1-02) i obsługi obrazów (S1-03). Test LSB zawiera
ręcznie wyznaczone wartości próbek, sprawdza pojemność i zachowanie
niewykorzystanych próbek oraz wyższych bitów. Test integracyjny Pillow
tworzy rzeczywisty plik PNG, osadza ramkę, zapisuje nowy plik i ponownie
go otwiera, porównując odzyskane bajty. Sprawdzane są również błędy
wejścia, limity, normalizacja i ochrona przed nadpisaniem oryginału.

Weryfikacja z 22 października 2026: **46 testów przeszło** (Python 3.14,
pytest 9.1.1, Pillow 12.3.0, NumPy 2.5.4). Uruchomiono cały zestaw
przez `python -m pytest -q` w tymczasowym środowisku testowym.

## Informacja o wykorzystaniu AI

Przy opracowaniu dokumentacji korzystano z narzędzia ChatGPT (OpenAI)
do przygotowania i uporządkowania opisu planowanego formatu ramki,
wymagań walidacji oraz propozycji testów. 
Jako wejście AI opisano strukturę, koncepcję działania i realizacji ramki.
Agent uporządkował te założenia w dokumencie Markdown, a następnie pomógł
uzupełnić implementację pakowania, testy i dokumentację weryfikacji.
