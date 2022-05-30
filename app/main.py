from enum import Enum
from pathlib import Path
from typing import Optional, cast

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
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
    approve: bool | None = None
    display: bool | None = None


@app.get("/", response_class=HTMLResponse)
async def display_all_papers(request: Request, db: Session = Depends(get_db)):
    papers = db.query(models.Paper).filter(models.Paper.is_displayed).all()
    return templates.TemplateResponse(
        "index.html", {"request": request, "papers": papers}
    )


@app.post("/approve/{paper_id}", response_class=HTMLResponse)
async def approve_a_paper(
    request: Request,
    paper_id: int,
    approve: bool | None = Form(None),
    display: bool | None = Form(None),
    hx_trigger_name: str | None = Header(None),
    db: Session = Depends(get_db),
):
    db_paper = db.get(entity=models.Paper, ident=paper_id)
    if db_paper is None:
        raise HTTPException(status_code=404, detail="Item not found")
    approve = approve is not None
    display = display is not None
    successful_approval = False
    if hx_trigger_name == "approve":
        db_paper.is_approved = approve
        db_paper.is_displayed = approve
        db.commit()
        db.refresh(db_paper)
        successful_approval = True
    elif hx_trigger_name == "display":
        db_paper.is_displayed = display
        db.commit()
        db.refresh(db_paper)
        successful_approval = True

    if successful_approval:
        return templates.TemplateResponse(
            "paper.html", {"request": request, "paper": db_paper}
        )
    else:
        raise HTTPException(status_code=500, detail="Error setting approval")


@app.get("/approve", response_class=HTMLResponse)
async def display_papers_for_approval(request: Request, db: Session = Depends(get_db)):
    papers = db.query(models.Paper).all()
    return templates.TemplateResponse(
        "approval.html", {"request": request, "papers": papers}
    )


@app.get("/submit", response_class=HTMLResponse)
async def display_submit_page(request: Request):
    return templates.TemplateResponse("submit.html", {"request": request})


@app.post("/submit", response_class=HTMLResponse)
async def submit_a_paper(
    request: Request,
    source: str = Form(),
    doi: str = Form(),
    db: Session = Depends(get_db),
):
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

    return templates.TemplateResponse(
        "response.html", {"request": request, "datasource": DataSource}
    )
