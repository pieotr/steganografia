"""Flask API dla steganografii z przygotowaniem pod rozszerzenia DCT.

Dostępne endpointy:
- /api/v1/health
- /api/v1/lsb/capacity
- /api/v1/lsb/embed
- /api/v1/lsb/extract
- /api/v1/openapi.json
- /api/v1/swagger
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence, Union

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import BadRequest

from .api import METHOD_REGISTRY, image_to_base64, load_png_from_bytes, read_png_bytes


def _resolve_frontend_dir() -> Path:
    packaged = Path(__file__).resolve().parent / "static"
    if packaged.exists():
        return packaged

    candidates = (
        Path(__file__).resolve().parents[3] / "steganography-frontend",
        Path(__file__).resolve().parents[2] / "steganography-frontend",
        Path(__file__).resolve().parents[1] / "steganography-frontend",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return packaged


FRONTEND_DIR = _resolve_frontend_dir()


OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "Steganografia API",
        "version": "1.0.0",
        "description": (
            "API do ukrywania i odczytu danych w obrazach PNG z użyciem "
            "metody LSB. Architektura jest przygotowana pod rozszerzenia o DCT."
        ),
    },
    "servers": [{"url": "/api/v1", "description": "Wewnętrzny serwer API"}],
    "paths": {
        "/health": {
            "get": {
                "summary": "Stan serwera",
                "responses": {"200": {"description": "Serwer działa"}},
            }
        },
        "/lsb/capacity": {
            "post": {
                "summary": "Pojemność obrazu dla LSB",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                },
                                "required": ["file"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Prawidłowa odpowiedź"}},
            }
        },
        "/lsb/embed": {
            "post": {
                "summary": "Osadź tekst w obrazie LSB",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                    "text": {"type": "string", "description": "Tekst UTF-8 do ukrycia"},
                                },
                                "required": ["file", "text"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Obraz z ukrytym tekstem"}},
            }
        },
        "/lsb/extract": {
            "post": {
                "summary": "Odczytaj tekst z obrazu LSB",
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                },
                                "required": ["file"],
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Tekst odzyskany z obrazu"}},
            }
        },
    },
}


def _json_error(message: str, status_code: int = 400):
    response = jsonify({"error": message, "status": "error"})
    response.status_code = status_code
    return response


def _resolve_method(method_name: str):
    try:
        return METHOD_REGISTRY.get(method_name)
    except Exception as exc:  # pragma: no cover - fallback do odpowiedzi HTTP
        raise ValueError(str(exc)) from exc


def create_app(frontend_dir: Optional[Union[str, os.PathLike[str]]] = None) -> Flask:
    """Funkcja fabryki aplikacji Flask. Ułatwia testowanie i uruchamianie."""
    static_dir = Path(frontend_dir) if frontend_dir is not None else FRONTEND_DIR
    app = Flask(__name__, static_folder=str(static_dir), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024
    app.config["JSON_SORT_KEYS"] = False

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(BadRequest)
    def handle_bad_request(exc: BadRequest):
        return _json_error(str(exc.description or "Nieprawidłowe żądanie."), 400)

    @app.errorhandler(ValueError)
    def handle_value_error(exc: ValueError):
        return _json_error(str(exc), 400)

    @app.get("/api/v1/health")
    def health():
        return jsonify({
            "status": "ok",
            "service": "steganografia",
            "methods": METHOD_REGISTRY.names(),
        })

    @app.get("/api/v1/openapi.json")
    def openapi_json():
        return jsonify(OPENAPI_SPEC)

    @app.get("/api/v1/swagger")
    def swagger_ui():
        html = """
        <!doctype html>
        <html lang="pl">
          <head>
            <meta charset="utf-8" />
            <title>Steganografia API</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css" />
            <style>
              body { margin: 0; background: #f7f9fc; }
              #swagger-ui { max-width: 1200px; margin: 20px auto; }
            </style>
          </head>
          <body>
            <div id="swagger-ui"></div>
            <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
            <script>
              window.onload = () => {
                SwaggerUIBundle({
                  url: '/api/v1/openapi.json',
                  dom_id: '#swagger-ui',
                  deepLinking: true,
                  presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SupportedSubmitMethods]
                });
              };
            </script>
          </body>
        </html>
        """
        return html

    @app.post("/api/v1/lsb/capacity")
    def lsb_capacity():
        uploaded_file = request.files.get("file")
        if uploaded_file is None:
            raise BadRequest("Brakuje pola 'file'.")

        image = load_png_from_bytes(read_png_bytes(uploaded_file), mode="cover")
        method = _resolve_method("lsb")
        stats = method.capacity(image)
        return jsonify({
            "method": "lsb",
            "format": "PNG",
            "capacity_bytes": stats["capacity_bytes"],
            "payload_capacity_bytes": stats["payload_capacity_bytes"],
            "image_shape": list(image.shape),
        })

    @app.post("/api/v1/lsb/embed")
    def lsb_embed():
        uploaded_file = request.files.get("file")
        if uploaded_file is None:
            raise BadRequest("Brakuje pola 'file'.")
        text = request.form.get("text")
        if text is None:
            raise BadRequest("Brakuje pola 'text'.")

        image = load_png_from_bytes(read_png_bytes(uploaded_file), mode="cover")
        method = _resolve_method("lsb")
        encoded = method.embed(image, text)
        return jsonify({
            "success": True,
            "method": "lsb",
            "format": "PNG",
            "image_base64": image_to_base64(encoded),
            "image_shape": list(encoded.shape),
            "payload_length_chars": len(text),
        })

    @app.post("/api/v1/lsb/extract")
    def lsb_extract():
        uploaded_file = request.files.get("file")
        if uploaded_file is None:
            raise BadRequest("Brakuje pola 'file'.")

        image = load_png_from_bytes(read_png_bytes(uploaded_file), mode="stego")
        method = _resolve_method("lsb")
        text = method.extract(image)
        return jsonify({
            "success": True,
            "method": "lsb",
            "text": text,
            "length_chars": len(text),
            "encoding": "utf-8",
        })

    return app


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Uruchom serwer deweloperski z opcjonalnym konfigurowaniem hosta, portu i frontendu."""
    parser = argparse.ArgumentParser(description="Uruchom Flask API z zintegrowanym frontendem steganografii.")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"), help="Host nasłuchu (domyślnie 0.0.0.0).")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")), help="Port nasłuchu (domyślnie 5000).")
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=FRONTEND_DIR,
        help="Katalog ze statycznym frontendem do podania przez Flask.",
    )
    parser.add_argument("--debug", action="store_true", help="Włącz debug mode Flask.")
    args = parser.parse_args(argv)

    app = create_app(args.frontend_dir)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
