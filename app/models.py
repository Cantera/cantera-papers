from sqlalchemy import Boolean, Column, Integer, String

from .database import Base


class Paper(Base):
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True)
    doi = Column(String, unique=True, index=True)
    title = Column(String, index=True)
    is_displayed = Column(Boolean, default=False)
    is_approved = Column(Boolean, default=False)
