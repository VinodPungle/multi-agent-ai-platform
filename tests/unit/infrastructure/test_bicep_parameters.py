"""Every Bicep parameter must be settable by `azd`.

This exists because the gap it guards was found the expensive way: a knowledge
base and an embedding deployment were added to `main.bicep`, configured through
`azd env set`, provisioned successfully — and had no effect. `azd` binds
parameters through `main.parameters.json`, so a parameter missing from that file
silently takes its Bicep default. Nothing fails; the feature is simply absent,
and the deployment reports success.

The same gap was quietly present for Redis, alerting, replica counts and trace
sampling, all of which were documented as configurable and were not.

A parsing test rather than a template deployment: `az bicep build` already
proves the template compiles, and what compiling cannot tell you is whether an
operator can reach a parameter.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

INFRA = Path(__file__).resolve().parents[3] / "infra" / "bicep"
TEMPLATE = INFRA / "main.bicep"
PARAMETERS = INFRA / "main.parameters.json"

#: Parameters deliberately not exposed to `azd`.
#:
#: `tags` is computed inside the template from the environment name and the
#: deployment environment. Exposing it would let a deployment drop the
#: `azd-env-name` tag that azd itself uses to find its resources.
COMPUTED_PARAMETERS = frozenset({"tags"})


def declared_parameters() -> set[str]:
    """Return every `param` declared by the template."""
    return set(re.findall(r"^param (\w+)", TEMPLATE.read_text(encoding="utf-8"), re.MULTILINE))


def mapped_parameters() -> dict[str, object]:
    """Return the parameter bindings azd will apply."""
    document = json.loads(PARAMETERS.read_text(encoding="utf-8"))
    parameters: dict[str, object] = document["parameters"]
    return parameters


class TestParameterCoverage:
    def test_every_parameter_is_settable(self) -> None:
        """A parameter azd cannot bind is one an operator cannot set."""
        unmapped = declared_parameters() - set(mapped_parameters()) - COMPUTED_PARAMETERS

        assert not unmapped, (
            "These template parameters have no binding in main.parameters.json, so "
            f"`azd env set` cannot reach them and they will silently take their "
            f"Bicep defaults: {sorted(unmapped)}"
        )

    def test_nothing_is_bound_that_does_not_exist(self) -> None:
        """A stale binding is a setting an operator will set and watch do nothing."""
        orphaned = set(mapped_parameters()) - declared_parameters()

        assert (
            not orphaned
        ), f"These bindings name parameters the template no longer declares: {sorted(orphaned)}"


class TestBindingShape:
    def test_every_binding_reads_an_environment_variable(self) -> None:
        """A literal here is a value nobody can change without editing the repository."""
        literal = [
            name
            for name, binding in mapped_parameters().items()
            if not str(dict(binding).get("value", "")).startswith("${")  # type: ignore[call-overload]
        ]

        assert not literal, f"These bindings hardcode a value: {sorted(literal)}"

    def test_optional_bindings_declare_a_default(self) -> None:
        """`${VAR}` with no default fails the deployment when the variable is unset.

        Only the two azd always provides may go without one.
        """
        always_supplied = {"environmentName", "location"}

        missing = [
            name
            for name, binding in mapped_parameters().items()
            if name not in always_supplied and "=" not in str(dict(binding).get("value", ""))  # type: ignore[call-overload]
        ]

        assert not missing, (
            "These bindings have no default, so a deployment fails unless the "
            f"variable happens to be set: {sorted(missing)}"
        )
