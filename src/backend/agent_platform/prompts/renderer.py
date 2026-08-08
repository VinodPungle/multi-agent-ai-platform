"""Prompt rendering.

Substitutes ``{{ variable }}`` placeholders in a prompt template.

Deliberately not Jinja2, and that is a real decision rather than an omission. A
prompt is data, and a template language is a small programming language — loops,
conditionals, filters, inheritance, and in Jinja's case attribute access on
whatever object is passed in. Putting one between a prompt author and a model
means prompt files can express logic, which then has to be reviewed, tested and
reasoned about like code, in files that exist precisely so they are not code.

Substitution covers what prompts actually need. If a prompt one day genuinely
needs a conditional, that is a signal the logic belongs in the agent, where it
can be tested.

Rendering is separate from :class:`FilePromptProvider` because the provider owns
loading and versioning. Changing how a prompt is rendered should not mean
touching how it is stored.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from agent_platform.exceptions.base import ValidationError
from agent_platform_sdk.dto.prompt import PromptAsset

__all__ = ["render_prompt"]

#: Matches ``{{ name }}`` with any surrounding whitespace.
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_prompt(asset: PromptAsset, variables: Mapping[str, str]) -> str:
    """Render ``asset`` with ``variables``.

    Args:
        asset: The prompt to render.
        variables: Values for the prompt's declared variables.

    Returns:
        The rendered prompt text.

    Raises:
        ValidationError: a variable the prompt declares as required was not
            supplied. Failing here is the point: the alternative is that
            ``{{ user_locale }}`` reaches a model as literal text, which
            produces a plausible-looking answer to a subtly wrong prompt.

    A placeholder that is *not* declared is left untouched rather than blanked.
    Prompts contain prose about code, and code contains braces; silently
    deleting something that merely looks like a placeholder would corrupt the
    prompt in a way nobody would think to look for.
    """
    missing = [
        variable.name
        for variable in asset.variables
        if variable.required and not variables.get(variable.name)
    ]
    if missing:
        message = (
            f"Prompt {asset.prompt_id!r} requires {', '.join(sorted(missing))}, "
            "which was not supplied."
        )
        raise ValidationError(
            message,
            details={"prompt_id": asset.prompt_id, "missing": sorted(missing)},
        )

    declared = {variable.name for variable in asset.variables}

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in declared:
            return match.group(0)
        return variables.get(name, "")

    return _PLACEHOLDER.sub(substitute, asset.template)
