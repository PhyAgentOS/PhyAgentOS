"""Clean-room scene-understanding provider seam for the RoboTwin adapter.

The provider receives only the provider-neutral observation contract.  It does
not inspect RoboTwin actors, segmentation truth, internal poses, task
evaluators, or simulator metadata.  A deployment may inject a detector/VLM
behind ``inference``; this package deliberately does not import that model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol


class SceneUnderstandingInference(Protocol):
    """Injected model/service seam; implementation remains outside PAOS."""

    def infer(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class RoboTwinUnderstandingSnapshot:
    """Provider-neutral claims projected from measured observation artifacts."""

    entities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    relations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    spatial_envelopes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ambiguities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provider_available: bool = True


class RoboTwinSceneUnderstandingProvider:
    """Adapt an injected inference service to the generic understanding port.

    Only observation identity and artifact references cross this boundary.
    The generic ``SceneUnderstandingEndpoint`` remains the owner of the public
    ToolSpec validation and result projection.
    """

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
    _RESULT_KEYS = frozenset(
        {"entities", "relations", "spatial_envelopes", "ambiguities", "provider_available"}
    )

    def __init__(self, inference: SceneUnderstandingInference | Callable[[Mapping[str, Any]], Any]) -> None:
        if not callable(getattr(inference, "infer", None)) and not callable(inference):
            raise TypeError("scene understanding inference must expose infer(request) or be callable")
        self.inference = inference

    def understand(self, request: Mapping[str, Any]) -> RoboTwinUnderstandingSnapshot | None:
        if not isinstance(request, Mapping):
            return None
        projected = {key: request[key] for key in self._REQUEST_KEYS if key in request}
        infer = getattr(self.inference, "infer", None)
        raw = infer(projected) if callable(infer) else self.inference(projected)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise TypeError("scene understanding inference must return an object or null")
        unknown = set(raw) - self._RESULT_KEYS
        if unknown:
            raise ValueError(
                "scene understanding inference returned provider-specific fields: "
                + ", ".join(sorted(unknown))
            )
        return RoboTwinUnderstandingSnapshot(
            entities=_tuple_of_mappings(raw.get("entities", ()), "entities"),
            relations=_tuple_of_mappings(raw.get("relations", ()), "relations"),
            spatial_envelopes=_tuple_of_mappings(
                raw.get("spatial_envelopes", ()), "spatial_envelopes"
            ),
            ambiguities=_tuple_of_mappings(raw.get("ambiguities", ()), "ambiguities"),
            provider_available=raw.get("provider_available", True),
        )


def _tuple_of_mappings(value: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"scene understanding {field_name} must be an array")
    if any(not isinstance(item, Mapping) for item in value):
        raise TypeError(f"scene understanding {field_name} entries must be objects")
    return tuple(dict(item) for item in value)


__all__ = [
    "RoboTwinSceneUnderstandingProvider",
    "RoboTwinUnderstandingSnapshot",
    "SceneUnderstandingInference",
]
