from typing import Any
from sqlalchemy.orm import Session
from . import models


def create_db_paper(db: Session, data: dict[str, Any]) -> models.Paper:
    if db_paper := db_paper_doi_exists(db, data["doi"]):
        return db_paper

    db_paper = models.Paper(doi=data["doi"], title=data["title"])
    db.add(db_paper)
    db.commit()
    db.refresh(db_paper)

    return db_paper


def db_paper_doi_exists(db: Session, doi: str) -> models.Paper | None:
    return db.query(models.Paper).filter(models.Paper.doi == doi).first()


def get_db_paper_by_doi(db: Session, doi: str) -> models.Paper:
    return (
        db.query(models.Paper)
        .filter(models.Paper.doi == doi, models.Paper.is_displayed)
        .first()
    )
