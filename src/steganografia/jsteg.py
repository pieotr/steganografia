"""Minimalne osadzanie JSteg w skwantyzowanych współczynnikach luminancji."""

from collections.abc import Iterable

import numpy as np

from .dct import (
    LUMINANCE_QUANTIZATION,
    dct_block,
    get_block,
    idct_block,
    quantize_block,
    rgb_to_ycbcr,
    zigzag_scan,
)
from .frame import HEADER_SIZE, FrameError, parse_header, unpack

_MF_BIT_REPETITIONS = 3


def _validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray):
        raise TypeError("Obraz musi być tablicą NumPy")
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Obraz musi być tablicą uint8 o układzie (wysokość, szerokość, 3)")
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError("Obraz nie może być pusty")


def _blocks(image: np.ndarray) -> list[tuple[int, np.ndarray]]:
    y = rgb_to_ycbcr(image)[..., 0]
    count_y = (y.shape[0] + 7) // 8
    count_x = (y.shape[1] + 7) // 8
    result = []
    for index in range(count_y * count_x):
        quantized = quantize_block(
            dct_block(get_block(y, index)), LUMINANCE_QUANTIZATION
        )
        result.append((index, zigzag_scan(quantized)))
    return result


def _usable(
    blocks: Iterable[tuple[int, np.ndarray]],
    *,
    first_position: int = 1,
    last_position: int = 63,
    skip_unit_coefficients: bool = False,
) -> list[tuple[int, int]]:
    return [
        (block_index, position)
        for block_index, block in blocks
        for position in range(first_position, last_position + 1)
        if block[position] != 0
        and (not skip_unit_coefficients or abs(int(block[position])) > 1)
    ]


def capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność ramki w bajtach JSteg, bez nagłówka."""
    _validate_image(image)
    return len(_usable(_blocks(image))) // 8


def payload_capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność tekstu po odjęciu nagłówka STEG."""
    total = capacity_bytes(image)
    if total < HEADER_SIZE:
        raise FrameError("Obraz nie mieści nagłówka (13 bajtów) JSteg")
    return total - HEADER_SIZE


def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


def _majority_bits(values: list[int]) -> np.ndarray:
    groups = np.asarray(values, dtype=np.uint8).reshape(-1, _MF_BIT_REPETITIONS)
    return (groups.sum(axis=1) >= 2).astype(np.uint8)


def _rebuild(image: np.ndarray, blocks: list[tuple[int, np.ndarray]]) -> np.ndarray:
    ycbcr = rgb_to_ycbcr(image)
    y = ycbcr[..., 0].copy()
    width = y.shape[1]
    for index, zigzag in blocks:
        row, column = divmod(index, (width + 7) // 8)
        restored = idct_block(
            _unzigzag(zigzag) * LUMINANCE_QUANTIZATION
        )
        start_y, start_x = row * 8, column * 8
        y[start_y:min(start_y + 8, y.shape[0]), start_x:min(start_x + 8, width)] = (
            restored[:min(8, y.shape[0] - start_y), :min(8, width - start_x)]
        )
    ycbcr[..., 0] = y
    red = y + 1.402 * (ycbcr[..., 2] - 128)
    green = y - 0.344136 * (ycbcr[..., 1] - 128) - 0.714136 * (ycbcr[..., 2] - 128)
    blue = y + 1.772 * (ycbcr[..., 1] - 128)
    return np.clip(np.rint(np.stack((red, green, blue), axis=-1)), 0, 255).astype(np.uint8)


def _unzigzag(values: np.ndarray) -> np.ndarray:
    result = np.empty((8, 8), dtype=values.dtype)
    position = 0
    for diagonal in range(15):
        rows = (
            range(min(diagonal, 7), max(0, diagonal - 7) - 1, -1)
            if diagonal % 2 == 0
            else range(max(0, diagonal - 7), min(diagonal, 7) + 1)
        )
        for row in rows:
            result[row, diagonal - row] = values[position]
            position += 1
    return result


def embed_frame(image: np.ndarray, frame: bytes) -> np.ndarray:
    """Osadź ramkę przez parzystość niezerowych współczynników AC luminancji."""
    _validate_image(image)
    blocks = _blocks(image)
    positions = _usable(blocks)
    if not isinstance(frame, bytes):
        raise TypeError("Ramka musi mieć typ bytes")
    total = len(positions) // 8
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=total)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack(frame, capacity_bytes=total)
    bit_values = _bits(frame)
    for bit, (block_index, position) in zip(bit_values, positions):
        coefficient = blocks[block_index][1][position]
        if abs(int(coefficient)) % 2 != int(bit):
            if abs(int(coefficient)) == 1:
                blocks[block_index][1][position] = 2 if coefficient > 0 else -2
            else:
                blocks[block_index][1][position] += 1 if coefficient > 0 else -1
    return _rebuild(image, blocks)


