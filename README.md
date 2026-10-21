# Steganografia w obrazach

Moduł [`lsb`](src/steganografia/lsb.py) udostępnia własne osadzanie i
odczyt sekwencji bitów oraz kompletnych ramek STEG v1 w najmłodszych bitach
próbek obrazu RGB/RGBA.

```python
from steganografia import (
    capacity_bytes,
    embed_frame,
    extract_frame,
    payload_capacity_bytes,
)
from steganografia.frame import unpack

max_payload = payload_capacity_bytes(image)
encoded_image = embed_frame(image, frame_bytes)
frame_bytes = extract_frame(encoded_image)
text = unpack(frame_bytes, capacity_bytes=capacity_bytes(image))
```

Ramka ma 13-bajtowy nagłówek; `payload_capacity_bytes` zwraca pojemność
netto po jego odjęciu. Szczegóły kolejności próbek i bitów opisano w
[dokumentacji formatu i LSB](docs/frame-v1.md).
`frame_bytes` oznacza kompletną ramkę utworzoną przez moduł pakujący zgodny
z formatem STEG v1; samo pakowanie tekstu pozostaje osobnym zadaniem.

## Pliki obrazów (Pillow)

Instalacja: `python -m pip install -e .`.
Moduł [`images`](src/steganografia/images.py) obsługuje **statyczne PNG**,
rozpoznawane po zawartości pliku. Inne formaty (w tym JPEG), animowane
PNG/APNG i głębia 16 bitów są odrzucane z `ImageError`.

`load_cover` normalizuje wejście **przed osadzaniem** do tablicy NumPy
`uint8` o układzie `(wysokość, szerokość, 3)`:

| Tryb PNG | Normalizacja |
| --- | --- |
| 1, L | Rozwinięcie skali szarości do R, G, B |
| P (także palety 1/2/4-bitowe) | Rozwinięcie palety do RGB |
| LA, RGBA | Pominięcie alfa bez mieszania z tłem; zachowanie kolorów także przezroczystych pikseli |
| RGB | Zachowanie wartości 8-bitowych kanałów |

Nie wykonujemy skalowania obrazu, korekcji gamma, zarządzania kolorem ICC
ani obrotu według EXIF. Metadane, paleta i przezroczystość nie są przenoszone
do wyniku. Dopuszczalne głębie wejściowego PNG to 1, 2, 4 i 8 bitów,
zgodnie z dozwolonymi kombinacjami PNG; inne tryby są odrzucane.

```python
from steganografia import load_cover, load_stego, save_png, embed_frame, extract_frame

cover = load_cover("oryginal.png")
encoded = embed_frame(cover, frame_bytes)
save_png(encoded, "wiadomosc.png")
recovered_bytes = extract_frame(load_stego("wiadomosc.png"))
assert recovered_bytes == frame_bytes
```

`save_png` przyjmuje wyłącznie gotowe `uint8 RGB` i zapisuje **bezstratny
PNG**, z rozszerzeniem `.png`. JPEG nie jest ścieżką zapisu, ponieważ
stratna kompresja niszczy LSB. `load_stego` wymaga 8-bitowego RGB PNG
i odczytuje próbki bez ponownej normalizacji; inne tryby odrzuca.

Istniejący plik, w tym oryginał, jest domyślnie chroniony przed nadpisaniem.
Należy wybrać nową nazwę; nadpisanie wymaga jawnego
`save_png(encoded, "oryginal.png", overwrite=True)`. Zapis jest publikowany
atomowo po zakończeniu kodowania.

Limity: plik do **64 MiB**, do **16 000 000 pikseli**, każdy wymiar do
**16 384 pikseli**. Limity wejścia są sprawdzane przed dekodowaniem pikseli;
zapis również sprawdza wymiary i rozmiar pliku wynikowego. Błędne,
nieobsługiwane i zbyt duże pliki oraz błędy zapisu zgłaszają `ImageError`
z opisem przyczyny. Limit wiadomości pozostaje zależny od pojemności LSB
i jest zgłaszany jako `FrameError`.
