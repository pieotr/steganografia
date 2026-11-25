"""Walidacja tablic dla analiz przestrzennych."""

import numpy as np


def rgb_image(image: np.ndarray) -> np.ndarray:
    if not isinstance(image, np.ndarray):
        raise TypeError("Obraz musi być tablicą NumPy")
    if image.dtype != np.uint8:
        raise TypeError("Próbki obrazu muszą mieć typ uint8")
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("Obraz musi mieć układ (wysokość, szerokość, 3 lub 4 kanały)")
    if not image.shape[0] or not image.shape[1]:
        raise ValueError("Obraz nie może być pusty")
    return image[:, :, :3]


def positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} musi być liczbą całkowitą")
    if value < 1:
        raise ValueError(f"{name} musi być dodatnie")
    return int(value)
