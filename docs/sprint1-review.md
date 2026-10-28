# Sprint 1 Review: notatka

Cel sprintu: podstawowy algorytm działa na rzeczywistych plikach.

## Pokazano
- CLI LSB: `capacity`, `embed`, `extract` na prawdziwym PNG, z polskimi znakami
  (sekwencja w `docs/README-demo.md`).
- Testy referencyjne: `test_karty_s1.py` (30 testów, karty S1-01..S1-03) oraz
  `test_cli.py` (12 testów CLI); raport w `docs/raport-pytest.xml`.
- Workflow GitHub Actions `pytest.yml`.
- Stan backlogu:
  - GOTOWE: 11 kart, w tym S0-01..S0-08 (ustalenia startowe Sprintu 0) oraz
    S1-01, S1-02, S1-03 (ramka, autorski LSB, obsługa PNG).
  - W TRAKCIE (limit 3): S1-04 (ta karta — Demo CLI LSB, pytest i minimalne CI),
    kończona na dzisiejszym Review.
  - DO ZROBIENIA / DO SPRAWDZENIA / ZABLOKOWANE: puste.
  - PRZYSZŁOŚĆ (Sprint 2–4 + Review): S2-01 Specyfikacja DCT i testy
    matematyczne, S2-02 Autorski DCT, S2-03 Wspólne API i CLI dla obu metod,
    S2-04 Regresja i demo dwóch metod, S3-01 Lokalny interfejs Streamlit,
    S3-02 Wizualizacja różnic i metryk.

## Ograniczenia znane na dziś
- Tylko PNG 8-bit (JPEG niszczy LSB).
- CRC32 wykrywa przypadkowe uszkodzenia, nie jest uwierzytelnieniem.
- Brak szyfrowania treści (LSB ukrywa, nie szyfruje).

## Uwagi z Review
<uzupełnić po spotkaniu>
