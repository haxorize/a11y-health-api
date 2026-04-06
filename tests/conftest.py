import pytest
from fastapi.testclient import TestClient

from a11y_quality_api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
