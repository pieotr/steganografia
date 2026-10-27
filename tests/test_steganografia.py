import pytest
import numpy as np
from PIL import Image
import zlib
import struct

from steganografia import (
    load_cover,
    load_stego,
    save_png,
    embed_frame,
    extract_frame,
    payload_capacity_bytes,
    capacity_bytes,
    ImageError,
    FrameError,
)
from steganografia.frame import HEADER_SIZE, MAGIC, VERSION, parse_header, unpack


def create_test_frame(text_payload: str) -> bytes:
    payload = text_payload.encode("utf-8")
    length = len(payload)
    checksum = zlib.crc32(payload)
    header = struct.pack(">4sBII", MAGIC, VERSION, length, checksum)
    return header + payload


def test_full_steganography_roundtrip(tmp_path):
    img_path = tmp_path / "cover.png"
    out_path = tmp_path / "stego.png"

    img = Image.new("RGB", (50, 50), color=(255, 0, 0))
    img.save(img_path)

    cover = load_cover(img_path)
    assert isinstance(cover, np.ndarray)
    assert cover.dtype == np.uint8

    test_msg = "Tajny komunikat z kryptografii!"
    frame = create_test_frame(test_msg)

    assert payload_capacity_bytes(cover) >= len(frame)

    encoded_image = embed_frame(cover, frame)
    assert isinstance(encoded_image, np.ndarray)

    save_png(encoded_image, out_path, overwrite=False)
    assert out_path.exists()

    stego_cover = load_stego(out_path)
    recovered_frame = extract_frame(stego_cover)

    recovered_text = unpack(recovered_frame, capacity_bytes=capacity_bytes(stego_cover))
    assert recovered_text == test_msg


def test_save_png_overwrite_protection(tmp_path):
    out_path = tmp_path / "test.png"
    img = np.zeros((10, 10, 3), dtype=np.uint8)

    save_png(img, out_path, overwrite=False)
    assert out_path.exists()

    with pytest.raises(ImageError, match="już istnieje"):
        save_png(img, out_path, overwrite=False)

    save_png(img, out_path, overwrite=True)


def test_invalid_format_rejection(tmp_path):
    jpg_path = tmp_path / "test.jpg"
    img = Image.new("RGB", (20, 20), color="blue")
    img.save(jpg_path, "JPEG")

    with pytest.raises(ImageError, match="Nieobsługiwany format obrazu"):
        load_cover(jpg_path)


def test_parse_header_and_crc_errors():
    frame = create_test_frame("Test CRC")

    corrupted_frame = bytearray(frame)
    corrupted_frame[-1] ^= 0xFF

    capacity = len(corrupted_frame) * 8
    with pytest.raises(FrameError, match="Niezgodna suma CRC32"):
        unpack(bytes(corrupted_frame), capacity_bytes=capacity)