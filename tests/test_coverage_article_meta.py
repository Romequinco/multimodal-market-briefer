"""Cobertura de ``ingest.article_meta`` sin red: capa HTTP con una sesión falsa, descodificación de
Google News en sus casos raros, ``robots.txt`` desde la caché y ramas de error de
``fetch_article_meta`` (que nunca lanza)."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from briefer.ingest import article_meta, cache

G_URL = "https://news.google.com/rss/articles/CBMiZZZ999?oc=5"
ART = "https://www.medio.es/mercados/noticia"


# ── sesión HTTP falsa ─────────────────────────────────────────────────────────────


class FakeResp:
    def __init__(self, status: int = 200, chunks: list[bytes] | None = None, url: str = ART,
                 ctype: str = "text/html", text: str = "") -> None:
        self.status_code = status
        self._chunks = chunks or []
        self.url = url
        self.headers = {"Content-Type": ctype}
        self.text = text
        self.read_chunks = 0

    def __enter__(self) -> FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def iter_content(self, chunk_size: int = 0):
        for chunk in self._chunks:
            self.read_chunks += 1
            yield chunk


class FakeSession:
    def __init__(self, resp: FakeResp) -> None:
        self.resp = resp
        self.cookies = SimpleNamespace(cleared=0)
        self.cookies.clear = self._clear  # type: ignore[attr-defined]
        self.calls: list[tuple[str, str, dict]] = []

    def _clear(self) -> None:
        self.cookies.cleared += 1

    def get(self, url: str, **kw):
        self.calls.append(("GET", url, kw))
        return self.resp

    def post(self, url: str, **kw):
        self.calls.append(("POST", url, kw))
        return self.resp


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch):
    def install(resp: FakeResp) -> FakeSession:
        session = FakeSession(resp)
        monkeypatch.setattr(article_meta, "_session", session)
        return session

    return install


def test_get_session_is_created_once_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(article_meta, "_session", None)
    first = article_meta._get_session()
    assert article_meta._get_session() is first
    assert "market-briefer" in first.headers["User-Agent"]
    assert first.adapters["https://"].max_retries.total == 0  # sin reintentos ocultos


def test_http_fetch_raises_on_http_error_and_clears_cookies(fake_session) -> None:
    session = fake_session(FakeResp(status=503))
    with pytest.raises(article_meta.MetaHTTPError) as info:
        article_meta._http_fetch(ART)
    assert info.value.status == 503 and "www.medio.es" in str(info.value)
    assert session.cookies.cleared == 1  # no se arrastran cookies aunque falle


def test_http_fetch_truncates_at_max_bytes(fake_session) -> None:
    resp = FakeResp(chunks=[b"a" * 10, b"b" * 10, b"c" * 10])
    fake_session(resp)
    final, ctype, body = article_meta._http_fetch(ART, max_bytes=15)
    assert (final, ctype) == (ART, "text/html")
    assert body == b"a" * 10 + b"b" * 5 and resp.read_chunks == 2  # no sigue descargando


def test_http_fetch_stops_at_marker(fake_session) -> None:
    resp = FakeResp(chunks=[b"<html><HEAD>", b"<meta></HEAD><body>", b"cuerpo que no se lee"])
    session = fake_session(resp)
    _final, _ctype, body = article_meta._http_fetch(ART, stop_marker=b"</head>", cookies={"SOCS": "x"})
    assert b"cuerpo" not in body and resp.read_chunks == 2
    assert session.calls[0][2]["cookies"] == {"SOCS": "x"} and session.calls[0][2]["stream"] is True


def test_http_post_ok_and_error(fake_session) -> None:
    session = fake_session(FakeResp(text="respuesta"))
    assert article_meta._http_post("https://x.example/api", {"f.req": "1"}) == "respuesta"
    assert session.cookies.cleared == 1
    fake_session(FakeResp(status=429))
    with pytest.raises(article_meta.MetaHTTPError) as info:
        article_meta._http_post("https://x.example/api", {})
    assert info.value.status == 429


# ── Google News ───────────────────────────────────────────────────────────────────


def test_google_article_id_edge_cases() -> None:
    assert article_meta.google_article_id(ART) is None
    assert article_meta.google_article_id("https://news.google.com/rss/articles/") is None
    assert article_meta.google_article_id("") is None


def test_parse_batch_response_skips_garbage_and_uses_regex_fallback() -> None:
    bad_outer = "[[no es json"
    bad_inner = json.dumps([["wrb.fr", "Fbv4je", "{roto", None]])
    other_rpc = json.dumps([["wrb.fr", "Fbv4je", json.dumps(["otro", "https://x"]), None]])
    assert article_meta._parse_batch_response("\n".join([bad_outer, bad_inner, other_rpc])) is None
    escaped = r'[["wrb.fr","Fbv4je","[\"garturlres\",\"https://medio.es/a\",1]"'  # línea cortada
    assert article_meta._parse_batch_response(escaped) == "https://medio.es/a"


def test_google_blocked_is_read_from_daily_cache() -> None:
    assert not article_meta.google_blocked()
    cache.write_cache("news-meta", "google-blocked", {"until": time.time() + 60})
    assert article_meta.google_blocked()
    article_meta._reset_google_state()
    cache.write_cache("news-meta", "google-blocked", {"until": time.time() - 1})
    assert not article_meta.google_blocked()  # pausa caducada


def test_resolve_google_uses_cache_and_ignores_non_google(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_a, **_k):
        raise AssertionError("no debe haber red")

    monkeypatch.setattr(article_meta, "_http_fetch", offline)
    assert article_meta.resolve_google_news_url(ART) is None
    key = cache.cache_key(article_meta.google_article_id(G_URL))
    cache.write_cache("news-gurl", key, "https://medio.es/cacheada")
    assert article_meta.resolve_google_news_url(G_URL) == "https://medio.es/cacheada"


@pytest.mark.parametrize(
    ("page", "resolved"),
    [
        (b"<html>sin tokens</html>", None),
        (b'data-n-a-sg="S" data-n-a-ts="1"', "https://news.google.com/otra"),  # vuelve a Google
        (b'data-n-a-sg="S" data-n-a-ts="1"', "javascript:alert(1)"),            # no es http(s)
    ],
)
def test_resolve_google_rejects_unusable_answers(monkeypatch: pytest.MonkeyPatch, page: bytes,
                                                 resolved: str | None) -> None:
    monkeypatch.setattr(article_meta, "_http_fetch", lambda *a, **k: (G_URL, "text/html", page))
    inner = json.dumps(["garturlres", resolved, 1])
    monkeypatch.setattr(article_meta, "_http_post",
                        lambda *a, **k: json.dumps([["wrb.fr", "Fbv4je", inner, None]]))
    assert article_meta.resolve_google_news_url(G_URL) is None
    meta = article_meta.fetch_article_meta(G_URL)
    assert meta == {"url": G_URL, "description": "", "error": "google: sin URL final"}


def test_resolve_google_non_429_error_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(url: str, **_k):
        raise article_meta.MetaHTTPError(500, url)

    monkeypatch.setattr(article_meta, "_http_fetch", fail)
    with pytest.raises(article_meta.MetaHTTPError):
        article_meta.resolve_google_news_url(G_URL)
    assert not article_meta.google_blocked()


# ── robots.txt ────────────────────────────────────────────────────────────────────


def test_robots_rejects_non_http_urls() -> None:
    assert not article_meta.robots_allows("ftp://medio.es/a")
    assert not article_meta.robots_allows("noticia-sin-host")


def test_robots_read_from_cache_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_a, **_k):
        raise AssertionError("no debe haber red")

    monkeypatch.setattr(article_meta, "_http_fetch", offline)
    cache.write_cache("news-robots", cache.cache_key("https://www.medio.es"),
                      {"allow_all": None, "text": "User-agent: *\nDisallow: /privado/\n"})
    cache.write_cache("news-robots", cache.cache_key("https://abierto.es"), {"allow_all": True})
    assert article_meta.robots_allows("https://www.medio.es/publico/a")
    assert not article_meta.robots_allows("https://www.medio.es/privado/a")
    assert article_meta.robots_allows("https://abierto.es/x")


def test_robots_html_page_means_allow_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(article_meta, "_http_fetch",
                        lambda url, **k: (url, "text/html", b"<!doctype html><html><body>404</body></html>"))
    assert article_meta.robots_allows(ART)
    cached = cache.read_cache("news-robots", cache.cache_key("https://www.medio.es"))
    assert cached == {"allow_all": True}


def test_robots_network_error_is_conservative_and_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def down(url: str, **_k):
        calls.append(url)
        raise TimeoutError("lento")

    monkeypatch.setattr(article_meta, "_http_fetch", down)
    assert not article_meta.robots_allows(ART)
    assert not article_meta.robots_allows(ART)
    assert len(calls) == 2  # no definitivo: se reintenta


def test_robots_429_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def limited(url: str, **_k):
        raise article_meta.MetaHTTPError(429, url)

    monkeypatch.setattr(article_meta, "_http_fetch", limited)
    assert not article_meta.robots_allows(ART)
    assert cache.read_cache("news-robots", cache.cache_key("https://www.medio.es")) is None


# ── decodificación y metadatos ────────────────────────────────────────────────────


def test_decode_skips_unknown_charsets_and_falls_back() -> None:
    assert article_meta._decode("ñ".encode(), "text/html; charset=no-existe") == "ñ"
    assert article_meta._decode("Señal".encode("cp1252"), "") == "Señal"  # no es UTF-8 válido


def test_same_site_ignores_common_prefixes() -> None:
    assert article_meta._same_site("https://amp.medio.es/a", "https://www.medio.es/b")
    assert article_meta._same_site("https://m.medio.es:443/a", "https://medio.es/b")
    assert not article_meta._same_site("https://otro.es/a", "https://medio.es/b")
    assert not article_meta._same_site("/relativa", "/otra")


def test_classify_errors() -> None:
    assert article_meta._classify(article_meta.MetaHTTPError(404, ART)) == "HTTP 404 en www.medio.es"
    assert article_meta._classify(article_meta.MetaHTTPError(502, ART)).startswith("transient: HTTP 502")
    assert article_meta._classify(ValueError("x")) == "transient: ValueError"


def _page(head: str) -> bytes:
    return f"<html><head>{head}</head><body></body></html>".encode()


def test_fetch_meta_ignores_canonical_of_another_site(monkeypatch: pytest.MonkeyPatch) -> None:
    head = ('<meta property="og:description" content="Descripción larga del artículo de mercados">'
            '<link rel="canonical" href="https://agregador.com/copia">')
    monkeypatch.setattr(article_meta, "robots_allows", lambda _u: True)
    monkeypatch.setattr(article_meta, "_http_fetch", lambda url, **k: (url, "text/html", _page(head)))
    meta = article_meta.fetch_article_meta(ART)
    assert meta["url"] == ART and meta["error"] is None


def test_fetch_meta_uses_same_site_canonical_and_reports_missing_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = '<link rel="canonical" href="https://medio.es/mercados/noticia-canonica">'
    monkeypatch.setattr(article_meta, "robots_allows", lambda _u: True)
    monkeypatch.setattr(article_meta, "_http_fetch",
                        lambda url, **k: ("https://www.medio.es/redir", "text/html", _page(head)))
    meta = article_meta.fetch_article_meta(ART, use_cache=False)
    assert meta["url"] == "https://medio.es/mercados/noticia-canonica"
    assert meta["error"] == "sin descripción en la cabecera"


def test_fetch_meta_respects_robots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(article_meta, "robots_allows", lambda _u: False)
    monkeypatch.setattr(article_meta, "_http_fetch", lambda *a, **k: pytest.fail("no debe leer la página"))
    assert article_meta.fetch_article_meta(ART)["error"] == "robots.txt no permite leer la página"


def test_fetch_meta_ignores_redirect_back_to_google(monkeypatch: pytest.MonkeyPatch) -> None:
    head = '<meta name="description" content="Descripción suficientemente larga para servir">'
    monkeypatch.setattr(article_meta, "robots_allows", lambda _u: True)
    monkeypatch.setattr(article_meta, "_http_fetch", lambda url, **k: (G_URL, "", _page(head)))
    meta = article_meta.fetch_article_meta(ART)
    assert meta["url"] == ART and meta["description"].startswith("Descripción")
