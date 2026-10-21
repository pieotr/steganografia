"""Osadzanie ramek STEG w najmłodszych bitach próbek RGB obrazu."""

from collections.abc import Sequence

import numpy as np

from .frame import HEADER_SIZE, FrameError, parse_header, unpack


def _validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray):
        raise TypeError("Obraz musi być tablicą NumPy")
    if image.dtype != np.uint8:
        raise TypeError("Próbki obrazu muszą mieć typ uint8")
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("Obraz musi mieć układ (wysokość, szerokość, 3 lub 4 kanały)")
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError("Obraz nie może być pusty")


def _rgb_samples(image: np.ndarray) -> np.ndarray:
    _validate_image(image)
    return image[:, :, :3].reshape(-1, order="C")


def capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność całej ramki w bajtach, bez niepełnej końcówki."""
    _validate_image(image)
    return image.shape[0] * image.shape[1] * 3 // 8


def payload_capacity_bytes(image: np.ndarray) -> int:
    """Zwróć pojemność payloadu po odjęciu nagłówka ramki STEG v1."""
    total_capacity = capacity_bytes(image)
    if total_capacity < HEADER_SIZE:
        raise FrameError(
            f"Obraz mieści {total_capacity} bajtów; nagłówek wymaga "
            f"{HEADER_SIZE} bajtów"
        )
    return total_capacity - HEADER_SIZE


def _write_bytes(image: np.ndarray, data: bytes) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8), bitorder="big")
    return embed_bits(image, bits)


def embed_bits(image: np.ndarray, bits: Sequence[int] | np.ndarray) -> np.ndarray:
    """Osadź podaną sekwencję zer i jedynek w wybranych próbkach RGB."""
    samples = _rgb_samples(image)
    bit_values = np.asarray(bits)
    if bit_values.ndim != 1:
        raise ValueError("Sekwencja bitów musi być jednowymiarowa")
    if not np.all((bit_values == 0) | (bit_values == 1)):
        raise ValueError("Sekwencja może zawierać wyłącznie bity 0 i 1")
    bit_values = bit_values.astype(np.uint8, copy=False)
    if bit_values.size > samples.size:
        raise FrameError(
            f"Sekwencja ma {bit_values.size} bitów; obraz mieści "
            f"maksymalnie {samples.size} bitów"
        )

    changed_samples = image[:, :, :3].copy().reshape(-1, order="C")
    changed_samples[: bit_values.size] = (
        (changed_samples[: bit_values.size] & np.uint8(0xFE)) | bit_values
    )
    result = image.copy()
    result[:, :, :3] = changed_samples.reshape(image.shape[0], image.shape[1], 3)
    return result


def extract_bits(image: np.ndarray, bit_count: int) -> np.ndarray:
    """Odczytaj z góry zadaną liczbę bitów w kolejności osadzania."""
    samples = _rgb_samples(image)
    if isinstance(bit_count, bool) or not isinstance(bit_count, int):
        raise TypeError("bit_count musi być liczbą całkowitą")
    if bit_count < 0:
        raise ValueError("bit_count nie może być ujemne")
    if bit_count > samples.size:
        raise FrameError(
            f"Żądano {bit_count} bitów; obraz zawiera maksymalnie "
            f"{samples.size} próbek RGB"
        )
    return (samples[:bit_count] & np.uint8(1)).copy()


def embed_frame(image: np.ndarray, frame: bytes) -> np.ndarray:
    """Osadź kompletną, poprawną ramkę STEG v1 i zwróć kopię obrazu."""
    samples = _rgb_samples(image)
    if not isinstance(frame, bytes):
        raise TypeError("Ramka musi mieć typ bytes")

    total_capacity = samples.size // 8
    if len(frame) < HEADER_SIZE:
        raise FrameError(f"Ramka musi zawierać co najmniej {HEADER_SIZE} bajtów")
    header = parse_header(frame[:HEADER_SIZE], capacity_bytes=total_capacity)
    if len(frame) != header.frame_size:
        raise FrameError(
            f"Ramka ma {len(frame)} bajtów; oczekiwano {header.frame_size}"
        )
    unpack(frame, capacity_bytes=total_capacity)
    return _write_bytes(image, frame)


def extract_frame(image: np.ndarray) -> bytes:
    """Odczytaj ramkę STEG v1 z obrazu i zweryfikuj jej zawartość."""
    samples = _rgb_samples(image)
    total_capacity = samples.size // 8
    header_bit_count = HEADER_SIZE * 8
    if samples.size < header_bit_count:
        raise FrameError(
            f"Obraz mieści {samples.size} próbek; nagłówek wymaga "
            f"{header_bit_count}"
        )

    header_bits = samples[:header_bit_count] & np.uint8(1)
    header_bytes = np.packbits(header_bits, bitorder="big").tobytes()
    header = parse_header(header_bytes, capacity_bytes=total_capacity)

    frame_bit_count = header.frame_size * 8
    frame_bits = samples[:frame_bit_count] & np.uint8(1)
    frame = np.packbits(frame_bits, bitorder="big").tobytes()
    unpack(frame, capacity_bytes=total_capacity)
    return frame


__all__ = [
    "capacity_bytes",
    "embed_bits",
    "embed_frame",
    "extract_bits",
    "extract_frame",
    "payload_capacity_bytes",
]
