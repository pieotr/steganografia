"""Statystyczne osadzanie OutGuess w skwantyzowanych współczynnikach JPEG."""

from pathlib import Path
import hashlib

import numpy as np

from .dct import CHROMINANCE_QUANTIZATION, LUMINANCE_QUANTIZATION, rgb_to_ycbcr, subsample_420
from .frame import FrameError, HEADER_SIZE, parse_header, unpack_bytes
from .images import ImageError, load_cover
from .jpeg import _encode_component, read_jpeg, write_jpeg

DEFAULT_KEY = "steganografia-outguess"
_MIN_ABS_COEFFICIENT = 2
_SELECTION_INTERVAL = 4


class _RC4:
    def __init__(self, key: bytes) -> None:
        if not key:
            raise ValueError("Klucz OutGuess nie może być pusty")
        self._state = list(range(256))
        j = 0
        for index in range(256):
            j = (j + self._state[index] + key[index % len(key)]) & 0xFF
            self._state[index], self._state[j] = self._state[j], self._state[index]
        self._i = 0
        self._j = 0

    def read(self, count: int) -> bytes:
        output = bytearray()
        for _ in range(count):
            self._i = (self._i + 1) & 0xFF
            self._j = (self._j + self._state[self._i]) & 0xFF
            self._state[self._i], self._state[self._j] = (
                self._state[self._j],
                self._state[self._i],
            )
            output.append(self._state[
                (self._state[self._i] + self._state[self._j]) & 0xFF
            ])
        return bytes(output)


def _key_bytes(key: str, purpose: bytes) -> bytes:
    return hashlib.sha256(purpose + b"\0" + key.encode("utf-8")).digest()


def _bits(data: bytes) -> list[int]:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big").tolist()


def _bytes(bits: list[int]) -> bytes:
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder="big").tobytes()


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
        if abs(int(values[position])) >= _MIN_ABS_COEFFICIENT
    ]


def _value(components: list[list[np.ndarray]], location: tuple[int, int, int]) -> int:
    component, block, position = location
    return int(components[component][block][position])


def _set_value(
    components: list[list[np.ndarray]],
    location: tuple[int, int, int],
    value: int,
) -> None:
    component, block, position = location
    components[component][block][position] = value


def _selection_order(count: int, key: str) -> list[int]:
    """Zwróć pseudolosową kolejność z rozrzuceniem podobnym do OutGuess."""
    generator = _RC4(_key_bytes(key, b"selection"))
    position = -1
    result = []
    while True:
        position += 1 + (generator.read(1)[0] % _SELECTION_INTERVAL)
        if position >= count:
            return result
        result.append(position)


def _histogram(
    components: list[list[np.ndarray]],
    locations: list[tuple[int, int, int]],
) -> dict[int, int]:
    result: dict[int, int] = {}
    for location in locations:
        value = _value(components, location)
        result[value] = result.get(value, 0) + 1
    return result


def _candidate_values(value: int, bit: int) -> list[int]:
    sign = 1 if value > 0 else -1
    magnitude = abs(value)
    return [
        sign * candidate
        for candidate in (magnitude - 1, magnitude + 1)
        if candidate >= _MIN_ABS_COEFFICIENT and candidate % 2 == bit
    ]


def _embed(
    components: list[list[np.ndarray]],
    frame: bytes,
    *,
    key: str,
) -> int:
    locations = _locations(components)
    selection = _selection_order(len(locations), key)
    capacity = len(selection) // 8
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack_bytes(frame, capacity_bytes=capacity)

    selected_indices = set(selection[: len(frame) * 8])
    payload_locations = [locations[index] for index in selection[: len(frame) * 8]]
    reserve = [
        location for index, location in enumerate(locations)
        if index not in selected_indices
    ]
    original_histogram = _histogram(components, locations)
    encrypted = bytes(
        left ^ right
        for left, right in zip(frame, _RC4(_key_bytes(key, b"payload")).read(len(frame)))
    )
    reserve_by_value: dict[int, list[tuple[int, int, int]]] = {}
    for location in reserve:
        reserve_by_value.setdefault(_value(components, location), []).append(location)

    for bit, location in zip(_bits(encrypted), payload_locations):
        old_value = _value(components, location)
        if abs(old_value) % 2 == bit:
            continue
        candidates = _candidate_values(old_value, bit)
        candidate = next(
            (value for value in candidates if reserve_by_value.get(value)),
            None,
        )
        if candidate is None:
            raise FrameError("OutGuess nie może skorygować histogramu dla tej wiadomości")
        correction_location = reserve_by_value[candidate].pop()
        _set_value(components, location, candidate)
        _set_value(components, correction_location, old_value)
        reserve_by_value.setdefault(old_value, []).append(correction_location)

    if _histogram(components, locations) != original_histogram:
        raise FrameError("OutGuess nie zachował histogramu współczynników JPEG")
    return capacity


def _extract(components: list[list[np.ndarray]], *, key: str) -> bytes:
    locations = _locations(components)
    selection = _selection_order(len(locations), key)
    capacity = len(selection) // 8
    if capacity < HEADER_SIZE:
        raise FrameError("JPEG nie mieści nagłówka OutGuess")
    encrypted_header = _bytes([
        abs(_value(components, locations[index])) & 1
        for index in selection[: HEADER_SIZE * 8]
    ])
    header_mask = _RC4(_key_bytes(key, b"payload")).read(HEADER_SIZE)
    header = bytes(left ^ right for left, right in zip(encrypted_header, header_mask))
    parsed = parse_header(header, capacity_bytes=capacity)
    encrypted_frame = _bytes([
        abs(_value(components, locations[index])) & 1
        for index in selection[: parsed.frame_size * 8]
    ])
    stream = _RC4(_key_bytes(key, b"payload")).read(parsed.frame_size)
    frame = bytes(left ^ right for left, right in zip(encrypted_frame, stream))
    unpack_bytes(frame, capacity_bytes=capacity)
    return frame


def capacity_from_png(image: np.ndarray, *, key: str = DEFAULT_KEY) -> int:
    locations = _locations(_components(image)[2])
    return len(_selection_order(len(locations), key)) // 8


def capacity_from_jpeg(path: str, *, key: str = DEFAULT_KEY) -> int:
    coefficients = read_jpeg(path)
    locations = _locations([coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks])
    return len(_selection_order(len(locations), key)) // 8


def embed_jpeg(
    input_path: str,
    output_path: str,
    frame: bytes,
    *,
    key: str = DEFAULT_KEY,
    overwrite: bool = False,
) -> None:
    if not isinstance(key, str):
        raise TypeError("Klucz OutGuess musi mieć typ str")
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
        raise TypeError("Klucz OutGuess musi mieć typ str")
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
