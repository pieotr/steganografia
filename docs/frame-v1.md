# Plan formatu ramki — Sprint 1, zadanie 1 (LSB)

**Status: dokumentacja projektowa. Implementacja i testy pozostają do wykonania.**

**Właściciel:** S1 | **Sprawdza:** S5 | **Etap:** Sprint 1, tygodnie 2–3  
**Priorytet:** MUST | **Rozmiar:** M | **Zależność:** S0-08

Dokument określa, co należy przygotować w zadaniu dotyczącym ramki
wiadomości dla steganografii LSB w obrazach. Obecny krok obejmuje wyłącznie
opis formatu i wymagań. Moduł oraz testy pytest mają powstać w kolejnym
kroku, po zakończeniu S0-08. Nie należy rozpoczynać implementacji w Sprincie 0.

## Cel i zakres

Należy opracować ramkę umożliwiającą zapis tekstu jako bajtów, rozpoznanie
formatu, ustalenie długości wiadomości i wykrywanie przypadkowych uszkodzeń.
Tekst ma być kodowany w UTF-8, bez dodawania BOM i terminatora NUL.
Należy dopuścić pustą wiadomość. Nie przewiduje się kompresji, szyfrowania
ani normalizacji Unicode w ramach tego zadania.

Osadzanie ramki w pikselach obrazu ma stanowić osobny krok.

## Planowana budowa ramki

```text
MAGIC(4 B) | VERSION(1 B) | LENGTH(4 B) | CRC32(4 B) | PAYLOAD
```

| Offset (bajty) | Pole | Rozmiar | Planowane znaczenie |
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

Każdy kolejny bit ramki ma zajmować najmłodszy bit kolejnej wybranej
próbki obrazu. Dla podstawowego wariantu RGB proponuje się kolejność:
wiersze od góry, piksele od lewej, kanały R, G, B, z pominięciem alfa.
Na jeden kanał ma przypadać jeden bit wiadomości. Zapis i odczyt mają
stosować identyczną kolejność.

## Limit długości zależny od pojemności

Dla `N` dostępnych próbek obrazu pojemność należy obliczać jako
`C = floor(N / 8)` bajtów. Niepełną końcówkę bajtu należy pominąć.
W wariancie RGB z jednym LSB na kanał należy przyjąć
`N = szerokość × wysokość × 3`.

Przyszła implementacja ma stosować następujące ograniczenia:

- Dla `C < 13` należy odrzucić zapis, ponieważ nie zmieści się nagłówek.
- Dla `C >= 13` długość payloadu ma spełniać
  `0 <= LENGTH <= min(2**32 - 1, C - 13)`.
- Limit samego pola LENGTH ma wynosić 4 294 967 295 bajtów.
- Pusta wiadomość ma wymagać 13 bajtów, czyli 104 próbek obrazu.
- Wiadomość `ą` ma wymagać 15 bajtów, czyli 120 próbek obrazu.

Pojemność przekazywana do parsera ma pochodzić z parametrów obrazu
i wybranego sposobu osadzania. Nie wolno ustalać jej na podstawie
niezaufanego pola LENGTH.

## Planowana kontrola CRC32

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

W przyszłych testach należy porównać CRC tekstu ASCII `123456789`
z wartością kontrolną `0xCBF43926`. Dla pustego payloadu należy oczekiwać
`0x00000000`. Źródło parametrów i wartości kontrolnej:
[CRC catalogue, CRC-32/ISO-HDLC](https://reveng.sourceforge.io/crc-catalogue/17plus.htm#crc.cat.crc-32-iso-hdlc).

CRC ma służyć do wykrywania przypadkowych uszkodzeń.
**Nie jest uwierzytelnieniem wiadomości** — osoba zmieniająca dane
może obliczyć dla nich nową, pasującą sumę kontrolną.

## Wymagania dla przyszłego modułu i parsera

Należy przygotować funkcję pakującą tekst do ramki oraz funkcję
odczytującą tekst z ramki. Funkcja pakująca ma kodować tekst do UTF-8,
sprawdzać limit długości, obliczać CRC32 i łączyć nagłówek z payloadem.

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
Przyszły czytnik LSB ma najpierw pobrać nagłówek, zweryfikować MAGIC,
wersję i długość względem pojemności, a dopiero potem pobrać payload.
Niewykorzystane próbki obrazu mają pozostawać poza ramką.

## Plan testów pytest

Po przygotowaniu implementacji należy sprawdzić:

- Pakowanie i odczyt pustego tekstu.
- Obsługę polskich znaków, np. `Zażółć gęślą jaźń`, oraz długość w bajtach UTF-8.
- Odrzucanie niepełnego nagłówka, błędnego MAGIC i nieobsługiwanej wersji.
- Odrzucanie długości przekraczającej pojemność obrazu lub dostępne dane.
- Odrzucanie uciętego payloadu i nadmiarowych bajtów po ramce.
- Wykrywanie zmiany danych lub sumy kontrolnej.
- Odrzucanie błędnego UTF-8, nawet gdy CRC jest poprawne.
- Przyjęcie ramki mieszczącej się dokładnie w limicie i odrzucenie większej.

Co najmniej jeden test parsera ma korzystać ze stałej ramki zapisanej
bez wywoływania funkcji pakującej. Proponowane wektory do przyszłej
weryfikacji:

```text
Tekst: ""
53 54 45 47 01 00 00 00 00 00 00 00 00

Tekst: "123456789"
53 54 45 47 01 00 00 00 09 CB F4 39 26 31 32 33 34 35 36 37 38 39
```

CRC należy dodatkowo sprawdzić niezależnie od funkcji pakującej,
np. za pomocą referencyjnego algorytmu bitowego i wartości kontrolnej
podanej w źródle. Nie należy określać tych przykładów jako „wektorów NIST
dla LSB”. Są to proponowane wektory ramki projektu i przykład kontrolny CRC.

## Warunki ukończenia zadania

W kolejnym kroku należy dostarczyć działający moduł i testy pytest.
Całe zadanie będzie można uznać za ukończone po sprawdzeniu implementacji
zgodnie z powyższymi wymaganiami. Obecna dokumentacja nie stanowi
potwierdzenia wykonania modułu ani zaliczenia testów.

## Informacja o wykorzystaniu AI

Przy opracowaniu dokumentacji korzystano z narzędzia ChatGPT (OpenAI)
do przygotowania i uporządkowania opisu planowanego formatu ramki,
wymagań walidacji oraz propozycji testów. 
Jako wejście AI była opisana cała struktura, koncept działania i realizacji ramki, agent kodujący jedynie uporządkował te założenia i przygotował je w sformatowanym formacie MD
