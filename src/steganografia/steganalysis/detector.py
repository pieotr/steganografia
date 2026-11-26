"""Detektor nietypowych histogramów: odległość Hellingera i próg empiryczny."""

from collections import Counter
from collections.abc import Mapping
from math import fsum, isfinite, sqrt
from numbers import Integral, Real
from typing import Iterable, Optional

import numpy as np

from .histograms import dct_histogram_report


def _number(value, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} musi być liczbą")
    value = float(value)
    if not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} musi należeć do [{minimum}, {maximum}]")
    return value


def _distribution(histogram: Mapping) -> dict:
    """Normalizuj liczności/wagi; zachowaj także wartości ujemne i rzadkie."""
    if not isinstance(histogram, Mapping):
        raise TypeError("Histogram musi być słownikiem z values i counts")
    if "values" not in histogram or "counts" not in histogram:
        raise ValueError("Histogram musi zawierać values i counts")
    values, counts = list(histogram["values"]), list(histogram["counts"])
    if not values or len(values) != len(counts):
        raise ValueError("values i counts muszą być niepuste i mieć tę samą długość")
    result = {}
    for value, count in zip(values, counts):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
            raise TypeError("Wartości histogramu muszą być liczbami całkowitymi")
        value = int(value)
        if value in result:
            raise ValueError("Wartości histogramu nie mogą się powtarzać")
        result[value] = _number(count, "Liczność histogramu", 0, float("inf"))
    try:
        total = fsum(result.values())
    except OverflowError as exc:
        raise ValueError("Suma liczności histogramu jest zbyt duża") from exc
    if total <= 0:
        raise ValueError("Histogram musi zawierać dodatnią sumę liczności")
    return {value: count / total for value, count in result.items()}


def _distance(first: dict, second: dict) -> float:
    distance = sqrt(fsum(
        (sqrt(first.get(value, 0.0)) - sqrt(second.get(value, 0.0))) ** 2
        for value in first.keys() | second.keys()
    ) / 2.0)
    return min(1.0, distance)


def hellinger_distance(first: Mapping, second: Mapping) -> float:
    """Porównaj histogramy ``{values, counts}`` po normalizacji do udziałów.

    counts może zawierać liczności lub nieujemne wagi. Kolejność values
    nie ma znaczenia; brakująca wartość ma udział zero. Wynik leży w [0, 1].
    Nie jest prawdopodobieństwem steganografii ani wartością p.
    """
    return _distance(_distribution(first), _distribution(second))


def calibrate_histogram_detector(
    reference_histograms: Iterable[Mapping],
    calibration_histograms: Iterable[Mapping],
    *,
    quantile: float = 0.95,
) -> dict:
    """Zbuduj wzorzec i próg z dwóch osobnych zbiorów czystych histogramów.

    Każdy obraz ma taką samą wagę, niezależnie od liczby współczynników.
    Próg to kwantyl odległości kalibracyjnych (numpy, method='higher').
    Alarm wymaga distance > threshold, więc remisy nie wywołują alarmu.
    Zbiory muszą być rozłączne; funkcja nie zna tożsamości ich obrazów.
    Zwracany model można zapisać przez json.dumps i wczytać przez json.loads.
    """
    quantile = _number(quantile, "quantile", 0, 1)
    if quantile == 0:
        raise ValueError("quantile musi być większe od zera")
    mean = Counter()
    reference_count = 0
    for histogram in reference_histograms:
        mean.update(_distribution(histogram))
        reference_count += 1
    if not reference_count:
        raise ValueError("Zbiór wzorcowy nie może być pusty")
    values = sorted(mean)
    reference_histogram = {
        "values": values,
        "counts": [mean[value] / reference_count for value in values],
    }
    reference = _distribution(reference_histogram)
    distances = [
        _distance(_distribution(histogram), reference)
        for histogram in calibration_histograms
    ]
    if not distances:
        raise ValueError("Zbiór kalibracyjny nie może być pusty")
    threshold = float(np.quantile(distances, quantile, method="higher"))
    return {
        "method": "histogram_hellinger",
        "version": 1,
        # Wagi sumują się do 1; nie są sumą liczności wszystkich obrazów.
        "reference": reference_histogram,
        "reference_image_count": reference_count,
        "threshold": threshold,
        "quantile": quantile,
        "quantile_method": "higher",
        "calibration_image_count": len(distances),
        "calibration_distances": distances,
        "calibration_false_alarm_rate": sum(d > threshold for d in distances) / len(distances),
    }


