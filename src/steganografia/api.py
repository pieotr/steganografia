"""Warstwa usług steganograficznych z możliwością rozszerzenia o DCT.

Każda metoda implementuje wspólny kontrakt: pojemność, osadzanie i ekstrakcję.
W praktyce ta warstwa umożliwia łatwe dodanie kolejnych metod, np. DCT,
bez zmiany endpointów HTTP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import io
import os
import tempfile
from typing import Any

import numpy as np
from PIL import Image

from .frame import FrameError, pack, unpack
from .images import ImageError, load_cover, load_stego, save_png
from .lsb import capacity_bytes, embed_frame, extract_frame, payload_capacity_bytes


class MethodNotFoundError(KeyError):
    """Wyjątek dla nieznanej metody steganograficznej."""


class SteganographyMethod(ABC):
    """Abstrakcyjny kontrakt dla każdej metody ukrywania."""

    name: str = ""

    @abstractmethod
    def capacity(self, image: np.ndarray) -> dict[str, int]:
        """Zwróć informacje o pojemności dla danego obrazu."""

    @abstractmethod
    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        """Zamknij payload do obrazu i zwróć obrazu wynikowy."""

    @abstractmethod
    def extract(self, image: np.ndarray) -> str:
        """Wydobądź payload z obrazu."""


class LSBMethod(SteganographyMethod):
    """Metoda LSB implementująca kontrakt dla endpointów HTTP."""

    name = "lsb"

    def capacity(self, image: np.ndarray) -> dict[str, int]:
        return {
            "capacity_bytes": capacity_bytes(image),
            "payload_capacity_bytes": payload_capacity_bytes(image),
        }

    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        if not isinstance(payload, str):
            raise TypeError("Payload musi być tekstem UTF-8")
        frame = pack(payload, capacity_bytes=capacity_bytes(image))
        return embed_frame(image, frame)

    def extract(self, image: np.ndarray) -> str:
        frame = extract_frame(image)
        return unpack(frame, capacity_bytes=capacity_bytes(image))


class SteganographyRegistry:
    """Rejestr metod. Struktura ta jest przygotowana pod DCT i kolejne algorytmy."""

    def __init__(self) -> None:
        self._methods: dict[str, SteganographyMethod] = {}

    def register(self, method: SteganographyMethod) -> None:
        self._methods[method.name] = method

    def get(self, name: str) -> SteganographyMethod:
        try:
            return self._methods[name]
        except KeyError as exc:
            raise MethodNotFoundError(f"Nieznana metoda steganografii: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._methods)


METHOD_REGISTRY = SteganographyRegistry()
METHOD_REGISTRY.register(LSBMethod())


def read_png_bytes(file_storage: Any) -> bytes:
    """Wczytaj bajty pliku PNG z żądania multipart."""
    if file_storage is None:
        raise ValueError("Brakuje pliku 'file'.")
    file_storage.seek(0)
    payload = file_storage.read()
    if not payload:
        raise ValueError("Przesłany plik jest pusty.")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format != "PNG":
                raise ValueError("Obsługiwany jest tylko format PNG.")
            image.verify()
    except Exception as exc:  # pragma: no cover - obsługa błędu wejścia
        raise ValueError("Nie można odczytać pliku PNG.") from exc
    return payload


def load_png_from_bytes(payload: bytes, *, mode: str = "cover") -> np.ndarray:
    """Wczytaj PNG z bajtów do tablicy NumPy. Tryb cover/extract ma znaczenie."""
    if mode not in {"cover", "stego"}:
        raise ValueError("Nieznany tryb wczytania PNG: {mode}")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as stream:
            stream.write(payload)
            temporary_path = stream.name
        return load_cover(temporary_path) if mode == "cover" else load_stego(temporary_path)
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def save_png_to_bytes(image: np.ndarray) -> bytes:
    """Zapisz NumPy image do PNG i zwróć bajty."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as stream:
            temporary_path = stream.name
        os.unlink(temporary_path)
        save_png(image, temporary_path, overwrite=True)
        with open(temporary_path, "rb") as stream:
            return stream.read()
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def image_to_base64(image: np.ndarray) -> str:
    """Konwertuj PNG do base64, przygotowanego dla frontendu."""
    png_bytes = save_png_to_bytes(image)
    return base64.b64encode(png_bytes).decode("ascii")


__all__ = [
    "LSBMethod",
    "MethodNotFoundError",
    "SteganographyMethod",
    "SteganographyRegistry",
    "METHOD_REGISTRY",
    "image_to_base64",
    "load_png_from_bytes",
    "read_png_bytes",
    "save_png_to_bytes",
]
