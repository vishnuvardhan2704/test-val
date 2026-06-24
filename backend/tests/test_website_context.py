from app.services.website_context import extract_website_url, normalize_website_url, fetch_website_context


def test_normalize_website_url_adds_scheme():
    assert normalize_website_url("example.com") == "https://example.com/"


def test_extract_website_url_from_text():
    assert extract_website_url("Check our site at https://acme.example/about") == "https://acme.example/about"


def test_fetch_website_context_uses_visible_text(monkeypatch):
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            return None

    def fake_get(*args, **kwargs):
        return FakeResponse(
            """
            <html>
              <head><title>Acme Textiles</title><meta name="description" content="We make fabrics."></head>
              <body><h1>Acme Textiles</h1><p>B2B manufacturer supplying garment exporters.</p></body>
            </html>
            """
        )

    monkeypatch.setattr("app.services.website_context.requests.get", fake_get)
    context = fetch_website_context("acme.example")
    assert context is not None
    assert "Acme Textiles" in context
    assert "B2B manufacturer" in context