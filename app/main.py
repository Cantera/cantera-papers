from enum import Enum
from pathlib import Path
from typing import cast

import httpx
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import config, crud, models
from .config import get_settings
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


class ActorModel(BaseModel):
    display: str = Field(..., alias="login")
    gh_id: str = Field(..., alias="id")
    gh_name: str = Field(..., alias="name")
    gh_email: str = Field(..., alias="email")
    teams: str | None = None

    class Config:
        allow_population_by_field_name = True


class PaperModel(BaseModel):
    doi: str
    title: str
    is_displayed: bool
    is_approved: bool

    class Config:
        orm_mode = True


class PaperInfo(PaperModel):
    url: str | None


@app.get("/", response_class=HTMLResponse)
async def display_all_papers(request: Request, db: Session = Depends(get_db)):
    papers = db.query(models.Paper).filter(models.Paper.is_displayed).all()
    return templates.TemplateResponse(
        "index.html", {"request": request, "papers": papers}
    )


@app.get("/github_login", response_class=RedirectResponse)
async def github_login(
    scope: str = Query(default="user:email"),
    redirect_uri: str = Query(regex="^submit|approve$"),
    settings: config.Settings = Depends(get_settings),
):
    client_id = settings.github_client_id
    state = settings.secret_state
    url = (
        "https://github.com/login/oauth/authorize?"
        f"scope={scope}&client_id={client_id}&state={state}"
        "&redirect_uri="
        f"http://127.0.0.1:8000/github_callback/{redirect_uri}"
    )
    return RedirectResponse(url, status_code=302)


@app.get("/github_callback")
async def handle_callback_eror():
    pass


@app.get("/github_callback/{redirect_uri}")
async def github_callback(
    redirect_uri: str,
    request: Request,
    settings: config.Settings = Depends(get_settings),
):
    code = request.query_params.get("code")
    if code is None:
        raise HTTPException(
            status_code=401, detail="Authentication failed, no code from GitHub"
        )
    state = request.query_params.get("state")
    if state is None or state != settings.secret_state:
        raise HTTPException(
            status_code=401, detail="Authentication failed, state does not match"
        )
    client_secret = settings.github_client_secret
    client_id = settings.github_client_id
    async with httpx.AsyncClient() as client:
        github_response = (
            await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                },
                headers={
                    "Accept": "application/json",
                },
            )
        ).json()
    access_token = github_response.get("access_token")
    if access_token is None:
        if github_response.get("error"):
            detail = (
                github_response["error"]
                + "\n\n"
                + github_response.get("error_description", "")
            )
        else:
            detail = "Authorization failed, did not get access token"
        raise HTTPException(status_code=401, detail=detail)
    profile_url = "https://api.github.com/user"
    async with httpx.AsyncClient() as client:
        profile = (
            await client.get(
                profile_url,
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/json",
                },
            )
        ).json()
    actor = ActorModel(**profile)
    if "read:org" in github_response.get("scope"):
        async with httpx.AsyncClient() as client:
            membership = await client.get(
                "https://api.github.com/orgs/Cantera/teams/Committers/memberships/"
                f"{profile['login']}",
                headers={
                    "Authorization": f"token {access_token}",
                    "Accept": "application/json",
                },
            )
        if membership.status_code == 200:
            actor.teams = "Committers"
        else:
            actor.teams = ""

    response = RedirectResponse(f"/{redirect_uri}")
    s = URLSafeSerializer(settings.cookie_secret, salt=b"cantera-papers")
    cookie_value = s.dumps(actor.dict())
    cookie_key = "cantera_papers_auth_token"
    response.set_cookie(
        key=cookie_key,
        value=cookie_value,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@app.get("/logout", response_class=RedirectResponse)
async def logout(redirect_uri: str):
    response = RedirectResponse(f"/{redirect_uri}")
    response.delete_cookie(
        "cantera_papers_auth_token", secure=True, httponly=True, samesite="strict"
    )
    return response


async def get_actor_from_cookie(
    cantera_papers_auth_token: str | None = Cookie(default=None),
    settings: config.Settings = Depends(get_settings),
) -> ActorModel | None:
    if cantera_papers_auth_token is None:
        return None

    s = URLSafeSerializer(settings.cookie_secret, salt=b"cantera-papers")
    try:
        actor = ActorModel(**s.loads(cantera_papers_auth_token))
    except BadSignature:
        raise HTTPException(status_code=403, detail="Bad signature on cookie")

    return actor


@app.get("/approve", response_class=HTMLResponse)
async def display_papers_for_approval(
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorModel | None = Depends(get_actor_from_cookie),
):
    logged_in = False
    papers = None
    if actor is not None and actor.teams == "Committers":
        logged_in = True
        papers = db.query(models.Paper).all()

    return templates.TemplateResponse(
        "approval.html", {"request": request, "papers": papers, "logged_in": logged_in}
    )


@app.post("/approve/{paper_id}", response_class=HTMLResponse)
async def approve_a_paper(
    request: Request,
    paper_id: int,
    approve: bool | None = Form(None),
    display: bool | None = Form(None),
    hx_trigger_name: str | None = Header(None),
    db: Session = Depends(get_db),
    actor: ActorModel | None = Depends(get_actor_from_cookie),
):
    if actor is None or actor.teams != "Committers":
        raise HTTPException(
            status_code=403, detail="Must be a committer to approve papers"
        )
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


@app.get("/submit", response_class=HTMLResponse)
async def display_submit_page(
    request: Request, actor: ActorModel | None = Depends(get_actor_from_cookie)
):
    logged_in = actor is not None
    return templates.TemplateResponse(
        "submit.html", {"request": request, "logged_in": logged_in, "actor": actor}
    )


@app.post("/submit", response_class=HTMLResponse)
async def submit_a_paper(
    request: Request,
    source: str = Form(),
    doi: str = Form(),
    db: Session = Depends(get_db),
    actor: ActorModel | None = Depends(get_actor_from_cookie),
):
    if actor is None:
        raise HTTPException(
            status_code=403, detail="No GitHub login available, cannot submit papers"
        )
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
