# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.routing import APIRoute

API_PREFIX = "/api/"
API_V1_PREFIX = "/api/v1/"


def register_v1_aliases(app: FastAPI, *, excluded_prefixes: Sequence[str] = (API_V1_PREFIX,)) -> int:
    """Register `/api/v1/...` aliases for existing `/api/...` HTTP routes.

    Returns the number of aliases added. Existing aliases are left untouched.
    """
    existing_paths = {route.path for route in app.routes if hasattr(route, "path")}
    aliases_added = 0

    for route in list(app.routes):
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith(API_PREFIX):
            continue
        if any(route.path.startswith(prefix) for prefix in excluded_prefixes):
            continue

        v1_path = route.path.replace(API_PREFIX, API_V1_PREFIX, 1)
        if v1_path in existing_paths:
            continue

        app.add_api_route(
            v1_path,
            route.endpoint,
            methods=list(route.methods or {"GET"}),
            tags=list(route.tags),
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            status_code=route.status_code,
            responses=route.responses,
            deprecated=route.deprecated,
            operation_id=(f"v1_{route.operation_id}" if route.operation_id else None),
            response_model=route.response_model,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            name=f"v1_{route.name}",
            openapi_extra={
                "x-adaad-versioned-alias": True,
                "x-adaad-original-path": route.path,
            },
        )
        existing_paths.add(v1_path)
        aliases_added += 1

    return aliases_added
