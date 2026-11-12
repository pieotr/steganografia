"""Klasyczne osadzanie F5 w skwantyzowanych współczynnikach JPEG."""

from pathlib import Path
import hashlib
import random

import numpy as np

from .dct import CHROMINANCE_QUANTIZATION, LUMINANCE_QUANTIZATION, rgb_to_ycbcr, subsample_420
from .frame import HEADER_SIZE, FrameError, parse_header, unpack
from .images import ImageError, load_cover
from .jpeg import _encode_component, read_jpeg, write_jpeg

DEFAULT_KEY = "steganografia-f5"
_GROUP_SIZE = 3
_MESSAGE_BITS = 2


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


def _positions(
    components: list[list[np.ndarray]], *, nonzero_only: bool = True
) -> list[tuple[int, int, int]]:
    return [
        (component, block, position)
        for component, blocks in enumerate(components)
        for block, values in enumerate(blocks)
        for position in range(1, 64)
        if not nonzero_only or values[position] != 0
    ]


def _permutation(size: int, key: str) -> list[int]:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    generator = random.Random(int.from_bytes(digest, "big"))
    result = list(range(size))
    generator.shuffle(result)
    return result


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


def _embed(
    components: list[list[np.ndarray]],
    frame: bytes,
    *,
    key: str,
) -> int:
    available = _positions(components)
    locations = _positions(components, nonzero_only=False)
    capacity = _capacity_from_count(len(available))
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack(frame, capacity_bytes=capacity)

    shuffled = [
        locations[index]
        for index in _permutation(len(locations), key)
        if _coefficient(components, locations[index]) != 0
    ]
    bits = _bits(frame)
    bit_index = 0
    candidate_index = 0
    group: list[tuple[int, int, int]] = []
    while bit_index < len(bits):
        while len(group) < _GROUP_SIZE and candidate_index < len(shuffled):
            group.append(shuffled[candidate_index])
            candidate_index += 1
        if len(group) < _GROUP_SIZE:
            raise FrameError("Pojemność F5 zmniejszyła się przez shrinkage")

        target = (bits[bit_index] << 1) | bits[bit_index + 1]
        values = [_coefficient(components, location) for location in group]
        index = _syndrome(values) ^ target
        if index:
            location = group[index - 1]
            value = _coefficient(components, location)
            changed = abs(value) - 1
            _set_coefficient(components, location, changed if value > 0 else -changed)
            if changed == 0:
                group.pop(index - 1)
                if candidate_index >= len(shuffled):
                    raise FrameError("Pojemność F5 zmniejszyła się przez shrinkage")
                group.append(shuffled[candidate_index])
                candidate_index += 1
                continue
        group = []
        bit_index += _MESSAGE_BITS
    return capacity


def _extract(components: list[list[np.ndarray]], *, key: str) -> bytes:
    available = _positions(components)
    locations = _positions(components, nonzero_only=False)
    capacity = _capacity_from_count(len(available))
    shuffled = [
        locations[index]
        for index in _permutation(len(locations), key)
        if _coefficient(components, locations[index]) != 0
    ]
    values: list[int] = []
    for offset in range(0, len(shuffled) - _GROUP_SIZE + 1, _GROUP_SIZE):
        values.extend(
            [( _syndrome([_coefficient(components, location) for location in shuffled[offset:offset + _GROUP_SIZE]]) >> shift) & 1
             for shift in (1, 0)]
        )
    if len(values) < HEADER_SIZE * 8:
        raise FrameError("JPEG nie mieści nagłówka F5")
    header = parse_header(
        bytes(np.packbits(np.asarray(values[:HEADER_SIZE * 8], dtype=np.uint8), bitorder="big")),
        capacity_bytes=capacity,
    )
    frame_bits = values[:header.frame_size * 8]
    if len(frame_bits) < header.frame_size * 8:
        raise FrameError("JPEG nie zawiera całej ramki F5")
    frame = bytes(np.packbits(np.asarray(frame_bits, dtype=np.uint8), bitorder="big"))
    unpack(frame, capacity_bytes=capacity)
    return frame


def capacity_from_png(image: np.ndarray) -> int:
    return _capacity_from_count(len(_positions(_components(image)[2])))


def capacity_from_jpeg(path: str) -> int:
    coefficients = read_jpeg(path)
    return _capacity_from_count(
        len(_positions([coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks]))
    )


def embed_jpeg(
    input_path: str,
    output_path: str,
    frame: bytes,
    *,
    key: str = DEFAULT_KEY,
    overwrite: bool = False,
) -> None:
    if not isinstance(key, str):
        raise TypeError("Klucz F5 musi mieć typ str")
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
        raise TypeError("Klucz F5 musi mieć typ str")
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
