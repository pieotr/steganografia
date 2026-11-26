\# Rejestr znanych błędów i ograniczeń (S4)



\## Aktywne błędy

\* \*\*\[BUG-01] Brakująca implementacja `rs\_analysis`\*\*: Nazwa `rs\_analysis` znajduje się w `steganografia.\_\_all\_\_` oraz `steganografia.steganalysis.\_\_all\_\_`, ale nie istnieje odpowiadający jej moduł `steganalysis/rs.py`. Powoduje to błąd `AttributeError` przy `from steganografia import \*`.



\## Jawne ograniczenia systemu

\* \*\*Brak korekcji błędów (ECC):\*\* Suma kontrolna CRC32 wykrywa przekłamania bitów po zakłóceniach (rekompresja JPEG, szum Gaussa, skalowanie), ale nie rekonstruuje uszkodzonego payloadu.

\* \*\*Format JPEG:\*\* Obsługiwany jest wyłącznie baseline JPEG 4:2:0; obrazy progresywne (SOF2) oraz 4:4:4 są jawnie odrzucane przez parser `read\_jpeg`.

\* \*\*Steganaliza:\*\* Wskaźniki statystyczne (test par chi-kwadrat, odległość Hellingera) wskazują na anomalie rozkładu próbek/współczynników i nie stanowią dowodu kryptograficznego ani absolutnego wykrycia.

