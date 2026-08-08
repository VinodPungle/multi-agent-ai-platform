"""Azure AI Foundry inference provider.

The platform's first production provider, and the test of everything built
before it: if the abstraction is real, adding this changed no agent, no runtime
code and no business logic — only configuration and this package.

It did. The gateway (ADR-0006), the runtime (ADR-0009) and the tool loop
(ADR-0010) are untouched by this milestone.

Containment
    This module and `agent_platform.security.credentials` are the only places
    `azure.*` may be imported. Every Azure type is converted at the boundary:
    what leaves this file is `CompletionResponse`, `CompletionChunk`,
    `ComponentHealth` and `ProviderError`, all provider-neutral.

Authentication
    `DefaultAzureCredential`. No API key is accepted, stored or logged — the
    same code authenticates with the Azure CLI locally and Managed Identity in
    Azure. See `security/credentials.py`.

Model neutrality
    Nothing here names a model. The deployment is configuration, so pointing at
    Gemma 4, GPT, DeepSeek or Cohere is an environment variable. That is the
    property this whole architecture exists to have, and it is why this file
    reads the same whichever model answers.

Scale-to-zero
    A Managed Compute deployment that has scaled to zero takes tens of seconds to
    answer its first request while an instance starts. The timeout policy has to
    accommodate that or every cold start looks like an outage, which is why
    `AzureFoundrySettings.cold_start_timeout_seconds` exists and is generous.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import (
    AssistantMessage,
    ChatCompletionsToolCall,
    ChatCompletionsToolDefinition,
    FunctionCall,
    FunctionDefinition,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from azure.core.credentials_async import AsyncTokenCredential
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceResponseError,
)

from agent_platform.exceptions.base import ConfigurationError, ProviderError
from agent_platform.security.credentials import COGNITIVE_SERVICES_SCOPE
from agent_platform.telemetry.logging import get_logger
from agent_platform_sdk.contracts.execution_context import ExecutionContext
from agent_platform_sdk.contracts.health import ComponentHealth
from agent_platform_sdk.dto.completion import (
    CompletionChunk,
    CompletionRequest,
    CompletionResponse,
    TokenUsage,
)
from agent_platform_sdk.dto.message import Message, ToolCall
from agent_platform_sdk.dto.model import ModelDescriptor, ModelPricing
from agent_platform_sdk.types.enums import Capability, HealthStatus, MessageRole

__all__ = ["AzureFoundryProvider"]

_logger = get_logger(__name__)

#: Tokens are billed per million. Pricing is configuration, never hardcoded:
#: rates change, differ by region, and are negotiated per customer.
_TOKENS_PER_PRICING_UNIT = Decimal(1_000_000)


@dataclass
class _PartialToolCall:
    """A tool call being assembled from streamed fragments.

    Mutable and private on purpose: it exists only between the first fragment
    and the terminal chunk, and never leaves this module. The immutable
    :class:`ToolCall` is what the rest of the platform sees.
    """

    call_id: str
    name: str = ""
    arguments: str = ""


class AzureFoundryProvider:
    """Inference against an Azure AI Foundry deployment.

    Satisfies :class:`~agent_platform_sdk.interfaces.llm_provider.LLMProvider`
    structurally — it inherits nothing, per ADR-0004.
    """

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        model_id: str,
        credential: AsyncTokenCredential,
        provider_id: str = "azure-foundry",
        max_context_tokens: int = 128_000,
        max_output_tokens: int = 4_096,
        input_cost_per_million_tokens: Decimal = Decimal(0),
        output_cost_per_million_tokens: Decimal = Decimal(0),
        supports_tools: bool = True,
        # S107: "token" here is a model output-length parameter name, not a credential.
        output_token_parameter: str = "max_tokens",  # noqa: S107
        client: ChatCompletionsClient | None = None,
    ) -> None:
        """Create the provider.

        Args:
            endpoint: Foundry endpoint, e.g.
                ``https://<resource>.services.ai.azure.com/models``.
            deployment: Deployment name to invoke. This is what makes the model
                a configuration value.
            model_id: Platform-wide model identifier this deployment serves.
            credential: Async token credential. Injected rather than constructed
                so tests never touch the credential chain and so a future
                deployment can supply a narrower identity.
            provider_id: Identifier it registers under.
            max_context_tokens: Declared on the model descriptor.
            max_output_tokens: Declared on the model descriptor.
            input_cost_per_million_tokens: Published input rate.
            output_cost_per_million_tokens: Published output rate.
            supports_tools: Whether the deployed model can call tools. A
                configuration value because it varies per model, not per
                provider — claiming it universally would make the runtime route
                tool work to a model that silently ignores it.
            output_token_parameter: Which parameter caps generated tokens.
                `max_tokens` for most models, `max_completion_tokens` for
                reasoning models, which reject the former outright. Found by a
                live call — every mock accepted `max_tokens` happily.
            client: Injected client. Tests supply a fake so the whole adapter is
                exercised without a network call or a credential.
        """
        self._endpoint = endpoint.rstrip("/")
        self._deployment = deployment
        self._model_id = model_id
        self._credential = credential
        self._provider_id = provider_id
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens
        self._input_cost = input_cost_per_million_tokens
        self._output_cost = output_cost_per_million_tokens
        self._supports_tools = supports_tools
        self._output_token_parameter = output_token_parameter
        self._client = client
        self._owns_client = client is None

    # -- Provider ----------------------------------------------------------

    @property
    def provider_id(self) -> str:
        """Identifier this provider is registered under."""
        return self._provider_id

    async def initialize(self) -> None:
        """Open the inference client.

        Deliberately does *not* call the endpoint. A startup probe against a
        scale-to-zero deployment would wake an instance on every process start —
        turning a cost-saving feature into a cost, and making a rolling restart
        an unnecessary spend. Connectivity is proven by the first real request,
        and reported by :meth:`health_check`.

        Raises:
            ConfigurationError: the endpoint is missing or malformed.
        """
        if not self._endpoint or not self._endpoint.startswith("https://"):
            message = (
                f"Azure AI Foundry endpoint must be an https URL. Got {self._endpoint!r}. "
                "Set PLATFORM_AZURE_FOUNDRY__ENDPOINT to the endpoint shown in the "
                "Foundry portal."
            )
            raise ConfigurationError(message, details={"provider_id": self._provider_id})

        if self._client is None:
            self._client = ChatCompletionsClient(
                endpoint=self._endpoint,
                credential=self._credential,
                credential_scopes=[COGNITIVE_SERVICES_SCOPE],
            )

        _logger.info(
            "provider.initialized",
            provider_id=self._provider_id,
            model_id=self._model_id,
            deployment=self._deployment,
            # The endpoint is a resource identifier, not a secret, and is the
            # first thing anyone needs when diagnosing a 401 or a 404.
            endpoint=self._endpoint,
            auth="DefaultAzureCredential",
        )

    async def health_check(self) -> ComponentHealth:
        """Report configuration readiness without calling the model.

        Deliberately not an inference call. A readiness probe that invoked the
        model would wake a scaled-to-zero deployment on every poll, bill for it,
        and fail this instance for an upstream outage it cannot fix.

        A caller that genuinely needs end-to-end proof should send a request; the
        gateway's retry and timeout policies then report the truth.
        """
        if self._client is None:
            return ComponentHealth(
                name=self._provider_id,
                status=HealthStatus.UNKNOWN,
                detail="Not initialised.",
            )

        return ComponentHealth(
            name=self._provider_id,
            status=HealthStatus.HEALTHY,
            detail=(
                f"Configured for deployment {self._deployment!r}. "
                "Connectivity is proven by the first request, not by this probe — "
                "polling a scale-to-zero deployment would keep it awake."
            ),
        )

    def supports(self, capability: Capability) -> bool:
        """Declare what the *deployed model* can do.

        Tool calling is configuration rather than a constant: one Foundry
        resource serves models that support it and models that do not, and
        claiming it universally would route tool work to a model that ignores it.
        """
        if capability is Capability.TOOL_CALLING:
            return self._supports_tools
        return capability in {Capability.STREAMING, Capability.COST_REPORTING}

    async def close(self) -> None:
        """Close the client and the credential.

        The credential holds its own HTTP session and token cache. Leaving it
        open leaks a connection pool per process restart in a long-lived host.
        """
        if self._client is not None and self._owns_client:
            await self._client.close()
        self._client = None

        if self._owns_client:
            await self._credential.close()

    # -- Inference ---------------------------------------------------------

    async def generate(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> CompletionResponse:
        """Produce a complete response.

        Raises:
            ProviderError: authentication, transport or service failure. The
                gateway's retry policy decides whether to try again.
        """
        del context
        client = self._require_client()

        try:
            completion = await client.complete(
                messages=self._to_azure_messages(request),
                model=self._deployment,
                temperature=request.temperature,
                top_p=request.top_p,
                stop=list(request.stop_sequences) or None,
                tools=self._to_azure_tools(request),
                stream=False,
                **self._output_token_kwargs(request),
            )
        except Exception as error:
            raise self._to_provider_error(error) from error

        choice = completion.choices[0] if completion.choices else None
        if choice is None:
            message = "Azure AI Foundry returned no choices."
            raise ProviderError(message, provider_id=self._provider_id)

        usage = self._to_usage(getattr(completion, "usage", None))

        return CompletionResponse(
            message=Message(
                role=MessageRole.ASSISTANT,
                content=choice.message.content or "",
                tool_calls=self._to_platform_tool_calls(choice.message),
            ),
            model_id=request.model_id,
            provider_id=self._provider_id,
            usage=usage,
            estimated_cost=self.estimate_cost(request.model_id, usage),
            finish_reason=self._to_finish_reason(choice.finish_reason),
            provider_metadata=self._provider_metadata(completion),
            model_metadata={
                "deployment": self._deployment,
                "served_model": str(getattr(completion, "model", "") or self._model_id),
            },
        )

    async def stream(
        self,
        request: CompletionRequest,
        context: ExecutionContext,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """Produce a response incrementally.

        Usage arrives only on the final update, and some deployments omit it
        entirely — so the terminal chunk carries whatever was reported, and the
        gateway fills in cost from whatever tokens it has.
        """
        del context
        client = self._require_client()

        try:
            updates = await client.complete(
                messages=self._to_azure_messages(request),
                model=self._deployment,
                temperature=request.temperature,
                top_p=request.top_p,
                stop=list(request.stop_sequences) or None,
                tools=self._to_azure_tools(request),
                stream=True,
                **self._output_token_kwargs(request),
            )
        except Exception as error:
            raise self._to_provider_error(error) from error

        usage = TokenUsage()
        finish_reason: str | None = None
        # Insertion-ordered, so the calls reach the model in the order it asked
        # for them. Fragments arrive across many updates and are assembled here.
        pending_calls: dict[str, _PartialToolCall] = {}
        last_call_id: str | None = None

        try:
            async for update in updates:
                reported = self._to_usage(getattr(update, "usage", None))
                if reported.total_tokens:
                    usage = reported

                choices = getattr(update, "choices", None) or []
                if not choices:
                    continue

                choice = choices[0]
                if choice.finish_reason:
                    finish_reason = self._to_finish_reason(choice.finish_reason)

                delta = getattr(choice, "delta", None)
                if delta is not None:
                    last_call_id = self._accumulate_tool_calls(delta, pending_calls, last_call_id)

                content = getattr(delta, "content", None) if delta else None
                if content:
                    yield CompletionChunk(delta=content)
        except Exception as error:
            raise self._to_provider_error(error) from error
        finally:
            # The SDK's streaming response holds an open HTTP connection.
            # Abandoning it — which is what "stop generating" does — leaks that
            # connection unless it is closed here.
            #
            # `aclose` first, and it is not a stylistic preference: the SDK's
            # `AsyncStreamingChatCompletions` defines only `aclose`. This looked
            # for `close`, found nothing, and silently closed nothing on every
            # stream. The test passed because the fake defined `close()` — a
            # double shaped to the code instead of to the thing it stands for.
            for name in ("aclose", "close"):
                closer = getattr(updates, name, None)
                if closer is not None:
                    await closer()
                    break

        tool_calls = tuple(
            ToolCall(call_id=partial.call_id, tool_id=partial.name, arguments=partial.arguments)
            for partial in pending_calls.values()
            # A fragment that never carried a function name is not a call the
            # runtime can dispatch. Emitting it would fail tool resolution with
            # an empty id rather than saying the stream was incomplete.
            if partial.name
        )

        yield CompletionChunk(
            delta="",
            tool_calls=tool_calls,
            # `tool_calls` is the honest reason when the model asked for tools:
            # some deployments report `stop` on the terminal update regardless.
            finish_reason=("tool_calls" if tool_calls else finish_reason or "stop"),
            usage=usage,
        )

    async def count_tokens(self, request: CompletionRequest) -> TokenUsage:
        """Estimate prompt tokens.

        An approximation, and documented as one. The exact count depends on the
        deployed model's tokeniser, which is not exposed by the inference API —
        so this is a budget guard, never a billing figure. Real usage comes back
        on the response.
        """
        text = "\n".join(
            [request.system_prompt or "", *(message.content for message in request.messages)]
        )
        return TokenUsage(prompt_tokens=max(0, len(text) // 4))

    def estimate_cost(self, model_id: str, usage: TokenUsage) -> Decimal:
        """Return the estimated cost of ``usage``.

        Computed from configured pricing rather than read from the service,
        because the inference API does not report spend. Rates default to zero,
        so an unconfigured deployment reports zero cost rather than a fabricated
        number that would flow into cost dashboards as if it were real.
        """
        del model_id

        return (
            Decimal(usage.prompt_tokens) * self._input_cost
            + Decimal(usage.completion_tokens) * self._output_cost
        ) / _TOKENS_PER_PRICING_UNIT

    async def list_models(self) -> tuple[ModelDescriptor, ...]:
        """Return the model this provider is configured to serve.

        One deployment, one model. Enumerating the resource's whole catalogue
        would advertise models this provider is not pointed at and cannot serve.
        """
        capabilities = {Capability.STREAMING, Capability.COST_REPORTING}
        if self._supports_tools:
            capabilities.add(Capability.TOOL_CALLING)

        return (
            ModelDescriptor(
                model_id=self._model_id,
                provider_id=self._provider_id,
                display_name=self._model_id,
                deployment_name=self._deployment,
                endpoint=self._endpoint,
                capabilities=frozenset(capabilities),
                max_context_tokens=self._max_context_tokens,
                max_output_tokens=self._max_output_tokens,
                pricing=ModelPricing(
                    input_cost_per_million_tokens=self._input_cost,
                    output_cost_per_million_tokens=self._output_cost,
                ),
            ),
        )

    # -- Translation -------------------------------------------------------

    def _require_client(self) -> ChatCompletionsClient:
        """Return the client, or fail with an actionable message."""
        if self._client is None:
            message = (
                f"Provider {self._provider_id!r} was not initialised. "
                "This is a wiring error: initialise() runs during application startup."
            )
            raise ProviderError(message, provider_id=self._provider_id)
        return self._client

    def _output_token_kwargs(self, request: CompletionRequest) -> dict[str, Any]:
        """Return the output-token cap under the name this model accepts.

        Not cosmetic. A live call against a reasoning model returned HTTP 400 for
        `max_tokens`, which every mock had accepted without complaint — the
        parameter is simply rejected rather than ignored. Models that want
        `max_completion_tokens` get it through `model_extras`, which is the SDK's
        pass-through for parameters it does not model directly.

        Nothing is sent when the caller set no cap: an explicit `None` is not the
        same as absent to the service.
        """
        if request.max_output_tokens is None:
            return {}

        if self._output_token_parameter == "max_tokens":  # noqa: S105 — a parameter name
            return {"max_tokens": request.max_output_tokens}

        return {"model_extras": {self._output_token_parameter: request.max_output_tokens}}

    @staticmethod
    def _to_azure_messages(request: CompletionRequest) -> list[Any]:
        """Convert platform messages into the SDK's message types.

        The system prompt is prepended here rather than carried as a message by
        the caller, which is exactly why `CompletionRequest.system_prompt` is a
        separate field: each provider places it where its own API expects.
        """
        messages: list[Any] = []

        if request.system_prompt:
            messages.append(SystemMessage(content=request.system_prompt))

        for message in request.messages:
            if message.role is MessageRole.USER:
                messages.append(UserMessage(content=message.content))
            elif message.role is MessageRole.ASSISTANT:
                # Tool calls must survive the round trip. A tool result is only
                # valid if the transcript contains the assistant turn that asked
                # for it: dropping them here left a `ToolMessage` answering a
                # question nobody had asked, and the service rejected the whole
                # conversation with an HTTP 400. The tool had already run by
                # then, so the cost was paid and the answer thrown away.
                messages.append(
                    AssistantMessage(
                        content=message.content,
                        tool_calls=[
                            ChatCompletionsToolCall(
                                id=call.call_id,
                                function=FunctionCall(name=call.tool_id, arguments=call.arguments),
                            )
                            for call in message.tool_calls
                        ]
                        or None,
                    )
                )
            elif message.role is MessageRole.TOOL:
                # `tool_call_id` is what pairs a result with the call that asked
                # for it. Without it the service rejects the conversation.
                messages.append(
                    ToolMessage(content=message.content, tool_call_id=message.tool_call_id or "")
                )
            elif message.role is MessageRole.SYSTEM:
                messages.append(SystemMessage(content=message.content))

        return messages

    def _to_azure_tools(self, request: CompletionRequest) -> list[Any] | None:
        """Declare the requested tools to the service.

        The platform's tool *descriptors* live in the tool registry, which this
        provider must not reach into — a provider that read the registry would
        couple inference to tooling. The runtime therefore passes tool ids, and
        until the descriptor travels on the request there is nothing to declare.

        Returns ``None`` when there is nothing to send, because an empty list is
        not the same as absent to the service.
        """
        if not self._supports_tools:
            return None

        if request.tools:
            return [
                ChatCompletionsToolDefinition(
                    function=FunctionDefinition(
                        name=descriptor.tool_id,
                        description=descriptor.description,
                        parameters=dict(descriptor.input_schema),
                    )
                )
                for descriptor in request.tools
            ]

        if not request.tool_ids:
            return None

        # Ids without declarations. Kept as a fallback for a caller that has not
        # resolved descriptors, but it is close to useless and says so: a model
        # told only that `internet-search` exists, with no parameters, either
        # never calls it or calls it with nothing and the invocation fails
        # validation. Some deployments reject an empty schema outright with an
        # HTTP 400, which is how this was found.
        _logger.warning(
            "provider.tools_declared_without_schemas",
            provider_id=self._provider_id,
            tool_ids=list(request.tool_ids),
            detail=(
                "Tool ids arrived without descriptors. The model cannot be told "
                "what arguments these tools take."
            ),
        )
        return [
            ChatCompletionsToolDefinition(
                function=FunctionDefinition(
                    name=tool_id,
                    description=f"Platform tool {tool_id}.",
                    parameters={"type": "object", "properties": {}},
                )
            )
            for tool_id in request.tool_ids
        ]

    @staticmethod
    def _to_platform_tool_calls(message: Any) -> tuple[ToolCall, ...]:  # noqa: ANN401 - SDK type
        """Convert SDK tool calls into platform ones."""
        calls = getattr(message, "tool_calls", None) or []
        converted: list[ToolCall] = []

        for call in calls:
            function = getattr(call, "function", None)
            if function is None:
                continue
            converted.append(
                ToolCall(
                    call_id=str(getattr(call, "id", "") or ""),
                    tool_id=str(getattr(function, "name", "") or ""),
                    # Arguments stay a raw string: models emit malformed JSON
                    # often enough that parsing must be a validation step the
                    # runtime controls.
                    arguments=str(getattr(function, "arguments", "") or ""),
                )
            )

        return tuple(converted)

    @staticmethod
    def _accumulate_tool_calls(
        delta: Any,  # noqa: ANN401 - SDK type
        pending: dict[str, _PartialToolCall],
        last_call_id: str | None,
    ) -> str | None:
        """Fold one update's tool-call fragments into ``pending``.

        A streamed tool call does not arrive whole. The first fragment carries
        the id and function name; the arguments follow as a series of string
        pieces that mean nothing until concatenated — a JSON object split
        mid-token. Assembling them is the provider's job, because it is the only
        layer that knows this wire format.

        Fragments after the first often omit the id, identifying their call only
        by position, so an id-less fragment continues the call most recently
        seen. Guessing wrong here concatenates two calls' arguments into one
        unparseable string, which is why the id is preferred whenever present.

        Returns:
            The call id these fragments belonged to, to continue from next time.
        """
        for update in getattr(delta, "tool_calls", None) or []:
            call_id = str(getattr(update, "id", "") or "") or last_call_id
            if call_id is None:
                continue

            partial = pending.setdefault(call_id, _PartialToolCall(call_id=call_id))

            function = getattr(update, "function", None)
            if function is not None:
                name = getattr(function, "name", None)
                if name:
                    partial.name = str(name)
                arguments = getattr(function, "arguments", None)
                if arguments:
                    partial.arguments += str(arguments)

            last_call_id = call_id

        return last_call_id

    @staticmethod
    def _to_finish_reason(reason: Any) -> str | None:  # noqa: ANN401 - SDK enum
        """Convert the SDK's finish reason into the platform's vocabulary.

        `str()` on the SDK enum yields `CompletionsFinishReason.STOPPED` — the
        member repr, not the wire value. That string reached the public API
        response body, putting an Azure type name in front of every client and
        breaking provider neutrality in the one place it is most visible.

        `.value` is the OpenAI-shaped vocabulary the platform already speaks
        (`stop`, `length`, `content_filter`, `tool_calls`), so no translation
        table is needed — only the discipline to read it instead of the repr.

        Only a live call exposed this: the mock returns plain strings, so every
        test and every local run looked correct.

        An unrecognised reason passes through lowercased rather than being
        dropped or forced to `stop`. A reason we have not seen is information;
        inventing a successful one hides a truncated answer.
        """
        if not reason:
            return None

        return str(getattr(reason, "value", reason)).strip().lower()

    @staticmethod
    def _to_usage(usage: Any) -> TokenUsage:  # noqa: ANN401 - SDK type
        """Convert SDK usage into platform usage, tolerating its absence."""
        if usage is None:
            return TokenUsage()
        return TokenUsage(
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )

    @staticmethod
    def _provider_metadata(completion: Any) -> dict[str, str]:  # noqa: ANN401 - SDK type
        """Flatten provider-side facts worth keeping into strings.

        Strings only, and only these: the upstream request id is what an Azure
        support case needs. Nothing here may become a place an SDK object hides.
        """
        metadata: dict[str, str] = {}

        upstream_id = getattr(completion, "id", None)
        if upstream_id:
            metadata["upstream_id"] = str(upstream_id)

        return metadata

    def _to_provider_error(self, error: Exception) -> ProviderError:
        """Map an SDK exception onto a platform error with an actionable message.

        Authentication and configuration failures get specific guidance because
        they are the two that actually happen during setup, and the SDK's own
        messages for them are famously unhelpful — a bare 401 says nothing about
        which of five credential sources was tried.

        The original message is never included: it can carry the endpoint,
        headers and token fragments, and this text reaches an HTTP client.
        """
        if isinstance(error, ClientAuthenticationError):
            message = (
                "Azure authentication failed. Locally, run `az login` and confirm the "
                "subscription with `az account show`. In Azure, confirm the Managed "
                "Identity has the 'Cognitive Services User' role on the Foundry resource."
            )
            return ProviderError(message, provider_id=self._provider_id)

        if isinstance(error, HttpResponseError):
            status = getattr(error, "status_code", None)
            if status == 404:
                message = (
                    f"Deployment {self._deployment!r} was not found at this endpoint. "
                    "Check PLATFORM_AZURE_FOUNDRY__DEPLOYMENT against the deployment "
                    "name in the Foundry portal — it is the deployment name, not the "
                    "model name."
                )
            elif status == 429:
                message = (
                    "Azure AI Foundry rate limit reached. The gateway will retry with "
                    "backoff; sustained 429s mean the deployment needs more capacity."
                )
            else:
                message = f"Azure AI Foundry returned HTTP {status}."
            return ProviderError(
                message,
                provider_id=self._provider_id,
                details={"status_code": status},
            )

        if isinstance(error, ServiceRequestError | ServiceResponseError):
            message = (
                "Could not reach Azure AI Foundry. If the deployment uses Managed "
                "Compute with scale-to-zero, the first request after idling can take "
                "tens of seconds while an instance starts."
            )
            return ProviderError(message, provider_id=self._provider_id)

        return ProviderError(
            f"Azure AI Foundry call failed: {type(error).__name__}.",
            provider_id=self._provider_id,
            details={"error_type": type(error).__name__},
        )
