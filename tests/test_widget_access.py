from shared.widget_access import (
    LEGACY_WIDGET_TOKEN_SCOPE,
    WIDGET_SESSION_TOKEN_SCOPE,
    issue_widget_access_token,
    issue_widget_session_token,
    normalize_widget_allowed_origins,
    verify_widget_access_token,
)


def test_normalize_widget_allowed_origins_dedupes_and_normalizes():
    origins = normalize_widget_allowed_origins([
        "https://Example.com/",
        "https://example.com",
        "http://localhost:3000",
    ])

    assert origins == [
        "https://example.com",
        "http://localhost:3000",
    ]


def test_issue_and_verify_widget_session_token(monkeypatch):
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", "test-widget-secret")

    token = issue_widget_session_token(
        tenant_id="tenant-123",
        tenant_slug="tenant-slug",
        parent_origin="https://app.example.com/path",
    )

    claims = verify_widget_access_token(token, expected_scopes=(WIDGET_SESSION_TOKEN_SCOPE,))

    assert claims is not None
    assert claims["tenant_id"] == "tenant-123"
    assert claims["tenant_slug"] == "tenant-slug"
    assert claims["parent_origin"] == "https://app.example.com"


def test_verify_embed_widget_token_scope(monkeypatch):
    monkeypatch.setenv("WIDGET_TOKEN_SECRET", "test-widget-secret")

    token = issue_widget_access_token(
        tenant_id="tenant-legacy",
        tenant_slug="legacy",
    )

    claims = verify_widget_access_token(
        token,
        expected_scopes=(LEGACY_WIDGET_TOKEN_SCOPE, "public_widget_embed"),
    )

    assert claims is not None
    assert claims["tenant_id"] == "tenant-legacy"
