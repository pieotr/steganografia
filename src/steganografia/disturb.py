"""Symulator kontrolowanych zakłóceń (JPEG, szum Gaussa, skalowanie) i raportowanie CSV."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from .api import METHOD_REGISTRY
from .frame import FrameError
from .images import ImageError


def _klasyfikuj_blad(exc: Exception) -> str:
    msg = str(exc).lower()
    if "magic" in msg:
        return "MAGIC"
    if "length" in msg or "pojemność" in msg or "ucięty" in msg:
        return "LENGTH"
    if "crc32" in msg:
        return "CRC"
    if isinstance(exc, ImageError) or "jpeg" in msg or "png" in msg or "huffmana" in msg:
        return "format"
    return f"error: {exc}"


def apply_disturbance(image_bytes: bytes, *, kind: str, param: str, seed: int = 42) -> bytes:
    """Zastosuj zakłócenie i zwróć bajty obrazu w tym samym formacie (PNG lub JPEG)."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        orig_format = img.format or "PNG"
        rgb = np.array(img.convert("RGB"), dtype=np.uint8)

    if kind == "none":
        return image_bytes

    if kind == "jpeg":
        quality = int(param)
        buf = io.BytesIO()
        Image.fromarray(rgb).save(buf, format="JPEG", quality=quality)
        if orig_format == "PNG":
            out_png = io.BytesIO()
            Image.open(io.BytesIO(buf.getvalue())).save(out_png, format="PNG")
            return out_png.getvalue()
        return buf.getvalue()

    if kind == "noise":
        sigma = float(param)
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, sigma, size=rgb.shape)
        noisy = np.clip(np.rint(rgb.astype(np.float64) + noise), 0, 255).astype(np.uint8)
        out = io.BytesIO()
        Image.fromarray(noisy).save(out, format=orig_format, quality=95)
        return out.getvalue()

    if kind == "scale":
        factor = float(param)
        h, w = rgb.shape[:2]
        new_w = max(1, int(round(w * factor)))
        new_h = max(1, int(round(h * factor)))
        pil_img = Image.fromarray(rgb)
        scaled = pil_img.resize((new_w, new_h), Image.Resampling.BILINEAR).resize(
            (w, h), Image.Resampling.BILINEAR
        )
        out = io.BytesIO()
        scaled.save(out, format=orig_format, quality=95)
        return out.getvalue()

    raise ValueError(f"Nieznany typ zakłócenia: {kind}")


def run_disturb_experiments(
    cover_path: str | Path,
    output_dir: str | Path,
    *,
    text: str = "Kontrolny payload S4 — Zażółć gęślą jaźń",
    methods: Sequence[str] | None = None,
    seed: int = 42,
) -> Path:
    """Przeprowadź eksperymenty zakłóceń dla wybranych metod i zapisz wyniki + CSV."""
    cover_file = Path(cover_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cover_bytes = cover_file.read_bytes()

    selected_methods = list(methods) if methods is not None else METHOD_REGISTRY.names()
    scenarios = [
        ("none", "0"),
        ("jpeg", "90"),
        ("jpeg", "70"),
        ("jpeg", "50"),
        ("noise", "2.0"),
        ("noise", "5.0"),
        ("scale", "0.75"),
    ]

    rows: list[list[str | int]] = []
    for method_name in selected_methods:
        method = METHOD_REGISTRY.get(method_name)
        artifact = method.embed_bytes(cover_bytes, text)

        for kind, param in scenarios:
            disturbed = apply_disturbance(artifact.data, kind=kind, param=param, seed=seed)
            out_img = out_dir / f"{cover_file.stem}_{method_name}_{kind}_{param}{artifact.extension}"
            out_img.write_bytes(disturbed)

            try:
                recovered = method.extract_bytes(disturbed)
                if recovered == text:
                    status = "OK"
                    payload_match = "IDENTICAL"
                else:
                    status = "CORRUPTED_PAYLOAD"
                    payload_match = "MISMATCH"
            except (FrameError, ImageError, Exception) as exc:
                status = _klasyfikuj_blad(exc)
                payload_match = "NONE"

            rows.append([
                cover_file.name,
                method_name,
                len(text.encode("utf-8")),
                f"{kind}:{param}:seed={seed}",
                out_img.name,
                status,
                payload_match,
            ])

    csv_path = out_dir / "disturb_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id_obrazu",
            "metoda",
            "rozmiar_payloadu_B",
            "parametry_zaklocenia",
            "plik_wynikowy",
            "status_ramki",
            "wynik_odzyskania",
        ])
        writer.writerows(rows)
    return csv_path