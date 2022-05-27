from enum import Enum
from pathlib import Path
from typing import Optional, cast

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import crud, models
from .database import SessionLocal, engine
from .external import crossref_request, datacite_request

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

app = FastAPI()
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
models.Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DataSource(str, Enum):
    figshare = "figshare"
    zenodo = "zenodo"
    crossref = "crossref"


class PaperRequest(BaseModel):
    doi: str
    source: DataSource


class PaperModel(BaseModel):
    doi: str
    title: str
    is_displayed: bool
    is_approved: bool

    class Config:
        orm_mode = True


class PaperInfo(PaperModel):
    url: Optional[str]


class ApprovalModel(BaseModel):
    id: int


@app.get("/", response_class=HTMLResponse)
async def display_all_papers(request: Request, db: Session = Depends(get_db)):
    papers = db.query(models.Paper).filter(models.Paper.is_displayed).all()
    return templates.TemplateResponse(
        "index.html", {"request": request, "papers": papers}
    )


@app.post("/approve", response_class=HTMLResponse)
async def approve_a_paper(paper_id: ApprovalModel, db: Session = Depends(get_db)):
    db_paper = db.get(entity=models.Paper, ident=paper_id.id)
    if db_paper is None:
        raise HTTPException(status_code=404, detail="Item not found")
    db_paper.is_approved = not db_paper.is_approved
    db_paper.is_displayed = db_paper.is_approved
    db.commit()
    db.refresh(db_paper)
    checked = " checked" if db_paper.is_approved else ""
    response = f"""\
        <tr id='row-id-{paper_id.id}'>
            <td>{paper_id.id}</td>
            <td>{db_paper.doi}</td>
            <td>{db_paper.title}</td>
            <td>
                <input type='checkbox' id='approve-id-{paper_id.id}'{checked}
                       hx-post='/approve' hx-ext='json-enc'
                       hx-vals='{{"id": {paper_id.id}}}'
                       hx-target='#row-id-{paper_id.id}'>
                <label for='approve-id-{paper_id.id}'> Approve</label>
            </td>
            <td>
                <input type='checkbox' id='display-id-{paper_id.id}'{checked}
                       hx-post='/display' hx-ext='json-enc'
                       hx-vals='{{"id": {paper_id.id}}}' hx-swap='outerHTML'>
                <label for='display-id-{paper_id.id}'> Display</label>
            </td>
        </tr>
    """
    return response


@app.get("/approve", response_class=HTMLResponse)
async def display_papers_for_approval(request: Request, db: Session = Depends(get_db)):
    papers = db.query(models.Paper).all()
    return templates.TemplateResponse(
        "approval.html", {"request": request, "papers": papers}
    )


@app.post("/display", response_class=HTMLResponse)
async def display_a_paper(paper_id: ApprovalModel, db: Session = Depends(get_db)):
    db_paper = db.get(entity=models.Paper, ident=paper_id.id)
    if db_paper is None:
        raise HTTPException(status_code=404, detail="Item not found")
    db_paper.is_displayed = not db_paper.is_displayed
    db.commit()
    db.refresh(db_paper)
    checked = " checked" if db_paper.is_displayed else ""
    response = f"""\
                <input type='checkbox' id='display-id-{paper_id.id}'{checked}
                       hx-post='/display' hx-ext='json-enc'
                       hx-vals='{{"id": {paper_id.id}}}' hx-swap='outerHTML'>
    """
    return response


@app.post("/submit", response_model=PaperInfo)
async def submit_a_paper(request: PaperRequest, db: Session = Depends(get_db)):
    source = request.source
    doi = request.doi
    if source == DataSource.figshare or source == DataSource.zenodo:
        data = await datacite_request(doi)
    elif source == DataSource.crossref:
        data = await crossref_request(doi)
    else:
        data = {}
    db_paper = crud.create_db_paper(db, data=data)
    paper = cast(PaperInfo, db_paper)
    paper.doi = data["doi"]
    paper.title = data["title"]
    paper.url = data["url"]

    return paper
