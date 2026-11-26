# Procedura benchmarku jakosci, czasu, pamieci i BER (S4-02)

## Cel i zakres
Benchmark porownuje w identycznych warunkach 6 metod: lsb (PNG) oraz jsteg, jsteg-mf, f5, nsf5, outguess (JPEG).

## Zbior testowy (10 obrazow)
Skrypt benchmarks/run.py generuje deterministycznie (seed=20261126) 10 obrazow RGB: 2 gladkie, 3 sceny, 3 tekstury oraz 2 wzory o wysokim kontrascie i rozdzielczosci 256x256.

## Dobor payloadu i pojemnosc
Dla kazdego obrazu i metody wyznaczana jest pojemnosc netto. Wybierany jest jeden wspolny payload (70% najmniejszej pojemnosci netto w zbiorze), aby zmiescil sie w kazdej metodzie (najmniejsza ma OutGuess), a procent wykorzystania pojemnosci jest raportowany w osobnej kolumnie.

## Metryki i metodyka pomiaru
1. MSE i PSNR: liczone na tej samej siatce RGB po konwersji uint8 do float64; dla MSE=0 PSNR wynosi inf.
2. Czas wykonania: mierzony przez time.perf_counter() w 5 powtorzeniach dla kazdej pary (obraz x metoda); raportowana jest mediana oraz wszystkie 5 probek.
3. Zuzycie pamieci RAM: mierzone przez tracemalloc.get_traced_memory()[1] po gc.collect(). Uwaga: tracemalloc obejmuje sledzone alokacje sterty Pythona, a nie pelny szczytowy RSS procesu w systemie operacyjnym.
4. BER (Bit Error Rate): porownuje bity odzyskanego payloadu ze znana sekwencja przy zgodnej dlugosci; uszkodzona ramka lub blad odczytu raportowany jest jako osobny status (np. CORRUPTED_FRAME) i ber=NA, nigdy jako BER=0.

## Uruchomienie
Uruchom z katalogu glownego: python benchmarks/run.py
Wyniki zapisuja sie do benchmarks/results/benchmark_raw.csv oraz benchmarks/results/summary.md.
