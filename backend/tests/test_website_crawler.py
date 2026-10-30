from app.application.seller_intel.website_crawler import crawl_site, normalize_url, page_score

PAGES = {
    "https://acme.test/": """
        <html><head><title>Acme | Field sales software</title></head><body>
        <nav><a href="/login">Log in</a></nav>
        <h1>Acme</h1><p>Acme builds field sales software for FMCG distributors across India.</p>
        <a href="/about-us">About</a> <a href="/products/">Products</a>
        <a href="https://other.test/partner">External</a> <a href="/privacy">Privacy</a>
        <a href="/blog/2024/some-post">Post</a> <a href="mailto:hi@acme.test">Mail</a>
        </body></html>""",
    "https://acme.test/about-us": """<html><body><h1>About Acme</h1>
        <p>Founded in Pune, Acme serves 200 distributors and their field teams every day.</p>
        <a href="/team">Team</a></body></html>""",
    "https://acme.test/products": """<html><body><h1>Products</h1>
        <p>FieldApp tracks visits, orders and collections for every sales rep in the field.</p>
        </body></html>""",
    "https://acme.test/products-copy": """<html><body><h1>Products</h1>
        <p>FieldApp tracks visits, orders and collections for every sales rep in the field.</p>
        </body></html>""",
    "https://acme.test/solutions/route-planning": """<html><body><h2>Route planning</h2>
        <p>Plan beats and territories so reps visit the right outlets on the right day.</p>
        </body></html>""",
    "https://acme.test/team": """<html><body><h2>Team</h2>
        <p>Our team has built distribution software for fifteen years across India and Nepal.</p></body></html>""",
}

SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://acme.test/solutions/route-planning</loc></url>
<url><loc>https://acme.test/products-copy</loc></url>
<url><loc>https://evil.test/x</loc></url>
</urlset>"""


async def fake_fetch(url: str, *, timeout: float, max_bytes: int) -> str:
    key = url if url.endswith("/") and url.count("/") == 3 else url.rstrip("/")
    if key not in PAGES:
        raise ValueError("404")
    return PAGES[key]


async def fake_sitemap(url: str, *, timeout: float, max_bytes: int) -> str:
    if url.endswith("/sitemap.xml"):
        return SITEMAP
    raise ValueError("404")


async def test_crawl_follows_sitemap_and_links_with_dedupe() -> None:
    sources, report = await crawl_site(
        "https://acme.test",
        fetch_page=fake_fetch,
        fetch_sitemap=fake_sitemap,
        is_safe_url=lambda url: True,
        max_pages=10,
        max_depth=2,
    )
    urls = [source.source_url for source in sources]
    assert urls[0] == "https://acme.test/"
    assert "https://acme.test/about-us" in urls
    assert "https://acme.test/products" in urls
    assert "https://acme.test/solutions/route-planning" in urls
    assert "https://acme.test/team" in urls
    assert report.used_sitemap
    assert not any("login" in url or "privacy" in url or "other.test" in url or "evil" in url for url in urls)
    assert any("duplicate content" in item for item in report.skipped)
    assert len({source.source_id for source in sources}) == len(sources)
    assert sources[0].source_name == "Acme | Field sales software"
    assert "Log in" not in sources[0].normalized_markdown


async def test_crawl_limits_pages_and_depth() -> None:
    sources, _ = await crawl_site(
        "https://acme.test/", fetch_page=fake_fetch, fetch_sitemap=fake_sitemap,
        is_safe_url=lambda url: True, max_pages=2, max_depth=1,
    )
    assert len(sources) == 2
    shallow, _ = await crawl_site(
        "https://acme.test/", fetch_page=fake_fetch, is_safe_url=lambda url: True, max_pages=10, max_depth=1,
    )
    assert "https://acme.test/team" not in [source.source_url for source in shallow]


async def test_crawl_reports_blocked_or_unreachable_homepage() -> None:
    sources, report = await crawl_site("http://127.0.0.1/", fetch_page=fake_fetch, is_safe_url=lambda url: False)
    assert sources == []
    assert "blocked_url" in report.errors[0]


async def test_crawl_survives_slow_or_failing_inner_pages() -> None:
    async def flaky(url: str, *, timeout: float, max_bytes: int) -> str:
        if "about" in url:
            raise TimeoutError("slow")
        return await fake_fetch(url, timeout=timeout, max_bytes=max_bytes)

    sources, report = await crawl_site("https://acme.test/", fetch_page=flaky, is_safe_url=lambda url: True)
    assert sources and any("TimeoutError" in error for error in report.errors)


def test_url_helpers() -> None:
    assert normalize_url("HTTPS://Acme.test/About/?utm=1#x") == "https://acme.test/About"
    assert page_score("https://acme.test/") > page_score("https://acme.test/about") > page_score("https://acme.test/random")
    assert page_score("https://acme.test/blog/2024/post") == 0
