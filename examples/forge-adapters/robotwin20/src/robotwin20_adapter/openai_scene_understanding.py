"""OpenAI Responses API inference provider for the RoboTwin adapter.

This module is deliberately adapter-owned.  It references the PAOS scene
understanding contract only through the injected ``RoboTwinSceneUnderstandingProvider``
seam and never imports Hephaestus or simulator APIs.  Artifact IO, credentials,
and the OpenAI client are injected or resolved at runtime.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse


class ArtifactPayload:
    """Bytes and media type for one externally stored observation artifact."""

    def __init__(self, data: bytes, media_type: str) -> None:
        if not isinstance(data, bytes) or not data:
            raise ValueError("artifact data must be non-empty bytes")
        if not isinstance(media_type, str) or not media_type.startswith("image/"):
            raise ValueError("scene understanding requires an image/* artifact")
        self.data = data
        self.media_type = media_type


class ArtifactResolver(Protocol):
    """Resolve opaque artifact references without exposing filesystem paths to PAOS."""

    def resolve(self, artifact_ref: str) -> ArtifactPayload | None: ...


class ResponsesClient(Protocol):
    """Minimal OpenAI client surface used by the provider."""

    responses: Any


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    """External model configuration; no credential value is persisted here."""

    api_base: str = "https://api.shuaiapi.com/v1"
    model: str = "gpt-5.6-sol"
    api_key_env: str = "HEPHAESTUS_RELAY_API_KEY"
    reasoning_effort: str | None = "high"
    timeout_seconds: float = 60.0
    max_output_tokens: int = 512

    def validate(self) -> None:
        parsed = urlparse(self.api_base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("api_base must be an absolute HTTP(S) URL")
        if not self.model.strip() or not self.api_key_env.strip():
            raise ValueError("model and api_key_env must be non-empty")
        if self.timeout_seconds <= 0 or self.max_output_tokens <= 0:
            raise ValueError("timeout_seconds and max_output_tokens must be positive")


class OpenAIResponsesInferenceError(RuntimeError):
    """Bounded provider error safe to project as a generic ToolResult failure."""


SCENE_UNDERSTANDING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entities", "relations", "spatial_envelopes", "ambiguities"],
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entity_ref", "category", "confidence", "provenance"],
                "properties": {
                    "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                    "category": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "provenance": {
                        "type": "array",
                        "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                    },
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "relation_ref", "subject_ref", "predicate", "object_ref", "confidence", "provenance",
                ],
                "properties": {
                    "relation_ref": {"type": "string", "pattern": r"^relation://[^/]+$"},
                    "subject_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                    "predicate": {"type": "string", "minLength": 1},
                    "object_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "provenance": {
                        "type": "array",
                        "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                    },
                },
            },
        },
        "spatial_envelopes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "entity_ref", "frame_id", "unit", "min_xyz_m", "max_xyz_m", "confidence", "provenance",
                ],
                "properties": {
                    "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                    "frame_id": {"type": "string", "minLength": 1},
                    "unit": {"const": "m"},
                    "min_xyz_m": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}},
                    "max_xyz_m": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "number"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "provenance": {
                        "type": "array",
                        "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                    },
                },
            },
        },
        "ambiguities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message", "entity_refs"],
                "properties": {
                    "code": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                    "entity_refs": {
                        "type": "array",
                        "items": {"type": "string", "pattern": r"^entity://[^/]+$"},
                    },
                },
            },
        },
    },
}


def _default_client_factory(**kwargs: Any) -> ResponsesClient:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - exercised in deployment envs
        raise OpenAIResponsesInferenceError(
            "OpenAI SDK is not installed in the adapter environment"
        ) from exc
    return OpenAI(**kwargs)


class OpenAIResponsesSceneUnderstandingInference:
    """Call a configured GPT Responses endpoint and return neutral claim fields."""

    _REQUEST_KEYS = frozenset(
        {
            "observation_ref",
            "scene_revision",
            "frame_id",
            "calibration_ref",
            "freshness_ms",
            "max_age_ms",
            "artifacts",
        }
    )

    def __init__(
        self,
        resolver: ArtifactResolver | Callable[[str], ArtifactPayload | None],
        *,
        config: OpenAIResponsesConfig | None = None,
        client_factory: Callable[..., ResponsesClient] | None = None,
    ) -> None:
        if not callable(getattr(resolver, "resolve", None)) and not callable(resolver):
            raise TypeError("artifact resolver must expose resolve(ref) or be callable")
        self.resolver = resolver
        self.config = config or OpenAIResponsesConfig()
        self.config.validate()
        self.client_factory = client_factory or _default_client_factory

    def infer(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping):
            raise OpenAIResponsesInferenceError("scene understanding request must be an object")
        unknown = set(request) - self._REQUEST_KEYS
        if unknown:
            raise OpenAIResponsesInferenceError("scene understanding request contains unknown fields")
        artifacts = request.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise OpenAIResponsesInferenceError("scene understanding request has no artifacts")
        image = self._resolve_image(artifacts)
        api_key = os.environ.get(self.config.api_key_env)
        if not api_key:
            raise OpenAIResponsesInferenceError(f"Missing {self.config.api_key_env} for scene understanding")
        client = None
        try:
            client = self.client_factory(
                api_key=api_key,
                base_url=self.config.api_base,
                timeout=self.config.timeout_seconds,
            )
            payload: dict[str, Any] = {
                "model": self.config.model,
                "instructions": self._system_prompt(),
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": self._user_prompt(request)},
                            {
                                "type": "input_image",
                                "image_url": self._data_url(image),
                                "detail": "high",
                            },
                        ],
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "scene_understanding",
                        "strict": True,
                        "schema": SCENE_UNDERSTANDING_JSON_SCHEMA,
                    }
                },
                "max_output_tokens": self.config.max_output_tokens,
                "store": False,
            }
            if self.config.reasoning_effort is not None:
                payload["reasoning"] = {"effort": self.config.reasoning_effort}
            response = client.responses.create(**payload)
            return self._parse_response(response)
        except OpenAIResponsesInferenceError:
            raise
        except Exception as exc:
            raise OpenAIResponsesInferenceError("scene understanding Responses request failed") from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _resolve_image(self, artifact_refs: list[Any]) -> ArtifactPayload:
        for ref in artifact_refs:
            if not isinstance(ref, str):
                continue
            try:
                resolve = getattr(self.resolver, "resolve", None)
                payload = resolve(ref) if callable(resolve) else self.resolver(ref)
            except Exception as exc:
                raise OpenAIResponsesInferenceError("observation artifact resolution failed") from exc
            if payload is None:
                continue
            if not isinstance(payload, ArtifactPayload):
                raise OpenAIResponsesInferenceError("artifact resolver returned an invalid payload")
            return payload
        raise OpenAIResponsesInferenceError("no image artifact was available for scene understanding")

    @staticmethod
    def _data_url(image: ArtifactPayload) -> str:
        return f"data:{image.media_type};base64,{base64.b64encode(image.data).decode('ascii')}"

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a query-only visual scene understanding service. Infer only claims supported by the "
            "provided observation image. Return the requested JSON schema. Use opaque entity:// references, "
            "confidence values in [0,1], and artifact:// provenance supplied by the caller. Do not use or "
            "invent simulator actor IDs, segmentation truth, task success, robot poses, IK, collision, or "
            "motion authorization. If the image is ambiguous, return an ambiguity entry instead of guessing."
        )

    @staticmethod
    def _user_prompt(request: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "observation_ref": request.get("observation_ref"),
                "scene_revision": request.get("scene_revision"),
                "frame_id": request.get("frame_id"),
                "calibration_ref": request.get("calibration_ref"),
                "artifact_refs": request.get("artifacts"),
                "task": "desktop organization scene understanding",
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _parse_response(response: Any) -> Mapping[str, Any]:
        content = getattr(response, "output_text", None)
        if not isinstance(content, str) or not content.strip():
            raise OpenAIResponsesInferenceError("Responses result did not contain structured output")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesInferenceError("Responses structured output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenAIResponsesInferenceError("Responses structured output must be an object")
        allowed = {"entities", "relations", "spatial_envelopes", "ambiguities"}
        if set(parsed) - allowed or any(not isinstance(parsed.get(key), list) for key in allowed):
            raise OpenAIResponsesInferenceError("Responses structured output violated the provider contract")
        return parsed


__all__ = [
    "ArtifactPayload",
    "ArtifactResolver",
    "OpenAIResponsesConfig",
    "OpenAIResponsesInferenceError",
    "OpenAIResponsesSceneUnderstandingInference",
    "SCENE_UNDERSTANDING_JSON_SCHEMA",
]
