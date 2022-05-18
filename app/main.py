from enum import Enum
from fastapi import FastAPI
import requests
import json

app = FastAPI()

FIGSHARE_URL = "https://api.figshare.com/v2"
DATACITE_URL = "https://api.datacite.org"
CROSSREF_URL = "https://api.crossref.org"


class DataSource(str, Enum):
    figshare = "figshare"
    zenodo = "zenodo"
    crossref = "crossref"


@app.get("/paper")
async def post_doi(doi: str, source: DataSource):
    if source == DataSource.figshare or source == DataSource.zenodo:
        response = requests.get(DATACITE_URL + f"/dois/{doi}")
    elif source == DataSource.crossref:
        response = requests.get(CROSSREF_URL + f"/works/{doi}")
    return json.loads(response.content.decode("utf-8"))
