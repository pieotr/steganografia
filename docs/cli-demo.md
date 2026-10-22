# Demonstracja CLI LSB — Sprint 1

Komendy poniżej są przeznaczone dla powłoki Bash na Linux/macOS.
Uruchom je w terminalu obsługującym UTF-8, z katalogu repozytorium.

## Przygotowanie

```sh
python -m venv .venv
```

```sh
source .venv/bin/activate
python -m pip install -e .
mkdir demo
python -c "from PIL import Image; Image.new('RGB', (40, 40), (120, 80, 200)).save('demo/oryginal.png')"
```

## Ukrycie i odzyskanie polskiego tekstu

```sh
steganografia capacity demo/oryginal.png
steganografia embed demo/oryginal.png demo/wiadomosc.png --text "Zażółć gęślą jaźń"
steganografia extract demo/wiadomosc.png > demo/odzyskany.txt
python -c "from pathlib import Path; p = Path('demo/odzyskany.txt'); print(repr(p.read_text(encoding='utf-8'))); print(len(p.read_bytes()), 'bajtów UTF-8')"
```

Oczekiwane wyniki: pojemność `600 B ramki; 587 B tekstu UTF-8`,
odzyskany tekst `'Zażółć gęślą jaźń'`, długość `26 bajtów UTF-8`.
Oryginał pozostaje bez zmian. Wynik to nowy, bezstratny PNG w trybie RGB.
Ekstrakcja nie normalizuje ponownie obrazu.

Na stdout komendy `extract` trafia wyłącznie tekst, bez dodanego końca
wiersza. Pojemność i pozostałe komunikaty trafiają na stderr, więc nie
trafią do `odzyskany.txt`. Nie łącz strumieni przez `2>&1` podczas zapisu tekstu.
Przekierowanie `>` nadpisuje wskazany plik tekstowy zgodnie z regułami powłoki.

## Wiadomość z pliku TXT i odzyskanie do TXT

Przygotuj plik UTF-8, a następnie użyj `--text-file` zamiast `--text`:

```sh
python -c "from pathlib import Path; Path('demo/wiadomosc.txt').write_bytes('Zażółć gęślą jaźń\nDrugi wiersz.\n'.encode('utf-8'))"
steganografia embed demo/oryginal.png demo/z-pliku.png --text-file demo/wiadomosc.txt
steganografia extract demo/z-pliku.png --output demo/odzyskany-z-pliku.txt
```

`--output` można skrócić do `-o`. Zapisuje dokładne bajty wiadomości UTF-8,
z zachowaniem końców wierszy i ewentualnego BOM. Nie dopisuje końca wiersza
ani BOM. Na stdout nie trafia wtedy tekst; komunikat o zapisie trafia na stderr.
Istniejący TXT jest chroniony przed nadpisaniem, chyba że podasz
`--overwrite`. Katalog docelowy musi istnieć. Niepoprawna ramka nie zmienia
pliku docelowego. Dozwolona jest dokładnie jedna opcja źródła wiadomości:
`--text` albo `--text-file`.

## Komunikaty błędów

Dla obrazu 40×40 payload może zawierać maksymalnie 587 bajtów. Tekst
złożony z 294 znaków `ą` zajmuje 588 bajtów i zostanie odrzucony:

```text
Pojemność: 600 B ramki; 587 B tekstu UTF-8 (po odjęciu nagłówka 13 B).
Błąd: LENGTH (588 B) przekracza pojemność obrazu (maksymalnie 587 B payloadu)
```

Odczyt wejściowego obrazu bez wiadomości:

```sh
steganografia extract demo/oryginal.png
```

```text
Błąd: Niepoprawna ramka STEG: Niepoprawne MAGIC
```

Oba błędy kończą komendę kodem `1`. Nie powstaje częściowa wiadomość.
Błędny CRC, wersja, długość i kodowanie UTF-8 również przerywają odczyt.

Ponowne wykonanie `embed` z tą samą nazwą wyjściową zgłasza błąd
istniejącego pliku. Świadome nadpisanie wymaga flagi:

```sh
steganografia embed demo/oryginal.png demo/wiadomosc.png --text "Nowa wiadomość" --overwrite
```

Pusty tekst jest obsługiwany przez `--text ""` i nadal wymaga 13 bajtów
na nagłówek. Opcja `--help` opisuje komendy i ich argumenty.

## Podpowiedzi pod Tab w fish

Po zainstalowaniu projektu aktywuj środowisko w fish:

```fish
source .venv/bin/activate.fish
```

Z głównego katalogu repozytorium włącz podpowiedzi w bieżącej sesji:

```fish
source completions/steganografia.fish
```

Teraz `steganografia ` i Tab pokaże `embed`, `extract` i `capacity`.
`steganografia embed --` i Tab podpowie `--text`, `--overwrite` oraz
`--help`. Dla argumentów plikowych podpowiedzi preferują pliki `.png`.

Aby fish ładował je automatycznie w kolejnych sesjach, skopiuj plik:

```fish
mkdir -p $__fish_config_dir/completions
cp completions/steganografia.fish $__fish_config_dir/completions/steganografia.fish
```

Po zmianach w pliku repozytorium ponów kopiowanie. Uzupełnienia dotyczą
komendy `steganografia`; wariant `python -m steganografia` nie jest nimi objęty.

## Materiał dla osoby odpowiedzialnej za testy

Nie dodano nowych testów CLI w tym zadaniu. Do przygotowania pozostają
automatyczne sprawdzenia komend i kodów zakończenia, polskiego i pustego
tekstu, granicy pojemności, błędnej ramki, rozdzielenia stdout/stderr oraz
ochrony przed nadpisaniem. Istniejące testy rdzenia są w `tests/`.
Workflow pytest jest przygotowany w `.github/workflows/pytest.yml`.
