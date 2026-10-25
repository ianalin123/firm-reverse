from fastapi import FastAPI
from fastapi.testclient import TestClient

from firm_reverse.access import COOKIE, AccessCodeMiddleware


def make_client(code: str) -> TestClient:
    app = FastAPI()

    @app.get("/")
    def index():
        return {"ok": True}

    @app.post("/api/thing")
    def thing():
        return {"ok": True}

    app.add_middleware(AccessCodeMiddleware, code=code)
    return TestClient(app, base_url="https://testserver")


def test_disabled_when_no_code():
    assert make_client("").get("/").status_code == 200


def test_blocks_without_cookie():
    client = make_client("s3cret")
    page = client.get("/")
    assert page.status_code == 401 and b"/unlock" in page.content
    assert client.post("/api/thing").status_code == 401


def test_wrong_code_rejected():
    client = make_client("s3cret")
    response = client.get("/unlock?code=nope", follow_redirects=False)
    assert response.status_code == 401
    assert COOKIE not in client.cookies


def test_unlock_sets_cookie_and_grants_access():
    client = make_client("s3cret")
    response = client.get("/unlock?code=s3cret", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie and "SameSite=Lax" in set_cookie
    assert client.get("/").status_code == 200
    assert client.post("/api/thing").status_code == 200
