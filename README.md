# Wikipedia Search Tool for OpenWebUI

An [OpenWebUI](https://github.com/open-webui/open-webui) tool that lets your LLM search [Wikipedia](https://www.wikipedia.org/) and retrieve full article text from the [Wikipedia API](https://www.mediawiki.org/wiki/API:Main_page).

## How it works

1. OpenWebUI reads this tool's `/openapi.json` to learn what endpoints are available
2. The LLM uses the endpoint and field descriptions to construct Wikipedia search queries from natural language
3. The proxy forwards queries to Wikipedia and processes the results:
   - Searches English or Latvian Wikipedia
   - Automatically detects the query language if no language is provided
   - Fetches full article text using Wikipedia page IDs
   - Removes empty article results
   - Returns clean article data with title, URL, page ID, language, content, and content length
4. The returned article text can be used directly by the LLM for answering user questions

The tool description is defined in `config.yaml`

## Prerequisites

- Docker and Docker Compose
- No Wikipedia API key required

## Quick start

### Building from source

```bash
git clone https://github.com/YOUR_USERNAME/wikipedia-openwebui-tool.git
cd wikipedia-openwebui-tool

cp .env.example .env
```

Edit `.env`:

```env
WIKIPEDIA_LANGUAGE=en
WIKIPEDIA_DEFAULT_COUNT=3
REQUEST_TIMEOUT=20
WIKIPEDIA_BEARER_TOKEN=
```

```bash
docker-compose up -d --build
```

### Verify it's running

```bash
curl http://localhost:8000/health
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WIKIPEDIA_LANGUAGE` | No | Default Wikipedia language if auto-detection fails. Default: `en` |
| `WIKIPEDIA_DEFAULT_COUNT` | No | Default number of results to return. Default: `3` |
| `REQUEST_TIMEOUT` | No | Request timeout in seconds for Wikipedia API calls. Default: `20` |
| `WIKIPEDIA_BEARER_TOKEN` | No | Bearer token for endpoint authentication. If not set, endpoints are open |
## Adding to OpenWebUI

This project provides a FastAPI backend. To use it in OpenWebUI, create a custom Tool that calls this backend.

1. Go to **Workspace** > **Tools**
2. Click **Create Tool**
3. Paste the tool code into the OpenWebUI tool editor
4. Save the tool
5. Enable the tool in your chat/model

OpenWebUI tool code:

```python
import requests
from typing import Optional


class Tools:
    def __init__(self):
        self.base_url = "http://host.docker.internal:8000"

    def wikipedia_search(
        self,
        query: str,
        count: int = 3,
        language: Optional[str] = None,
    ) -> str:
        """
        Search Wikipedia using the custom FastAPI backend.

        :param query: Wikipedia search query
        :param count: Number of results. Maximum 3.
        :param language: Optional language (en/lv). Leave empty for auto-detect.
        """

        # result count may be passed as text, so converts it
        try:
            count = int(count)
        except (TypeError, ValueError):
            count = 3

        # result limit between 1 and 3.
        count = min(max(count, 1), 3)

        # JSON payload sent to the FastAPI backend.
        payload = {
            "query": query,
            "count": count,
        }

        # only sends language if the user explicitly provided a real value.
        # if not, the backend will auto-detect it
        if language and str(language).strip().lower() not in [
            "",
            "auto",
            "none",
            "null",
        ]:
            payload["language"] = str(language).strip().lower()

        try:
            # calls the backend /search endpoint
            response = requests.post(
                f"{self.base_url}/search",
                json=payload,
                timeout=120,
            )

            # raise an error for HTTP errors
            response.raise_for_status()

        except requests.exceptions.RequestException as error:
            return f"Wikipedia backend request failed: {error}"

        # parses backend JSON response
        data = response.json()
        entries = data.get("entries", [])

        if not entries:
            return "No Wikipedia results found."

        formatted_results = []

        # converts structured JSON results into readable text for the model
        for index, item in enumerate(entries, start=1):
            title = item.get("title", "")
            result_language = item.get("language", "")
            url = item.get("url", "")
            text = item.get("content") or "No article text available."

            formatted_results.append(f"""
Result {index}
Title: {title}
Language: {result_language}
URL: {url}

Text:
{text}
""".strip())

        # separates multiple results
        return "\n\n---\n\n".join(formatted_results)

```

If OpenWebUI runs in Docker, use:

```python
self.base_url = "http://host.docker.internal:8000"
```

If OpenWebUI runs directly on the same machine without Docker, use:

```python
self.base_url = "http://localhost:8000"
```

## Configuration

LLM-facing metadata is defined in [`config.yaml`](config.yaml).

| Key | What it controls |
|-----|-----------------|
| `tool_description` | The tool description shown in the OpenAPI spec |

Example:

```yaml
tool_description: >
  Wikipedia Search Tool for OpenWebUI. This tool searches English and Latvian
  Wikipedia and returns full article text with title, URL, page ID, language,
  content, and content length.
```

After editing `config.yaml`, restart the container:

```bash
docker-compose restart
```

## Supported languages

| Code | Language |
|------|----------|
| `en` | English |
| `lv` | Latvian |

If no language is provided, the backend attempts to detect the language from the query.

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/search` | POST | JSON-based Wikipedia search returning full article text |
| `/docs` | GET | Swagger UI |
| `/openapi.json` | GET | OpenAPI specification |

## Usage examples

### English search

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Area 51",
    "count": 3,
    "language": "en"
  }'
```

### Latvian search

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Rīga",
    "count": 3,
    "language": "lv"
  }'
```

### Auto language detection

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Latvijas vēsture",
    "count": 3
  }'
```

If `WIKIPEDIA_BEARER_TOKEN` is set, include the `Authorization` header:

```bash
curl -X POST "http://localhost:8000/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your_bearer_token_here" \
  -d '{
    "query": "Area 51",
    "count": 3
  }'
```

## Response format

```json
{
  "query": "Area 51",
  "language": "en",
  "count": 1,
  "entries": [
    {
      "title": "Area 51",
      "url": "https://en.wikipedia.org/wiki/Area_51",
      "page_id": 29004,
      "language": "en",
      "content": "Area 51 is a highly classified United States Air Force facility...",
      "content_length": 152344
    }
  ]
}
```

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker-compose up -d --build
```

Stop the container:

```bash
docker-compose down
```

View logs:

```bash
docker-compose logs -f
```

