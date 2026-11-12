"""Podstawowe operacje przygotowujące obraz do kodowania DCT."""

import numpy as np
from heapq import heappop, heappush


LUMINANCE_QUANTIZATION = np.array(
    [
        [16, 11, 10, 16, 24, 40, 51, 61],
        [12, 12, 14, 19, 26, 58, 60, 55],
        [14, 13, 16, 24, 40, 57, 69, 56],
        [14, 17, 22, 29, 51, 87, 80, 62],
        [18, 22, 37, 56, 68, 109, 103, 77],
        [24, 35, 55, 64, 81, 104, 113, 92],
        [49, 64, 78, 87, 103, 121, 120, 101],
        [72, 92, 95, 98, 112, 100, 103, 99],
    ],
    dtype=np.float64,
)

CHROMINANCE_QUANTIZATION = np.array(
    [
        [17, 18, 24, 47, 99, 99, 99, 99],
        [18, 21, 26, 66, 99, 99, 99, 99],
        [24, 26, 56, 99, 99, 99, 99, 99],
        [47, 66, 99, 99, 99, 99, 99, 99],
        [99, 99, 99, 99, 99, 99, 99, 99],
        [99, 99, 99, 99, 99, 99, 99, 99],
        [99, 99, 99, 99, 99, 99, 99, 99],
        [99, 99, 99, 99, 99, 99, 99, 99],
    ],
    dtype=np.float64,
)

_DCT_BASIS = np.empty((8, 8), dtype=np.float64)
for _frequency in range(8):
    _normalization = 1 / np.sqrt(2) if _frequency == 0 else 1.0
    _DCT_BASIS[_frequency] = (
        0.5
        * _normalization
        * np.cos((2 * np.arange(8) + 1) * _frequency * np.pi / 16)
    )


