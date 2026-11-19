"""Dynamiczne Flask API dla wszystkich metod z METHOD_REGISTRY.

Dostępne endpointy:
- /api/v1/health
- /api/v1/lsb/capacity
- /api/v1/lsb/embed
- /api/v1/lsb/extract
- /api/v1/dct/capacity
- /api/v1/dct/embed
- /api/v1/dct/extract
- /api/v1/jsteg-mf/capacity
- /api/v1/jsteg-mf/embed
- /api/v1/jsteg-mf/extract
- /api/v1/f5/capacity
- /api/v1/f5/embed
- /api/v1/f5/extract
- /api/v1/openapi.json
- /api/v1/swagger
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import BadRequest

from .api import (
    METHOD_REGISTRY,
    read_jpeg_bytes,
    read_png_bytes,
)


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


def build_openapi_spec() -> dict[str, Any]:
    """Generuj specyfikację OpenAPI bezpośrednio z METHOD_REGISTRY."""
    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "summary": "Stan serwera",
                "responses": {"200": {"description": "Serwer działa"}},
            }
        }
    }

    for name in METHOD_REGISTRY.names():
        metadata = METHOD_REGISTRY.get(name).metadata
        label = metadata.label
        input_format = metadata.input_formats[0] if metadata.input_formats else "png"
        output_format = metadata.output_format

        option_properties: dict[str, Any] = {}
        for option_name, option in metadata.options.items():
            option_properties[option_name] = {
                "type": option.get("type", "string"),
                "default": option.get("default"),
            }

        base_file_properties = {
            "file": {
                "type": "string",
                "format": "binary",
                "description": f"Obraz wejściowy {input_format.upper()}",
            }
        }

        for operation in ("capacity", "embed", "extract"):
            properties = dict(base_file_properties)
            if operation == "embed":
                properties["text"] = {
                    "type": "string",
                    "description": "Tekst UTF-8 do ukrycia",
                }
            properties.update(option_properties)
            required = ["file", "text"] if operation == "embed" else ["file"]

            if operation == "capacity":
                summary = f"Pojemność obrazu dla {label}"
                response_description = "Pojemność w bajtach"
            elif operation == "embed":
                summary = f"Osadź tekst metodą {label}"
                response_description = f"Obraz {output_format.upper()} zakodowany w base64"
            else:
                summary = f"Odczytaj tekst metodą {label}"
                response_description = "Tekst odzyskany z obrazu"

            paths[f"/{name}/{operation}"] = {
                "post": {
                    "summary": summary,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": properties,
                                    "required": required,
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": response_description}},
                }
            }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Steganografia API",
            "version": "1.0.0",
            "description": "Dynamiczne API steganografii generowane z METHOD_REGISTRY.",
        },
        "servers": [{"url": "/api/v1", "description": "Wewnętrzny serwer API"}],
        "paths": paths,
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
        return jsonify(build_openapi_spec())

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

    def _method_options(method) -> dict[str, Any]:
        options: dict[str, Any] = {}
        for option_name, option in method.metadata.options.items():
            value = request.form.get(option_name)
            if value is not None:
                options[option_name] = value
        return options

    def _register_method_routes(method_name: str) -> None:
        method = _resolve_method(method_name)

        @app.post(f"/api/v1/{method_name}/capacity", endpoint=f"{method_name}_capacity")
        def capacity(method=method, method_name=method_name):
            cover = read_png_bytes(request.files.get("file"))
            stats = method.capacity_bytes(cover, **_method_options(method))
            return jsonify({
                "method": method_name,
                "format": "PNG",
                "output_format": method.metadata.output_format.upper(),
                "capacity_bytes": stats["capacity_bytes"],
                "payload_capacity_bytes": stats["payload_capacity_bytes"],
            })

        @app.post(f"/api/v1/{method_name}/embed", endpoint=f"{method_name}_embed")
        def embed(method=method, method_name=method_name):
            text = request.form.get("text")
            if text is None:
                raise BadRequest("Brakuje pola 'text'.")
            cover = read_png_bytes(request.files.get("file"))
            encoded = method.embed_bytes(cover, text, **_method_options(method))
            return jsonify({
                "success": True,
                "method": method_name,
                "format": encoded.extension.lstrip(".").upper(),
                "image_base64": base64.b64encode(encoded.data).decode("ascii"),
                "payload_length_chars": len(text),
            })

        @app.post(f"/api/v1/{method_name}/extract", endpoint=f"{method_name}_extract")
        def extract(method=method, method_name=method_name):
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise BadRequest("Brakuje pola 'file'.")
            if method.metadata.output_format == "png":
                encoded = read_png_bytes(uploaded_file)
            else:
                encoded = read_jpeg_bytes(uploaded_file)
            text = method.extract_bytes(encoded, **_method_options(method))
            return jsonify({
                "success": True,
                "method": method_name,
                "text": text,
                "length_chars": len(text),
                "encoding": "utf-8",
            })

    for registered_method_name in METHOD_REGISTRY.names():
        _register_method_routes(registered_method_name)

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
