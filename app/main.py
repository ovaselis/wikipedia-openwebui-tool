import os
import re
import html
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx
import yaml
from fastapi import FastAPI, Form, Header, HTTPException
from pydantic import BaseModel, Field
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException


CONFIG_PATH = Path("config.yaml")

#supported Wikipedia languages
SUPPORTED_LANGUAGES = {"en", "lv"}

#runtime settings from env
WIKIPEDIA_LANGUAGE = os.getenv("WIKIPEDIA_LANGUAGE", "en")
WIKIPEDIA_DEFAULT_COUNT = int(os.getenv("WIKIPEDIA_DEFAULT_COUNT", "3"))
WIKIPEDIA_BEARER_TOKEN = os.getenv("WIKIPEDIA_BEARER_TOKEN")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "20"))

#loads metadata from config.yaml
def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}
    return {}


config = load_config()

#creates a FastAPI app
app = FastAPI(
    title="Wikipedia Search Tool for Open WebUI",
    description=config.get(
        "tool_description",
        "Wikipedia search tool returning full article text for LLM usage.",
    ),
    version="0.2.0",
)

#JSON request model for POST /search.
class SearchRequest(BaseModel):
    query: str = Field(..., description="Wikipedia search query.")

    #limits the returned article count
    count: int = Field(
        default=WIKIPEDIA_DEFAULT_COUNT,
        ge=1,
        le=3,
        description="Maximum number of full articles to return.",
    )

    language: Optional[str] = Field(
        default=None,
        description="Optional language code: en or lv.",
    )


#optional bearer token check.
def check_auth(authorization: Optional[str]) -> None:
    if not WIKIPEDIA_BEARER_TOKEN:
        return

    if authorization != f"Bearer {WIKIPEDIA_BEARER_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


#cleans text and removes artifacts like html code
def clean_text(text: str | None) -> str:
    if not text:
        return ""

    text = re.sub(r"<.*?>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()

#if language is not provided it tries to detect it
def detect_language(query: str) -> str:
    try:
        detected = detect(query)

        if detected in SUPPORTED_LANGUAGES:
            return detected

    except LangDetectException:
        pass

    return WIKIPEDIA_LANGUAGE

#uses provided language or detects it
def resolve_language(query: str, language: Optional[str]) -> str:
    resolved_language = language or detect_language(query)

    if resolved_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail="Only 'en' and 'lv' are supported",
        )

    return resolved_language


#creates HTTP headers for requests to Wikipedia
def wikipedia_headers(language: str) -> dict:
    accept_language = (
        "lv-LV,lv;q=0.9,en;q=0.8" #if we search latvian Wikipedia, prefer latvian, else english
        if language == "lv"
        else "en-US,en;q=0.9"
    )

    return {
        "User-Agent": "wikipedia-openwebui-tool/0.2.0 (Open WebUI Wikipedia Tool)",
        "Accept": "application/json",
        "Accept-Language": accept_language,
    }

#searches wikipedia and returns raw search results with page IDs
async def search_wikipedia_api(query: str, count: int, language: str) -> dict:
    api_url = f"https://{language}.wikipedia.org/w/api.php"

    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srlimit": str(count),
        "utf8": "1",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        #sends GET request to wikipedia
        response = await client.get(
            api_url,
            params=params,
            headers=wikipedia_headers(language),
        )
        response.raise_for_status()
        return response.json()

#fetches full article text for the returned page IDs
async def get_full_page_content(page_ids: list[int], language: str) -> dict:
    if not page_ids:
        return {}

    api_url = f"https://{language}.wikipedia.org/w/api.php"

    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "pageids": "|".join(str(page_id) for page_id in page_ids),
        "explaintext": "1",
        "redirects": "1",
        "utf8": "1",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(
            api_url,
            params=params,
            headers=wikipedia_headers(language),
        )
        response.raise_for_status()
        data = response.json()

    pages = data.get("query", {}).get("pages", {})
    results = {}

    for page_id, page_data in pages.items():
        content = clean_text(page_data.get("extract"))

        if content:
            results[int(page_id)] = content

    return results

#combines search metadata with full article text.
async def format_results(data: dict, query: str, language: str) -> dict:
    search_data = data.get("query", {}).get("search", [])

    page_ids = [
        item.get("pageid")
        for item in search_data
        if item.get("pageid") is not None
    ]

    full_content_map = await get_full_page_content(
        page_ids=page_ids,
        language=language,
    )

    entries = []

    for item in search_data:
        title = item.get("title", "")
        page_id = item.get("pageid")

        full_content = full_content_map.get(page_id, "")

        if not full_content:
            continue

        url = f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"

        entries.append(
            {
                "title": title,
                "url": url,
                "page_id": page_id,
                "language": language,
                "content": full_content,
                "content_length": len(full_content),
            }
        )

    return {
        "query": query,
        "language": language,
        "count": len(entries),
        "entries": entries,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "wikipedia-openwebui-tool",
        "version": "0.2.0",
        "supported_languages": sorted(SUPPORTED_LANGUAGES),
    }


@app.post("/search")
async def search(
    request: SearchRequest,
    authorization: Optional[str] = Header(default=None),
):
    check_auth(authorization)

    query = request.query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    #tries to resolve the language else tries detecting
    language = resolve_language(query=query, language=request.language)

    try:
        data = await search_wikipedia_api(
            query=query,
            count=request.count,
            language=language,
        )

        return await format_results(
            data=data,
            query=query,
            language=language,
        )

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Wikipedia API returned an error: {exc.response.status_code}",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Wikipedia API request failed: {str(exc)}",
        )

