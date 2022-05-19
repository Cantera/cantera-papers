from enum import Enum
from fastapi import FastAPI
from pydantic import BaseModel

from .external import datacite_request, crossref_request


app = FastAPI()


class PaperModel(BaseModel):
    doi: str
    title: str


class DataSource(str, Enum):
    figshare = "figshare"
    zenodo = "zenodo"
    crossref = "crossref"


@app.get("/paper", response_model=PaperModel)
async def post_doi(doi: str, source: DataSource):
    if source == DataSource.figshare or source == DataSource.zenodo:
        data = await datacite_request(doi)
    elif source == DataSource.crossref:
        data = await crossref_request(doi)
    return data
