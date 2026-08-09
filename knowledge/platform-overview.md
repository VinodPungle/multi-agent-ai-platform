# Multi-Agent AI Platform Overview

The platform hosts multiple collaborating AI agents. It is not a chatbot: it is
reusable infrastructure on which chatbots, research assistants and automation
agents are configured rather than written.

## Agent Runtime

The Agent Runtime owns the request lifecycle. It validates the agent, loads
conversation memory, assembles the prompt, chooses a model through the router,
enforces budget policy, executes the turn through a workflow engine, records
evaluation metadata, and stores the result.

Agents never call infrastructure directly. An agent reasons within its domain
and the runtime does everything else, which is why adding an agent is a
configuration change rather than a code change.

## Agent collaboration

Agents never call each other directly. Delegation is a tool, so the runtime
mediates every hop and applies authorisation, timeouts, retries, telemetry and
budgets to it. Delegation depth is carried on the execution context and refused
at the configured limit, so a cycle of agents delegating to one another
terminates.

## Model routing

Models are chosen by policy rather than hardcoded. A chain of constraints —
availability, capability, context window — removes models that cannot serve a
turn, and a ranking policy orders the rest according to the configured
objective: balanced, lowest cost, largest context, or highest capability.

Every routing decision records the policy that made it, the reason, and the
models that were considered.

## Memory

Conversation memory is a platform capability, not an agent capability. The
in-process provider is per-replica and lost on restart; the Redis provider is
durable and shared between replicas, and authenticates with a Managed Identity
token rather than an access key.

A memory backend that is unavailable degrades the turn rather than failing it:
the user loses history, which is visible and survivable, instead of losing the
answer.

## Tools

Tools are executed by the runtime, never by an agent. Internet search, knowledge
search, agent delegation and any tool hosted on a Model Context Protocol server
all run through one pipeline, so authorisation, validation, timeout, retry,
telemetry and budget enforcement are implemented once.
