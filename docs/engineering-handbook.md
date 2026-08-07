# Engineering Handbook

**Project:** Enterprise Multi-Agent AI Platform

**Version:** 1.0

**Status:** Active

---

# Purpose

This handbook defines the engineering standards, development workflow, coding conventions, quality expectations, and contribution process for the Enterprise Multi-Agent AI Platform.

It applies equally to:

* Human developers
* Claude Code
* OpenAI Codex
* GitHub Copilot
* Future AI coding assistants

When this handbook conflicts with convenience, the handbook takes precedence.

---

# Engineering Philosophy

This platform is intended to evolve for years.

Every design decision should optimize for long-term maintainability rather than short-term speed.

Priorities:

1. Correctness
2. Simplicity
3. Maintainability
4. Extensibility
5. Security
6. Observability
7. Performance
8. Cost

---

# Engineering Principles

Every contributor should follow these principles.

## SOLID

Every module should satisfy SOLID principles.

Prefer small focused classes.

Avoid large utility classes.

---

## Clean Architecture

Business logic must never depend on infrastructure.

Dependencies always point inward.

Infrastructure should be replaceable.

---

## High Cohesion

Each package owns a single responsibility.

Avoid "misc" or "utils" dumping grounds.

---

## Loose Coupling

Communicate through interfaces.

Never couple business logic directly to Azure SDKs or third-party APIs.

---

## Configuration over Code

Behavior should be changed using configuration whenever practical.

Avoid recompilation or code modification for operational changes.

---

## Composition over Inheritance

Favor composition unless inheritance clearly improves clarity.

---

## Explicit Dependencies

All dependencies should be constructor injected.

Never create infrastructure objects directly inside business logic.

---

## Fail Fast

Validate configuration during startup.

Invalid configuration should stop application startup.

---

## Observability by Default

Every feature must answer:

* How is it logged?
* How is it traced?
* How is it monitored?
* How is it measured?

---

# Repository Standards

The repository should be understandable by a new engineer within one day.

Every top-level directory should have a clear purpose.

Recommended structure:

```
multi-agent-ai-platform/

.claude/

docs/

infra/

prompts/

src/

tests/

docker/

tools/
```

---

# Directory Responsibilities

## docs/

Architecture

Runbooks

Design Decisions

Developer Guides

Deployment Guides

---

## infra/

Infrastructure as Code

Azure Developer CLI

Bicep

Deployment Scripts

Environment Configuration

---

## prompts/

Versioned prompts

Agent prompts

System prompts

Evaluation prompts

Shared prompt fragments

---

## src/

Production code only.

Never place documentation or deployment scripts here.

---

## tests/

Automated tests only.

Mirror production package structure whenever practical.

---

# Branch Strategy

Main

Production-ready code.

Develop

Integration branch (optional).

Feature branches

```
feature/<feature-name>
```

Bug fixes

```
fix/<issue-name>
```

Documentation

```
docs/<topic>
```

Infrastructure

```
infra/<component>
```

Refactoring

```
refactor/<component>
```

---

# Commit Standards

Use conventional, descriptive commits.

Examples:

```
feat(runtime): add workflow execution engine

feat(provider): implement Azure AI Foundry provider

fix(memory): handle empty conversation state

docs: update architecture diagrams

refactor(agent): simplify runtime lifecycle
```

Avoid generic messages such as:

* Update
* Changes
* Fixes
* Misc

---

# Pull Request Expectations

Every pull request must include:

* Summary
* Motivation
* Architecture impact
* Testing performed
* Documentation updates
* Deployment impact
* Risk assessment
* Rollback strategy (if applicable)

---

# Documentation Standards

Every major feature requires:

* Design explanation
* Usage guide
* Configuration reference
* Sequence diagram (if applicable)
* ADR for significant architectural decisions

Use Mermaid for diagrams.

---

# Naming Standards

Use descriptive names.

Good:

* AgentRuntime
* WorkflowEngine
* ModelRegistry
* PromptRepository
* EvaluationService

Avoid:

* Util
* Helper
* Manager
* Thing
* Misc
* Common

---

# Code Organization

Each module should contain one primary responsibility.

Example:

