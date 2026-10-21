# Steganografia w obrazach

Sprint 1, zadanie 1: zaplanowanie ramki tekstowej dla metody LSB.

Przygotowano [dokumentację formatu](docs/frame-v1.md) oraz
[parser ramki](src/steganografia/frame.py). Parser sprawdza rozmiar nagłówka,
MAGIC, wersję i długość przed dostępem do payloadu, a następnie CRC32 i UTF-8.

Funkcja pakująca, testy pytest i osadzanie wiadomości w obrazie
pozostają do wykonania.