def rgb_to_ycbcr(image: np.ndarray) -> np.ndarray:
    """Konwertuj obraz RGB do składowych Y, Cb i Cr.

    Wynik ma kształt ``(wysokość, szerokość, 3)`` i typ ``float64``.
    Wartości są zgodne z pełnozakresową konwencją używaną w JPEG:
    ``Y`` opisuje jasność, a ``Cb`` i ``Cr`` różnicę koloru względem
    jasności. Składowe chrominancji mają przesunięcie o 128.

    Nie wykonujemy tutaj klamrowania ani zaokrąglania. Jest to celowe:
    kolejne etapy DCT powinny pracować na wartościach zmiennoprzecinkowych.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError("image musi być tablicą NumPy")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(
            "image musi mieć układ (wysokość, szerokość, 3) dla obrazu RGB"
        )
    if image.dtype != np.uint8:
        raise ValueError("image musi mieć typ uint8")

    red = image[..., 0].astype(np.float64)
    green = image[..., 1].astype(np.float64)
    blue = image[..., 2].astype(np.float64)

    return np.stack(
        (
            0.299000 * red + 0.587000 * green + 0.114000 * blue,
            -0.168736 * red - 0.331264 * green + 0.500000 * blue + 128.0,
            0.500000 * red - 0.418688 * green - 0.081312 * blue + 128.0,
        ),
        axis=-1,
    )


def quantize_block(
    coefficients: np.ndarray,
    matrix: np.ndarray = LUMINANCE_QUANTIZATION,
) -> np.ndarray:
    """Podziel współczynniki DCT przez macierz kwantyzacji i zaokrąglij.

    Domyślna macierz jest przeznaczona dla luminancji. Dla ``Cb`` i ``Cr``
    należy przekazać ``CHROMINANCE_QUANTIZATION``. Zaokrąglenie powoduje
    utratę części informacji i jest pierwszym stratnym etapem JPEG.
    """
    if not isinstance(coefficients, np.ndarray):
        raise TypeError("coefficients musi być tablicą NumPy")
    if coefficients.shape != (8, 8):
        raise ValueError("coefficients musi mieć kształt (8, 8)")
    if not np.issubdtype(coefficients.dtype, np.number):
        raise TypeError("coefficients musi zawierać wartości liczbowe")
    if not isinstance(matrix, np.ndarray):
        raise TypeError("matrix musi być tablicą NumPy")
    if matrix.shape != (8, 8):
        raise ValueError("matrix musi mieć kształt (8, 8)")
    if not np.issubdtype(matrix.dtype, np.number):
        raise TypeError("matrix musi zawierać wartości liczbowe")
    if np.any(matrix <= 0):
        raise ValueError("matrix musi zawierać wyłącznie liczby dodatnie")

    return np.rint(coefficients.astype(np.float64) / matrix).astype(np.int32)


def zigzag_scan(block: np.ndarray) -> np.ndarray:
    """Odczytaj kwantyzowany blok 8x8 w kolejności zygzakowej.

    Kolejność zaczyna się od współczynnika DC ``(0, 0)`` i przechodzi
    naprzemiennie po przekątnych macierzy. Zwracana tablica ma 64 elementy.
    Taki układ grupuje zwykle wyzerowane współczynniki wysokich częstotliwości
    na końcu, co przygotowuje dane do kodowania RLE.
    """
    if not isinstance(block, np.ndarray):
        raise TypeError("block musi być tablicą NumPy")
    if block.shape != (8, 8):
        raise ValueError("block musi mieć kształt (8, 8)")
    if not np.issubdtype(block.dtype, np.number):
        raise TypeError("block musi zawierać wartości liczbowe")

    result = np.empty(64, dtype=block.dtype)
    position = 0
    for diagonal in range(15):
        if diagonal % 2 == 0:
            rows = range(min(diagonal, 7), max(0, diagonal - 7) - 1, -1)
        else:
            rows = range(max(0, diagonal - 7), min(diagonal, 7) + 1)
        for row in rows:
            column = diagonal - row
            result[position] = block[row, column]
            position += 1
    return result


def subsample_420(ycbcr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Wykonaj subsampling chrominancji 4:2:0.

    Zwraca osobno ``Y``, ``Cb`` i ``Cr``. Składowa jasności zachowuje
    oryginalny rozmiar obrazu, natomiast każda składowa chrominancji ma
    rozmiar ``(ceil(wysokość / 2), ceil(szerokość / 2))``. Wartości
    chrominancji są uśredniane z obszarów 2x2; przy nieparzystym rozmiarze
    ostatni wiersz lub kolumna jest powtarzana przed uśrednieniem.

    Jest to redukcja rozdzielczości chrominancji stosowana przed blokami DCT
    w typowym JPEG. Nie wykonuje jeszcze dopełniania komponentów do bloków
    8x8 ani zapisu pliku JPEG.
    """
    if not isinstance(ycbcr, np.ndarray):
        raise TypeError("ycbcr musi być tablicą NumPy")
    if ycbcr.ndim != 3 or ycbcr.shape[2] != 3:
        raise ValueError(
            "ycbcr musi mieć układ (wysokość, szerokość, 3)"
        )
    if ycbcr.dtype != np.float64:
        raise ValueError("ycbcr musi mieć typ float64")
    if ycbcr.shape[0] == 0 or ycbcr.shape[1] == 0:
        raise ValueError("ycbcr nie może być pustym obrazem")

    height, width = ycbcr.shape[:2]
    padded = np.pad(
        ycbcr[..., 1:],
        ((0, height % 2), (0, width % 2), (0, 0)),
        mode="edge",
    )
    chroma = padded.reshape(
        (padded.shape[0] // 2, 2, padded.shape[1] // 2, 2, 2)
    ).mean(axis=(1, 3))

    return ycbcr[..., 0], chroma[..., 0], chroma[..., 1]


def get_block(component: np.ndarray, index: int, *, block_size: int = 8) -> np.ndarray:
    """Zwróć blok o podanym indeksie z dwuwymiarowej składowej obrazu.

    Bloki są numerowane w kolejności wierszami, od zera. Obraz jest logicznie
    dopełniany przez powielenie wartości z jego ostatniego wiersza i kolumny,
    aby jego wymiary były wielokrotnością rozmiaru bloku. Zwrócony blok ma
    zawsze kształt ``(block_size, block_size)`` i jest kopią danych.
    """
    if not isinstance(component, np.ndarray):
        raise TypeError("component musi być tablicą NumPy")
    if component.ndim != 2:
        raise ValueError("component musi być tablicą dwuwymiarową")
    if component.shape[0] == 0 or component.shape[1] == 0:
        raise ValueError("component nie może być pustym obrazem")
    if not isinstance(index, (int, np.integer)) or isinstance(index, (bool, np.bool_)):
        raise TypeError("index musi być liczbą całkowitą")
    if not isinstance(block_size, (int, np.integer)) or isinstance(
        block_size, (bool, np.bool_)
    ) or block_size < 1:
        raise ValueError("block_size musi być dodatnią liczbą całkowitą")

    block_size = int(block_size)
    blocks_y = (component.shape[0] + block_size - 1) // block_size
    blocks_x = (component.shape[1] + block_size - 1) // block_size
    block_count = blocks_y * blocks_x
    if index < 0 or index >= block_count:
        raise IndexError(
            f"index poza zakresem; obraz zawiera {block_count} bloków"
        )

    row = (int(index) // blocks_x) * block_size
    column = (int(index) % blocks_x) * block_size
    row_end = min(row + block_size, component.shape[0])
    column_end = min(column + block_size, component.shape[1])

    block = component[row:row_end, column:column_end]
    return np.pad(
        block,
        ((0, block_size - block.shape[0]), (0, block_size - block.shape[1])),
        mode="edge",
    ).copy()


def dct_block(block: np.ndarray, *, level_shift: bool = True) -> np.ndarray:
    """Oblicz dwuwymiarową DCT-II dla pojedynczego bloku 8x8.

    Przy ustawieniu ``level_shift=True`` (domyślnie) od każdej próbki
    odejmowane jest 128, zgodnie z przygotowaniem danych w JPEG. Wynik
    zawiera 64 współczynniki częstotliwości i ma typ ``float64``.

    Funkcja używa bezpośredniego wzoru DCT zamiast gotowej implementacji,
    żeby pokazać kolejne operacje algorytmu.
    """
    if not isinstance(block, np.ndarray):
        raise TypeError("block musi być tablicą NumPy")
    if block.shape != (8, 8):
        raise ValueError("block musi mieć kształt (8, 8)")
    if not np.issubdtype(block.dtype, np.number):
        raise TypeError("block musi zawierać wartości liczbowe")
    if not isinstance(level_shift, (bool, np.bool_)):
        raise TypeError("level_shift musi być wartością bool")

    samples = block.astype(np.float64, copy=True)
    if level_shift:
        samples -= 128.0

    return _DCT_BASIS @ samples @ _DCT_BASIS.T


__all__ = [
    "CHROMINANCE_QUANTIZATION",
    "LUMINANCE_QUANTIZATION",
    "dct_block",
    "get_block",
    "quantize_block",
    "rgb_to_ycbcr",
    "subsample_420",
    "zigzag_scan",
]