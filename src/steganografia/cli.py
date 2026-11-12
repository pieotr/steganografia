"""Komendy LSB oraz konwersja PNG do JPEG z własnym pipeline'em DCT."""

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional

from .frame import FrameError, pack, unpack
from .f5 import (
    DEFAULT_KEY as F5_DEFAULT_KEY,
    capacity_from_jpeg as f5_capacity_from_jpeg,
    capacity_from_png as f5_capacity_from_png,
    embed_jpeg as f5_embed_jpeg,
    extract_jpeg as f5_extract_jpeg,
)
from .images import ImageError, load_cover, load_stego, save_png
from .jpeg import png_to_jpeg
from .lsb import capacity_bytes, embed_frame, extract_frame, payload_capacity_bytes
from .jsteg import (
    embed_jpeg as jsteg_embed_jpeg,
    extract_jpeg as jsteg_extract_jpeg,
    jpeg_capacity_bytes as jsteg_jpeg_capacity_bytes,
    png_jpeg_capacity_bytes as jsteg_png_jpeg_capacity_bytes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steganografia",
        description="Ukrywanie tekstu UTF-8 w PNG metodą LSB i jego odczyt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Przykład: steganografia embed oryginal.png wynik.png --text "Cześć!"\n'
            "Drugi argument (wynik.png) wskazuje miejsce zapisu wynikowego PNG;\n"
            "ścieżka względna jest liczona od bieżącego katalogu terminala.\n"
            "Tekst z TXT: embed oryginal.png wynik.png --text-file wiadomosc.txt\n"
            "Zapis do TXT: extract wynik.png --output odzyskany.txt\n"
            "Szczegóły: steganografia embed --help"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, title="komendy")

    embed = commands.add_parser(
        "embed",
        help="ukryj tekst i zapisz wynikowy PNG pod ścieżką z drugiego argumentu",
        description=(
            "Ukryj tekst w obrazie wejściowym i zapisz wynikowy PNG pod ścieżką "
            "podaną jako drugi argument (WYJŚCIE). Ścieżki względne są liczone "
            "od bieżącego katalogu terminala. Katalog docelowy musi istnieć. "
            "Istniejący plik można nadpisać wyłącznie z --force."
        ),
        epilog=(
            'Przykład: steganografia embed oryginal.png wynik.png --text "Cześć!" '
            '— zapisze obraz z wiadomością do pliku wynik.png w bieżącym katalogu.'
        ),
    )
    embed.add_argument("input", metavar="WEJŚCIE", help="statyczny PNG do osadzania")
    embed.add_argument(
        "output", metavar="WYJŚCIE",
        help="drugi argument: ścieżka zapisu wynikowego PNG, np. wynik.png lub demo/wiadomosc.png",
    )
    source = embed.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", metavar="TEKST", help="wiadomość UTF-8, także pusty tekst")
    source.add_argument(
        "--text-file", metavar="PLIK.txt",
        help="wczytaj wiadomość z pliku UTF-8, zachowując końce wierszy",
    )
    embed.add_argument(
        "--force", "--overwrite", dest="overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie istniejącego pliku wynikowego",
    )

    extract = commands.add_parser("extract", help="odczytaj tekst z wynikowego PNG")
    extract.add_argument("input", metavar="WEJŚCIE", help="8-bitowy RGB PNG z ramką STEG v1")
    extract.add_argument(
        "-o", "--output", metavar="PLIK.txt",
        help="zapisz tekst UTF-8 do pliku; domyślnie tekst trafia na stdout",
    )
    extract.add_argument(
        "--force", "--overwrite", dest="overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie pliku tekstowego wskazanego przez --output",
    )

    capacity = commands.add_parser("capacity", help="pokaż pojemność PNG przed osadzaniem")
    capacity.add_argument("input", metavar="WEJŚCIE", help="statyczny PNG do osadzania")

    jpeg = commands.add_parser(
        "jpeg",
        help="przetwórz PNG przez DCT i zapisz wynik jako JPEG",
        description=(
            "Wczytaj PNG, wykonaj konwersję YCbCr, subsampling 4:2:0, DCT "
            "i kwantyzację, a następnie zapisz własny baseline JPEG."
        ),
    )
    jpeg.add_argument("input", metavar="WEJŚCIE", help="statyczny PNG źródłowy")
    jpeg.add_argument(
        "output",
        metavar="WYJŚCIE",
        help="ścieżka zapisu wynikowego pliku .jpg lub .jpeg",
    )
    jpeg.add_argument(
        "--force", "--overwrite", dest="overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie istniejącego pliku",
    )
    for method, help_text in (
        ("jsteg", "JSteg"),
        ("jsteg-mf", "JSteg-MF"),
        ("f5", "F5"),
    ):
        method_parser = commands.add_parser(
            method,
            help=f"osadzaj lub odczytuj tekst metodą {help_text}",
        )
        method_commands = method_parser.add_subparsers(
            dest=f"{method.replace('-', '_')}_command",
            required=True,
        )
        method_capacity = method_commands.add_parser(
            "capacity", help=f"pokaż pojemność {help_text}"
        )
        method_capacity.add_argument("input", metavar="WEJŚCIE", help="obraz RGB")
        method_embed = method_commands.add_parser(
            "embed", help=f"osadź tekst metodą {help_text}"
        )
        method_embed.add_argument("input", metavar="WEJŚCIE", help="obraz RGB")
        method_embed.add_argument("output", metavar="WYJŚCIE", help="wynikowy JPEG")
        method_source = method_embed.add_mutually_exclusive_group(required=True)
        method_source.add_argument("--text", metavar="TEKST")
        method_source.add_argument("--text-file", metavar="PLIK.txt")
        method_embed.add_argument(
            "--force", "--overwrite", dest="overwrite", action="store_true"
        )
        if method == "f5":
            method_embed.add_argument("--key", default=F5_DEFAULT_KEY, help="opcjonalny klucz F5")
        method_extract = method_commands.add_parser(
            "extract", help=f"odczytaj tekst metodą {help_text}"
        )
        method_extract.add_argument("input", metavar="WEJŚCIE", help="obraz JPEG")
        method_extract.add_argument("-o", "--output", metavar="PLIK.txt")
        method_extract.add_argument(
            "--force", "--overwrite", dest="overwrite", action="store_true"
        )
        if method == "f5":
            method_extract.add_argument("--key", default=F5_DEFAULT_KEY, help="opcjonalny klucz F5")
    return parser


