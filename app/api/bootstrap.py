# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_DEV_CORS_ORIGINS = ["http://localhost", "http://127.0.0.1"]
_DEV_CORS_ORIGIN_REGEX = r"http://(localhost|127\.0\.0\.1)(:\d+)?"


def resolve_cors_settings(env: Mapping[str, str] | None = None) -> tuple[list[str], str | None]:
    scope = env if env is not None else __import__("os").environ
    origins_raw = scope.get("ADAAD_CORS_ORIGINS")
    regex_raw = scope.get("ADAAD_CORS_ORIGIN_REGEX")
    if origins_raw is None and regex_raw is None:
        return list(_DEV_CORS_ORIGINS), _DEV_CORS_ORIGIN_REGEX
    origins = [o.strip() for o in (origins_raw or "").split(",") if o.strip()]
    regex = (regex_raw or "").strip() or None
    return origins, regex


def apply_cors(app: FastAPI) -> None:
    origins, regex = resolve_cors_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