```
runtime/

execution/

policies/

events/

registries/

providers/

memory/
```

Avoid deeply nested packages without a clear reason.

---

# Design Reviews

Before implementing any major feature, answer:

1. Does it fit Clean Architecture?
2. Can it be replaced independently?
3. Is configuration externalized?
4. Is it testable?
5. Is it observable?
6. Is it secure?
7. Is it documented?
8. Does it increase unnecessary complexity?

If any answer is "No", revisit the design.

---

# Engineering Quality Checklist

Every completed feature should satisfy:

✓ Architecture reviewed

✓ Interfaces defined

✓ Configuration externalized

✓ Logging added

✓ Telemetry added

✓ Tests added

✓ Documentation updated

✓ Security reviewed

✓ Cost implications considered

✓ Ready for code review

This checklist forms the minimum engineering quality bar for the project.

# Backend Engineering Standards

---

# Technology Stack

The backend technology stack is standardized.

Python 3.12+

FastAPI

Pydantic v2

LangGraph

LangChain

dependency-injector

Azure AI Foundry SDK

OpenTelemetry

structlog

uv

pytest

Ruff

Black

mypy

Avoid introducing new libraries unless they provide significant architectural value.

---

# Project Structure

The backend follows a feature-oriented Clean Architecture.

```text
backend/

api/
application/
domain/
runtime/
workflow/
agents/
providers/
registries/
memory/
tools/
prompts/
evaluation/
telemetry/
configuration/
security/
storage/
events/
exceptions/
factories/
dependencies/
```

Business logic belongs in `application` and `domain`.

Infrastructure-specific code belongs in `providers`, `storage`, and `security`.

---

# Python Standards

Use:

* Python 3.12+
* Type hints everywhere
* dataclasses where appropriate
* Pydantic models for API contracts
* pathlib instead of os.path
* context managers for resources
* enums instead of magic strings
* Protocols for interfaces where suitable

Avoid:

* Global mutable state
* Circular imports
* Dynamic attribute creation
* Hidden side effects

---

# Dependency Injection

Use constructor injection.

Never instantiate providers directly inside services.

Example:

Good:

```python
class ChatService:

    def __init__(
        self,
        llm_provider: LLMProvider,
        memory_provider: MemoryProvider,
    ):
        ...
```

Avoid:

```python
provider = AzureFoundryProvider()
```

inside business logic.

Use `dependency-injector` to wire implementations.

---

# FastAPI Standards

One router per feature.

Examples:

```text
/api/v1/chat
/api/v1/agents
/api/v1/models
/api/v1/tools
```

Use dependency injection for request-scoped services.

Use async endpoints.

Validate requests with Pydantic.

Generate OpenAPI automatically.

Version all public APIs.

---

# Async Programming

Use async for:

* HTTP requests
* Azure SDK calls
* Tool execution
* Streaming
* Database operations
* Search providers

Never block the event loop with synchronous I/O.

Use `asyncio.TaskGroup` (Python 3.11+) where parallel execution is appropriate.

---

# Error Handling

Create a hierarchy of custom exceptions.

Examples:

ConfigurationError

ValidationError

ProviderError

ToolExecutionError

MemoryError

PolicyViolationError

WorkflowError

Convert exceptions to consistent API responses.

Never expose stack traces to clients.

Always log the original exception.

---

# Logging

Use `structlog`.

Never use `print()`.

Every log entry should include:

* Correlation ID
* Request ID
* Conversation ID
* Session ID
* Agent ID
* Provider
* Model
* Latency
* Severity

Never log secrets or sensitive user data.

---

# OpenTelemetry

Instrument:

* Incoming requests
* Agent execution
* Workflow execution
* LLM calls
* Tool execution
* Memory operations
* Search operations

Every span should include useful attributes for troubleshooting.

Integrate with Azure Application Insights.

---

# LangGraph Conventions

Keep graphs small and composable.

Each graph should have a single responsibility.

Avoid deeply nested graph logic.

Represent state using typed models.

Separate graph construction from graph execution.

---

# Provider Implementations

Provider implementations must:

* Implement the common interface
* Contain no business logic
* Be stateless where practical
* Handle retries and provider-specific concerns
* Translate provider responses into platform contracts

