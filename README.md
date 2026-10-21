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
