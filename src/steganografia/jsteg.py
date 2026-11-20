"""Minimalne osadzanie JSteg w skwantyzowanych współczynnikach Y, Cb i Cr."""

from pathlib import Path

import numpy as np

from .dct import (
    CHROMINANCE_QUANTIZATION,
    LUMINANCE_QUANTIZATION,
    rgb_to_ycbcr,
    subsample_420,
)
from .frame import HEADER_SIZE, FrameError, parse_header, unpack
from .images import ImageError, load_cover
from .jpeg import _encode_component, read_jpeg, write_jpeg

def _jpeg_blocks(image: np.ndarray) -> tuple[int, int, list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    y, cb, cr = subsample_420(rgb_to_ycbcr(image))
    return (
        image.shape[1],
        image.shape[0],
        _encode_component(y, LUMINANCE_QUANTIZATION),
        _encode_component(cb, CHROMINANCE_QUANTIZATION),
        _encode_component(cr, CHROMINANCE_QUANTIZATION),
    )


def _jpeg_positions(
    blocks: list[np.ndarray],
    *,
    first_position: int,
    last_position: int,
    skip_unit_coefficients: bool,
) -> list[tuple[int, int]]:
    return [
        (index, position)
        for index, block in enumerate(blocks)
        for position in range(first_position, last_position + 1)
        if block[position] != 0
        and (not skip_unit_coefficients or abs(int(block[position])) > 1)
    ]


def _embed_coefficients(
    blocks: list[np.ndarray],
    frame: bytes,
    *,
    first_position: int,
    last_position: int,
    skip_unit_coefficients: bool,
) -> int:
    positions = _jpeg_positions(
        blocks,
        first_position=first_position,
        last_position=last_position,
        skip_unit_coefficients=skip_unit_coefficients,
    )
    capacity = len(positions) // 8
    if not isinstance(frame, bytes):
        raise TypeError("Ramka musi mieć typ bytes")
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity)
    if len(frame) != header.frame_size:
        raise FrameError(f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}")
    unpack(frame, capacity_bytes=capacity)
    bits = _bits(frame)
    for bit, (block_index, position) in zip(bits, positions):
        coefficient = int(blocks[block_index][position])
        if abs(coefficient) % 2 != int(bit):
            if abs(coefficient) == 1:
                blocks[block_index][position] = 2 if coefficient > 0 else -2
            else:
                blocks[block_index][position] = coefficient + (1 if coefficient > 0 else -1)
    return capacity


def _extract_coefficients(
    blocks: list[np.ndarray],
    *,
    first_position: int,
    last_position: int,
    skip_unit_coefficients: bool,
) -> bytes:
    positions = _jpeg_positions(
        blocks,
        first_position=first_position,
        last_position=last_position,
        skip_unit_coefficients=skip_unit_coefficients,
    )
    capacity = len(positions) // 8
    values = [abs(int(blocks[i][p])) & 1 for i, p in positions]
    if len(values) < HEADER_SIZE * 8:
        raise FrameError("JPEG nie mieści nagłówka")
    decoded = np.asarray(values, dtype=np.uint8)
    header = parse_header(
        np.packbits(decoded[:HEADER_SIZE * 8], bitorder="big").tobytes(),
        capacity_bytes=capacity,
    )
    frame_bits = decoded[:header.frame_size * 8]
    frame = np.packbits(frame_bits, bitorder="big").tobytes()
    unpack(frame, capacity_bytes=capacity)
    return frame


def _all_blocks(
    y_blocks: list[np.ndarray],
    cb_blocks: list[np.ndarray],
    cr_blocks: list[np.ndarray],
) -> list[np.ndarray]:
    """Połącz bloki luminancji i chrominancji; tablice pozostają współdzielone."""
    return [*y_blocks, *cb_blocks, *cr_blocks]


def _position_range(mf: bool) -> dict[str, int | bool]:
    if mf:
        return {"first_position": 5, "last_position": 40, "skip_unit_coefficients": True}
    return {"first_position": 1, "last_position": 63, "skip_unit_coefficients": False}


def jpeg_capacity_bytes(path: str, *, mf: bool = False) -> int:
    coefficients = read_jpeg(path)
    blocks = _all_blocks(coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks)
    return len(_jpeg_positions(blocks, **_position_range(mf))) // 8


def png_jpeg_capacity_bytes(image: np.ndarray, *, mf: bool = False) -> int:
    _, _, y_blocks, cb_blocks, cr_blocks = _jpeg_blocks(image)
    blocks = _all_blocks(y_blocks, cb_blocks, cr_blocks)
    return len(_jpeg_positions(blocks, **_position_range(mf))) // 8


def embed_jpeg(
    input_path: str,
    output_path: str,
    frame: bytes,
    *,
    mf: bool = False,
    overwrite: bool = False,
) -> None:
    image = load_cover(input_path)
    width, height, y_blocks, cb_blocks, cr_blocks = _jpeg_blocks(image)
    _embed_coefficients(
        _all_blocks(y_blocks, cb_blocks, cr_blocks), frame, **_position_range(mf)
    )
    target = Path(output_path)
    if target.exists() and not overwrite:
        raise ImageError(f"Plik '{target}' już istnieje; wybierz inną nazwę lub --overwrite")
    write_jpeg(target, width=width, height=height, y_blocks=y_blocks, cb_blocks=cb_blocks, cr_blocks=cr_blocks)


def extract_jpeg(path: str, *, mf: bool = False) -> bytes:
    coefficients = read_jpeg(path)
    return _extract_coefficients(
        _all_blocks(coefficients.y_blocks, coefficients.cb_blocks, coefficients.cr_blocks),
        **_position_range(mf),
    )


def _bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")


__all__ = [
    "embed_jpeg",
    "extract_jpeg",
    "jpeg_capacity_bytes",
    "png_jpeg_capacity_bytes",
]