def histogram_detection(histogram: Mapping, model: Mapping) -> dict:
    """Oblicz odległość i alarm względem skalibrowanego modelu.

    Alarm oznacza nietypowy histogram; jego skuteczność detekcji trzeba
    ocenić na osobnym zbiorze obrazów czystych i stego.
    """
    if not isinstance(model, Mapping):
        raise TypeError("Model musi być słownikiem")
    if model.get("method") not in ("histogram_hellinger", "dct_histogram_hellinger") or model.get("version") != 1:
        raise ValueError("Nieobsługiwany typ lub wersja modelu")
    if "threshold" not in model or "reference" not in model:
        raise ValueError("Model musi zawierać threshold i reference")
    threshold = _number(model["threshold"], "threshold", 0, 1)
    distance = hellinger_distance(histogram, model["reference"])
    return {
        "method": "histogram_hellinger",
        "distance": distance,
        "threshold": threshold,
        "alarm": distance > threshold,
    }


def _selector(component: str, zigzag_position: Optional[int]) -> None:
    if component not in ("all", "Y", "Cb", "Cr"):
        raise ValueError("component musi być jednym z: all, Y, Cb, Cr")
    if zigzag_position is not None:
        if isinstance(zigzag_position, (bool, np.bool_)) or not isinstance(zigzag_position, Integral):
            raise TypeError("zigzag_position musi być liczbą całkowitą")
        if not 1 <= zigzag_position <= 63:
            raise ValueError("zigzag_position musi należeć do [1, 63]")


def _dct_histogram(source, component: str, zigzag_position: Optional[int]) -> dict:
    report = dct_histogram_report(source)
    counts = Counter()
    names = ("Y", "Cb", "Cr") if component == "all" else (component,)
    for name in names:
        data = report["components"][name]
        histogram = data["ac"] if zigzag_position is None else data["ac_by_position"][zigzag_position - 1]
        counts.update(dict(zip(histogram["values"], histogram["counts"])))
    if not counts:
        raise ValueError(f"Brak współczynników dla komponentu {component}")
    values = sorted(counts)
    return {"values": values, "counts": [counts[v] for v in values]}


def calibrate_dct_histogram_detector(
    reference_sources: Iterable,
    calibration_sources: Iterable,
    *,
    component: str = "all",
    zigzag_position: Optional[int] = None,
    quantile: float = 0.95,
) -> dict:
    """Kalibruj detektor z JPEG/obiektów JpegCoefficients, bez zmiany wejść.

    Domyślnie łączy wszystkie AC (bez DC) z Y/Cb/Cr. Można wybrać komponent
    i/lub pozycję AC 1–63. Wybór zostaje zapisany w modelu i jest ponownie
    używany przy detekcji. Parametry kompresji obrazów należy dopasować
    przed kalibracją; funkcja nie sprawdza zgodności tablic kwantyzacji.
    """
    _selector(component, zigzag_position)
    model = calibrate_histogram_detector(
        (_dct_histogram(source, component, zigzag_position) for source in reference_sources),
        (_dct_histogram(source, component, zigzag_position) for source in calibration_sources),
        quantile=quantile,
    )
    model.update({
        "method": "dct_histogram_hellinger",
        "component": component,
        "zigzag_position": int(zigzag_position) if zigzag_position is not None else None,
    })
    return model


def dct_histogram_detection(source, model: Mapping) -> dict:
    """Przeanalizuj JPEG albo JpegCoefficients według ustawień modelu DCT.

    Zachowanie zbiorczego histogramu przez OutGuess oznacza również
    zachowanie jego odległości od wzorca. Alarm nie dowodzi steganografii.
    """
    if not isinstance(model, Mapping):
        raise TypeError("Model musi być słownikiem")
    if model.get("method") != "dct_histogram_hellinger":
        raise ValueError("Wymagany model detektora histogramów DCT")
    if "component" not in model or "zigzag_position" not in model:
        raise ValueError("Model DCT musi zawierać component i zigzag_position")
    component, position = model["component"], model["zigzag_position"]
    _selector(component, position)
    histogram = _dct_histogram(source, component, position)
    result = histogram_detection(histogram, model)
    result.update({
        "method": "dct_histogram_hellinger",
        "component": component,
        "zigzag_position": int(position) if position is not None else None,
        "coefficient_count": sum(histogram["counts"]),
    })
    return result
