import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings, cors_origins
from backend.app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_vite_dev_server():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_blocks_random_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "https://not-ours.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def preflight(method="GET", headers=None):
    request_headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": method,
    }
    if headers:
        request_headers["Access-Control-Request-Headers"] = headers
    return client.options("/orders", headers=request_headers)


@pytest.mark.parametrize("header", ["Authorization", "X-API-Key", "Content-Type"])
def test_cors_allows_the_headers_the_api_uses(header):
    assert preflight(headers=header).status_code == 200


def test_cors_blocks_other_headers():
    assert preflight(headers="X-Something-Else").status_code == 400


def test_cors_blocks_methods_nothing_in_a_browser_uses():
    assert preflight(method="DELETE").status_code == 400


def test_cors_doesnt_allow_credentials_or_a_wildcard():
    response = preflight()

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


def test_127_0_0_1_isnt_the_same_origin_as_localhost():
    response = client.options(
        "/orders",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_frontend_origins_defaults_to_the_vite_dev_server(monkeypatch):
    monkeypatch.delenv("FRONTEND_ORIGINS", raising=False)

    assert Settings(_env_file=None).frontend_origins == "http://localhost:5173"


@pytest.mark.parametrize(("setting", "expected"), [
    ("http://localhost:5173", ["http://localhost:5173"]),
    ("http://localhost:5173,https://shop.example.com",
     ["http://localhost:5173", "https://shop.example.com"]),
    (" http://localhost:5173 , https://shop.example.com ",
     ["http://localhost:5173", "https://shop.example.com"]),
    # browsers never send the slash, so it would just silently never match
    ("https://shop.example.com/", ["https://shop.example.com"]),
    ("http://localhost:5173,", ["http://localhost:5173"]),
    ("", []),
    # no wildcard, whatever the env var says
    ("*", []),
    ("*,https://shop.example.com", ["https://shop.example.com"]),
])
def test_origins_are_parsed_from_the_env_var(setting, expected):
    assert cors_origins(setting) == expected
