"""Obsługa ramki wiadomości dla steganografii LSB."""

from .frame import (
    HEADER_SIZE,
    MAGIC,
    MAX_PAYLOAD_SIZE,
    VERSION,
    FrameError,
    FrameHeader,
    pack,
    parse_header,
    unpack,
)
from .lsb import (
    capacity_bytes,
    embed_bits,
    embed_frame,
    extract_bits,
    extract_frame,
    payload_capacity_bytes,
)
from .images import ImageError, load_cover, load_stego, save_png

__all__ = [
    "HEADER_SIZE",
    "MAGIC",
    "MAX_PAYLOAD_SIZE",
    "VERSION",
    "FrameError",
    "FrameHeader",
    "ImageError",
    "capacity_bytes",
    "embed_bits",
    "embed_frame",
    "extract_bits",
    "extract_frame",
    "load_cover",
    "load_stego",
    "pack",
    "parse_header",
    "payload_capacity_bytes",
    "save_png",
    "unpack",
]