Do not expose provider SDK types outside the provider package.

---

# Configuration

Configuration should be loaded once at startup.

Use strongly typed configuration classes.

Validate all required values.

Do not access environment variables directly throughout the codebase.

---

# Testing Strategy

Use pytest.

Testing pyramid:

* Unit Tests
* Integration Tests
* End-to-End Tests (critical workflows)

Mock provider interfaces rather than cloud SDKs whenever possible.

Avoid network access in unit tests.

---

# Performance

Prefer asynchronous APIs.

Reuse HTTP clients.

Avoid repeated object creation in hot paths.

Measure before optimizing.

Track:

* Time to First Token
* Total latency
* Token usage
* Tool latency

---

# Security

Use Azure DefaultCredential where possible.

Use Managed Identity in Azure.

Store secrets in Azure Key Vault.

Validate all user input.

Sanitize logs.

Follow the principle of least privilege.

---

# Backend Definition of Done

A backend feature is complete only when:

✓ Architecture follows project standards

✓ Interfaces are defined

✓ Dependency injection is used

✓ Configuration is externalized

✓ Async implementation is used where appropriate

✓ Logging is added

✓ OpenTelemetry spans are added

✓ Unit tests are written

✓ Integration tests are written (where applicable)

✓ Documentation is updated

✓ Code passes Ruff, Black, mypy, and pytest

Only then is the feature ready for review.

# Frontend Engineering Standards

---

# Vision

The frontend is an AI Platform Portal.

The chat interface is one module within the platform.

Future modules include:

* Chat
* Agents
* Models
* Prompts
* Evaluations
* Cost Dashboard
* Settings
* Administration
* Monitoring

The architecture should support these additions without major refactoring.

---

# Technology Stack

React 19

TypeScript 5

Vite

TailwindCSS

shadcn/ui

React Router

TanStack Query

React Hook Form

Zod

ESLint

Prettier

Vitest

Playwright

---

# Frontend Architecture

Use a feature-based structure.

```text
frontend/

src/

app/

components/

features/

hooks/

layouts/

services/

api/

contexts/

config/

types/

utils/

styles/

assets/
```

Avoid organizing by file type alone.

Group related functionality into feature modules.

---

# Component Design

Prefer small, composable components.

Separate:

Presentation

↓

Business Logic

↓

Data Fetching

↓

State Management

Avoid large "God Components."

---

# Design System

Use shadcn/ui components as the foundation.

Extend them rather than replacing them.

Follow consistent:

Spacing

Typography

Colors

Icons

Responsive behavior

Accessibility

Avoid ad-hoc styling.

---

# State Management

Use local component state by default.

Use React Context for shared UI state.

Use TanStack Query for:

* API requests
* Caching
* Background refresh
* Mutations

Avoid global state unless clearly justified.

---

# API Layer

All backend communication goes through a centralized API client.

Responsibilities:

Authentication

Error handling

Retries

Request IDs

Streaming

Timeouts

Avoid calling fetch() directly throughout the application.

---

# Streaming

Use Server-Sent Events (SSE) for streaming responses.

Responsibilities:

Open connection

Handle reconnects

Display partial responses

Support cancellation

Capture streaming metrics

The streaming implementation should be isolated from UI components.

---

# Chat Module

Initial capabilities:

Streaming responses

Markdown

Syntax highlighting

Code copy button

Auto-scroll

Typing indicator

Conversation history

Dark mode

Error handling

Regenerate response

Stop generation

Future:

Conversation folders

Pinned chats

Conversation search

Export

Sharing

---

# Accessibility

Every feature should satisfy:

Keyboard navigation

Screen reader compatibility

Sufficient color contrast

Accessible form labels

Meaningful error messages

Use semantic HTML whenever possible.

---

# Performance

Lazy-load feature modules.

Code-split large bundles.

Optimize images and assets.

Avoid unnecessary re-renders.

Measure before optimizing.

---

# Error Handling

Provide consistent error experiences.

Never expose backend implementation details.

Offer retry actions where appropriate.

Log client-side errors for diagnostics.

---

# Frontend Testing

Testing strategy:

Unit Tests (Vitest)

Component Tests

Integration Tests

End-to-End Tests (Playwright)

