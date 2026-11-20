# API Flask dla steganografii

Serwer Flask jest przygotowany do pracy z frontendem i generuje routy HTTP oraz dokumentację OpenAPI bezpośrednio z `METHOD_REGISTRY`. Obecnie dostępne są metody LSB, DCT, JSteg, JSteg-MF, F5, OutGuess i nsF5. Metody JPEG wykonują osadzanie w skwantyzowanych współczynnikach AC i zwracają wynikowy obraz JPEG.

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
  "methods": ["f5", "jsteg", "jsteg-mf", "lsb", "nsf5", "outguess"]
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

### POST /api/v1/jsteg/capacity

Wczytuje obraz PNG i zwraca pojemność dla metody JSteg. Pojemność obejmuje 13-bajtowy nagłówek ramki.

```sh
curl -X POST http://localhost:5000/api/v1/jsteg/capacity \
  -F "file=@oryginal.png"
```

Odpowiedź zawiera `capacity_bytes`, `payload_capacity_bytes`, `format: "PNG"` oraz `output_format: "JPEG"`.

### POST /api/v1/jsteg/embed

Osadza tekst UTF-8 w obrazie PNG metodą JSteg (parzystość niezerowych współczynników AC DCT). Wynik jest obrazem JPEG zakodowanym w `image_base64`.

```sh
curl -X POST http://localhost:5000/api/v1/jsteg/embed \
  -F "file=@oryginal.png" \
  -F "text=Cześć metodą JSteg!"
```

### POST /api/v1/jsteg/extract

Odczytuje tekst z wynikowego obrazu JPEG.

```sh
curl -X POST http://localhost:5000/api/v1/jsteg/extract \
  -F "file=@stego.jpg"
```

Odpowiedź ma taki sam format jak dla LSB: `text`, `length_chars` i `encoding`.

### POST /api/v1/jsteg-mf/{capacity,embed,extract}

Endpointy JSteg-MF mają ten sam format żądań i odpowiedzi co endpointy JSteg, ale używają metody `jsteg-mf`.

### POST /api/v1/f5/{capacity,embed,extract}

Endpointy F5 mają ten sam format co endpointy metod JPEG. Endpointy `embed` i `extract` przyjmują opcjonalne pole formularza `key`; jego brak oznacza domyślny klucz `steganografia-f5`.

### POST /api/v1/outguess/{capacity,embed,extract}

Endpointy OutGuess mają format metod JPEG i przyjmują opcjonalne pole formularza `key`.

### POST /api/v1/nsf5/{capacity,embed,extract}

Endpointy nsF5 mają format metod JPEG i przyjmują opcjonalne pole formularza `key`.

## Architektura rozszerzalna

Warstwa `steganografia.api` wykorzystuje wzorzec metody steganograficznej:

- `SteganographyMethod` — wspólny kontrakt dla metod,
- `SteganographyRegistry` — rejestr metod,
- `METHOD_REGISTRY` — globalna lista dostępnych algorytmów.

JSteg jest zarejestrowany w `METHOD_REGISTRY` jako metoda `jsteg`; endpointy używają kontraktu bajtowego `capacity_bytes`, `embed_bytes` i `extract_bytes`.

Materiał prezentacyjny z diagramem UML i przebiegiem działania rejestru:
[UML i rejestr metod](rejestr-metod.md).

## Uwagi integracyjne

- LSB przyjmuje i zwraca PNG. Metody JPEG (np. JSteg) przyjmują PNG podczas osadzania, a zwracają i odczytują JPEG.
- Żądania są form-data, więc frontend może wysyłać plik bezpośrednio z formularza.
- Odpowiedzi API są w formacie JSON, z wyjątkiem wygenerowanego obrazu, który jest zwracany jako `image_base64`.
- Endpointy są nazwane według metody (`lsb`, `jsteg`, `f5`…), a metody JPEG korzystają z 13-bajtowej ramki STEG v1.
- Format wejściowy i wyjściowy każdego endpointu pochodzi z `MethodMetadata.input_formats` oraz `MethodMetadata.output_format` i może być różny dla metod.
- Specyfikacja OpenAPI opisuje kody `200`, `400`, `404`, `405`, `413` i `500` oraz zawiera schematy odpowiedzi błędów `{"error": "...", "status": "error"}`.
