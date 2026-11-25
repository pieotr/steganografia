"""Raport rozkładów skwantyzowanych współczynników DCT pliku JPEG."""

from os import PathLike
from typing import Union

import numpy as np

from ..jpeg import JpegCoefficients, read_jpeg


def _histogram(values: np.ndarray) -> dict:
    bins, counts = np.unique(values, return_counts=True)
    total = int(values.size)
    nonzero = int(np.count_nonzero(values))
    return {
        "count": total,
        "values": bins.tolist(),
        "counts": counts.tolist(),
        "zero_count": total - nonzero,
        "zero_fraction": (total - nonzero) / total if total else None,
        "positive_one_count": int(np.count_nonzero(values == 1)),
        "negative_one_count": int(np.count_nonzero(values == -1)),
        "nonzero_count": nonzero,
        "even_nonzero_count": int(np.count_nonzero((values != 0) & (values % 2 == 0))),
        "odd_count": int(np.count_nonzero(values % 2 != 0)),
    }


def dct_histogram_report(
    source: Union[str, PathLike, JpegCoefficients],
) -> dict:
    """Zwróć histogramy DC i AC, osobno dla Y, Cb, Cr i pozycji zig-zag.

    Przyjmuje ścieżkę baseline JPEG obsługiwanego przez read_jpeg albo
    odczytany JpegCoefficients. Histogramy zachowują znak i pełny zakres
    wartości; values[i] odpowiada counts[i]. AC nie obejmuje DC (pozycja 0).
    Dla nieobecnego komponentu histogramy są puste, a udziały mają None.
    Raport obejmuje wszystkie zapisane bloki, w tym dopełnienie obrazu.
    Jest opisem statystycznym, bez kalibracji i decyzji o steganografii.
    """
    coefficients = source if isinstance(source, JpegCoefficients) else read_jpeg(source)
    components = {}
    for name, blocks in (
        ("Y", coefficients.y_blocks),
        ("Cb", coefficients.cb_blocks),
        ("Cr", coefficients.cr_blocks),
    ):
        array = np.asarray(blocks)
        if array.size == 0:
            if len(blocks):
                raise ValueError(f"Komponent {name} zawiera puste bloki")
            array = np.empty((0, 64), dtype=np.int64)
        if array.ndim != 2 or array.shape[1] != 64 or array.dtype.kind not in "iu":
            raise ValueError(f"Komponent {name} musi zawierać całkowitoliczbowe bloki po 64 współczynniki")
        components[name] = {
            "block_count": int(array.shape[0]),
            "dc": _histogram(array[:, 0]),
            "ac": _histogram(array[:, 1:].reshape(-1)),
            "ac_by_position": [
                {"zigzag_position": position, **_histogram(array[:, position])}
                for position in range(1, 64)
            ],
        }
    return {
        "method": "dct_histograms",
        "width": int(coefficients.width),
        "height": int(coefficients.height),
        "components": components,
    }