Critical user journeys should be covered by automated tests.

---

# Docker

Frontend should run in Docker during local development.

Support:

Hot reload

Environment variables

Proxy to backend

Consistent development experience

---

# Azure Deployment

Frontend should be deployable to Azure Container Apps.

Configuration should be environment-specific.

Avoid rebuilding the application for configuration changes where possible.

---

# GitHub Actions

Frontend pipeline:

Install dependencies

Type checking

Lint

Unit tests

Build

Artifact creation

Deployment (environment dependent)

---

# Quality Standards

Every frontend feature should include:

✓ Responsive layout

✓ Accessibility review

✓ Error handling

✓ Loading states

✓ Empty states

✓ Automated tests

✓ Documentation updates

✓ Performance considerations

Only then is the feature ready for review.

---

# DevOps Engineering Standards

---

# Infrastructure as Code

Use:

Bicep

Azure Developer CLI (azd)

Infrastructure must be:

Repeatable

Version controlled

Environment aware

---

# CI/CD

Every pull request should execute:

Formatting

Linting

Type checking

Unit tests

Integration tests

Docker build

Infrastructure validation

Security scanning

No failing pipeline should be merged.

---

# Container Standards

Containers should be:

Stateless

Small

Secure

Reproducible

Use multi-stage Docker builds.

Run as non-root where practical.

---

# Dependency Management

Backend:

uv

Frontend:

npm (or pnpm if adopted consistently)

Regularly update dependencies.

Use Dependabot for automated update proposals.

---

# Security

Enable automated dependency scanning.

Review high-severity vulnerabilities promptly.

Store secrets outside source control.

Validate container images before deployment.

---

# Environment Management

Support:

Development

Testing

Staging

Production

Each environment should have:

Independent configuration

Independent secrets

Independent telemetry

Independent deployment pipeline

---

# Monitoring

Monitor:

Deployment success

Application health

Container health

Response times

Error rates

Availability

Future dashboards should include AI-specific operational metrics.

---

# Release Management

Prefer incremental releases.

Document breaking changes.

Maintain release notes.

Tag production releases.

Support rollback procedures.

---

# DevOps Definition of Done

A deployment is considered production-ready only when:

✓ Infrastructure provisions successfully

✓ Application deploys successfully

✓ Health checks pass

✓ Monitoring is active

✓ Logs are visible

✓ Metrics are collected

✓ Security validation passes

✓ Rollback procedure is documented

# AI Engineering Playbook

---

# Engineering Workflow

Every feature should follow the same lifecycle.

Requirements

↓

Architecture

↓

Interfaces

↓

Implementation

↓

Tests

↓

Documentation

↓

Review

↓

Deployment

Never skip a stage.

---

# Engineering Story Template

Every significant feature should start with:

## Objective

What problem is being solved?

## Scope

What is included?

What is excluded?

## Architecture

Which components are affected?

## Interfaces

What contracts are required?

## Risks

Potential technical risks.

## Acceptance Criteria

How will success be measured?

---

# Agent Development Checklist

When implementing a new agent:

✓ Create Agent Descriptor

✓ Create Agent Prompt

✓ Register Agent

✓ Configure Model

✓ Configure Memory

✓ Configure Tools

✓ Configure Policies

✓ Add Tests

✓ Add Documentation

✓ Update Architecture if needed

Never modify existing agents to add a new one.

---

# Provider Development Checklist

When implementing a new LLM provider:

✓ Implement LLMProvider interface

✓ Register Provider

✓ Register Models

✓ Add Authentication

✓ Add Health Check

✓ Add Streaming Support

✓ Add Token Usage Support (where available)

✓ Add Cost Estimation

✓ Add Tests

✓ Update Documentation

Business logic must remain unchanged.

---

# Tool Development Checklist

When implementing a new tool:

✓ Implement Tool interface

✓ Register Tool

✓ Define Input Schema

✓ Define Output Schema

✓ Define Permissions

✓ Define Timeout

✓ Define Retry Policy

✓ Add Tests

✓ Update Documentation

Agents must discover tools through the Tool Registry.

---

# Memory Provider Checklist

✓ Implement MemoryProvider

✓ Register Provider

