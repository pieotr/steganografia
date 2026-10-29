"""Minimalny enkoder baseline JPEG dla gotowych współczynników DCT."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
from typing import Iterable, Sequence

import numpy as np

from .dct import (
    CHROMINANCE_QUANTIZATION,
    LUMINANCE_QUANTIZATION,
    dct_block,
    get_block,
    quantize_block,
    rgb_to_ycbcr,
    subsample_420,
    zigzag_scan,
)
from .images import ImageError, load_cover


_DC_LUMA_BITS = (0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)
_DC_LUMA_VALUES = tuple(range(12))
_AC_LUMA_BITS = (0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 125)
_AC_LUMA_VALUES = (
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41,
    0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91,
    0xA1, 0x08, 0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24,
    0x33, 0x62, 0x72, 0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A,
    0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38,
    0x39, 0x3A, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53,
    0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63, 0x64, 0x65, 0x66,
    0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79,
    0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92, 0x93,
    0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3, 0xA4, 0xA5,
    0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7,
    0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
    0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1,
    0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2,
    0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA,
)
_DC_CHROMA_BITS = (0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
_DC_CHROMA_VALUES = tuple(range(12))
_AC_CHROMA_BITS = (0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77)
_AC_CHROMA_VALUES = (
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41,
    0x51, 0x07, 0x61, 0x71, 0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91,
    0xA1, 0xB1, 0xC1, 0x09, 0x23, 0x33, 0x52, 0xF0, 0x15, 0x62, 0x72, 0xD1,
    0x0A, 0x16, 0x24, 0x34, 0xE1, 0x25, 0xF1, 0x17, 0x18, 0x19, 0x1A, 0x26,
    0x27, 0x28, 0x29, 0x2A, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44,
    0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
    0x59, 0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74,
    0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
    0x88, 0x89, 0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A,
    0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4,
    0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA,
    0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF2, 0xF3, 0xF4,
    0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA,
)


def _huffman_codes(bits: Sequence[int], values: Sequence[int]) -> dict[int, tuple[int, int]]:
    codes = {}
    code = 0
    position = 0
    for length, count in enumerate(bits, 1):
        for _ in range(count):
            codes[values[position]] = (code, length)
            code += 1
            position += 1
        code <<= 1
    return codes


def _amplitude(value: int) -> tuple[int, int]:
    if value == 0:
        return 0, 0
    size = abs(value).bit_length()
    return size, value if value > 0 else (1 << size) - 1 + value


class _BitWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.current = 0
        self.count = 0

    def write(self, value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            self.current = (self.current << 1) | ((value >> shift) & 1)
            self.count += 1
            if self.count == 8:
                self.data.append(self.current)
                if self.current == 0xFF:
                    self.data.append(0)
                self.current = 0
                self.count = 0

    def finish(self) -> bytes:
        if self.count:
            self.write((1 << (8 - self.count)) - 1, 8 - self.count)
        return bytes(self.data)


def _segment(marker: int, payload: bytes) -> bytes:
    return b"\xff" + bytes((marker,)) + struct.pack(">H", len(payload) + 2) + payload


def _quantization_segment() -> bytes:
    luma = zigzag_scan(LUMINANCE_QUANTIZATION.astype(np.int32))
    chroma = zigzag_scan(CHROMINANCE_QUANTIZATION.astype(np.int32))
    payload = bytes((0,)) + bytes(int(value) for value in luma)
    payload += bytes((1,)) + bytes(int(value) for value in chroma)
    return _segment(0xDB, payload)


def _huffman_segment() -> bytes:
    tables = (
        (0, _DC_LUMA_BITS, _DC_LUMA_VALUES),
        (0x10, _AC_LUMA_BITS, _AC_LUMA_VALUES),
        (1, _DC_CHROMA_BITS, _DC_CHROMA_VALUES),
        (0x11, _AC_CHROMA_BITS, _AC_CHROMA_VALUES),
    )
    payload = bytearray()
    for identifier, bits, values in tables:
        payload.append(identifier)
        payload.extend(bits)
        payload.extend(values)
    return _segment(0xC4, bytes(payload))


def _encode_block(
    writer: _BitWriter,
    block: Sequence[int],
    previous_dc: int,
    dc_codes: dict[int, tuple[int, int]],
    ac_codes: dict[int, tuple[int, int]],
) -> int:
    difference = int(block[0]) - previous_dc
    size, bits = _amplitude(difference)
    code, length = dc_codes[size]
    writer.write(code, length)
    if size:
        writer.write(bits, size)

    zeroes = 0
    for value in block[1:]:
        value = int(value)
        if value == 0:
            zeroes += 1
            if zeroes == 16:
                code, length = ac_codes[0xF0]
                writer.write(code, length)
                zeroes = 0
            continue
        size, bits = _amplitude(value)
        code, length = ac_codes[(zeroes << 4) | size]
        writer.write(code, length)
        writer.write(bits, size)
        zeroes = 0
    if zeroes:
        code, length = ac_codes[0]
        writer.write(code, length)
    return int(block[0])


def _validate_blocks(blocks: Iterable[Sequence[int]], name: str) -> list[Sequence[int]]:
    result = list(blocks)
    if not result:
        raise ValueError(f"{name} nie może być puste")
    for block in result:
        if len(block) != 64:
            raise ValueError(f"Każdy blok {name} musi mieć 64 współczynniki")
    return result


def write_jpeg(
    path: str | Path,
    *,
    width: int,
    height: int,
    y_blocks: Iterable[Sequence[int]],
    cb_blocks: Iterable[Sequence[int]] | None = None,
    cr_blocks: Iterable[Sequence[int]] | None = None,
) -> None:
    """Zapisz baseline JPEG z gotowych, skwantyzowanych bloków zigzag.

    Dla obrazu kolorowego wymagane są bloki w układzie 4:2:0:
    cztery bloki Y, następnie jeden Cb i jeden Cr na każdą MCU. Bloki
    przekazuje się w kolejności raster-scan komponentu.
    """
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        raise ValueError("width i height muszą być dodatnimi liczbami całkowitymi")
    y = _validate_blocks(y_blocks, "Y")
    color = (cb_blocks is not None) or (cr_blocks is not None)
    if color and (cb_blocks is None or cr_blocks is None):
        raise ValueError("Cb i Cr muszą być podane razem")
    cb = _validate_blocks(cb_blocks, "Cb") if cb_blocks is not None else []
    cr = _validate_blocks(cr_blocks, "Cr") if cr_blocks is not None else []
    y_blocks_x = (width + 7) // 8
    y_blocks_y = (height + 7) // 8
    mcu_x = (width + 15) // 16 if color else y_blocks_x
    mcu_y = (height + 15) // 16 if color else y_blocks_y
    expected_y = y_blocks_x * y_blocks_y
    expected_chroma = mcu_x * mcu_y
    if len(y) != expected_y or (color and (len(cb) != expected_chroma or len(cr) != expected_chroma)):
        raise ValueError("Liczba bloków nie pasuje do wymiarów obrazu")
    if color:
        padded_y = []
        for row in range(mcu_y * 2):
            source_row = min(row, y_blocks_y - 1)
            for column in range(mcu_x * 2):
                source_column = min(column, y_blocks_x - 1)
                padded_y.append(y[source_row * y_blocks_x + source_column])
        y = padded_y
        y_blocks_x = mcu_x * 2

    dc_luma = _huffman_codes(_DC_LUMA_BITS, _DC_LUMA_VALUES)
    ac_luma = _huffman_codes(_AC_LUMA_BITS, _AC_LUMA_VALUES)
    dc_chroma = _huffman_codes(_DC_CHROMA_BITS, _DC_CHROMA_VALUES)
    ac_chroma = _huffman_codes(_AC_CHROMA_BITS, _AC_CHROMA_VALUES)
    writer = _BitWriter()
    previous = [0, 0, 0]
    if color:
        for mcu_row in range(mcu_y):
            for mcu_column in range(mcu_x):
                for row_offset in range(2):
                    for column_offset in range(2):
                        y_index = (
                            (mcu_row * 2 + row_offset) * y_blocks_x
                            + mcu_column * 2
                            + column_offset
                        )
                        previous[0] = _encode_block(
                            writer, y[y_index], previous[0], dc_luma, ac_luma
                        )
                chroma_index = mcu_row * mcu_x + mcu_column
                previous[1] = _encode_block(
                    writer, cb[chroma_index], previous[1], dc_chroma, ac_chroma
                )
                previous[2] = _encode_block(
                    writer, cr[chroma_index], previous[2], dc_chroma, ac_chroma
                )
    else:
        for block in y:
            previous[0] = _encode_block(writer, block, previous[0], dc_luma, ac_luma)

    sof = struct.pack(">BHHB", 8, height, width, 3 if color else 1)
    sof += b"\x01\x22\x00\x02\x11\x01\x03\x11\x01" if color else b"\x01\x11\x00"
    sos = b"\x01\x00" if not color else b"\x01\x00\x02\x11\x03\x11"
    data = b"\xff\xd8" + _quantization_segment()
    data += _segment(0xC0, sof) + _huffman_segment()
    data += _segment(0xDA, bytes((len(sos) // 2,)) + sos + b"\x00\x3f\x00")
    data += writer.finish() + b"\xff\xd9"
    Path(path).write_bytes(data)


def _encode_component(
    component: np.ndarray,
    quantization: np.ndarray,
) -> list[np.ndarray]:
    block_count_y = (component.shape[0] + 7) // 8
    block_count_x = (component.shape[1] + 7) // 8
    blocks = []
    for index in range(block_count_y * block_count_x):
        dct = dct_block(get_block(component, index))
        quantized = quantize_block(dct, quantization)
        blocks.append(zigzag_scan(quantized))
    return blocks


def png_to_jpeg(
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
) -> None:
    """Przetwórz PNG przez własny pipeline DCT i zapisz baseline JPEG 4:2:0."""
    target = Path(output_path)
    if target.suffix.lower() not in {".jpg", ".jpeg"}:
        raise ImageError("Obraz wynikowy musi mieć rozszerzenie .jpg lub .jpeg")

    image = load_cover(input_path)
    ycbcr = rgb_to_ycbcr(image)
    y, cb, cr = subsample_420(ycbcr)
    y_blocks = _encode_component(y, LUMINANCE_QUANTIZATION)
    cb_blocks = _encode_component(cb, CHROMINANCE_QUANTIZATION)
    cr_blocks = _encode_component(cr, CHROMINANCE_QUANTIZATION)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            suffix=target.suffix,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        write_jpeg(
            temporary,
            width=image.shape[1],
            height=image.shape[0],
            y_blocks=y_blocks,
            cb_blocks=cb_blocks,
            cr_blocks=cr_blocks,
        )
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    except FileExistsError as exc:
        raise ImageError(
            f"Plik '{target}' już istnieje; wybierz nową nazwę "
            "lub jawnie ustaw overwrite=True"
        ) from exc
    except OSError as exc:
        raise ImageError(f"Nie można zapisać JPEG '{target}': {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


__all__ = ["png_to_jpeg", "write_jpeg"]
