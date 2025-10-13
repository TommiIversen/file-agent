"""
Pytest configuration og shared fixtures.
"""

import pytest
import asyncio
from app.dependencies import reset_singletons


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def clean_singletons():
    """Automatically reset singletons before hver test."""
    reset_singletons()
    yield
    reset_singletons()
