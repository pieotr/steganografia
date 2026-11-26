# Podsumowanie benchmarku S4-02

- Data pomiaru (UTC): 2026-11-26T19:12:27Z
- Srodowisko: Python 3.11.9, Windows-AMD64, CPU AMD64 Family 25 Model 33 Stepping 2, AuthenticAMD
- Zbior testowy: 10 obrazow, seed=20261126, powtorzenia=5 (mediana)
- Wspolny payload: 16 B
- Pomiar RAM: tracemalloc.get_traced_memory()[1] (sledzone alokacje Pythona, bez RSS procesu)

| Metoda | Odzyskanie | Sr. wykorzystanie poj. [%] | Mediana PSNR [dB] | Mediana MSE | Mediana embed [ms] | Mediana extract [ms] | Mediana RAM embed [KiB] | BER |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| lsb | 10/10 | 0.21% | 74.81 | 0.0021 | 6.188 | 1.264 | 175.97 | 0.000000 |
| jsteg | 9/10 | nan% | 26.58 | 142.8714 | 72.499 | 36.628 | 1372.58 | 0.000000 |
| jsteg-mf | 4/10 | nan% | 18.46 | 1153.0443 | 76.155 | 44.475 | 1343.72 | 0.000000 |
| f5 | 8/10 | nan% | 25.91 | 169.2903 | 101.138 | 53.482 | 4129.08 | 0.000000 |
| nsf5 | 3/10 | nan% | 21.45 | 466.0433 | 141.426 | 71.096 | 2918.07 | 0.000000 |
| outguess | 5/10 | nan% | 21.43 | 467.3059 | 79.591 | 56.084 | 1430.30 | 0.000000 |