def _capacity_message(image) -> str:
    return (
        f"Pojemność: {capacity_bytes(image)} B ramki; "
        f"{payload_capacity_bytes(image)} B tekstu UTF-8 "
        "(po odjęciu nagłówka 13 B)."
    )


def _read_text(path: str, limit: int) -> str:
    with open(path, "rb") as stream:
        print(f"Rozmiar pliku TXT: {os.fstat(stream.fileno()).st_size} B tekstu UTF-8 ({path}).", file=sys.stderr)
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise FrameError(f"za długa wiadomość: plik tekstowy przekracza pojemność obrazu: maksymalnie {limit} B tekstu UTF-8")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameError(f"plik tekstowy '{path}' nie jest poprawnym UTF-8") from exc


def _save_text(text: str, path: str, *, overwrite: bool) -> None:
    """Zapisz dokładne bajty UTF-8; opublikuj plik dopiero po pełnym zapisie."""
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text.encode("utf-8"))
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom CLI; kod 0 oznacza sukces, 1 błąd danych/pliku, 2 błąd składni."""
    parser = _parser()
    args = parser.parse_args(argv)
    args.overwrite = bool(getattr(args, "overwrite", False))
    method_command = (
        getattr(args, "jsteg_command", None)
        if args.command == "jsteg"
        else (
            getattr(args, "jsteg_mf_command", None)
            if args.command == "jsteg-mf"
            else getattr(args, "f5_command", None)
        )
    )
    if args.command in {"jsteg", "jsteg-mf", "f5"} and method_command == "extract" and args.overwrite and args.output is None:
        parser.error("--force wymaga --output wskazującego plik tekstowy")
    if args.command == "extract" and args.overwrite and args.output is None:
        parser.error("--force wymaga --output wskazującego plik tekstowy")
    try:
        if args.command == "f5":
            if method_command == "capacity":
                image = load_cover(args.input)
                total = f5_capacity_from_png(image)
                if total < 13:
                    raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
                print(f"Pojemność F5: {total} B ramki; {total - 13} B tekstu UTF-8 (po odjęciu nagłówka 13 B).")
                return 0
            if method_command == "extract":
                frame = f5_extract_jpeg(args.input, key=args.key)
                total = f5_capacity_from_jpeg(args.input)
                text = unpack(frame, capacity_bytes=total)
                print(f"Pojemność F5: {total} B ramki; {max(0, total - 13)} B tekstu UTF-8 (po odjęciu nagłówka 13 B).", file=sys.stderr)
                if args.output is not None:
                    _save_text(text, args.output, overwrite=args.overwrite)
                else:
                    sys.stdout.write(text)
                return 0
            image = load_cover(args.input)
            total = f5_capacity_from_png(image)
            if Path(args.output).suffix.lower() not in {".jpg", ".jpeg"}:
                raise ImageError("Obraz wynikowy musi mieć rozszerzenie .jpg lub .jpeg")
            if total < 13:
                raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
            print(f"Pojemność F5: {total} B ramki; {total - 13} B tekstu UTF-8 (po odjęciu nagłówka 13 B).", file=sys.stderr)
            text = _read_text(args.text_file, total - 13) if args.text_file is not None else args.text
            frame = pack(text, capacity_bytes=total)
            f5_embed_jpeg(args.input, args.output, frame, key=args.key, overwrite=args.overwrite)
            print(f"Zapisano JPEG: {args.output}", file=sys.stderr)
        elif args.command in {"jsteg", "jsteg-mf"}:
            is_mf = args.command == "jsteg-mf"
            label = "JSteg-MF" if is_mf else "JSteg"
            if method_command == "capacity":
                image = load_cover(args.input)
                total = jsteg_png_jpeg_capacity_bytes(image, mf=is_mf)
                if total < 13:
                    raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
                print(f"Pojemność {label}: {total} B ramki; {total - 13} B tekstu UTF-8 (po odjęciu nagłówka 13 B).")
                return 0
            if method_command == "extract":
                frame = jsteg_extract_jpeg(args.input, mf=is_mf)
                total = jsteg_jpeg_capacity_bytes(args.input, mf=is_mf)
                text = unpack(frame, capacity_bytes=total)
                print(f"Pojemność {label}: {total} B ramki; {max(0, total - 13)} B tekstu UTF-8 (po odjęciu nagłówka 13 B).", file=sys.stderr)
                if args.output is not None:
                    _save_text(text, args.output, overwrite=args.overwrite)
                else:
                    sys.stdout.write(text)
                return 0
            image = load_cover(args.input)
            total = jsteg_png_jpeg_capacity_bytes(image, mf=is_mf)
            if Path(args.output).suffix.lower() not in {".jpg", ".jpeg"}:
                raise ImageError("Obraz wynikowy musi mieć rozszerzenie .jpg lub .jpeg")
            if Path(args.input).resolve() == Path(args.output).resolve():
                raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
            if total < 13:
                raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
            print(f"Pojemność {label}: {total} B ramki; {total - 13} B tekstu UTF-8 (po odjęciu nagłówka 13 B).", file=sys.stderr)
            text = (
                _read_text(args.text_file, total - 13)
                if args.text_file is not None else args.text
            )
            frame = pack(text, capacity_bytes=total)
            jsteg_embed_jpeg(args.input, args.output, frame, mf=is_mf, overwrite=args.overwrite)
            print(f"Zapisano JPEG: {args.output}", file=sys.stderr)
        elif args.command == "extract":
            image = load_stego(args.input)
            try:
                frame = extract_frame(image)
                text = unpack(frame, capacity_bytes=capacity_bytes(image))
            except FrameError as exc:
                raise FrameError(f"niepoprawna ramka STEG: {str(exc).lower()}") from exc
            print(_capacity_message(image), file=sys.stderr)
            if args.output is not None:
                _save_text(text, args.output, overwrite=args.overwrite)
                print(f"Zapisano tekst UTF-8: {args.output}", file=sys.stderr)
            else:
                sys.stdout.write(text)
        else:
            if args.command == "jpeg":
                if args.command != "capacity" and Path(args.input).resolve() == Path(args.output).resolve():
                    raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
                png_to_jpeg(args.input, args.output, overwrite=args.overwrite)
                print(f"Zapisano JPEG: {args.output}", file=sys.stderr)
                return 0
            if args.command != "capacity" and Path(args.input).resolve() == Path(args.output).resolve():
                raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
            image = load_cover(args.input)
            message = _capacity_message(image)
            if args.command == "capacity":
                print(message)
                return 0
            print(message, file=sys.stderr)
            text = (
                _read_text(args.text_file, payload_capacity_bytes(image))
                if args.text_file is not None else args.text
            )
            frame = pack(text, capacity_bytes=capacity_bytes(image))
            save_png(embed_frame(image, frame), args.output, overwrite=args.overwrite)
            print(f"Zapisano PNG: {args.output}", file=sys.stderr)
    except (FrameError, ImageError, OSError, UnicodeError, ValueError) as exc:
        message = str(exc)
        if isinstance(exc, FileExistsError) or isinstance(exc.__cause__, FileExistsError):
            message = (
                f"Plik '{args.output}' już istnieje; "
                "wybierz nową nazwę lub jawnie podaj --force"
            )
        print(f"Błąd: {message}", file=sys.stderr)
        return 1
    return 0
