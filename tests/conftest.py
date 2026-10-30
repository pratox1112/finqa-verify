import pytest


@pytest.fixture(autouse=True)
def no_tracing_in_unit_tests(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit tests never reach Langfuse, even if a developer's .env has keys.

    Environment variables take precedence over .env, and empty keys turn tracing off.
    """
    if "integration" not in request.keywords:
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
