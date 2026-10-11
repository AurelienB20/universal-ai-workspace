import pytest


@pytest.fixture
def anyio_backend() -> str:
    # Async tests run on asyncio via the anyio pytest plugin (no extra dependency).
    return "asyncio"
