from typing import Any
from enum import Enum
from fastapi import FastAPI
from pydantic import BaseModel, validator
import requests
from urllib.parse import quote

app = FastAPI()

DATACITE_URL = "https://api.datacite.org"
DATACITE_SESSION = requests.Session()
DATACITE_SESSION.headers.update({"Accept": "application/vnd.api+json"})
CROSSREF_URL = "https://api.crossref.org"
CROSSREF_SESSION = requests.Session()
CROSSREF_SESSION.headers.update({
    "User-Agent": "CanteraPapers/0.1 (https://cantera.org/paper; mailto:developers@cantera.org)",
    # "Accept": "application/vnd.crossref-api-message+json",
})


class PaperModel(BaseModel):
    doi: str
    title: str


def datacite_munger(*, doi: str, titles: list[dict[str, str]], **response: dict[str, Any]) -> dict[str, str]:
    return {"doi": doi, "title": titles[0]["title"]} 


def crossref_munger(*, DOI: str, title: list[str], **response: dict[str, Any]) -> dict[str, str]:
    return {"doi": DOI, "title": title[0]} 


class DataSource(str, Enum):
    figshare = "figshare"
    zenodo = "zenodo"
    crossref = "crossref"


@app.get("/paper", response_model=PaperModel)
async def post_doi(doi: str, source: DataSource):
    if source == DataSource.figshare or source == DataSource.zenodo:
        response = DATACITE_SESSION.get(DATACITE_URL + quote(f"/dois/{doi}"))
        data = datacite_munger(**response.json().get("data").get("attributes"))
    elif source == DataSource.crossref:
        response = CROSSREF_SESSION.get(CROSSREF_URL + quote(f"/works/{doi}"))
        data = crossref_munger(**response.json().get("message"))
    return data
