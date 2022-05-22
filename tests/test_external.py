import pytest

from app.external import crossref_request, datacite_request

request = {
    "crossref": crossref_request,
    "figshare": datacite_request,
    "zenodo": datacite_request,
}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("doi", "source"),
    [
        ("10.1016/j.combustflame.2015.03.001", "crossref"),
        ("10.5281/zenodo.6387882", "zenodo"),
        ("10.6084/m9.figshare.5089594", "figshare"),
    ],
)
async def test_request(doi: str, source: str):
    data = await request[source](doi)
    assert data["doi"] == doi
    assert "title" in data.keys()
