# UML i przebieg działania rejestru metod

Materiał prezentacyjny opisujący dynamiczne generowanie API i dokumentacji
Swagger/OpenAPI z `METHOD_REGISTRY`.

## Diagram klas
```mermaid
classDiagram
    direction LR

    class SteganographyRegistry {
        -dict _methods
        +register(method)
        +get(name) SteganographyMethod
        +names() list
        +metadata() list
    }

    class SteganographyMethod {
        <<abstract>>
        +name: str
        +metadata: MethodMetadata
        +capacity_bytes(cover, options) dict
        +embed_bytes(cover, payload, options) EncodedArtifact
        +extract_bytes(encoded, options) str
    }

    class MethodMetadata {
        +name: str
        +label: str
        +input_formats: tuple
        +output_format: str
        +options: dict
    }

    class EncodedArtifact {
        +data: bytes
        +media_type: str
        +extension: str
    }

    class LSBMethod
    class JStegMethod
    class JStegMFMethod
    class F5Method
    class OutGuessMethod
    class NSF5Method

    SteganographyRegistry o-- "*" SteganographyMethod : przechowuje
    SteganographyMethod *-- "1" MethodMetadata : posiada
    SteganographyMethod ..> EncodedArtifact : zwraca
    SteganographyMethod <|-- LSBMethod
    SteganographyMethod <|-- JStegMethod
    SteganographyMethod <|-- JStegMFMethod
    SteganographyMethod <|-- F5Method
    SteganographyMethod <|-- OutGuessMethod
    SteganographyMethod <|-- NSF5Method
```

## Jak działa rejestr

![Schemat rejestru metod](assets/rejestr-metod.svg)

Każda implementacja jest jednorazowo rejestrowana w globalnym obiekcie
`METHOD_REGISTRY`. Nazwa metody jest kluczem rejestru, a `MethodMetadata`
opisuje jej formaty wejścia i wyjścia oraz opcje, takie jak `key`.

Serwer Flask nie zawiera osobnych endpointów zapisanych dla każdej metody.
Dla każdej pozycji zwróconej przez `METHOD_REGISTRY.names()` rejestruje
dynamicznie trzy ścieżki:

- `POST /api/v1/{method}/capacity`
- `POST /api/v1/{method}/embed`
- `POST /api/v1/{method}/extract`

## Przepływ żądania HTTP

```mermaid
sequenceDiagram
    actor Klient
    participant Flask as Serwer Flask
    participant Registry as METHOD_REGISTRY
    participant Method as Wybrana metoda
    participant OpenAPI as Generator OpenAPI

    Klient->>Flask: POST /api/v1/{method}/{operacja}
    Flask->>Registry: get(method)
    Registry-->>Flask: obiekt SteganographyMethod

    alt capacity
        Flask->>Method: capacity_bytes(plik, opcje)
        Method-->>Flask: pojemność
    else embed
        Flask->>Method: embed_bytes(plik, tekst, opcje)
        Method-->>Flask: EncodedArtifact
    else extract
        Flask->>Method: extract_bytes(plik, opcje)
        Method-->>Flask: tekst
    end

    Flask-->>Klient: odpowiedź JSON

    Klient->>Flask: GET /api/v1/openapi.json
    Flask->>OpenAPI: build_openapi_spec()
    OpenAPI->>Registry: names() i metadata()
    Registry-->>OpenAPI: metody i metadane
    OpenAPI-->>Flask: kompletna specyfikacja OpenAPI
    Flask-->>Klient: OpenAPI JSON
```

## Rozszerzalność

```mermaid
flowchart TD
    A[Implementacja nowej metody] --> B[Definicja MethodMetadata]
    B --> C[Rejestracja w METHOD_REGISTRY]
    C --> D[Automatycznie tworzone trasy Flask]
    C --> E[Automatycznie generowane endpointy Swagger/OpenAPI]
    D --> F[capacity / embed / extract]
    E --> G[Opis formatu, opcji i błędów]
```

Dodanie metody wymagające rejestracji polega więc na implementacji kontraktu
`SteganographyMethod` i dodaniu jednej instancji do `METHOD_REGISTRY`.
Serwer i Swagger uzupełniają pozostałe elementy dynamicznie.

