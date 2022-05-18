import pytest
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.mark.parametrize(
    ("doi", "source"),
    [
        ("10.1016/j.combustflame.2015.03.001", "crossref"),
        ("10.5281/zenodo.6387882", "zenodo"),
        ("10.6084/m9.figshare.5089594", "figshare"),
    ],
)
def test_crossref(doi: str, source: str):
    response = client.get(f"/paper?doi={doi}&source={source}")
    assert response.status_code == 200
    assert list(response.json().keys()) == ["doi", "title"]
