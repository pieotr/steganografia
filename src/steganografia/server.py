"""Dynamiczne Flask API dla wszystkich metod z METHOD_REGISTRY.

Dostępne endpointy:
- /api/v1/health
- /api/v1/lsb/capacity
- /api/v1/lsb/embed
- /api/v1/lsb/extract
- /api/v1/jsteg/capacity
- /api/v1/jsteg/embed
- /api/v1/jsteg/extract
- /api/v1/jsteg-mf/capacity
- /api/v1/jsteg-mf/embed
- /api/v1/jsteg-mf/extract
- /api/v1/f5/capacity
- /api/v1/f5/embed
- /api/v1/f5/extract
- /api/v1/outguess/capacity
- /api/v1/outguess/embed
- /api/v1/outguess/extract
- /api/v1/nsf5/capacity
- /api/v1/nsf5/embed
- /api/v1/nsf5/extract
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
from werkzeug.exceptions import BadRequest, HTTPException, MethodNotAllowed

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
    error_schema = {
        "type": "object",
        "properties": {
            "error": {"type": "string", "description": "Opis błędu"},
            "status": {"type": "string", "enum": ["error"]},
        },
        "required": ["error", "status"],
    }
    standard_error_responses = {
        "400": {
            "description": "Nieprawidłowe dane wejściowe lub nieobsługiwany format pliku",
            "content": {"application/json": {"schema": error_schema}},
        },
        "413": {
            "description": "Przekroczono limit 64 MB zawartości żądania",
            "content": {"application/json": {"schema": error_schema}},
        },
        "404": {
            "description": "Nie znaleziono zasobu lub metody",
            "content": {"application/json": {"schema": error_schema}},
        },
        "405": {
            "description": "Nieobsługiwana metoda HTTP",
            "content": {"application/json": {"schema": error_schema}},
        },
        "500": {
            "description": "Wewnętrzny błąd serwera",
            "content": {"application/json": {"schema": error_schema}},
        },
    }
    health_error_responses = {
        "500": standard_error_responses["500"],
    }

    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "summary": "Stan serwera",
                "responses": {
                    "200": {
                        "description": "Serwer działa",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "enum": ["ok"]},
                                        "service": {"type": "string"},
                                        "methods": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["status", "service", "methods"],
                                }
                            }
                        },
                    },
                    **health_error_responses,
                },
            }
        },
        "/openapi.json": {
            "get": {
                "summary": "Specyfikacja OpenAPI",
                "responses": {
                    "200": {
                        "description": "Dynamiczna specyfikacja OpenAPI",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    **health_error_responses,
                },
            }
        },
        "/swagger": {
            "get": {
                "summary": "Interfejs Swagger UI",
                "responses": {
                    "200": {
                        "description": "Strona HTML Swagger UI",
                        "content": {"text/html": {"schema": {"type": "string"}}},
                    },
                    **health_error_responses,
                },
            }
        },
    }

    for name in METHOD_REGISTRY.names():
        metadata = METHOD_REGISTRY.get(name).metadata
        label = metadata.label
        input_formats = tuple(metadata.input_formats)
        output_format = metadata.output_format
        input_description = (
            "Jeden z obsługiwanych formatów: " + ", ".join(fmt.upper() for fmt in input_formats)
            if input_formats
            else "Obsługiwany format obrazu"
        )

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
                "description": input_description,
            }
        }

        for operation in ("capacity", "embed", "extract"):
            properties = {
                "file": dict(base_file_properties["file"])
            }
            if operation == "extract":
                properties["file"]["description"] = (
                    f"Obraz wynikowy {output_format.upper()}"
                )
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
                success_schema = {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "enum": [name]},
                        "format": {"type": "string", "enum": [fmt.upper() for fmt in input_formats]},
                        "output_format": {"type": "string", "enum": [output_format.upper()]},
                        "capacity_bytes": {"type": "integer", "minimum": 0},
                        "payload_capacity_bytes": {"type": "integer", "minimum": 0},
                    },
                    "required": ["method", "format", "output_format", "capacity_bytes", "payload_capacity_bytes"],
                }
            elif operation == "embed":
                summary = f"Osadź tekst metodą {label}"
                response_description = f"Obraz {output_format.upper()} zakodowany w base64"
                success_schema = {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean", "enum": [True]},
                        "method": {"type": "string", "enum": [name]},
                        "format": {"type": "string", "enum": [output_format.upper()]},
                        "image_base64": {"type": "string", "format": "byte"},
                        "payload_length_chars": {"type": "integer", "minimum": 0},
                    },
                    "required": [
                        "success",
                        "method",
                        "format",
                        "image_base64",
                        "payload_length_chars",
                    ],
                }
            else:
                summary = f"Odczytaj tekst metodą {label}"
                response_description = "Tekst odzyskany z obrazu"
                success_schema = {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean", "enum": [True]},
                        "method": {"type": "string", "enum": [name]},
                        "text": {"type": "string"},
                        "length_chars": {"type": "integer", "minimum": 0},
                        "encoding": {"type": "string", "enum": ["utf-8"]},
                    },
                    "required": ["success", "method", "text", "length_chars", "encoding"],
                }

            # Formaty obrazów dla frontendu: embed/capacity przyjmują format
            # wejściowy metody, extract przyjmuje jej format wynikowy.
            operation_input = (
                output_format if operation == "extract" else (input_formats[0] if input_formats else output_format)
            )
            paths[f"/{name}/{operation}"] = {
                "post": {
                    "summary": summary,
                    "x-steganography": {
                        "input_format": operation_input.upper(),
                        "output_format": output_format.upper(),
                    },
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
                    "responses": {
                        "200": {
                            "description": response_description,
                            "content": {
                                "application/json": {"schema": success_schema}
                            },
                        },
                        **standard_error_responses,
                    },
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


def _read_method_input(uploaded_file, image_format: str) -> bytes:
    """Wczytaj przesłany obraz zgodnie z formatem z metadanych metody."""
    normalized_format = image_format.lower()
    if normalized_format in {"png"}:
        return read_png_bytes(uploaded_file)
    if normalized_format in {"jpg", "jpeg"}:
        return read_jpeg_bytes(uploaded_file)
    raise BadRequest(f"Nieobsługiwany format obrazu wejściowego: {image_format}.")


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

    @app.errorhandler(404)
    def handle_not_found(exc):
        return _json_error("Nie znaleziono zasobu.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return _json_error("Nieobsługiwana metoda HTTP.", 405)

    @app.errorhandler(413)
    def handle_request_too_large(exc):
        return _json_error("Przekroczono limit rozmiaru żądania.", 413)

    @app.errorhandler(500)
    def handle_internal_error(exc):
        return _json_error("Wewnętrzny błąd serwera.", 500)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        return _json_error(exc.description, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        app.logger.exception("Nieoczekiwany błąd API", exc_info=exc)
        return _json_error("Wewnętrzny błąd serwera.", 500)

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
        input_format = (
            method.metadata.input_formats[0]
            if method.metadata.input_formats
            else "png"
        )
        output_format = method.metadata.output_format
        route_prefix = f"/api/v1/{method_name}"

        for operation_name in ("capacity", "embed", "extract"):
            unsupported_path = f"{route_prefix}/{operation_name}"

            @app.route(
                unsupported_path,
                methods=["GET", "PUT", "PATCH", "DELETE"],
                endpoint=f"{method_name}_{operation_name}_unsupported",
            )
            def unsupported_method(operation_name=operation_name):
                raise MethodNotAllowed(
                    valid_methods=["POST"],
                    description=f"Endpoint wymaga metody POST; operacja {operation_name} nie jest dostępna metodą HTTP żądania.",
                )

        @app.post(f"{route_prefix}/capacity", endpoint=f"{method_name}_capacity")
        def capacity(method=method, method_name=method_name):
            cover = _read_method_input(request.files.get("file"), input_format)
            stats = method.capacity_bytes(cover, **_method_options(method))
            return jsonify({
                "method": method_name,
                "format": input_format.upper(),
                "output_format": output_format.upper(),
                "capacity_bytes": stats["capacity_bytes"],
                "payload_capacity_bytes": stats["payload_capacity_bytes"],
            })

        @app.post(f"/api/v1/{method_name}/embed", endpoint=f"{method_name}_embed")
        def embed(method=method, method_name=method_name):
            text = request.form.get("text")
            if text is None:
                raise BadRequest("Brakuje pola 'text'.")
            cover = _read_method_input(request.files.get("file"), input_format)
            encoded = method.embed_bytes(cover, text, **_method_options(method))
            return jsonify({
                "success": True,
                "method": method_name,
                "format": output_format.upper(),
                "image_base64": base64.b64encode(encoded.data).decode("ascii"),
                "payload_length_chars": len(text),
            })

        @app.post(f"/api/v1/{method_name}/extract", endpoint=f"{method_name}_extract")
        def extract(method=method, method_name=method_name):
            uploaded_file = request.files.get("file")
            if uploaded_file is None:
                raise BadRequest("Brakuje pola 'file'.")
            encoded = _read_method_input(uploaded_file, output_format)
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
