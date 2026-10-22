# Weryfikacja integracji CLI — 22 października 2026

Weryfikacja lokalna: Python 3.14, Pillow 12.3.0, NumPy 2.5.4.
Demonstrację wykonano przez `PYTHONPATH=src python -m steganografia`,
na rzeczywistych plikach w `/tmp/steganografia-cli-demo/`.
Sekwencja odtwarzalna znajduje się w [instrukcji demonstracji](../cli-demo.md).
Potwierdzono również instalację projektu w trybie edytowalnym i uruchomienie
zainstalowanej komendy `steganografia` (`--help`, `capacity`, `extract`).

| Ręcznie sprawdzony scenariusz | Wynik |
| --- | --- |
| Pojemność RGB PNG 40×40 | 600 B ramki, 587 B tekstu UTF-8 |
| Osadzenie i odczyt „Zażółć gęślą jaźń” | Kod 0; dokładnie 26 bajtów UTF-8 |
| Tekst 588 B przy limicie 587 B | Kod 1; komunikat o przekroczeniu pojemności |
| Ekstrakcja ze zwykłego obrazu bez ramki | Kod 1; komunikat „Niepoprawna ramka STEG: Niepoprawne MAGIC” |
| Zapis pod istniejącą nazwą | Kod 1; plik chroniony przed nadpisaniem |
| Brak pliku wejściowego | Kod 1; komunikat z przyczyną i ścieżką |
| Osadzenie i odczyt pustego tekstu | Kod 0; pusty stdout ekstrakcji |
| Zapis z `--overwrite` | Kod 0; świadome zastąpienie pliku wynikowego |
| Zachowanie oryginalnego PNG | Bajty oryginału bez zmian |

## Istniejący zestaw pytest

Uruchomiono istniejące testy bez zmian ich źródła:

```sh
/tmp/steganografia-test-env/bin/python -m pytest -q
```

```text
..............................................                           [100%]
46 passed in 0.18s
```

Środowisko testowe: pytest 9.1.1. Zestaw sprawdza ramkę, CRC, LSB i PNG;
nie obejmuje nowych komend CLI. Ich testy automatyczne przygotowuje inny
członek zespołu. Powyższa tabela opisuje ręczną weryfikację integracji.

## Workflow

Dodano `.github/workflows/pytest.yml`: Python 3.12, instalacja `.[test]`,
pytest i raport JUnit w artefakcie `raport-pytest`. Workflow nie został
jeszcze uruchomiony na GitHubie. Po wykonaniu należy dodać link do runu
i jego wynik do notatki Review. Nie wdraża aplikacji do chmury.

## Rozszerzenie: wejście i wyjście TXT

Ręcznie sprawdzono `embed --text-file` oraz `extract --output` (także `-o`)
na rzeczywistych plikach. Przepływ TXT → PNG → TXT zachował identyczne
bajty UTF-8 z polskimi znakami, BOM i końcami wierszy CRLF/LF.
Potwierdzono pusty plik, odrzucenie błędnego UTF-8 i zbyt długiego tekstu,
brak pliku źródłowego, wzajemne wykluczanie `--text`/`--text-file`, ochronę
istniejącego TXT oraz jawne nadpisanie przez `--overwrite`.
Niepoprawna ramka nie zmieniła istniejącego pliku tekstowego.
Nie dodano nowych automatycznych testów CLI.
