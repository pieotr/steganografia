"""Komendy LSB łączące ramkę STEG v1 z odczytem i zapisem PNG."""

import argparse
from collections.abc import Sequence
import sys

from .frame import FrameError, pack, unpack
from .images import ImageError, load_cover, load_stego, save_png
from .lsb import capacity_bytes, embed_frame, extract_frame, payload_capacity_bytes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steganografia",
        description="Ukrywanie tekstu UTF-8 w PNG metodą LSB i jego odczyt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Przykład: steganografia embed oryginal.png wynik.png --text "Cześć!"\n'
            "Drugi argument (wynik.png) wskazuje miejsce zapisu wynikowego PNG;\n"
            "ścieżka względna jest liczona od bieżącego katalogu terminala.\n"
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
            "Istniejący plik można nadpisać wyłącznie z --overwrite."
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
    embed.add_argument("--text", required=True, metavar="TEKST", help="wiadomość UTF-8, także pusty tekst")
    embed.add_argument(
        "--overwrite", action="store_true",
        help="jawnie zezwól na nadpisanie istniejącego pliku wynikowego",
    )

    extract = commands.add_parser("extract", help="odczytaj tekst z wynikowego PNG")
    extract.add_argument("input", metavar="WEJŚCIE", help="8-bitowy RGB PNG z ramką STEG v1")

    capacity = commands.add_parser("capacity", help="pokaż pojemność PNG przed osadzaniem")
    capacity.add_argument("input", metavar="WEJŚCIE", help="statyczny PNG do osadzania")
    return parser


def _capacity_message(image) -> str:
    return (
        f"Pojemność: {capacity_bytes(image)} B ramki; "
        f"{payload_capacity_bytes(image)} B tekstu UTF-8 "
        "(po odjęciu nagłówka 13 B)."
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Uruchom CLI; kod 0 oznacza sukces, 1 błąd danych/pliku, 2 błąd składni."""
    args = _parser().parse_args(argv)
    try:
        if args.command == "extract":
            image = load_stego(args.input)
            try:
                frame = extract_frame(image)
                text = unpack(frame, capacity_bytes=capacity_bytes(image))
            except FrameError as exc:
                raise FrameError(f"Niepoprawna ramka STEG: {exc}") from exc
            print(_capacity_message(image), file=sys.stderr)
            # Bez dodawania końca wiersza: przekierowanie zachowuje dokładny tekst.
            sys.stdout.write(text)
        else:
            image = load_cover(args.input)
            message = _capacity_message(image)
            if args.command == "capacity":
                print(message)
                return 0
            print(message, file=sys.stderr)
            frame = pack(args.text, capacity_bytes=capacity_bytes(image))
            save_png(embed_frame(image, frame), args.output, overwrite=args.overwrite)
            print(f"Zapisano PNG: {args.output}", file=sys.stderr)
    except (FrameError, ImageError, OSError, UnicodeError) as exc:
        message = str(exc)
        if args.command == "embed" and isinstance(exc.__cause__, FileExistsError):
            message = (
                f"Plik '{args.output}' już istnieje; "
                "wybierz nową nazwę lub jawnie podaj --overwrite"
            )
        print(f"Błąd: {message}", file=sys.stderr)
        return 1
    return 0
