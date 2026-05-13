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
        except:
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

        # coonverts structured JSON results into readable text for the model
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

        # seperates multiple results
        return "\n\n---\n\n".join(formatted_results)
