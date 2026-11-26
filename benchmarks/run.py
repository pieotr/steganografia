from __future__ import annotations
import argparse, gc, io, math, platform, statistics, sys, time, tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image
import steganografia as steg
from steganografia.api import METHOD_REGISTRY
from steganografia.frame import FrameError, HEADER_SIZE

METHODS = ("lsb", "jsteg", "jsteg-mf", "f5", "nsf5", "outguess")
DEFAULT_REPEATS = 5
DEFAULT_SEED = 20261126

def build_benchmark_dataset(seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    images = []
    def _add(image_id: str, category: str, arr: np.ndarray) -> None:
        rgb = np.clip(arr, 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(rgb, mode='RGB').save(buf, format='PNG')
        images.append({'id': image_id, 'category': category, 'width': int(rgb.shape[1]), 'height': int(rgb.shape[0]), 'png_bytes': buf.getvalue(), 'rgb': rgb})
    def _rgb_noise(h: int, w: int, base2d: np.ndarray, sigma: float) -> np.ndarray:
        return np.repeat(base2d[:, :, None], 3, axis=2) + rng.normal(0.0, sigma, size=(h, w, 3))
    y1, x1 = np.mgrid[0:128, 0:128]
    _add('01_smooth_gradient_128', 'smooth', np.stack([80 + x1 * 0.6, 110 + y1 * 0.5, 140 + (x1 + y1) * 0.25], axis=-1))
    _add('02_smooth_waves_128', 'smooth', _rgb_noise(128, 128, 128.0 + 18.0 * np.sin(x1 / 16.0) + 14.0 * np.cos(y1 / 14.0), 2.0))
    scene = np.zeros((128, 128, 3), dtype=np.float64)
    scene[:72, :, 0] = 95 + y1[:72, :] * 0.8; scene[:72, :, 1] = 145 + y1[:72, :] * 0.7; scene[:72, :, 2] = 215 - y1[:72, :] * 0.3
    scene[72:, :, 0] = 55 + (y1[72:, :] - 72) * 0.9; scene[72:, :, 1] = 110 + (x1[72:, :] * 0.4); scene[72:, :, 2] = 48
    scene[36:96, 28:68] = [185, 165, 145]
    scene[np.sqrt((x1 - 96) ** 2 + (y1 - 28) ** 2) < 12] = [245, 225, 110]
    _add('03_scene_landscape_128', 'photo_like', scene + rng.normal(0.0, 4.5, size=(128, 128, 3)))
    y160, x160 = np.mgrid[0:160, 0:160]
    p160 = _rgb_noise(160, 160, 130.0 + 45.0 * np.sin(x160 / 22.0) * np.cos(y160 / 19.0) + 25.0 * np.cos((x160 + y160) / 13.0), 6.0)
    p160[:, :, 0] *= 1.08; p160[:, :, 2] *= 0.88
    _add('04_scene_warm_tones_160', 'photo_like', p160)
    _add('05_scene_architecture_160', 'photo_like', _rgb_noise(160, 160, 100.0 + 40.0 * ((x160 // 16) % 2) + 35.0 * ((y160 // 20) % 2) + 0.35 * x160, 5.0))
    _add('06_texture_fabric_128', 'texture', _rgb_noise(128, 128, 128.0 + 55.0 * np.sin(x1 * 0.45 + np.cos(y1 * 0.35)) + 45.0 * np.cos(y1 * 0.55 - np.sin(x1 * 0.25)), 14.0))
    _add('07_texture_fine_grain_128', 'texture', rng.integers(20, 236, size=(128, 128, 3), dtype=np.uint8))
    y192, x192 = np.mgrid[0:192, 0:192]
    _add('08_texture_foliage_192', 'texture', _rgb_noise(192, 192, 115.0 + 60.0 * np.sin(x192 * 0.7) * np.sin(y192 * 0.65), 22.0))
    chk = (((x1 // 4) + (y1 // 4)) % 2) * 180 + 35
    _add('09_pattern_checker_128', 'high_contrast', np.stack([chk, 255 - chk, (chk // 2) + 60], axis=-1) + rng.normal(0.0, 6.0, size=(128, 128, 3)))
    y256, x256 = np.mgrid[0:256, 0:256]
    _add('10_mixed_scene_256', 'photo_like', _rgb_noise(256, 256, 125.0 + 50.0 * np.sin(x256 / 18.0) + 40.0 * np.cos(y256 / 15.0), 12.0))
    return images

def compute_mse_psnr(original_rgb: np.ndarray, stego_bytes: bytes) -> tuple[float, float]:
    with Image.open(io.BytesIO(stego_bytes)) as img:
        stego_rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    orig_f64 = np.asarray(original_rgb, dtype=np.float64)
    if orig_f64.shape != stego_rgb.shape:
        raise ValueError("Niezgodne wymiary obrazow")
    diff = orig_f64 - stego_rgb
    mse = float(np.mean(diff * diff))
    if mse == 0.0:
        return 0.0, float("inf")
    return mse, float(10.0 * math.log10((255.0 * 255.0) / mse))

def compute_bit_error_rate(expected: bytes, actual: bytes) -> float:
    if len(expected) != len(actual):
        raise ValueError("Dlugosci buforow musza byc identyczne")
    if not expected:
        return 0.0
    a = np.frombuffer(expected, dtype=np.uint8)
    b = np.frombuffer(actual, dtype=np.uint8)
    return float(np.mean(np.unpackbits(np.bitwise_xor(a, b))))

def _measure_call(fn, *args, repeats: int = DEFAULT_REPEATS, **kwargs) -> tuple[Any, float, list[float], int]:
    times_ms = []
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
    gc.collect()
    tracemalloc.start()
    result = fn(*args, **kwargs)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, float(statistics.median(times_ms)), times_ms, int(peak_bytes)

def run_benchmark(output_csv: Path, summary_md: Path, *, repeats: int = DEFAULT_REPEATS, seed: int = DEFAULT_SEED, payload_bytes: int | None = None) -> list[dict[str, Any]]:
    dataset = build_benchmark_dataset(seed=seed)
    rng = np.random.default_rng(seed + 999)
    capacities = {}
    min_common_payload = sys.maxsize
    for item in dataset:
        for method_name in METHODS:
            method = METHOD_REGISTRY.get(method_name)
            cap_info = method.capacity_bytes(item["png_bytes"])
            net_cap = int(cap_info.get("payload_capacity_bytes", max(0, cap_info["capacity_bytes"] - HEADER_SIZE)))
            capacities[(item["id"], method_name)] = net_cap
            if net_cap < min_common_payload:
                min_common_payload = net_cap
    common_payload_len = max(16, int(min_common_payload * 0.70)) if payload_bytes is None else payload_bytes
    reference_payload = rng.integers(0, 256, size=common_payload_len, dtype=np.uint8).tobytes()
    env_python = platform.python_version()
    env_platform = f"{platform.system()}-{platform.machine()}"
    env_cpu = platform.processor() or "unknown"
    pkg_version = getattr(steg, "__version__", "0.1.0")
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for item in dataset:
        img_id = item["id"]
        resolution = f"{item['width']}x{item['height']}"
        for method_name in METHODS:
            method = METHOD_REGISTRY.get(method_name)
            net_cap = capacities[(img_id, method_name)]
            cap_util_pct = (common_payload_len / net_cap * 100.0) if net_cap > 0 else float("nan")
            try:
                artifact, embed_med_ms, embed_runs, embed_peak_ram = _measure_call(method.embed_bytes, item["png_bytes"], reference_payload, repeats=repeats)
            except (FrameError, ValueError, RuntimeError) as exc:
                rows.append({"timestamp_utc": timestamp_utc, "pakiet_wersja": pkg_version, "python_wersja": env_python, "platforma": env_platform, "cpu": env_cpu, "seed": seed, "powtorzenia": repeats, "id_obrazu": img_id, "kategoria_obrazu": item["category"], "rozdzielczosc": resolution, "metoda": method_name, "pojemnosc_netto_B": net_cap, "payload_B": common_payload_len, "wykorzystanie_pojemnosci_pct": f"{cap_util_pct:.2f}", "mse": "", "psnr_dB": "", "czas_osadzania_mediana_ms": "", "czas_osadzania_probki_ms": "", "ram_osadzania_tracemalloc_KiB": "", "czas_odczytu_mediana_ms": "", "czas_odczytu_probki_ms": "", "ram_odczytu_tracemalloc_KiB": "", "status_ramki": f"EMBED_ERROR:{type(exc).__name__}", "skutecznosc_odzyskania": "FALSE", "ber": "NA"})
                continue
            mse, psnr = compute_mse_psnr(item["rgb"], artifact.data)
            try:
                recovered, extract_med_ms, extract_runs, extract_peak_ram = _measure_call(method.extract_payload_bytes, artifact.data, repeats=repeats)
                if len(recovered) == len(reference_payload):
                    ber_val = compute_bit_error_rate(reference_payload, recovered)
                    ber_str = f"{ber_val:.6f}"
                    full_ok = ber_val == 0.0
                    frame_status = "OK" if full_ok else "BIT_ERRORS"
                else:
                    ber_str = "NA"
                    full_ok = False
                    frame_status = "LENGTH_MISMATCH"
            except (FrameError, ValueError, RuntimeError) as exc:
                extract_med_ms = float("nan"); extract_runs = []; extract_peak_ram = 0; ber_str = "NA"; full_ok = False; frame_status = f"CORRUPTED_FRAME:{type(exc).__name__}"
            rows.append({"timestamp_utc": timestamp_utc, "pakiet_wersja": pkg_version, "python_wersja": env_python, "platforma": env_platform, "cpu": env_cpu, "seed": seed, "powtorzenia": repeats, "id_obrazu": img_id, "kategoria_obrazu": item["category"], "rozdzielczosc": resolution, "metoda": method_name, "pojemnosc_netto_B": net_cap, "payload_B": common_payload_len, "wykorzystanie_pojemnosci_pct": f"{cap_util_pct:.2f}", "mse": f"{mse:.6f}", "psnr_dB": "inf" if math.isinf(psnr) else f"{psnr:.2f}", "czas_osadzania_mediana_ms": f"{embed_med_ms:.3f}", "czas_osadzania_probki_ms": ";".join(f"{t:.3f}" for t in embed_runs), "ram_osadzania_tracemalloc_KiB": f"{embed_peak_ram / 1024.0:.2f}", "czas_odczytu_mediana_ms": "" if math.isnan(extract_med_ms) else f"{extract_med_ms:.3f}", "czas_odczytu_probki_ms": ";".join(f"{t:.3f}" for t in extract_runs), "ram_odczytu_tracemalloc_KiB": f"{extract_peak_ram / 1024.0:.2f}", "status_ramki": frame_status, "skutecznosc_odzyskania": "TRUE" if full_ok else "FALSE", "ber": ber_str})
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(fieldnames) + "\n")
        for r in rows:
            f.write(",".join(str(r[k]).replace(",", ";") for k in fieldnames) + "\n")
    summary_lines = ["# Podsumowanie benchmarku S4-02", "", f"- Data pomiaru (UTC): {timestamp_utc}", f"- Srodowisko: Python {env_python}, {env_platform}, CPU {env_cpu}", f"- Zbior testowy: 10 obrazow, seed={seed}, powtorzenia={repeats} (mediana)", f"- Wspolny payload: {common_payload_len} B", "- Pomiar RAM: tracemalloc.get_traced_memory()[1] (sledzone alokacje Pythona, bez RSS procesu)", "", "| Metoda | Odzyskanie | Sr. wykorzystanie poj. [%] | Mediana PSNR [dB] | Mediana MSE | Mediana embed [ms] | Mediana extract [ms] | Mediana RAM embed [KiB] | BER |", "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"]
    for method_name in METHODS:
        m_rows = [r for r in rows if r["metoda"] == method_name]
        ok_rows = [r for r in m_rows if r["skutecznosc_odzyskania"] == "TRUE"]
        valid = [r for r in m_rows if r["mse"] != ""]
        avg_util = statistics.mean(float(r["wykorzystanie_pojemnosci_pct"]) for r in m_rows)
        med_psnr = statistics.median(float(r["psnr_dB"]) for r in valid if r["psnr_dB"] != "inf") if valid else float("nan")
        med_mse = statistics.median(float(r["mse"]) for r in valid) if valid else float("nan")
        med_emb = statistics.median(float(r["czas_osadzania_mediana_ms"]) for r in valid) if valid else float("nan")
        med_ext = statistics.median(float(r["czas_odczytu_mediana_ms"]) for r in ok_rows) if ok_rows else float("nan")
        med_ram = statistics.median(float(r["ram_osadzania_tracemalloc_KiB"]) for r in valid) if valid else float("nan")
        ber_txt = "0.000000" if ok_rows else "NA"
        summary_lines.append(f"| {method_name} | {len(ok_rows)}/{len(m_rows)} | {avg_util:.2f}% | {med_psnr:.2f} | {med_mse:.4f} | {med_emb:.3f} | {med_ext:.3f} | {med_ram:.2f} | {ber_txt} |")
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    summary_md.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return rows

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="benchmarks/results/benchmark_raw.csv")
    parser.add_argument("--summary", default="benchmarks/results/summary.md")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--payload-bytes", type=int, default=None)
    args = parser.parse_args()
    rows = run_benchmark(Path(args.csv), Path(args.summary), repeats=args.repeats, seed=args.seed, payload_bytes=args.payload_bytes)
    print(f"Zapisano {len(rows)} rekordow do {args.csv}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
