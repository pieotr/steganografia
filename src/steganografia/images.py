"""Odczyt PNG do osadzania i ekstrakcji oraz bezstratny zapis RGB."""

import os
from os import PathLike
from pathlib import Path
import tempfile
import warnings
from typing import Union

import numpy as np
from PIL import Image


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 16_384
_INPUT_MODES = {"1", "L", "LA", "P", "RGB", "RGBA"}


class ImageError(ValueError):
    """Nieobsługiwany, uszkodzony lub zbyt duży obraz albo błąd zapisu."""


def _check_size(width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise ImageError("Obraz nie może być pusty")
    if max(width, height) > MAX_DIMENSION or width * height > MAX_PIXELS:
        raise ImageError(
            f"Rozmiar {width}×{height} przekracza limit: "
            f"{MAX_PIXELS} pikseli i {MAX_DIMENSION} na każdy wymiar"
        )


def _read_png(path: Union[str, PathLike[str]], *, normalize: bool) -> np.ndarray:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with open(path, "rb") as stream:
                if os.fstat(stream.fileno()).st_size > MAX_FILE_BYTES:
                    raise ImageError(f"Plik przekracza limit {MAX_FILE_BYTES} bajtów")
                header = stream.read(29)
                stream.seek(0)
                with Image.open(stream) as source:
                    if source.format != "PNG":
                        raise ImageError("Nieobsługiwany format obrazu; wymagany PNG")
                    _check_size(*source.size)
                    # Pillow potrafi po cichu zredukować 16-bitowy RGB do 8 bitów.
                    # Głębię sprawdzamy więc w IHDR, przed dekodowaniem pikseli.
                    if len(header) < 29 or header[12:16] != b"IHDR":
                        raise ImageError("Niepoprawny nagłówek PNG")
                    bit_depth = header[24]
                    if bit_depth not in (1, 2, 4, 8):
                        raise ImageError(
                            f"Nieobsługiwana głębia PNG: {bit_depth} bitów; maksymalnie 8"
                        )
                    if source.mode not in _INPUT_MODES:
                        raise ImageError(f"Nieobsługiwany tryb obrazu: {source.mode}")
                    if getattr(source, "is_animated", False):
                        raise ImageError("Animowany PNG (APNG) nie jest obsługiwany")
                    if not normalize and (source.mode != "RGB" or bit_depth != 8):
                        raise ImageError(
                            "Ekstrakcja wymaga PNG w trybie 8-bitowego RGB; "
                            "konwersja mogłaby zmienić LSB"
                        )
                    source.load()
                    if normalize:
                        return np.array(source.convert("RGB"), dtype=np.uint8)
                    return np.array(source, dtype=np.uint8)
    except ImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageError("Obraz przekracza limit bezpiecznego rozmiaru Pillow") from exc
    except (OSError, ValueError, SyntaxError) as exc:
        raise ImageError(f"Nie można odczytać obrazu '{path}': {exc}") from exc


def load_cover(path: Union[str, PathLike[str]]) -> np.ndarray:
    """Wczytaj statyczny PNG i znormalizuj do uint8 RGB przed osadzaniem.

    Obsługuje 1, L, LA, P, RGB, RGBA o głębi do 8 bitów. Alfa jest
    pomijana bez mieszania z tłem; paleta i skala szarości rozwijane do RGB.
    """
    return _read_png(path, normalize=True)


def load_stego(path: Union[str, PathLike[str]]) -> np.ndarray:
    """Wczytaj wyłącznie 8-bitowy RGB PNG bez normalizacji przed ekstrakcją."""
    return _read_png(path, normalize=False)


def save_png(
    image: np.ndarray,
    path: Union[str, PathLike[str]],
    *,
    overwrite: bool = False,
) -> None:
    """Zapisz uint8 RGB jako PNG; nadpisanie wymaga jawnego overwrite=True.

    Zapis tymczasowy i atomowe opublikowanie chronią istniejący plik także
    przy błędzie kodowania lub równoczesnym utworzeniu ścieżki docelowej.
    """
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8:
        raise ImageError("Zapis wymaga tablicy NumPy typu uint8")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ImageError("Zapis wymaga obrazu RGB o układzie (wysokość, szerokość, 3)")
    _check_size(image.shape[1], image.shape[0])
    target = Path(path)
    if target.suffix.lower() != ".png":
        raise ImageError("Obraz wynikowy musi mieć rozszerzenie .png")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".png", delete=False) as stream:
            temporary = Path(stream.name)
            Image.fromarray(image).save(stream, format="PNG")
        if temporary.stat().st_size > MAX_FILE_BYTES:
            raise ImageError(f"Plik wynikowy przekracza limit {MAX_FILE_BYTES} bajtów")
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
        raise ImageError(f"Nie można zapisać PNG '{target}': {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


__all__ = ["ImageError", "load_cover", "load_stego", "save_png"]
