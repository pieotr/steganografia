"""Obsługa ramki wiadomości dla steganografii LSB."""

from .frame import (
    HEADER_SIZE,
    MAGIC,
    MAX_PAYLOAD_SIZE,
    VERSION,
    FrameError,
    FrameHeader,
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

__all__ = [
    "HEADER_SIZE",
    "MAGIC",
    "MAX_PAYLOAD_SIZE",
    "VERSION",
    "FrameError",
    "FrameHeader",
    "capacity_bytes",
    "embed_bits",
    "embed_frame",
    "extract_bits",
    "extract_frame",
    "parse_header",
    "payload_capacity_bytes",
    "unpack",
]
