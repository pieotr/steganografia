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

__all__ = [
    "HEADER_SIZE",
    "MAGIC",
    "MAX_PAYLOAD_SIZE",
    "VERSION",
    "FrameError",
    "FrameHeader",
    "parse_header",
    "unpack",
]
