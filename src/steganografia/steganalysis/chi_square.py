"""Analiza par wartości (2k, 2k+1) dla podmiany LSB w RGB."""

from math import erfc, exp, lgamma, log, sqrt
from typing import Optional

import numpy as np

from ._common import positive_int, rgb_image


def _chi_square_sf(statistic: float, degrees: int) -> float:
    """Q(degrees/2, statistic/2) przez rekurencję górnej funkcji gamma.

    Całkowite stopnie swobody (tu najwyżej 128) dają całkowity lub
    połówkowy parametr gamma. Bazami są exp(-x) i erfc(sqrt(x));
    dodatnie składniki rekurencji nie wymagają odejmowania CDF od 1.
    """
    x = statistic / 2.0
    if x == 0:
        return 1.0
    shape = degrees / 2.0
    a = 0.5 if degrees % 2 else 1.0
    result = erfc(sqrt(x)) if degrees % 2 else exp(-x)
    while a < shape:
        result += exp(a * log(x) - x - lgamma(a + 1.0))
        a += 1.0
    return min(1.0, max(0.0, result))


def _analyse_samples(samples: np.ndarray, minimum: float) -> dict:
    pairs = np.bincount(samples, minlength=256).reshape(128, 2)
    totals = pairs.sum(axis=1)
    used = totals / 2.0 >= minimum
    selected = pairs[used].astype(np.float64)
    # Pearson dla dwóch komórek o wspólnej oczekiwanej liczności total/2.
    statistic = float(np.sum((selected[:, 0] - selected[:, 1]) ** 2 / totals[used]))
    degrees = int(np.count_nonzero(used))
    return {
        "sample_count": int(samples.size),
        "used_sample_count": int(totals[used].sum()),
        "used_pair_count": degrees,
        "omitted_pair_count": 128 - degrees,
        "statistic": statistic if degrees else None,
        "degrees_of_freedom": degrees,
        "p_value": _chi_square_sf(statistic, degrees) if degrees else None,
        "status": "ok" if degrees else "insufficient_samples",
    }


def chi_square_analysis(
    image: np.ndarray,
    *,
    window_size: Optional[int] = None,
    min_expected_count: float = 5.0,
) -> dict:
    """Zwróć globalną i opcjonalnie okienkową analizę RGB (alfa pomijana).

    Okno obejmuje ``window_size`` pikseli w kolejności wierszowej; zakresy
    start/end są półotwarte. Kanały analizowane są oddzielnie. Końcowe
    niepełne okno także jest raportowane. Pary z oczekiwaną licznością
    poniżej ``min_expected_count`` na komórkę są pomijane.

    H0: jednakowe liczebności obu wartości w każdej parze. Stosujemy pełną
    statystykę Pearsona (obie komórki) i jeden stopień swobody na parę,
    warunkowo względem jej sumy. To wariant testu par, nie konwencja k-1
    spotykana w oryginalnym ataku Westfelda/Pfitzmanna. Duże p oznacza
    zgodność z H0, a NIE prawdopodobieństwo ukrycia wiadomości.
    Przybliżenie chi-kwadrat zakłada niezależność próbek; naturalne obrazy
    i nielosowe wiadomości mogą naruszać to założenie.
    """
    rgb = rgb_image(image)
    if window_size is not None:
        window_size = positive_int(window_size, "window_size")
    if isinstance(min_expected_count, bool) or not isinstance(
        min_expected_count, (int, float, np.integer, np.floating)
    ):
        raise TypeError("min_expected_count musi być liczbą")
    if not np.isfinite(min_expected_count) or min_expected_count <= 0:
        raise ValueError("min_expected_count musi być dodatnie i skończone")
    channels = {}
    for index, name in enumerate(("R", "G", "B")):
        samples = rgb[:, :, index].reshape(-1)
        report = {"global": _analyse_samples(samples, min_expected_count)}
        if window_size is not None:
            report["windows"] = [
                {
                    "start": start,
                    "end": min(start + window_size, int(samples.size)),
                    **_analyse_samples(samples[start:start + window_size], min_expected_count),
                }
                for start in range(0, samples.size, window_size)
            ]
        channels[name] = report
    return {
        "method": "chi_square_pairs",
        "window_size": window_size,
        "min_expected_count": float(min_expected_count),
        "channels": channels,
    }
