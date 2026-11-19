"""
RLO schema registry and version dispatcher.

Every RLO carries a `schema_version` (semver). Validation is dispatched on the
MAJOR version only:

  - Additive, backward-compatible changes bump minor/patch and validate against
    the same model (new optional fields carry defaults, so older documents in
    the same major still pass).
  - Breaking changes bump major and register a new model here alongside the old.

Currently only v1 is accepted. A document with no `schema_version` is assumed
to be the current major (1); a document declaring an unregistered major is
rejected with SchemaVersionError.
"""

from __future__ import annotations

from pydantic import BaseModel

from .v1 import RLO as RLOv1

CURRENT_MAJOR = "1"

# major version string -> model class
_REGISTRY: dict[str, type[BaseModel]] = {
    "1": RLOv1,
}


class SchemaVersionError(ValueError):
    """Raised when an RLO declares a schema_version we do not support."""


def _major(version: str) -> str:
    return version.split(".", 1)[0].strip()


def supported_versions() -> list[str]:
    return sorted(_REGISTRY.keys())


def validate_rlo(raw: dict) -> tuple[BaseModel, str]:
    """
    Validate a raw RLO dict against the model for its declared schema_version.

    Returns (validated_model, schema_version_string).
    Raises SchemaVersionError for an unsupported major version, or
    pydantic.ValidationError for a document that does not satisfy its schema.
    """
    version = str(raw.get("schema_version") or f"{CURRENT_MAJOR}.0.0")
    major = _major(version)
    model = _REGISTRY.get(major)
    if model is None:
        raise SchemaVersionError(
            f"Unsupported schema_version {version!r}. "
            f"Supported major versions: {', '.join(supported_versions())}."
        )
    return model.model_validate(raw), version
