# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping, Protocol, Sequence

if importlib.util.find_spec("anthropic") is not None:  # pragma: no cover - optional dependency
    import anthropic as _anthropic
else:
    _anthropic = None

SENSITIVE_CONTEXT_KEYS: tuple[str, ...] = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)

DETERMINISTIC_PROVIDER_SET: frozenset[str] = frozenset({"ollama", "llama_cpp", "quantized"})
DEFAULT_DETERMINISTIC_OPTS: dict[str, Any] = {
    "temperature": 0.0,
    "top_p": 1.0,
    "repeat_penalty": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "seed": 0,
}


class Provider(Protocol):
    """Provider adapter contract for deterministic profile enforcement."""

    def supports_deterministic_mode(self) -> bool: ...

    def normalize_deterministic_opts(self, opts: Mapping[str, Any] | None = None) -> dict[str, Any]: ...


def _runtime_binary_version_digest() -> dict[str, str]:
    python_bin = shutil.which("python3") or shutil.which("python") or ""
    runtime_bits = {
        "python_binary": python_bin,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
    canonical = json.dumps(runtime_bits, sort_keys=True, separators=(",", ":"))
    return {
        **runtime_bits,
        "runtime_digest": f"sha256:{sha256(canonical.encode('utf-8')).hexdigest()}",
    }


class OpenAICompatibleProviderAdapter(Provider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def supports_deterministic_mode(self) -> bool:
        return self.provider_name in DETERMINISTIC_PROVIDER_SET

    def normalize_deterministic_opts(self, opts: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.supports_deterministic_mode():
            return {}
        normalized = dict(DEFAULT_DETERMINISTIC_OPTS)
        if opts:
            normalized.update({k: v for k, v in opts.items() if v is not None})
        return normalized


class OllamaAdapter(OpenAICompatibleProviderAdapter):
    def __init__(self) -> None:
        super().__init__("ollama")


class LlamaCppAdapter(OpenAICompatibleProviderAdapter):
    def __init__(self) -> None:
        super().__init__("llama_cpp")


class QuantizedAdapter(OpenAICompatibleProviderAdapter):
    def __init__(self) -> None:
        super().__init__("quantized")


def _provider_adapter_for(name: str) -> Provider:
    if name == "ollama":
        return OllamaAdapter()
    if name == "llama_cpp":
        return LlamaCppAdapter()
    if name == "quantized":
        return QuantizedAdapter()
    return OpenAICompatibleProviderAdapter(name)


def _noop_proposal(reason: str) -> dict[str, Any]:
    return {
        "proposal_type": "noop",
        "reason": reason,
        "actions": [],
        "governance_continuity": "preserved",
    }


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    backoff_seconds: tuple[float, ...] = (0.0, 0.25, 0.5)

    def delay_for_attempt(self, attempt_index: int) -> float:
        if attempt_index < len(self.backoff_seconds):
            return self.backoff_seconds[attempt_index]
        return self.backoff_seconds[-1]


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: str  # "anthropic", "gemini", "openai", "ollama"
    api_key: str
    model: str
    timeout_seconds: float
    max_tokens: int
    base_url: str | None = None
    fallback_to_noop: bool = False
    deterministic_mode: bool = False
    deterministic_opts: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class LLMProviderResult:
    ok: bool
    payload: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    fallback_used: bool = False
    response_sha256: str | None = None
    evidence_digest: str | None = None
    evidence_metadata: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "payload": self.payload,
            "error": {
                "code": self.error_code,
                "message": self.error_message,
            }
            if self.error_code
            else None,
            "fallback_used": self.fallback_used,
            "response_sha256": self.response_sha256,
            "evidence_digest": self.evidence_digest,
            "evidence_metadata": dict(self.evidence_metadata or {}),
        }


@dataclass(frozen=True)
class EvolutionContextContract:
    prior_cycle_summaries: Sequence[str]
    top_strategy_lineage: Sequence[str]
    rejection_causes: Sequence[str]
    accepted_mutations: Sequence[Mapping[str, Any]] = ()
    rejected_mutations: Sequence[Mapping[str, Any]] = ()
    federated_insight_summaries: Sequence[str] = ()


def sanitize_context_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        sanitized: dict[str, Any] = {}
        for key in sorted(payload.keys(), key=lambda item: str(item)):
            key_text = str(key)
            key_lower = key_text.lower()
            value = payload[key]
            if any(marker in key_lower for marker in SENSITIVE_CONTEXT_KEYS):
                sanitized[key_text] = "[redacted]"
                continue
            sanitized[key_text] = sanitize_context_payload(value)
        return sanitized

    if isinstance(payload, (list, tuple)):
        return [sanitize_context_payload(item) for item in payload]

    return payload


def build_evolution_user_prompt(context: EvolutionContextContract, *, history_window: int = 3, federated_window: int = 3) -> str:
    sanitized_context = sanitize_context_payload(
        {
            "prior_cycle_summaries": list(context.prior_cycle_summaries),
            "top_strategy_lineage": list(context.top_strategy_lineage),
            "rejection_causes": list(context.rejection_causes),
            "accepted_mutations": list(context.accepted_mutations)[-history_window:],
            "rejected_mutations": list(context.rejected_mutations)[-history_window:],
            "federated_insight_summaries": list(context.federated_insight_summaries)[-federated_window:],
        }
    )
    return (
        "Generate a JSON-only evolution proposal with adaptive reasoning.\n"
        "Historical context and federated insights:\n"
        f"{json.dumps(sanitized_context, sort_keys=True, separators=(',', ':'))}"
    )


def validate_adaptive_proposal_schema(payload: dict[str, Any]) -> bool:
    if payload.get("proposal_type") == "noop":
        return True

    required: dict[str, type] = {
        "proposal_hypothesis": str,
        "expected_roi": (float, int),
        "risk_confidence": (float, int),
        "fallback_plan": str,
    }
    for field_name, expected_type in required.items():
        value = payload.get(field_name)
        if not isinstance(value, expected_type):
            return False
        if isinstance(value, str) and not value.strip():
            return False

    risk_confidence = float(payload["risk_confidence"])
    return 0.0 <= risk_confidence <= 1.0


def load_provider_config(env: Mapping[str, str] | None = None) -> LLMProviderConfig:
    source = env or os.environ
    
    # Provider resolution priority
    provider = source.get("ADAAD_LLM_PROVIDER", "").strip().lower()
    if not provider:
        if source.get("ADAAD_ANTHROPIC_API_KEY"): provider = "anthropic"
        elif source.get("GOOGLE_API_KEY"): provider = "gemini"
        elif source.get("OPENAI_API_KEY"): provider = "openai"
        else: provider = "anthropic" # Default fallback

    return LLMProviderConfig(
        provider=provider,
        api_key=(
            source.get("ADAAD_ANTHROPIC_API_KEY") or 
            source.get("GOOGLE_API_KEY") or 
            source.get("OPENAI_API_KEY") or ""
        ).strip(),
        model=(
            source.get("ADAAD_LLM_MODEL") or 
            {
                "anthropic": "claude-3-5-sonnet-20241022",
                "gemini": "gemini-1.5-pro",
                "openai": "gpt-4-turbo",
                "ollama": "llama3"
            }.get(provider, "claude-3-5-sonnet-20241022")
        ).strip(),
        timeout_seconds=float(source.get("ADAAD_LLM_TIMEOUT_SECONDS") or "15"),
        max_tokens=int(source.get("ADAAD_LLM_MAX_TOKENS") or "800"),
        base_url=source.get("ADAAD_LLM_BASE_URL"),
        fallback_to_noop=(source.get("ADAAD_LLM_FALLBACK_TO_NOOP") or "false").strip().lower() in {"1", "true", "yes", "on"},
        deterministic_mode=(source.get("ADAAD_LLM_DETERMINISTIC_MODE") or "false").strip().lower() in {"1", "true", "yes", "on"},
        deterministic_opts=_parse_deterministic_opts(source.get("ADAAD_LLM_DETERMINISTIC_OPTS")),
    )


def _parse_deterministic_opts(raw_opts: str | None) -> dict[str, Any] | None:
    if not raw_opts:
        return None
    try:
        parsed = json.loads(raw_opts)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


class LLMProviderClient:
    def __init__(
        self,
        config: LLMProviderConfig,
        retry_policy: RetryPolicy | None = None,
        schema_validator: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self.config = config
        self.retry_policy = retry_policy or RetryPolicy()
        self.schema_validator = schema_validator or validate_adaptive_proposal_schema
        self.provider_adapter: Provider = _provider_adapter_for(config.provider)

    def request_json(self, *, system_prompt: str, user_prompt: str) -> LLMProviderResult:
        if not self.config.api_key and self.config.provider != "ollama":
            return self._safe_failure("missing_api_key", f"{self.config.provider} API key is not configured.")
        if self.config.deterministic_mode and not self.provider_adapter.supports_deterministic_mode():
            return self._safe_failure(
                "governance_reject_deterministic_unsupported",
                f"deterministic mode requested but unsupported by provider:{self.config.provider}",
                payload={
                    "proposal_type": "noop",
                    "reason": "deterministic_mode_unsupported",
                    "governance": {"action": "escalate/reject", "provider": self.config.provider},
                },
            )

        for attempt in range(self.retry_policy.attempts):
            delay = self.retry_policy.delay_for_attempt(attempt)
            if delay > 0:
                time.sleep(delay)
            try:
                text = self._dispatch_request(system_prompt, user_prompt)
                payload = self._parse_and_validate(text)
                response_sha = f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"
                evidence = self._build_evidence_metadata()
                evidence_digest = f"sha256:{sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()}"
                return LLMProviderResult(
                    ok=True,
                    payload=payload,
                    response_sha256=response_sha,
                    evidence_digest=evidence_digest,
                    evidence_metadata=evidence,
                )
            except Exception as exc:  # noqa: BLE001
                if attempt == self.retry_policy.attempts - 1:
                    return self._safe_failure("provider_request_failed", self._safe_error_text(exc))

        return self._safe_failure("provider_request_failed", "Provider request failed after retries.")

    def _dispatch_request(self, system: str, user: str) -> str:
        if self.config.provider == "anthropic":
            return self._request_anthropic(system, user)
        if self.config.provider == "gemini":
            return self._request_gemini(system, user)
        if self.config.provider in ("openai", "ollama"):
            return self._request_openai_compatible(system, user)
        raise ValueError(f"unsupported_provider:{self.config.provider}")

    def _request_anthropic(self, system: str, user: str) -> str:
        if _anthropic is None:
            raise ImportError("anthropic package not installed")
        client = _anthropic.Anthropic(api_key=self.config.api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            timeout=self.config.timeout_seconds,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return self._extract_text_anthropic(response)

    def _request_gemini(self, system: str, user: str) -> str:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.config.model}:generateContent?key={self.config.api_key}"
        payload = {
            "contents": [{"parts": [{"text": f"SYSTEM: {system}\n\nUSER: {user}"}]}],
            "generationConfig": {"maxOutputTokens": self.config.max_tokens}
        }
        resp = httpx.post(url, json=payload, timeout=self.config.timeout_seconds)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    def _request_openai_compatible(self, system: str, user: str) -> str:
        import httpx
        base_url = self.config.base_url or ("http://localhost:11434/v1" if self.config.provider == "ollama" else "https://api.openai.com/v1")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "max_tokens": self.config.max_tokens,
            "temperature": 0.0
        }
        if self.config.deterministic_mode and self.provider_adapter.supports_deterministic_mode():
            payload.update(self.provider_adapter.normalize_deterministic_opts(self.config.deterministic_opts))
        resp = httpx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=self.config.timeout_seconds)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _extract_text_anthropic(self, response: Any) -> str:
        content = getattr(response, "content", []) or []
        text_parts: list[str] = []
        for block in content:
            block_text = getattr(block, "text", "")
            if block_text:
                text_parts.append(str(block_text))
        return "\n".join(text_parts).strip()

    def _parse_and_validate(self, raw_text: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw_text)
        except Exception:  # noqa: BLE001
            # Opaque code — never expose raw parser exception text to callers or state dicts
            raise ValueError("llm_response_not_json") from None

        if not isinstance(parsed, dict):
            # Opaque code — response shape mismatch, no internal detail leaked
            raise ValueError("llm_response_not_object")
        if not self.schema_validator(parsed):
            raise ValueError("json_response_failed_schema_validation")
        return parsed

    def _build_evidence_metadata(self) -> dict[str, Any]:
        deterministic_profile = self.provider_adapter.normalize_deterministic_opts(self.config.deterministic_opts)
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "deterministic_mode": self.config.deterministic_mode,
            "deterministic_profile": deterministic_profile,
            "runtime": _runtime_binary_version_digest(),
        }

    def _safe_failure(self, code: str, message: str, *, payload: dict[str, Any] | None = None) -> LLMProviderResult:
        if self.config.fallback_to_noop:
            return LLMProviderResult(
                ok=False,
                payload=payload or _noop_proposal(reason=code),
                error_code=code,
                error_message=message,
                fallback_used=True,
                evidence_metadata=self._build_evidence_metadata(),
            )
        return LLMProviderResult(
            ok=False,
            payload=payload or {},
            error_code=code,
            error_message=message,
            fallback_used=False,
            evidence_metadata=self._build_evidence_metadata(),
        )

    @staticmethod
    def _safe_error_text(exc: Exception) -> str:
        return exc.__class__.__name__


__all__ = [
    "Provider",
    "OllamaAdapter",
    "LlamaCppAdapter",
    "QuantizedAdapter",
    "EvolutionContextContract",
    "LLMProviderClient",
    "LLMProviderConfig",
    "LLMProviderResult",
    "RetryPolicy",
    "build_evolution_user_prompt",
    "load_provider_config",
    "sanitize_context_payload",
    "validate_adaptive_proposal_schema",
]
