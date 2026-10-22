"""Pakowanie i odczyt ramki STEG v1 opisanej w docs/frame-v1.md."""

from dataclasses import dataclass
import struct
import zlib


MAGIC = b"STEG"
VERSION = 1
MAX_PAYLOAD_SIZE = (1 << 32) - 1
_HEADER = struct.Struct(">4sBII")
HEADER_SIZE = _HEADER.size


class FrameError(ValueError):
    """Niepoprawna ramka lub przekroczona pojemność obrazu."""


@dataclass(frozen=True)
class FrameHeader:
    """Zweryfikowany nagłówek; długość payloadu jest podana w bajtach."""

    length: int
    crc32: int

    @property
    def frame_size(self) -> int:
        return HEADER_SIZE + self.length


def _payload_limit(capacity_bytes: int) -> int:
    if isinstance(capacity_bytes, bool) or not isinstance(capacity_bytes, int):
        raise TypeError("capacity_bytes musi być liczbą całkowitą")
    if capacity_bytes < HEADER_SIZE:
        raise FrameError("Pojemność obrazu nie mieści nagłówka (13 bajtów)")
    return min(MAX_PAYLOAD_SIZE, capacity_bytes - HEADER_SIZE)


def pack(text: str, *, capacity_bytes: int) -> bytes:
    """Zakoduj tekst UTF-8 i utwórz ramkę mieszczącą się w pojemności obrazu.

    Nie dodaje BOM ani terminatora i nie normalizuje Unicode.
    capacity_bytes obejmuje także 13-bajtowy nagłówek.
    """
    if not isinstance(text, str):
        raise TypeError("Tekst musi mieć typ str")
    limit = _payload_limit(capacity_bytes)
    try:
        payload = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise FrameError("Tekstu nie można zakodować jako UTF-8") from exc
    if len(payload) > limit:
        raise FrameError(
            f"LENGTH ({len(payload)} B) przekracza pojemność obrazu "
            f"(maksymalnie {limit} B payloadu)"
        )
    return _HEADER.pack(MAGIC, VERSION, len(payload), zlib.crc32(payload)) + payload


def parse_header(header: bytes, *, capacity_bytes: int) -> FrameHeader:
    """Sprawdź dokładnie 13 bajtów nagłówka przed pobraniem payloadu.

    capacity_bytes to pojemność całej ramki obliczona z obrazu,
    niezależnie od LENGTH. Funkcja nie odczytuje ani nie alokuje payloadu.
    Poprawny nagłówek nie gwarantuje dostępności danych ani zgodności CRC.
    """
    if not isinstance(header, bytes):
        raise TypeError("Nagłówek musi mieć typ bytes")
    if len(header) != HEADER_SIZE:
        raise FrameError("Nagłówek musi mieć dokładnie 13 bajtów")

    magic, version, length, checksum = _HEADER.unpack(header)
    if magic != MAGIC:
        raise FrameError("Niepoprawne MAGIC")
    if version != VERSION:
        raise FrameError("Nieobsługiwana wersja ramki")

    limit = _payload_limit(capacity_bytes)
    if length > limit:
        raise FrameError(
            f"LENGTH ({length} B) przekracza pojemność obrazu "
            f"(maksymalnie {limit} B payloadu)"
        )

    return FrameHeader(length=length, crc32=checksum)


def unpack(frame: bytes, *, capacity_bytes: int) -> str:
    """Sprawdź jedną kompletną ramkę i odczytaj tekst UTF-8.

    Kontrola nagłówka, limitu LENGTH i rozmiaru ramki poprzedza dostęp
    do payloadu. Przekazany bufor bytes jest już w pamięci; czytnik obrazu
    powinien użyć parse_header przed pobraniem payloadu.
    """
    if not isinstance(frame, bytes):
        raise TypeError("Ramka musi mieć typ bytes")
    if len(frame) < HEADER_SIZE:
        raise FrameError("Ucięty nagłówek: wymagane 13 bajtów")

    # Kopiujemy najwyżej stałe 13 bajtów, nigdy rozmiar wskazany przez LENGTH.
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=capacity_bytes)
    if len(frame) < header.frame_size:
        raise FrameError("Ucięty payload: LENGTH przekracza dostępne dane")
    if len(frame) > header.frame_size:
        raise FrameError("Nadmiarowe bajty po ramce")

    # Dopiero po walidacji długości tworzymy widok payloadu, bez kopiowania.
    payload = memoryview(frame)[HEADER_SIZE:]
    if zlib.crc32(payload) != header.crc32:
        raise FrameError("Niezgodna suma CRC32")
    try:
        return str(payload, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FrameError("Payload nie jest poprawnym UTF-8") from exc
