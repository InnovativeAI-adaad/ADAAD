# SPDX-License-Identifier: Apache-2.0
from fastapi.testclient import TestClient

import server


def test_critical_routes_resolve() -> None:
    with TestClient(server.app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/version').status_code == 200
        assert client.get('/telemetry/decisions').status_code in {200, 401, 403}
        assert client.get('/governance/health').status_code in {200, 401, 403}
        assert client.get('/api/audit/bundles/missing-bundle').status_code in {401, 403, 404}
        assert client.get('/simulation/results/missing').status_code in {200, 401, 404}