def extract_frame(image: np.ndarray) -> bytes:
    """Odczytaj ramkę z parzystości niezerowych współczynników AC."""
    _validate_image(image)
    blocks = _blocks(image)
    positions = _usable(blocks)
    if len(positions) < HEADER_SIZE * 8:
        raise FrameError("Obraz nie mieści nagłówka JSteg")
    values = [abs(int(blocks[i][1][p])) & 1 for i, p in positions]
    header = parse_header(
        np.packbits(np.asarray(values[:HEADER_SIZE * 8]), bitorder="big").tobytes(),
        capacity_bytes=len(positions) // 8,
    )
    frame_bits = values[:header.frame_size * 8]
    if len(frame_bits) < header.frame_size * 8:
        raise FrameError("Obraz nie zawiera całej ramki JSteg")
    frame = np.packbits(np.asarray(frame_bits), bitorder="big").tobytes()
    unpack(frame, capacity_bytes=len(positions) // 8)
    return frame


def mf_capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność wariantu JSteg-MF (pozycje zig-zag 5..40)."""
    _validate_image(image)
    return len(
        _usable(
            _blocks(image),
            first_position=5,
            last_position=40,
            skip_unit_coefficients=True,
        )
    ) // (8 * _MF_BIT_REPETITIONS)


def mf_payload_capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność payloadu wariantu JSteg-MF."""
    total = mf_capacity_bytes(image)
    if total < HEADER_SIZE:
        raise FrameError("Obraz nie mieści nagłówka (13 bajtów) JSteg-MF")
    return total - HEADER_SIZE


def mf_embed_frame(image: np.ndarray, frame: bytes) -> np.ndarray:
    """Osadź ramkę JSteg-MF w niezerowych współczynnikach AC 5..40."""
    _validate_image(image)
    if not isinstance(frame, bytes):
        raise TypeError("Ramka musi mieć typ bytes")
    total = mf_capacity_bytes(image)
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=total)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack(frame, capacity_bytes=total)
    bits = np.repeat(_bits(frame), _MF_BIT_REPETITIONS)
    result = image
    for _ in range(12):
        blocks = _blocks(result)
        positions = _usable(
            blocks,
            first_position=5,
            last_position=40,
            skip_unit_coefficients=True,
        )
        for bit, (block_index, position) in zip(bits, positions):
            coefficient = blocks[block_index][1][position]
            if abs(int(coefficient)) % 2 != int(bit):
                blocks[block_index][1][position] += 1 if coefficient > 0 else -1
        result = _rebuild(result, blocks)
        checked = _blocks(result)
        checked_positions = _usable(
            checked,
            first_position=5,
            last_position=40,
            skip_unit_coefficients=True,
        )
        checked_values = [
            abs(int(checked[block_index][1][position])) & 1
            for block_index, position in checked_positions
        ]
        if np.array_equal(
            _majority_bits(checked_values[: len(bits)]),
            _bits(frame),
        ):
            return result
    raise FrameError("Nie udało się ustabilizować współczynników JSteg-MF")


def mf_extract_frame(image: np.ndarray) -> bytes:
    """Odczytaj ramkę JSteg-MF z pozycji zig-zag 5..40."""
    _validate_image(image)
    blocks = _blocks(image)
    positions = _usable(
        blocks,
        first_position=5,
        last_position=40,
        skip_unit_coefficients=True,
    )
    if len(positions) < HEADER_SIZE * 8:
        raise FrameError("Obraz nie mieści nagłówka JSteg-MF")
    values = [abs(int(blocks[i][1][p])) & 1 for i, p in positions]
    capacity = len(positions) // 8
    header_bits = _majority_bits(values[: HEADER_SIZE * 8 * _MF_BIT_REPETITIONS])
    header = parse_header(
        np.packbits(header_bits, bitorder="big").tobytes(),
        capacity_bytes=capacity // _MF_BIT_REPETITIONS,
    )
    encoded_frame_bits = values[: header.frame_size * 8 * _MF_BIT_REPETITIONS]
    if len(encoded_frame_bits) < header.frame_size * 8 * _MF_BIT_REPETITIONS:
        raise FrameError("Obraz nie zawiera całej ramki JSteg-MF")
    frame = np.packbits(_majority_bits(encoded_frame_bits), bitorder="big").tobytes()
    unpack(frame, capacity_bytes=capacity // _MF_BIT_REPETITIONS)
    return frame


__all__ = [
    "capacity_bytes",
    "embed_frame",
    "extract_frame",
    "mf_capacity_bytes",
    "mf_embed_frame",
    "mf_extract_frame",
    "mf_payload_capacity_bytes",
    "payload_capacity_bytes",
]
