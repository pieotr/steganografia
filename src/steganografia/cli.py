"""Komendy LSB oraz konwersja PNG do JPEG z własnym pipeline'em DCT."""

import argparse
from collections.abc import Sequence
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional

from .frame import FrameError, pack, pack_bytes, unpack, unpack_bytes
from .api import METHOD_REGISTRY
from .disturb import run_disturb_experiments
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
        description="Ukrywanie tekstu lub plików w obrazach metodą LSB i innymi metodami.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Przykład: steganografia embed oryginal.png wynik.png --text "Cześć!"\n'
            "Drugi argument (wynik.png) wskazuje miejsce zapisu wynikowego PNG;\n"
            "ścieżka względna jest liczona od bieżącego katalogu terminala.\n"
            "Tekst z TXT: embed oryginal.png wynik.png --text-file wiadomosc.txt\n"
            "Plik binarny: embed oryginal.png wynik.png --payload-file dokument.pdf\n"
            "Odzyskaj plik: extract wynik.png --output-file odzyskany.pdf\n"
            "Szczegóły: steganografia embed --help"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, title="komendy")

    embed = commands.add_parser(
        "embed",
        help="ukryj tekst lub plik i zapisz wynikowy PNG",
        description=(
            "Ukryj tekst lub plik w obrazie wejściowym i zapisz wynikowy PNG pod ścieżką "
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
    source.add_argument(
        "--payload-file", metavar="PLIK",
        help="ukryj dokładne bajty dowolnego pliku",
    )
    embed.add_argument(
        "--force", "--overwrite", dest="overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie istniejącego pliku wynikowego",
    )

    extract = commands.add_parser("extract", help="odczytaj tekst lub plik z wynikowego PNG")
    extract.add_argument("input", metavar="WEJŚCIE", help="8-bitowy RGB PNG z ramką STEG v1")
    extract_output = extract.add_mutually_exclusive_group()
    extract_output.add_argument(
        "-o", "--output", metavar="PLIK.txt",
        help="zapisz tekst UTF-8 do pliku; domyślnie tekst trafia na stdout",
    )
    extract_output.add_argument(
        "--output-file", metavar="PLIK",
        help="zapisz dokładne bajty payloadu do pliku zamiast odczytu tekstowego",
    )
    extract.add_argument(
        "--force", "--overwrite", dest="overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie pliku wskazanego przez --output lub --output-file",
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

    disturb = commands.add_parser(
        "disturb",
        help="uruchom eksperymenty zakłóceń (JPEG, szum, skalowanie) dla wszystkich metod i zapisz CSV",
    )
    disturb.add_argument("input", metavar="WEJŚCIE", help="statyczny PNG źródłowy")
    disturb.add_argument(
        "output_dir",
        metavar="KATALOG_WYJŚCIOWY",
        help="katalog zapisu obrazów po zakłóceniach oraz raportu disturb_report.csv",
    )
    disturb.add_argument(
        "--text",
        default="Kontrolny payload S4 — Zażółć gęślą jaźń",
        help="wiadomość testowa do osadzenia przed zakłóceniami",
    )
    disturb.add_argument(
        "--seed",
        type=int,
        default=42,
        help="ziarno generatora losowego dla szumu Gaussa (domyślnie: 42)",
    )

    for metadata in METHOD_REGISTRY.metadata():
        method = metadata["name"]
        help_text = metadata["label"]
        method_parser = commands.add_parser(
            method,
            help=f"osadzaj lub odczytuj tekst i pliki metodą {help_text}",
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
            "embed", help=f"osadź tekst lub plik metodą {help_text}"
        )
        method_embed.add_argument("input", metavar="WEJŚCIE", help="obraz RGB")
        method_embed.add_argument("output", metavar="WYJŚCIE", help="wynikowy obraz")
        method_source = method_embed.add_mutually_exclusive_group(required=True)
        method_source.add_argument("--text", metavar="TEKST")
        method_source.add_argument("--text-file", metavar="PLIK.txt")
        method_source.add_argument(
            "--payload-file", metavar="PLIK",
            help="ukryj dokładne bajty dowolnego pliku zamiast tekstu",
        )
        method_embed.add_argument(
            "--force", "--overwrite", dest="overwrite", action="store_true"
        )
        for option_name, schema in metadata["options"].items():
            method_embed.add_argument(
                f"--{option_name.replace('_', '-')}",
                default=schema.get("default"),
                help=f"opcja {option_name} (domyślnie: {schema.get('default')})",
            )
        method_extract = method_commands.add_parser(
            "extract", help=f"odczytaj tekst lub plik metodą {help_text}"
        )
        method_extract.add_argument("input", metavar="WEJŚCIE", help="obraz z ukrytą wiadomością")
        method_extract_output = method_extract.add_mutually_exclusive_group()
        method_extract_output.add_argument("-o", "--output", metavar="PLIK.txt")
        method_extract_output.add_argument(
            "--output-file", metavar="PLIK",
            help="zapisz dokładne bajty payloadu do pliku zamiast odczytu tekstowego",
        )
        method_extract.add_argument(
            "--force", "--overwrite", dest="overwrite", action="store_true"
        )
        for option_name, schema in metadata["options"].items():
            method_extract.add_argument(
                f"--{option_name.replace('_', '-')}",
                default=schema.get("default"),
                help=f"opcja {option_name} (domyślnie: {schema.get('default')})",
            )
    return parser


def _capacity_message(image) -> str:
    return (
        f"Pojemność: {capacity_bytes(image)} B ramki; "
        f"{payload_capacity_bytes(image)} B payloadu (tekst UTF-8 lub bajty pliku) "
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


def _read_payload_file(path: str, limit: int) -> bytes:
    with open(path, "rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        print(f"Rozmiar pliku payloadu: {size} B ({path}).", file=sys.stderr)
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise FrameError(
            f"plik payloadu przekracza pojemność obrazu: maksymalnie {limit} B"
        )
    return payload


def _save_bytes(data: bytes, path: str, *, overwrite: bool) -> None:
    """Zapisz bajty atomowo, nie nadpisując istniejącego pliku bez zgody."""
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if overwrite:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _save_text(text: str, path: str, *, overwrite: bool) -> None:
    """Zapisz dokładne bajty UTF-8; opublikuj plik dopiero po pełnym zapisie."""
    _save_bytes(text.encode("utf-8"), path, overwrite=overwrite)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Uruchom CLI; kod 0 oznacza sukces, 1 błąd danych/pliku, 2 błąd składni."""
    parser = _parser()
    args = parser.parse_args(argv)
    args.overwrite = bool(getattr(args, "overwrite", False))
    method_command = (
        getattr(args, f"{args.command.replace('-', '_')}_command", None)
        if args.command in METHOD_REGISTRY.names()
        else None
    )
    if (
        args.command in METHOD_REGISTRY.names()
        and method_command == "extract"
        and args.overwrite
        and args.output is None
        and args.output_file is None
    ):
        parser.error("--force wymaga --output lub --output-file")
    if (
        args.command == "extract"
        and args.overwrite
        and args.output is None
        and args.output_file is None
    ):
        parser.error("--force wymaga --output lub --output-file")
    try:
        if args.command in METHOD_REGISTRY.names():
            method = METHOD_REGISTRY.get(args.command)
            operation = method_command
            options = {
                name: getattr(args, name)
                for name in method.metadata.options
                if getattr(args, name, None) is not None
            }
            if operation == "capacity":
                stats = method.capacity_bytes(Path(args.input).read_bytes(), **options)
                total = stats["capacity_bytes"]
                if total < 13:
                    raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
                print(
                    f"Pojemność {method.metadata.label}: {total} B ramki; "
                    f"{stats.get('payload_capacity_bytes', max(0, total - 13))} B payloadu "
                    "(tekst UTF-8 lub bajty pliku)."
                )
                return 0
            if operation == "extract":
                encoded = Path(args.input).read_bytes()
                if args.output_file is not None:
                    if Path(args.input).resolve() == Path(args.output_file).resolve():
                        raise ImageError("Plik wejściowy i wyjściowy muszą się różnić")
                    try:
                        payload = method.extract_payload_bytes(encoded, **options)
                    except FrameError as exc:
                        raise FrameError(f"niepoprawna ramka STEG: {str(exc).lower()}") from exc
                    _save_bytes(payload, args.output_file, overwrite=args.overwrite)
                    print(f"Zapisano plik: {args.output_file}", file=sys.stderr)
                    return 0
                try:
                    text = method.extract_bytes(encoded, **options)
                except FrameError as exc:
                    raise FrameError(f"niepoprawna ramka STEG: {str(exc).lower()}") from exc
                if args.output is not None:
                    _save_text(text, args.output, overwrite=args.overwrite)
                else:
                    sys.stdout.write(text)
                return 0

            if Path(args.input).resolve() == Path(args.output).resolve():
                raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
            cover = Path(args.input).read_bytes()
            stats = method.capacity_bytes(cover, **options)
            total = stats["capacity_bytes"]
            if total < 13:
                raise FrameError(f"Obraz mieści {total} B; nagłówek wymaga 13 B")
            payload_limit = stats.get("payload_capacity_bytes", max(0, total - 13))
            payload_file = args.payload_file
            if payload_file is not None:
                if Path(payload_file).resolve() == Path(args.output).resolve():
                    raise ImageError("Plik payloadu i wynikowy obraz muszą się różnić")
                payload = _read_payload_file(payload_file, payload_limit)
            else:
                text = (
                    _read_text(args.text_file, payload_limit)
                    if args.text_file is not None
                    else args.text
                )
                if text is None:
                    raise FrameError("Brakuje źródła payloadu.")
                payload = text
            artifact = method.embed_bytes(cover, payload, **options)
            target = Path(args.output)
            allowed_suffixes = (
                {".jpg", ".jpeg"}
                if method.metadata.output_format == "jpeg"
                else {f".{method.metadata.output_format}"}
            )
            if target.suffix.lower() not in allowed_suffixes:
                raise ImageError(
                    f"Obraz wynikowy musi mieć rozszerzenie .{method.metadata.output_format}"
                )
            if target.exists() and not args.overwrite:
                raise ImageError(f"Plik '{target}' już istnieje; wybierz inną nazwę lub --force")
            target.write_bytes(artifact.data)
            print(f"Zapisano {method.metadata.output_format.upper()}: {target}", file=sys.stderr)
            return 0

        elif args.command == "disturb":
            load_cover(args.input)
            csv_path = run_disturb_experiments(
                args.input,
                args.output_dir,
                text=args.text,
                seed=args.seed,
            )
            print(f"Zapisano raport eksperymentów zakłóceń: {csv_path}")
            return 0

        elif args.command == "extract":
            image = load_stego(args.input)
            try:
                frame = extract_frame(image)
                if args.output_file is not None:
                    payload = unpack_bytes(frame, capacity_bytes=capacity_bytes(image))
                else:
                    text = unpack(frame, capacity_bytes=capacity_bytes(image))
            except FrameError as exc:
                raise FrameError(f"niepoprawna ramka STEG: {str(exc).lower()}") from exc
            print(_capacity_message(image), file=sys.stderr)
            if args.output_file is not None:
                if Path(args.input).resolve() == Path(args.output_file).resolve():
                    raise ImageError("Plik wejściowy i wyjściowy muszą się różnić")
                _save_bytes(payload, args.output_file, overwrite=args.overwrite)
                print(f"Zapisano plik: {args.output_file}", file=sys.stderr)
            elif args.output is not None:
                _save_text(text, args.output, overwrite=args.overwrite)
                print(f"Zapisano tekst UTF-8: {args.output}", file=sys.stderr)
            else:
                sys.stdout.write(text)
        else:
            if args.command == "jpeg":
                if Path(args.input).resolve() == Path(args.output).resolve():
                    raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
                png_to_jpeg(args.input, args.output, overwrite=args.overwrite)
                print(f"Zapisano JPEG: {args.output}", file=sys.stderr)
                return 0
            image = load_cover(args.input)
            if args.command == "capacity":
                print(_capacity_message(image))
                return 0
            if Path(args.input).resolve() == Path(args.output).resolve():
                raise ImageError("Plik wejściowy i wynikowy muszą się różnić")
            message = _capacity_message(image)
            print(message, file=sys.stderr)
            payload_file = args.payload_file
            payload_limit = payload_capacity_bytes(image)
            if payload_file is not None:
                if Path(payload_file).resolve() == Path(args.output).resolve():
                    raise ImageError("Plik payloadu i wynikowy obraz muszą się różnić")
                payload = _read_payload_file(payload_file, payload_limit)
                frame = pack_bytes(payload, capacity_bytes=capacity_bytes(image))
            else:
                text = (
                    _read_text(args.text_file, payload_limit)
                    if args.text_file is not None else args.text
                )
                if text is None:
                    raise FrameError("Brakuje źródła payloadu.")
                frame = pack(text, capacity_bytes=capacity_bytes(image))
            save_png(embed_frame(image, frame), args.output, overwrite=args.overwrite)
            print(f"Zapisano PNG: {args.output}", file=sys.stderr)
    except (FrameError, ImageError, OSError, UnicodeError, ValueError) as exc:
        message = str(exc)
        if isinstance(exc, FileExistsError) or isinstance(exc.__cause__, FileExistsError):
            output_path = getattr(args, "output_file", None) or getattr(args, "output", None)
            message = (
                f"Plik '{output_path}' już istnieje; "
                "wybierz nową nazwę lub jawnie podaj --force"
            )
        print(f"Błąd: {message}", file=sys.stderr)
        return 1
    return 0