✓ Add Configuration

✓ Add Tests

✓ Verify Compatibility

No agent changes required.

---

# Prompt Engineering Standards

Prompts are versioned assets.

Each prompt should include:

Prompt ID

Version

Purpose

Owner

Compatible Models

Variables

Examples (optional)

Store prompts in:

```text id="h5fggv"
prompts/
```

Never embed large prompts in Python code.

---

# AI Coding Workflow

Before generating code:

1. Read:

   * CLAUDE.md
   * project-spec.md
   * architecture.md
   * engineering-handbook.md

2. Explain the architecture.

3. Explain assumptions.

4. Identify risks.

5. Generate code.

6. Generate tests.

7. Explain how to run.

8. Explain how to validate.

9. Suggest Git commit message.

Then stop.

---

# Code Review Checklist

Every review should verify:

✓ Clean Architecture maintained

✓ SOLID respected

✓ Interfaces used

✓ Configuration externalized

✓ Dependency Injection used

✓ Logging implemented

✓ OpenTelemetry added

✓ Tests added

✓ Documentation updated

✓ Security reviewed

✓ Performance considered

✓ Cost implications considered

Reject changes that introduce tight coupling without clear justification.

---

# Pull Request Template

## Summary

## Motivation

## Architecture Impact

## Interfaces Added/Changed

## Tests

## Documentation

## Configuration Changes

## Deployment Impact

## Rollback Strategy

## Risks

---

# Performance Checklist

Review:

✓ Async implementation

✓ Efficient I/O

✓ Streaming performance

✓ Memory usage

✓ HTTP client reuse

✓ Database efficiency

✓ Token usage

✓ Provider latency

Measure before optimizing.

---

# Security Checklist

Review:

✓ Input validation

✓ Secret management

✓ Authentication

✓ Authorization readiness

✓ Least privilege

✓ Secure defaults

✓ Sensitive data protection

✓ Logging sanitization

---

# Documentation Checklist

Every feature should update:

Developer Guide

Architecture (if changed)

Configuration Reference

API Documentation

ADR (if applicable)

Runbook (if operationally significant)

---

# Definition of Done

A feature is complete only when:

✓ Requirements implemented

✓ Architecture respected

✓ Interfaces defined

✓ Tests pass

✓ Documentation updated

✓ Logs implemented

✓ Telemetry added

✓ Configuration externalized

✓ Security reviewed

✓ Performance considered

✓ Cost impact understood

✓ Code review completed

---

# AI Coding Rules

AI coding assistants should:

Prefer maintainability over brevity.

Prefer explicit code over clever code.

Avoid placeholders unless requested.

Avoid TODOs for core functionality.

Ask for clarification rather than making architectural assumptions.

Never bypass established abstractions.

---

# Common Anti-Patterns

Avoid:

❌ Business logic in providers

❌ Direct SDK calls from agents

❌ Hardcoded configuration

❌ Global mutable state

❌ Circular dependencies

❌ Duplicate abstractions

❌ Large utility classes

❌ Monolithic agents

❌ Hidden side effects

---

# Architecture Decision Records (ADR)

Create an ADR when introducing:

* New architectural patterns
* Major libraries
* Infrastructure changes
* Communication protocols
* Persistence technologies
* Authentication mechanisms

Template:

Title

Status

Context

Decision

Alternatives Considered

Consequences

References

Store ADRs in:

```text id="mqmjlwm"
docs/adr/
```

---

# Milestone Execution Workflow

For every milestone:

1. Review requirements.

2. Review architecture.

3. Implement interfaces.

4. Implement feature.

5. Write tests.

6. Update documentation.

7. Validate locally.

8. Commit changes.

9. Prepare for next milestone.

Do not skip milestones or implement future milestones prematurely.

---

# Continuous Improvement

Treat the platform as a long-lived product.

Refactor when architecture quality improves.

Record architectural decisions.

Measure outcomes.

Keep documentation synchronized with implementation.

Prefer incremental evolution over large rewrites.

---

# Engineering Culture

Every contribution should make the platform:

More maintainable

More extensible

More observable

More secure

More testable

More cost-efficient

Every engineer—human or AI—is responsible for leaving the codebase in a better state than they found it.
