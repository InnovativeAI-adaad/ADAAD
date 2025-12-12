from __future__ import annotations

import hashlib
import traceback
from dataclasses import dataclass


class Stage:
    MUTATE_AST = "MUTATE_AST"
    BUILD_CHILD = "BUILD_CHILD"
    SANDBOX_RUN = "SANDBOX_RUN"
    FITNESS_EVAL = "FITNESS_EVAL"
    CRYOVANT_CERT = "CRYOVANT_CERT"
    PROMOTE = "PROMOTE"


class ErrorCode:
    AST_SYNTAX_ERROR = "AST_SYNTAX_ERROR"
    AST_SEMANTIC_BREAK = "AST_SEMANTIC_BREAK"
    IMPORT_CANONICAL_VIOLATION = "IMPORT_CANONICAL_VIOLATION"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    SANDBOX_PERMISSION_DENIED = "SANDBOX_PERMISSION_DENIED"
    TEST_FAIL = "TEST_FAIL"
    FITNESS_BELOW_THRESHOLD = "FITNESS_BELOW_THRESHOLD"
    CRYOVANT_ANCESTRY_REJECTED = "CRYOVANT_ANCESTRY_REJECTED"
    CRYOVANT_SIGNING_FAILED = "CRYOVANT_SIGNING_FAILED"
    PROMOTION_WRITE_FAILED = "PROMOTION_WRITE_FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClassifiedError:
    error_code: str
    exception_type: str
    exception_msg_hash: str
    traceback_tail: str


def _hash_msg(msg: str) -> str:
    return hashlib.sha256((msg or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def classify_exception(exc: BaseException) -> ClassifiedError:
    et = type(exc).__name__
    msg = str(exc)[:2000]
    tb = traceback.format_exc(limit=12)
    tb_tail = "\n".join(tb.splitlines()[-10:])

    # Heuristics. Keep stable and conservative.
    if et in ("SyntaxError", "IndentationError", "TabError"):
        code = ErrorCode.AST_SYNTAX_ERROR
    elif et in ("PermissionError",):
        code = ErrorCode.SANDBOX_PERMISSION_DENIED
    elif et in ("TimeoutError",):
        code = ErrorCode.SANDBOX_TIMEOUT
    else:
        code = ErrorCode.UNKNOWN

    return ClassifiedError(
        error_code=code,
        exception_type=et,
        exception_msg_hash=_hash_msg(msg),
        traceback_tail=tb_tail,
    )
