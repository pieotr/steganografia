# API Flask dla steganografii

Serwer Flask jest przygotowany do pracy z frontendem i obsługuje metody LSB oraz DCT. DCT wykonuje osadzanie w niezerowych, skwantyzowanych współczynnikach AC luminancji i zwraca wynikowy obraz JPEG.

## Uruchomienie

```sh
python -m pip install -e .
steganografia-api
```

Serwer domyślnie nasłuchuje na `http://localhost:5000`.

## Dokumentacja Swagger

- Swagger UI: `http://localhost:5000/api/v1/swagger`
- Specyfikacja OpenAPI: `http://localhost:5000/api/v1/openapi.json`

## Endpointy

### GET /api/v1/health

Sprawdzenie statusu usługi.

Przykład odpowiedzi:

```json
{
  "status": "ok",
  "service": "steganografia",
  "methods": ["dct", "f5", "jsteg", "jsteg-mf", "lsb"]
}
```

### POST /api/v1/lsb/capacity

Wczytuje obraz PNG z formularza multipart i zwraca pojemność dla metody LSB.

Pole formularza:

- `file`: plik PNG

Przykład `curl`:

```sh
curl -X POST http://localhost:5000/api/v1/lsb/capacity \
  -F "file=@oryginal.png"
```

Przykład odpowiedzi:

```json
{
  "method": "lsb",
  "format": "PNG",
  "capacity_bytes": 1250,
  "payload_capacity_bytes": 1237,
  "image_shape": [256, 256, 3]
}
```

### POST /api/v1/lsb/embed

Osadza tekst UTF-8 w obrazie PNG za pomocą LSB.

Pola formularza:

- `file`: plik PNG wejściowy,
- `text`: tekst do ukrycia.

Przykład `curl`:

```sh
curl -X POST http://localhost:5000/api/v1/lsb/embed \
  -F "file=@oryginal.png" \
  -F "text=Cześć od frontendowca!"
```

Przykład odpowiedzi:

```json
{
  "success": true,
  "method": "lsb",
  "format": "PNG",
  "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "image_shape": [256, 256, 3],
  "payload_length_chars": 25
}
```

`image_base64` zawiera wynikowy obraz PNG zakodowany w formacie base64. Frontend może od razu zapisać go jako plik lub wysłać dalej do przeglądarki.

### POST /api/v1/lsb/extract

Odczytuje ukryty tekst z obrazu PNG.

Pole formularza:

- `file`: plik PNG ze stego-obrazem

Przykład `curl`:

```sh
curl -X POST http://localhost:5000/api/v1/lsb/extract \
  -F "file=@stego.png"
```

Przykład odpowiedzi:

```json
{
  "success": true,
  "method": "lsb",
  "text": "Cześć od frontendowca!",
  "length_chars": 25,
  "encoding": "utf-8"
}
```

### POST /api/v1/dct/capacity

Wczytuje obraz PNG i zwraca pojemność dla metody DCT. Pojemność obejmuje 13-bajtowy nagłówek ramki.

```sh
curl -X POST http://localhost:5000/api/v1/dct/capacity \
  -F "file=@oryginal.png"
```

Odpowiedź zawiera `capacity_bytes`, `payload_capacity_bytes`, `format: "PNG"` oraz `output_format: "JPEG"`.

### POST /api/v1/dct/embed

Osadza tekst UTF-8 w obrazie PNG metodą DCT. Wynik jest obrazem JPEG zakodowanym w `image_base64`.

```sh
curl -X POST http://localhost:5000/api/v1/dct/embed \
  -F "file=@oryginal.png" \
  -F "text=Cześć metodą DCT!"
```

### POST /api/v1/dct/extract

Odczytuje tekst z wynikowego obrazu JPEG.

```sh
curl -X POST http://localhost:5000/api/v1/dct/extract \
  -F "file=@stego.jpg"
```

Odpowiedź ma taki sam format jak dla LSB: `text`, `length_chars` i `encoding`.

## Architektura rozszerzalna

Warstwa `steganografia.api` wykorzystuje wzorzec metody steganograficznej:

- `SteganographyMethod` — wspólny kontrakt dla metod,
- `SteganographyRegistry` — rejestr metod,
- `METHOD_REGISTRY` — globalna lista dostępnych algorytmów.

DCT jest zarejestrowane w `METHOD_REGISTRY` jako metoda `dct`; endpointy używają kontraktu bajtowego `capacity_bytes`, `embed_bytes` i `extract_bytes`.

## Uwagi integracyjne

- LSB przyjmuje i zwraca PNG. DCT przyjmuje PNG podczas osadzania, a zwraca i odczytuje JPEG.
- Żądania są form-data, więc frontend może wysyłać plik bezpośrednio z formularza.
- Odpowiedzi API są w formacie JSON, z wyjątkiem wygenerowanego obrazu, który jest zwracany jako `image_base64`.
- Endpointy są nazwane według metody (`lsb`, `dct`), a DCT korzysta z 13-bajtowej ramki STEG v1.
