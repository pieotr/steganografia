# Sprint 1 Review — materiał do spotkania

**Status: przygotowanie; spotkanie Review nie zostało tu potwierdzone.**

Cel sprintu: podstawowy algorytm LSB działa na rzeczywistych plikach.
Lokalna demonstracja CLI jest opisana w [instrukcji](cli-demo.md),
a jej wyniki w [raporcie](reports/cli-verification.md).

## Stan prac widoczny w repozytorium

Poniższa tabela dotyczy zakresu omawianych zadań. Aktualny stan całego
backlogu należy uzupełnić z tablicy zespołu przed Review.

| Zakres | Stan |
| --- | --- |
| S1-01: ramka STEG v1 | Implementacja, dokumentacja i istniejące testy gotowe |
| S1-02: rdzeń LSB | Implementacja i istniejące testy gotowe |
| S1-03: Pillow / PNG | Implementacja, dokumentacja i test plikowy gotowe |
| CLI embed/extract/capacity | Gotowe; demonstracja lokalna wykonana |
| Nowe automatyczne testy CLI | Do przygotowania przez osobę odpowiedzialną za testy |
| Minimalny workflow pytest | Plik gotowy; wykonanie na GitHubie do potwierdzenia |
| Prezentacja na Review | Do wykonania |

## Plan prezentacji

1. Wykonać sekwencję z `docs/cli-demo.md`: pojemność, osadzenie polskiego
   tekstu, zapis nowego PNG i odzyskanie identycznego tekstu z pliku.
2. Pokazać czytelny błąd przekroczenia pojemności i niepoprawnej ramki.
3. Pokazać test stałej ramki `123456789`, kontrolne CRC `0xCBF43926`
   oraz test oczekiwanych wartości próbek LSB w `tests/test_karty_s1.py`.
4. Pokazać wynik pytest, nowe testy CLI po ich dostarczeniu oraz wynik workflow.
5. Otworzyć aktualny backlog zespołu i uzgodnić pozostałe zadania.

## Do uzupełnienia po spotkaniu

- Data i uczestnicy: do uzupełnienia.
- Osoba prezentująca CLI i wynik demonstracji: do uzupełnienia.
- Wynik i raport nowych testów CLI: do uzupełnienia przez osobę testującą.
- Link do wykonania workflow i wynik: do uzupełnienia.
- Link do backlogu oraz aktualny stan: do uzupełnienia.
- Uwagi, decyzje i zadania po Review: do uzupełnienia.

Kryterium „Podczas Review pokazano…” pozostaje otwarte do faktycznego
przeprowadzenia prezentacji. Lokalne wyniki istniejących testów nie
potwierdzają jeszcze zakończenia nowych testów CLI ani wykonania workflow.
