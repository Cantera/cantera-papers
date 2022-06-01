from enum import Enum
from pathlib import Path
from typing import Optional, cast

import httpx
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import config, crud, models
from .config import get_settings
from .database import SessionLocal, engine
from .external import crossref_request, datacite_request

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

app = FastAPI(debug=True)
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


@app.get("/github_login", response_class=RedirectResponse)
async def github_login(settings: config.Settings = Depends(get_settings)):
    scope = "read:org"
    client_id = settings.github_client_id
    state = settings.secret_state
    return (
        "https://github.com/login/oauth/authorize?"
        f"scope={scope}&client_id={client_id}&state={state}"
    )


@app.get("/github_callback")
async def github_callback(
    request: Request, settings: config.Settings = Depends(get_settings)
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
    actor = {
        "display": profile["login"],
        "gh_id": str(profile["id"]),
        "gh_name": profile["name"],
        "gh_login": profile["login"],
        "gh_email": profile["email"],
    }
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
        actor["teams"] = "Committers"
    else:
        actor["teams"] = ""

    response = RedirectResponse("/approve")
    s = URLSafeSerializer(settings.cookie_secret, salt=b"cantera-papers-approve")
    cookie_value = s.dumps(actor)
    response.set_cookie("cantera-papers-auth-cookie", cookie_value)
    return response


@app.post("/approve/{paper_id}", response_class=HTMLResponse)
async def approve_a_paper(
    request: Request,
    paper_id: int,
    approve: bool | None = Form(None),
    display: bool | None = Form(None),
    hx_trigger_name: str | None = Header(None),
    db: Session = Depends(get_db),
    settings: config.Settings = Depends(get_settings),
):
    if await check_for_auth(request, settings) is None:
        raise HTTPException(
            status_code=403, detail="You're not authorized to view this page"
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


# User goes to /approve
# /approve depends on some authorization checking function which is not an endpoint
# That function checks for a cookie with login data, if it finds it, it returns the
# user back to /approve
# If no cookie is found, that function redirects to the /github_login endpoint which
# redirects to GitHub for login
# When GitHub calls-back to /github_callback, that function collects the user data from
# the GitHub API and stores it in a cookie, then redirects back to /approve
# Since the cookie is now set, the auth checking function reads the cookie and we're
# all set

# What query parameters does the function need to take? Probably just the headers, which
# is where the cookie will be stored. Actually, cookies are handled by a separate type.

# Questions:
# 1. ~How to store the logged-in state?~ Cookie
# 2. How to handle the submission page?
# 3. How to secure the API (cURL access)?
async def check_for_auth(
    request: Request,
    settings: config.Settings,
) -> None | bool:
    cantera_papers_auth_cookie = request.cookies.get("cantera-papers-auth-cookie")
    if cantera_papers_auth_cookie is None:
        return None
    s = URLSafeSerializer(settings.cookie_secret, salt=b"cantera-papers-approve")
    try:
        auth_cookie = s.loads(cantera_papers_auth_cookie)
    except BadSignature:
        return None
    if auth_cookie["teams"] == "Committers":
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/approve")
async def display_papers_for_approval(
    request: Request,
    settings: config.Settings = Depends(get_settings),
    db: Session = Depends(get_db),
):
    if await check_for_auth(request, settings) is None:
        return RedirectResponse("/github_login")
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
