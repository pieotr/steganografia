"""Warstwa usług steganograficznych z możliwością rozszerzenia o DCT.

Każda metoda implementuje wspólny kontrakt: pojemność, osadzanie i ekstrakcję.
W praktyce ta warstwa umożliwia łatwe dodanie kolejnych metod, np. DCT,
bez zmiany endpointów HTTP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .frame import FrameError, pack, pack_bytes, unpack, unpack_bytes
from .images import ImageError, load_cover, load_stego, save_png
from .lsb import capacity_bytes, embed_frame, extract_frame, payload_capacity_bytes
from .jsteg import (
    embed_jpeg as jsteg_embed_jpeg,
    extract_jpeg as jsteg_extract_jpeg,
    jpeg_capacity_bytes as jsteg_jpeg_capacity_bytes,
    png_jpeg_capacity_bytes as jsteg_png_jpeg_capacity_bytes,
)
from .f5 import (
    DEFAULT_KEY as F5_DEFAULT_KEY,
    capacity_from_jpeg as f5_capacity_from_jpeg,
    capacity_from_png as f5_capacity_from_png,
    embed_jpeg as f5_embed_jpeg,
    extract_jpeg as f5_extract_jpeg,
)
from .outguess import (
    DEFAULT_KEY as OUTGUESS_DEFAULT_KEY,
    capacity_from_jpeg as outguess_capacity_from_jpeg,
    capacity_from_png as outguess_capacity_from_png,
    embed_jpeg as outguess_embed_jpeg,
    extract_jpeg as outguess_extract_jpeg,
)
from .nsf5 import (
    DEFAULT_KEY as NSF5_DEFAULT_KEY,
    capacity_from_jpeg as nsf5_capacity_from_jpeg,
    capacity_from_png as nsf5_capacity_from_png,
    embed_jpeg as nsf5_embed_jpeg,
    extract_jpeg as nsf5_extract_jpeg,
)


@dataclass(frozen=True)
class MethodMetadata:
    """Opis metody używany przez CLI, API i frontend."""

    name: str
    label: str
    input_formats: tuple[str, ...]
    output_format: str
    options: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class EncodedArtifact:
    """Wynik osadzania niezależny od konkretnego formatu obrazu."""

    data: bytes
    media_type: str
    extension: str


class MethodNotFoundError(KeyError):
    """Wyjątek dla nieznanej metody steganograficznej."""


class SteganographyMethod(ABC):
    """Wspólny kontrakt usługi steganograficznej."""

    name: str = ""
    metadata: MethodMetadata

    @abstractmethod
    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        """Zwróć pojemność dla bajtów obrazu źródłowego."""

    @abstractmethod
    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        """Osadź tekst lub bajty i zwróć wynikowy plik."""

    @abstractmethod
    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        """Odczytaj tekst z wynikowego pliku."""

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        """Odczytaj bajty payloadu, zachowując zgodność metod tekstowych."""
        return self.extract_bytes(encoded, **options).encode("utf-8")

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
    metadata = MethodMetadata(
        name="lsb", label="LSB", input_formats=("png",), output_format="png", options={}
    )

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

    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        image = load_png_from_bytes(cover, mode="cover")
        return self.capacity(image)

    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        image = load_png_from_bytes(cover, mode="cover")
        frame = _pack_payload(payload, capacity_bytes=capacity_bytes(image))
        encoded = embed_frame(image, frame)
        return EncodedArtifact(save_png_to_bytes(encoded), "image/png", ".png")

    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        return self.extract(load_png_from_bytes(encoded, mode="stego"))

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        image = load_png_from_bytes(encoded, mode="stego")
        frame = extract_frame(image)
        return unpack_bytes(frame, capacity_bytes=capacity_bytes(image))


class _JpegMethod(SteganographyMethod):
    """Adapter istniejącego pipeline'u JPEG do wspólnego kontraktu."""

    mf = False

    def capacity(self, image: np.ndarray) -> dict[str, int]:
        total = jsteg_png_jpeg_capacity_bytes(image, mf=self.mf)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        raise NotImplementedError("Metoda JPEG używa kontraktu bajtowego")

    def extract(self, image: np.ndarray) -> str:
        raise NotImplementedError("Metoda JPEG używa kontraktu bajtowego")

    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        return self.capacity(load_png_from_bytes(cover, mode="cover"))

    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        image = load_png_from_bytes(cover, mode="cover")
        total = jsteg_png_jpeg_capacity_bytes(image, mf=self.mf)
        frame = _pack_payload(payload, capacity_bytes=total)
        with _temporary_file(cover, ".png") as source, _temporary_output(".jpg") as target:
            jsteg_embed_jpeg(source, target, frame, mf=self.mf, overwrite=True)
            data = Path(target).read_bytes()
        return EncodedArtifact(data, "image/jpeg", ".jpg")

    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        with _temporary_file(encoded, ".jpg") as source:
            frame = jsteg_extract_jpeg(source, mf=self.mf)
            total = jsteg_jpeg_capacity_bytes(source, mf=self.mf)
        return unpack(frame, capacity_bytes=total)

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        with _temporary_file(encoded, ".jpg") as source:
            frame = jsteg_extract_jpeg(source, mf=self.mf)
            total = jsteg_jpeg_capacity_bytes(source, mf=self.mf)
        return unpack_bytes(frame, capacity_bytes=total)


