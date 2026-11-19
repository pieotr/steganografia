"""Non-shrinkage F5 z wet-paper codingiem dla współczynników JPEG."""

from pathlib import Path
import hashlib

import numpy as np

from .dct import CHROMINANCE_QUANTIZATION, LUMINANCE_QUANTIZATION, rgb_to_ycbcr, subsample_420
from .frame import HEADER_SIZE, FrameError, parse_header, unpack
from .images import ImageError, load_cover
from .jpeg import _encode_component, read_jpeg, write_jpeg

DEFAULT_KEY = "steganografia-nsf5"
_GROUP_SIZE = 31
_MESSAGE_BITS = 5


def _bits(data: bytes) -> list[int]:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big").tolist()


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


def _locations(components: list[list[np.ndarray]]) -> list[tuple[int, int, int]]:
    return [
        (component, block, position)
        for component, blocks in enumerate(components)
        for block, values in enumerate(blocks)
        for position in range(1, 64)
        if values[position] != 0
    ]


def _permutation(size: int, key: str) -> list[int]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    generator = np.random.default_rng(int.from_bytes(digest, "big"))
    result = np.arange(size)
    generator.shuffle(result)
    return result.tolist()


def _coefficient(components: list[list[np.ndarray]], location: tuple[int, int, int]) -> int:
    component, block, position = location
    return int(components[component][block][position])


def _set_coefficient(
    components: list[list[np.ndarray]],
    location: tuple[int, int, int],
    value: int,
) -> None:
    component, block, position = location
    components[component][block][position] = value


def _syndrome(values: list[int]) -> int:
    result = 0
    for index, value in enumerate(values, 1):
        if abs(value) & 1:
            result ^= index
    return result


def _capacity_from_count(count: int) -> int:
    return (count // _GROUP_SIZE * _MESSAGE_BITS) // 8


def _groups(
    components: list[list[np.ndarray]],
    *,
    key: str,
) -> list[list[tuple[int, int, int]]]:
    locations = _locations(components)
    shuffled = [locations[index] for index in _permutation(len(locations), key)]
    dry = [location for location in shuffled if abs(_coefficient(components, location)) > 1]
    wet = [location for location in shuffled if abs(_coefficient(components, location)) == 1]
    group_count = min(len(shuffled) // _GROUP_SIZE, len(dry) // _MESSAGE_BITS)
    basis = dry[:group_count * _MESSAGE_BITS]
    filler = wet + dry[group_count * _MESSAGE_BITS:]
    groups = []
    basis_positions = (0, 1, 3, 7, 15)
    for group_index in range(group_count):
        group: list[tuple[int, int, int] | None] = [None] * _GROUP_SIZE
        for basis_index, position in enumerate(basis_positions):
            group[position] = basis[group_index * _MESSAGE_BITS + basis_index]
        for position in range(_GROUP_SIZE):
            if group[position] is None:
                group[position] = filler.pop()
        groups.append([location for location in group if location is not None])
    return groups


def _wet_paper_changes(values: list[int], target: int) -> list[int] | None:
    """Znajdź najmniejszy podzbiór suchych pozycji o zadanym syndromie."""
    required = _syndrome(values) ^ target
    if required == 0:
        return []

    subsets: dict[int, list[int]] = {0: []}
    for index, value in enumerate(values, 1):
        if abs(value) <= 1:
            continue
        for syndrome, selected in list(subsets.items()):
            candidate = syndrome ^ index
            if candidate not in subsets:
                subsets[candidate] = selected + [index - 1]
    return subsets.get(required)


def _flip_without_zero(value: int) -> int:
    magnitude = abs(value)
    if magnitude == 2:
        magnitude += 1
    else:
        magnitude -= 1
    return magnitude if value > 0 else -magnitude


def _embed(
    components: list[list[np.ndarray]],
    frame: bytes,
    *,
    key: str,
) -> int:
    groups = _groups(components, key=key)
    capacity = len(groups) * _MESSAGE_BITS // 8
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack(frame, capacity_bytes=capacity)

    bits = _bits(frame)
    bits.extend([0] * ((-_MESSAGE_BITS - len(bits)) % _MESSAGE_BITS))
    for offset in range(0, len(bits), _MESSAGE_BITS):
        group = groups[offset // _MESSAGE_BITS]
        target = 0
        for bit in bits[offset:offset + _MESSAGE_BITS]:
            target = (target << 1) | bit
        values = [_coefficient(components, location) for location in group]
        changes = _wet_paper_changes(values, target)
        if changes is None:
            raise FrameError(
                "nsF5 nie znalazł wystarczającej liczby suchych współczynników "
                "dla grupy wet-paper"
            )
        for index in changes:
            location = group[index]
            _set_coefficient(
                components,
                location,
                _flip_without_zero(_coefficient(components, location)),
            )
    return capacity


def _extract(components: list[list[np.ndarray]], *, key: str) -> bytes:
    groups = _groups(components, key=key)
    capacity = len(groups) * _MESSAGE_BITS // 8
    values: list[int] = []
    for group in groups:
        values.extend(
            [
                (bit >> shift) & 1
                for shift in (4, 3, 2, 1, 0)
                for bit in [
                    _syndrome([
                        _coefficient(components, location)
                        for location in group
                    ])
                ]
            ]
        )
    if len(values) < HEADER_SIZE * 8:
        raise FrameError("JPEG nie mieści nagłówka nsF5")
    header = parse_header(
        bytes(np.packbits(np.asarray(values[:HEADER_SIZE * 8], dtype=np.uint8), bitorder="big")),
        capacity_bytes=capacity,
    )
    frame_bits = values[:header.frame_size * 8]
    if len(frame_bits) < header.frame_size * 8:
        raise FrameError("JPEG nie zawiera całej ramki nsF5")
    frame = bytes(np.packbits(np.asarray(frame_bits, dtype=np.uint8), bitorder="big"))
    unpack(frame, capacity_bytes=capacity)
    return frame


def capacity_from_png(image: np.ndarray, *, key: str = DEFAULT_KEY) -> int:
    return len(_groups(_components(image)[2], key=key)) * _MESSAGE_BITS // 8


def capacity_from_jpeg(path: str, *, key: str = DEFAULT_KEY) -> int:
    coefficients = read_jpeg(path)
    components = [coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks]
    return len(_groups(components, key=key)) * _MESSAGE_BITS // 8


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
