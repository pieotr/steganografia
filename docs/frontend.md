# Frontend i Flask

Aplikacja frontendowa z katalogu `steganography-frontend` jest teraz serwowana przez ten sam proces Flask, co API.

## Uruchomienie

Z katalogu repozytorium:

```sh
python -m pip install -e .
steganografia-api --host 0.0.0.0 --port 5000
```

Lub bez instalacji:

```sh
python -m steganografia.server --host 0.0.0.0 --port 5000
```

## Adresy

- Frontend: http://localhost:5000/
- Swagger: http://localhost:5000/api/v1/swagger
- OpenAPI: http://localhost:5000/api/v1/openapi.json
- API: http://localhost:5000/api/v1/*

## Uwagi

- Strona główna ładuje pliki statyczne z pakietu: `src/steganografia/static/`.
- W razie potrzeby projekt zachowuje kompatybilność z wcześniejszym katalogiem zewnętrznym, ale domyślna ścieżka frontendowa to katalog pakietu.
- Prawdziwe endpointy API nie kolidują z plikami frontendowymi, ponieważ są pod ścieżkami zaczynającymi się od `/api/v1`.
- Możesz zmienić port przez `--port` albo zmienną środowiskową `PORT`.