class JStegMethod(_JpegMethod):
    name = "jsteg"
    metadata = MethodMetadata(
        name="jsteg", label="JSteg", input_formats=("png",), output_format="jpeg", options={}
    )


class JStegMFMethod(_JpegMethod):
    name = "jsteg-mf"
    mf = True
    metadata = MethodMetadata(
        name="jsteg-mf", label="JSteg-MF", input_formats=("png",), output_format="jpeg", options={}
    )


class F5Method(SteganographyMethod):
    name = "f5"
    metadata = MethodMetadata(
        name="f5", label="F5", input_formats=("png",), output_format="jpeg",
        options={"key": {"type": "string", "required": False, "default": F5_DEFAULT_KEY}},
    )

    def capacity(self, image: np.ndarray) -> dict[str, int]:
        total = f5_capacity_from_png(image)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        raise NotImplementedError("Metoda F5 używa kontraktu bajtowego")

    def extract(self, image: np.ndarray) -> str:
        raise NotImplementedError("Metoda F5 używa kontraktu bajtowego")

    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        return self.capacity(load_png_from_bytes(cover, mode="cover"))

    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        key = options.get("key", F5_DEFAULT_KEY)
        total = self.capacity_bytes(cover)["capacity_bytes"]
        frame = _pack_payload(payload, capacity_bytes=total)
        with _temporary_file(cover, ".png") as source, _temporary_output(".jpg") as target:
            f5_embed_jpeg(source, target, frame, key=key, overwrite=True)
            data = Path(target).read_bytes()
        return EncodedArtifact(data, "image/jpeg", ".jpg")

    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        key = options.get("key", F5_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = f5_extract_jpeg(source, key=key)
            total = f5_capacity_from_jpeg(source)
        return unpack(frame, capacity_bytes=total)

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        key = options.get("key", F5_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = f5_extract_jpeg(source, key=key)
            total = f5_capacity_from_jpeg(source)
        return unpack_bytes(frame, capacity_bytes=total)


class OutGuessMethod(SteganographyMethod):
    name = "outguess"
    metadata = MethodMetadata(
        name="outguess",
        label="OutGuess",
        input_formats=("png",),
        output_format="jpeg",
        options={
            "key": {
                "type": "string",
                "required": False,
                "default": OUTGUESS_DEFAULT_KEY,
            }
        },
    )

    def capacity(self, image: np.ndarray) -> dict[str, int]:
        total = outguess_capacity_from_png(image)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        raise NotImplementedError("Metoda OutGuess używa kontraktu bajtowego")

    def extract(self, image: np.ndarray) -> str:
        raise NotImplementedError("Metoda OutGuess używa kontraktu bajtowego")

    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        key = options.get("key", OUTGUESS_DEFAULT_KEY)
        image = load_png_from_bytes(cover, mode="cover")
        total = outguess_capacity_from_png(image, key=key)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        key = options.get("key", OUTGUESS_DEFAULT_KEY)
        image = load_png_from_bytes(cover, mode="cover")
        total = outguess_capacity_from_png(image, key=key)
        frame = _pack_payload(payload, capacity_bytes=total)
        with _temporary_file(cover, ".png") as source, _temporary_output(".jpg") as target:
            outguess_embed_jpeg(source, target, frame, key=key, overwrite=True)
            data = Path(target).read_bytes()
        return EncodedArtifact(data, "image/jpeg", ".jpg")

    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        key = options.get("key", OUTGUESS_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = outguess_extract_jpeg(source, key=key)
            total = outguess_capacity_from_jpeg(source, key=key)
        return unpack(frame, capacity_bytes=total)

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        key = options.get("key", OUTGUESS_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = outguess_extract_jpeg(source, key=key)
            total = outguess_capacity_from_jpeg(source, key=key)
        return unpack_bytes(frame, capacity_bytes=total)


class NSF5Method(SteganographyMethod):
    name = "nsf5"
    metadata = MethodMetadata(
        name="nsf5",
        label="nsF5",
        input_formats=("png",),
        output_format="jpeg",
        options={
            "key": {
                "type": "string",
                "required": False,
                "default": NSF5_DEFAULT_KEY,
            }
        },
    )

    def capacity(self, image: np.ndarray) -> dict[str, int]:
        total = nsf5_capacity_from_png(image)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed(self, image: np.ndarray, payload: str) -> np.ndarray:
        raise NotImplementedError("Metoda nsF5 używa kontraktu bajtowego")

    def extract(self, image: np.ndarray) -> str:
        raise NotImplementedError("Metoda nsF5 używa kontraktu bajtowego")

    def capacity_bytes(self, cover: bytes, **options: Any) -> dict[str, int]:
        key = options.get("key", NSF5_DEFAULT_KEY)
        image = load_png_from_bytes(cover, mode="cover")
        total = nsf5_capacity_from_png(image, key=key)
        return {"capacity_bytes": total, "payload_capacity_bytes": max(0, total - 13)}

    def embed_bytes(self, cover: bytes, payload: str | bytes, **options: Any) -> EncodedArtifact:
        key = options.get("key", NSF5_DEFAULT_KEY)
        image = load_png_from_bytes(cover, mode="cover")
        total = nsf5_capacity_from_png(image, key=key)
        frame = _pack_payload(payload, capacity_bytes=total)
        with _temporary_file(cover, ".png") as source, _temporary_output(".jpg") as target:
            nsf5_embed_jpeg(source, target, frame, key=key, overwrite=True)
            data = Path(target).read_bytes()
        return EncodedArtifact(data, "image/jpeg", ".jpg")

    def extract_bytes(self, encoded: bytes, **options: Any) -> str:
        key = options.get("key", NSF5_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = nsf5_extract_jpeg(source, key=key)
            total = nsf5_capacity_from_jpeg(source, key=key)
        return unpack(frame, capacity_bytes=total)

    def extract_payload_bytes(self, encoded: bytes, **options: Any) -> bytes:
        key = options.get("key", NSF5_DEFAULT_KEY)
        with _temporary_file(encoded, ".jpg") as source:
            frame = nsf5_extract_jpeg(source, key=key)
            total = nsf5_capacity_from_jpeg(source, key=key)
        return unpack_bytes(frame, capacity_bytes=total)


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

    def metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "name": method.metadata.name,
                "label": method.metadata.label,
                "input_formats": list(method.metadata.input_formats),
                "output_format": method.metadata.output_format,
                "options": method.metadata.options,
            }
            for method in (self._methods[name] for name in self.names())
        ]


METHOD_REGISTRY = SteganographyRegistry()
METHOD_REGISTRY.register(LSBMethod())
METHOD_REGISTRY.register(JStegMethod())
METHOD_REGISTRY.register(JStegMFMethod())
METHOD_REGISTRY.register(F5Method())
METHOD_REGISTRY.register(OutGuessMethod())
METHOD_REGISTRY.register(NSF5Method())


_FILE_PAYLOAD_MAGIC = b"STEGFILE\x01"
_FILE_METADATA_LENGTH = struct.Struct(">I")


def _pack_payload(payload: str | bytes, *, capacity_bytes: int) -> bytes:
    if isinstance(payload, str):
        return pack(payload, capacity_bytes=capacity_bytes)
    if isinstance(payload, bytes):
        return pack_bytes(payload, capacity_bytes=capacity_bytes)
    raise TypeError("Payload musi mieć typ str lub bytes")


def encode_file_payload(filename: str, content_type: str, data: bytes) -> bytes:
    """Dołącz nazwę i typ MIME do pliku przed osadzeniem jego bajtów."""
    safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1] or "payload.bin"
    metadata = json.dumps(
        {"filename": safe_filename, "content_type": content_type},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(metadata) > 0xFFFFFFFF:
        raise ValueError("Metadane pliku są zbyt duże.")
    return _FILE_PAYLOAD_MAGIC + _FILE_METADATA_LENGTH.pack(len(metadata)) + metadata + data


def decode_file_payload(payload: bytes) -> tuple[str, str, bytes]:
    """Odczytaj nazwę, typ MIME i bajty pliku osadzonego przez API."""
    prefix_size = len(_FILE_PAYLOAD_MAGIC) + _FILE_METADATA_LENGTH.size
    if len(payload) < prefix_size or not payload.startswith(_FILE_PAYLOAD_MAGIC):
        raise ValueError("Payload nie zawiera osadzonego pliku.")
    metadata_size = _FILE_METADATA_LENGTH.unpack(
        payload[len(_FILE_PAYLOAD_MAGIC):prefix_size]
    )[0]
    metadata_end = prefix_size + metadata_size
    if metadata_end > len(payload):
        raise ValueError("Niekompletne metadane osadzonego pliku.")
    try:
        metadata = json.loads(payload[prefix_size:metadata_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Nie można odczytać metadanych osadzonego pliku.") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Niekompletne metadane osadzonego pliku.")
    filename = metadata.get("filename")
    content_type = metadata.get("content_type")
    if not isinstance(filename, str) or not isinstance(content_type, str):
        raise ValueError("Niekompletne metadane osadzonego pliku.")
    safe_filename = filename.replace("\\", "/").rsplit("/", 1)[-1] or "payload.bin"
    return safe_filename, content_type, payload[metadata_end:]


class _TemporaryPath:
    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self) -> str:
        return self.path

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def _temporary_file(data: bytes, suffix: str) -> _TemporaryPath:
    stream = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    stream.write(data)
    stream.close()
    return _TemporaryPath(stream.name)


def _temporary_output(suffix: str) -> _TemporaryPath:
    stream = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    stream.close()
    os.unlink(stream.name)
    return _TemporaryPath(stream.name)


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


def read_jpeg_bytes(file_storage: Any) -> bytes:
    """Wczytaj bajty pliku JPEG z żądania multipart."""
    if file_storage is None:
        raise ValueError("Brakuje pliku 'file'.")
    file_storage.seek(0)
    payload = file_storage.read()
    if not payload:
        raise ValueError("Przesłany plik jest pusty.")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if image.format not in {"JPEG", "JPG"}:
                raise ValueError("Obsługiwany jest tylko format JPEG.")
            image.verify()
    except Exception as exc:  # pragma: no cover - obsługa błędu wejścia
        raise ValueError("Nie można odczytać pliku JPEG.") from exc
    return payload


def load_png_from_bytes(payload: bytes, *, mode: str = "cover") -> np.ndarray:
    """Wczytaj PNG z bajtów do tablicy NumPy. Tryb cover/extract ma znaczenie."""
    if mode not in {"cover", "stego"}:
        raise ValueError(f"Nieznany tryb wczytania PNG: {mode}")
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
    "JStegMethod",
    "JStegMFMethod",
    "F5Method",
    "OutGuessMethod",
    "NSF5Method",
    "MethodMetadata",
    "EncodedArtifact",
    "MethodNotFoundError",
    "SteganographyMethod",
    "SteganographyRegistry",
    "METHOD_REGISTRY",
    "image_to_base64",
    "load_png_from_bytes",
    "read_png_bytes",
    "read_jpeg_bytes",
    "save_png_to_bytes",
]
