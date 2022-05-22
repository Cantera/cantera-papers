import httpx
from urllib.parse import quote
from typing import Any

DATACITE_URL = "https://api.datacite.org"
DATACITE_HEADERS = {"Accept": "application/vnd.api+json"}

CROSSREF_URL = "https://api.crossref.org"
CROSSREF_HEADERS = {
    "User-Agent": (
        "CanteraPapers/0.1 (https://cantera.org/paper; "
        "mailto:developers@cantera.org)"
    )
}


async def datacite_request(doi: str) -> dict[str, str]:
    def datacite_munger(
        *, doi: str, titles: list[dict[str, str]], url: str, **response: dict[str, Any]
    ) -> dict[str, Any]:
        return {"doi": doi, "title": titles[0]["title"], "url": url, **response}

    async with httpx.AsyncClient(
        base_url=DATACITE_URL, headers=DATACITE_HEADERS
    ) as client:
        response = await client.get(quote(f"/dois/{doi}"))
    return datacite_munger(**response.json().get("data").get("attributes"))


async def crossref_request(doi: str) -> dict[str, str]:
    def crossref_munger(
        *, DOI: str, title: list[str], URL: str, **response: dict[str, Any]
    ) -> dict[str, Any]:
        return {"doi": DOI, "title": title[0], "url": URL, **response}

    async with httpx.AsyncClient(
        base_url=CROSSREF_URL, headers=CROSSREF_HEADERS
    ) as client:
        response = await client.get(quote(f"/works/{doi}"))
    return crossref_munger(**response.json().get("message"))
