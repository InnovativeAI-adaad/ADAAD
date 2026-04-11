# SPDX-License-Identifier: Apache-2.0
from fastapi.testclient import TestClient

import server
from runtime.api import extension_sdk_descriptor


def test_runtime_api_exposes_extension_descriptor() -> None:
    descriptor = extension_sdk_descriptor()

    assert descriptor["sdk_version"] == "2026-03"
    assert descriptor["compatibility"]["manifest_schema"] == "plugin.manifest.v1"
    assert any(point["id"] == "mutation.pre_submit" for point in descriptor["extension_points"])


def test_api_extensions_spec_endpoint() -> None:
    with TestClient(server.app) as client:
        response = client.get("/api/extensions/spec")

    assert response.status_code == 200
    payload = response.json()
    assert payload["docs"]["spec_path"] == "docs/extensions/SDK_SPEC.md"
    assert payload["deprecation_policy"]["compatibility_window_days"] == 180
