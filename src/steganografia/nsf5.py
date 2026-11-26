"""nsF5 (non-shrinkage F5): kodowanie syndromowe wet paper na współczynnikach JPEG.

Schemat zgodny z ideą nsF5 (Fridrich, Pevný, Kodovský, 2007):

* nośnikiem są **wszystkie** współczynniki AC trzech kanałów, łącznie z zerami,
  potasowane pseudolosowo kluczem i podzielone na bloki niezależnie od wartości;
* bit współczynnika to ``|c| mod 2`` (dla zera 0), więc zmniejszenie ``|c|``
  o 1 zawsze odwraca bit, także przy ``±1 -> 0``;
* **suche** (zmienialne) są współczynniki niezerowe, **mokre** to zera; zmiany
  idą zawsze w stronę zera, zera nigdy nie są zmieniane;
* każdy blok niesie jeden bajt: syndrom to XOR pseudolosowych 8-bitowych
  kolumn pozycji o nieparzystym ``|c|``; nadawca szuka najmniejszego zbioru
  suchych pozycji, którego kolumny dają brakującą różnicę;
* odbiorca liczy syndromy ze wszystkich pozycji bloku, więc nie musi wiedzieć,
  które były suche; shrinkage (``±1 -> 0``) jest zwykłą, poprawną zmianą.

Pierwsze 1/16 pozycji przenosi 13-bajtowy nagłówek ramki (stały podział),
reszta jest dzielona na tyle bloków, ile bajtów ma payload, więc krótsze
wiadomości dostają większe bloki i wymagają mniej zmian.
"""

from pathlib import Path
import hashlib

import numpy as np

from .dct import CHROMINANCE_QUANTIZATION, LUMINANCE_QUANTIZATION, rgb_to_ycbcr, subsample_420
from .frame import HEADER_SIZE, FrameError, parse_header, unpack_bytes
from .images import ImageError, load_cover
from .jpeg import _encode_component, read_jpeg, write_jpeg

DEFAULT_KEY = "steganografia-nsf5"
_BITS_PER_BLOCK = 8
# Średnia liczba suchych pozycji na blok przy pełnej pojemności. Przy 48
# prawdopodobieństwo, że suche kolumny bloku nie rozpinają GF(2)^8, wynosi
# około 255 * e^-24, czyli praktycznie zero nawet dla dziesiątek tysięcy bloków.
_DRY_PER_BLOCK = 48
_HEADER_SHARE = 16


# --------------------------------------------------------------------------- dane


def _components(image: np.ndarray) -> tuple[int, int, list[list[np.ndarray]]]:
    y, cb, cr = subsample_420(rgb_to_ycbcr(image))
    return (
        image.shape[1],
        image.shape[0],
        [
            _encode_component(y, LUMINANCE_QUANTIZATION),
            _encode_component(cb, CHROMINANCE_QUANTIZATION),
            _encode_component(cr, CHROMINANCE_QUANTIZATION),
        ],
    )


def _flat_ac(components: list[list[np.ndarray]]) -> np.ndarray:
    """Wszystkie współczynniki AC (Y, Cb, Cr) w jednej tablicy int64."""
    return np.concatenate([
        np.asarray(blocks, dtype=np.int64)[:, 1:64].reshape(-1)
        for blocks in components
        if len(blocks)
    ])


def _write_back(components: list[list[np.ndarray]], flat: np.ndarray) -> None:
    offset = 0
    for blocks in components:
        for block in blocks:
            block[1:64] = flat[offset:offset + 63]
            offset += 63


class _Layout:
    """Podział potasowanych pozycji na bloki; zależy tylko od klucza i rozmiaru."""

    def __init__(self, size: int, key: str) -> None:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        generator = np.random.default_rng(int.from_bytes(digest, "big"))
        self.size = size
        self.order = generator.permutation(size)
        self.columns = generator.integers(1, 1 << _BITS_PER_BLOCK, size=size, dtype=np.int64)
        self.header_block = size // (HEADER_SIZE * _HEADER_SHARE)
        self.payload_start = HEADER_SIZE * self.header_block
        self.payload_size = size - self.payload_start

    def header_bounds(self) -> list[tuple[int, int]]:
        n = self.header_block
        return [(index * n, (index + 1) * n) for index in range(HEADER_SIZE)]

    def payload_bounds(self, block_count: int) -> list[tuple[int, int]]:
        if block_count == 0:
            return []
        n = self.payload_size // block_count
        if n == 0:
            raise FrameError("Ramka nsF5 jest dłuższa niż liczba współczynników obrazu")
        start = self.payload_start
        return [(start + index * n, start + (index + 1) * n) for index in range(block_count)]


def _syndromes(shuffled: np.ndarray, columns: np.ndarray, bounds: list[tuple[int, int]]) -> list[int]:
    odd = (np.abs(shuffled) & 1).astype(bool)
    contributions = np.where(odd, columns, 0)
    return [
        int(np.bitwise_xor.reduce(contributions[start:end])) if end > start else 0
        for start, end in bounds
    ]


def _rank(values: np.ndarray) -> int:
    """Rząd zbioru wektorów GF(2)^8 (baza XOR)."""
    basis = [0] * _BITS_PER_BLOCK
    rank = 0
    for value in np.unique(values).tolist():
        for bit in reversed(range(_BITS_PER_BLOCK)):
            if not (value >> bit) & 1:
                continue
            if basis[bit] == 0:
                basis[bit] = value
                rank += 1
                break
            value ^= basis[bit]
    return rank


# ------------------------------------------------------------------ wet paper


