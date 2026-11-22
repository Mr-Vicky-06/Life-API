"""Unit tests for the router gateway protocol and factory."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.gateway.router import GeneralLLMRouter, RouterBackend, get_router


def test_router_backend_protocol():
    """GeneralLLMRouter conforms to RouterBackend protocol."""
    router = GeneralLLMRouter()
    assert isinstance(router, RouterBackend)


def test_get_router_default():
    """get_router() returns GeneralLLMRouter by default."""
    router = get_router()
    assert isinstance(router, GeneralLLMRouter)


def test_get_router_needle_rejected():
    """get_router() raises ValueError when ROUTER_MODEL=needle because spike failed."""
    settings = Settings(
        app_api_key="test-key",
        database_url="postgresql+psycopg://life:life@localhost:5432/life_test",
        database_url_ro="postgresql+psycopg://life_ro:life_ro@localhost:5432/life_test",
        router_model="needle",
    )
    with pytest.raises(ValueError, match="Needle router is not enabled"):
        get_router(settings=settings)
