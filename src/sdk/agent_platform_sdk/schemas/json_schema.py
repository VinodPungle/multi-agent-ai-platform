"""Derivation of tool JSON Schemas from Pydantic models.

A tool's argument schema is used in three places: sent to a model for tool
calling, published in the OpenAPI document, and used to validate incoming
arguments. Hand-writing it three times guarantees they drift, so tool authors
declare a Pydantic model and this module derives the schema from it.

Used from Milestone 04, when the tool framework arrives.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["tool_schema_from_model"]


def tool_schema_from_model(model: type[BaseModel]) -> dict[str, Any]:
    """Return a JSON Schema for ``model`` suitable for a tool declaration.

    Pydantic emits ``$ref``/``$defs`` for nested models. Several providers'
    tool-calling APIs reject or silently mishandle those, so references are
    inlined here with ``ref_template`` resolution.

    Args:
        model: The Pydantic model describing a tool's arguments or output.

    Returns:
        A JSON Schema object with ``$defs`` resolved into the body.
    """
    schema = model.model_json_schema(ref_template="{model}")
    definitions = schema.pop("$defs", {})
    if definitions:
        schema = _inline_references(schema, definitions)
    return schema


def _inline_references(node: Any, definitions: dict[str, Any]) -> Any:  # noqa: ANN401
    """Recursively replace ``$ref`` entries with their definition bodies.

    Self-referential models would recurse forever; they are out of scope for
    tool arguments and are not defended against here beyond Python's own
    recursion limit, which surfaces the mistake immediately at registration time
    rather than on a user's request.
    """
    if isinstance(node, dict):
        reference = node.get("$ref")
        if isinstance(reference, str) and reference in definitions:
            return _inline_references(definitions[reference], definitions)
        return {key: _inline_references(value, definitions) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_references(item, definitions) for item in node]
    return node
