import socket

from app.infrastructure.tools.http_safety import url_is_public_http


def test_blocks_localhost_and_non_http() -> None:
    assert url_is_public_http("http://localhost/admin") is False
    assert url_is_public_http("http://127.0.0.1/") is False
    assert url_is_public_http("file:///etc/passwd") is False
    assert url_is_public_http("not-a-url") is False


def test_blocks_private_resolved_ip(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, 0, ("10.1.1.8", 0))],
    )
    assert url_is_public_http("https://internal.example") is False


def test_blocks_link_local_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, 0, ("169.254.169.254", 0))],
    )
    assert url_is_public_http("http://metadata.example") is False


def test_allows_public_resolved_ip(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, 0, ("93.184.216.34", 0))],
    )
    assert url_is_public_http("https://example.com/about") is True