def _min_changes(columns: np.ndarray, required: int) -> list[int] | None:
    """Najmniejszy zbiór pozycji (indeksy w ``columns``), których XOR = ``required``.

    Przeszukiwanie wszerz po 256 możliwych syndromach: warstwa ``w`` zawiera
    syndromy osiągalne dokładnie ``w`` zmianami, więc pierwsze trafienie jest
    rozwiązaniem o najmniejszej liczbie zmian. Pozycje o tej samej kolumnie
    są równoważne, dlatego wystarczy po jednej na wartość.
    """
    if required == 0:
        return []
    values, first = np.unique(columns, return_index=True)
    slot_of = dict(zip(values.tolist(), first.tolist()))
    parent: dict[int, tuple[int, int]] = {0: (0, 0)}
    frontier = [0]
    while frontier:
        next_frontier = []
        for state in frontier:
            for value in slot_of:
                candidate = state ^ value
                if candidate in parent:
                    continue
                parent[candidate] = (state, value)
                if candidate == required:
                    changes = []
                    while candidate != 0:
                        candidate, used = parent[candidate]
                        changes.append(slot_of[used])
                    return changes
                next_frontier.append(candidate)
        frontier = next_frontier
    return None


def _embed_block(
    shuffled: np.ndarray,
    columns: np.ndarray,
    start: int,
    end: int,
    target: int,
) -> None:
    values = shuffled[start:end]
    odd = (np.abs(values) & 1).astype(bool)
    current = int(np.bitwise_xor.reduce(np.where(odd, columns[start:end], 0))) if end > start else 0
    required = current ^ target
    if required == 0:
        return
    dry = np.flatnonzero(values != 0)
    changes = _min_changes(columns[start:end][dry], required)
    if changes is None:
        raise FrameError(
            "nsF5: suche współczynniki bloku nie wystarczają do zapisania bajtu; "
            "użyj krótszej wiadomości lub innego klucza"
        )
    for change in changes:
        slot = start + int(dry[change])
        value = int(shuffled[slot])
        shuffled[slot] = value - 1 if value > 0 else value + 1


def _embed(components: list[list[np.ndarray]], frame: bytes, *, key: str) -> int:
    flat = _flat_ac(components)
    layout = _Layout(flat.size, key)
    capacity = _capacity(flat, layout)
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack_bytes(frame, capacity_bytes=capacity)

    shuffled = flat[layout.order]
    bounds = layout.header_bounds() + layout.payload_bounds(len(frame) - HEADER_SIZE)
    for (start, end), target in zip(bounds, frame):
        _embed_block(shuffled, layout.columns, start, end, target)
    flat[layout.order] = shuffled
    _write_back(components, flat)
    return capacity


def _extract(components: list[list[np.ndarray]], *, key: str) -> bytes:
    flat = _flat_ac(components)
    layout = _Layout(flat.size, key)
    if layout.header_block == 0:
        raise FrameError("JPEG nie mieści nagłówka nsF5")
    shuffled = flat[layout.order]
    header = bytes(_syndromes(shuffled, layout.columns, layout.header_bounds()))
    parsed = parse_header(header, capacity_bytes=_upper_capacity(layout))
    payload = bytes(_syndromes(
        shuffled, layout.columns, layout.payload_bounds(parsed.length)
    ))
    frame = header + payload
    unpack_bytes(frame, capacity_bytes=_upper_capacity(layout))
    return frame


# ------------------------------------------------------------------ pojemność


def _capacity(flat: np.ndarray, layout: _Layout) -> int:
    """Pojemność ramki w bajtach dla okładki (nadawca zna suche pozycje)."""
    if layout.header_block == 0:
        return 0
    shuffled = flat[layout.order]
    for start, end in layout.header_bounds():
        dry = shuffled[start:end] != 0
        if _rank(layout.columns[start:end][dry]) < _BITS_PER_BLOCK:
            return 0
    dry_payload = int(np.count_nonzero(shuffled[layout.payload_start:]))
    return HEADER_SIZE + dry_payload // _DRY_PER_BLOCK


def _upper_capacity(layout: _Layout) -> int:
    """Górna granica ramki do odczytu: odbiorca nie zna suchych pozycji okładki."""
    return HEADER_SIZE + layout.payload_size


def capacity_from_png(image: np.ndarray, *, key: str = DEFAULT_KEY) -> int:
    flat = _flat_ac(_components(image)[2])
    return _capacity(flat, _Layout(flat.size, key))


def capacity_from_jpeg(path: str, *, key: str = DEFAULT_KEY) -> int:
    coefficients = read_jpeg(path)
    flat = _flat_ac([coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks])
    return _upper_capacity(_Layout(flat.size, key))


# ------------------------------------------------------------------ pliki


def embed_jpeg(
    input_path: str,
    output_path: str,
    frame: bytes,
    *,
    key: str = DEFAULT_KEY,
    overwrite: bool = False,
) -> None:
    if not isinstance(key, str):
        raise TypeError("Klucz nsF5 musi mieć typ str")
    image = load_cover(input_path)
    width, height, components = _components(image)
    _embed(components, frame, key=key)
    target = Path(output_path)
    if target.exists() and not overwrite:
        raise ImageError(f"Plik '{target}' już istnieje; wybierz inną nazwę lub --overwrite")
    write_jpeg(
        target,
        width=width,
        height=height,
        y_blocks=components[0],
        cb_blocks=components[1],
        cr_blocks=components[2],
    )


def extract_jpeg(path: str, *, key: str = DEFAULT_KEY) -> bytes:
    if not isinstance(key, str):
        raise TypeError("Klucz nsF5 musi mieć typ str")
    coefficients = read_jpeg(path)
    return _extract(
        [coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks],
        key=key,
    )


__all__ = [
    "DEFAULT_KEY",
    "capacity_from_jpeg",
    "capacity_from_png",
    "embed_jpeg",
    "extract_jpeg",
]
