# SPDX-License-Identifier: Apache-2.0
from fastapi.testclient import TestClient

from server import app


def test_v1_health_alias_is_available() -> None:
    with TestClient(app) as client:
        legacy = client.get('/api/health')
        v1 = client.get('/api/v1/health')
        assert legacy.status_code == 200
        assert v1.status_code == 200
        assert v1.json()['protocol'] == legacy.json()['protocol']


def test_v1_fast_path_alias_is_available() -> None:
    with TestClient(app) as client:
        response = client.get('/api/v1/fast-path/stats')
        assert response.status_code == 200
        assert response.json()['ok'] is True
