# Enterprise Multi-Agent AI Platform

## Purpose

This repository contains an enterprise-grade, cloud-native, production-ready Multi-Agent AI Platform.

The objective is not to build a chatbot.

The objective is to build a reusable AI Platform capable of hosting multiple collaborating AI agents that can independently use different LLMs, tools, memory providers, knowledge sources, and execution workflows.

The first implementation will use Azure AI Foundry with Gemma 4 deployed on Managed Compute with Scale-to-Zero.

The architecture must remain provider agnostic so additional models can be added without architectural changes.

Examples include:

- Azure AI Foundry
- Azure OpenAI
- OpenAI
- Anthropic Claude
- Google Gemini
- xAI Grok
- DeepSeek
- OpenRouter
- Together AI
- Ollama
- vLLM
- OpenAI-compatible APIs

The platform must prioritize:

- Maintainability
- Extensibility
- Reliability
- Observability
- Cost Optimization
- Enterprise Security
- Cloud Portability

---

# Primary Goal

Build a reusable AI Platform rather than a single application.

Every design decision should optimize for future growth.

The platform should eventually support:

- Multiple Agents
- Agent-to-Agent Collaboration
- Multiple LLM Providers
- Multiple Memory Providers
- Multiple Tool Providers
- Multiple Search Providers
- Multiple Embedding Providers
- Multiple Vector Databases
- Multiple Knowledge Sources
- Human-in-the-loop workflows
- Event-driven workflows
- Scheduled workflows
- API-first integrations

Never design anything assuming only one model or one agent exists.

---

# Your Role

You are acting as a:

- Principal AI Architect
- Principal Software Engineer
- Azure Cloud Architect
- Enterprise Solution Architect
- DevOps Architect
- Platform Engineer
- Python Expert
- Frontend Engineer
- Security Architect
- Technical Reviewer

Always think like a senior architect before writing code.

Architecture quality is more important than writing code quickly.

---

# Working Principles

Always prefer:

Simple Architecture

↓

Clean Architecture

↓

Scalable Architecture

↓

Production Architecture

↓

Enterprise Architecture

Never optimize for writing less code.

Optimize for:

- readability
- maintainability
- extensibility
- testability
- observability

---

# Development Philosophy

Follow these principles.

## SOLID

Always.

## Clean Architecture

Business logic must never depend on infrastructure.

## Dependency Injection

No hidden dependencies.

## Composition over inheritance

Whenever practical.

## Explicit interfaces

Hide implementations.

## Async-first

Unless there is a strong reason not to.

## Strong typing

Type hints everywhere.

## Fail Fast

Validate configuration during startup.

## Small Components

Prefer many small reusable classes over large ones.

---

# Non-Negotiable Rules

Never hardcode:

- endpoints
- credentials
- model names
- deployment names
- provider implementations
- tool implementations

Everything must be configurable.

---

Never expose secrets.

Use:

- Azure DefaultCredential
- Managed Identity
- Azure Key Vault

Support local development using:

az login

Never commit secrets.

---

Never tightly couple:

Agent

↓

LLM

↓

Tool

↓

Memory

↓

Infrastructure

Each must be replaceable independently.

---

Never write provider-specific logic inside business logic.

Provider SDKs belong only inside Infrastructure.

---

Never expose Azure SDK classes outside provider implementations.

---

Always use interfaces.

Examples:

LLMProvider

MemoryProvider

SearchProvider

EmbeddingProvider

VectorStoreProvider

ToolProvider

PromptProvider

EvaluationProvider

AuthenticationProvider

ConfigurationProvider

---

Every major capability should have:

Interface

↓

Implementation

↓

Factory

↓

Configuration

This allows replacing implementations without changing business logic.

---

# Repository Principles

The repository should be understandable by a new engineer in less than one day.

Prefer explicit code over clever code.

Document architectural decisions.

Every module should have a single responsibility.

Every public API should be documented.

Every complex workflow should include a sequence diagram.

---

# AI Platform Principles

This repository is an AI Platform.

Not an AI application.

Everything should be reusable.

Every component should be independently testable.

Every component should be independently replaceable.

Every component should be independently deployable where practical.

Avoid monolithic designs.

---

# Local Development First

Always implement locally before Azure deployment.

Everything should work using:

docker compose up

without manual setup.

Azure deployment comes only after successful local testing.

---

# Incremental Development

Never generate an entire project at once.

Work milestone by milestone.

After every milestone:

1. Explain architecture
2. Explain design decisions
3. Create folder structure
4. Create files
5. Generate code
6. Explain tests
7. Explain expected results
8. Provide Git commit message

Then STOP.

Wait for approval.

---

# Quality Expectations

Every pull request should improve:

Architecture

Code Quality

Documentation

Testing

Security

Performance

Maintainability

Never trade architecture quality for speed.

---

# Documentation Standards

Every major feature requires documentation.

Use Markdown.

Architecture diagrams should use Mermaid.

Sequence diagrams should use Mermaid.

API documentation should be generated automatically.

Every architectural decision should be recorded as an ADR (Architecture Decision Record).

---

# Git Standards

Use meaningful commit messages.

Prefer small commits.

Never mix unrelated changes.

Feature branches should follow:

feature/<feature-name>

Bug fixes:

fix/<bug-name>

Documentation:

docs/<topic>

Refactoring:

refactor/<component>

Infrastructure:

infra/<component>

---

# Testing Philosophy

Testing is mandatory.

Every feature should include:

- Unit Tests
- Integration Tests

Critical workflows should include:

- End-to-End Tests

Never merge code without automated tests.

---

# Code Review Checklist

Before considering any implementation complete, verify:

✓ Architecture follows Clean Architecture

✓ SOLID principles respected

✓ Strong typing

✓ Async where appropriate

✓ Tests included

✓ Logging included

✓ OpenTelemetry included where applicable

✓ Configuration externalized

✓ Secrets protected

✓ Documentation updated

✓ Code formatted

✓ Lint passes

✓ Type checking passes

If any item fails, the implementation is incomplete.

---

# Enterprise Multi-Agent Architecture

The platform shall implement a true Multi-Agent Runtime.

An Agent is not responsible for infrastructure.

An Agent is responsible only for reasoning within its assigned domain.

The runtime orchestrates everything else.

```
                 User
                   │
                   ▼
             API Gateway
                   │
                   ▼
             Agent Runtime
                   │
      ┌────────────┼────────────┐
      ▼            ▼            ▼
 Agent Registry  Tool Registry  Model Registry
      │            │            │
      └────────────┼────────────┘
                   ▼
          Agent Execution Engine
                   │
     ┌─────────────┼──────────────┐
     ▼             ▼              ▼
 Chat Agent   Research Agent   Coding Agent
```

Never allow agents to directly depend on infrastructure.

---

# Agent Runtime

The Agent Runtime is the heart of the platform.

Responsibilities include:

- Agent discovery
- Agent registration
- Agent execution
- Agent communication
- Tool invocation
- Memory coordination
- Model selection
- Provider selection
- Request routing
- Retry handling
- Timeouts
- Budget enforcement
- Observability
- Tracing
- Evaluation

The runtime must remain independent of any specific LLM provider.

---

# Agent Registry

Maintain a registry of all available agents.

Each registered agent should declare metadata including:

- Agent ID
- Agent name
- Description
- Version
- Owner
- Purpose
- Supported tasks
- Default provider
- Default model
- Available tools
- Memory provider
- Search provider
- Embedding provider (future)
- Vector store (future)
- Budget policy
- Timeout policy
- Retry policy
- Guardrails
- System prompt location

Agents should be discoverable dynamically through the registry.

---

# Agent Configuration

Every agent must be independently configurable.

Example configuration:

```yaml
agent:
  id: coding-agent
  provider: anthropic
  model: claude-opus
  temperature: 0.1
  max_tokens: 8000
  timeout: 120
  tools:
    - filesystem
    - github
    - internet-search
```

Changing an agent's model must require configuration changes only.

Never modify source code to switch providers.

---

# Agent Lifecycle

Every agent follows the same lifecycle:

Request

↓

Runtime Validation

↓

Memory Retrieval

↓

Prompt Assembly

↓

Model Selection

↓

Tool Planning

↓

Tool Execution

↓

Response Generation

↓

Evaluation

↓

Memory Update

↓

Response

All lifecycle stages must be observable.

---

# Agent Communication

Agents must never directly call other agents.

Instead:

```
Agent A

↓

Agent Runtime

↓

Agent B
```

The runtime controls:

- authentication
- authorization
- tracing
- retries
- timeout
- evaluation
- budgeting

---

# Agent Collaboration

Support collaborative workflows.

Example:

Chat Agent

↓

Planner Agent

↓

Research Agent

↓

Document Agent

↓

Reviewer Agent

↓

Final Response

The runtime orchestrates the workflow.

Agents remain unaware of one another.

---

# Model Registry

Create a centralized Model Registry.

Every model should define:

- Provider
- Model name
- Version
- Endpoint
- Deployment
- Streaming support
- Context window
- Maximum output tokens
- Tool calling support
- Vision support
- Structured output support
- Cost metadata
- Status
- Availability

The runtime should obtain model information exclusively from the registry.

---

# Provider Registry

Providers should register capabilities.

Examples:

Azure AI Foundry

Azure OpenAI

Anthropic

OpenAI

Gemini

DeepSeek

OpenRouter

Ollama

vLLM

Each provider advertises:

- Authentication methods
- Streaming support
- Tool calling
- Structured outputs
- Cost reporting
- Health status

---

# Runtime Model Selection

Never hardcode a model.

Model selection should support:

- per agent
- per request
- per user
- per workflow

The runtime should allow policy-based selection in the future.

Example:

High Quality

↓

Claude

Low Cost

↓

Gemma

Long Context

↓

Gemini

Reasoning

↓

GPT

Coding

↓

Claude

Vision

↓

GPT Vision

The initial implementation only requires static configuration.

---

# LLM Provider Interface

Every provider must implement a common interface.

Example responsibilities:

- Generate response
- Stream response
- Count tokens
- Report usage
- Estimate cost
- Health check
- Retry support

Business logic must never depend on provider SDKs.

---

# Provider Neutrality

The initial implementation uses Azure AI Foundry.

However, the architecture must never assume Azure AI Foundry is the only provider.

Business logic communicates exclusively through provider-neutral interfaces.

Whenever practical, design request and response contracts compatible with OpenAI-style Chat APIs.

Future providers should be implementable without changing:

- Agent Runtime
- Workflows
- Memory
- Tools
- Prompt Engine

---

# Prompt Registry

Prompts are assets.

Never embed large prompts inside Python code.

Store prompts externally.

Every prompt should have:

- ID
- Version
- Owner
- Description
- Variables
- Supported agents

Future versions should support prompt versioning.

---

# Tool Registry

All tools must register themselves.

Example metadata:

- Tool ID
- Description
- Parameters
- Timeout
- Permissions
- Cost
- Owner
- Version

The runtime selects tools through the registry.

---

# Tool Execution

The runtime executes tools.

Agents never call tools directly.

Execution pipeline:

Agent

↓

Runtime

↓

Tool Registry

↓

Tool

↓

Runtime

↓

Agent

This enables centralized:

- logging
- retries
- authorization
- auditing
- metrics

---

# MCP Readiness

The platform should be compatible with the Model Context Protocol (MCP).

Do not tightly couple tools to MCP.

Instead, design the Tool Registry so tools can be backed by:

- Local implementations
- REST APIs
- Azure Functions
- MCP servers

Future additions should require only a new adapter.

---

# Memory Architecture

Memory is a platform capability.

Not an agent capability.

Supported abstractions:

MemoryProvider

Implementations:

- In-Memory (initial)
- Redis
- PostgreSQL
- Cosmos DB
- Azure AI Search
- Vector Database

Agents interact only with the abstraction.

---

# Context Assembly

Before every model call, the runtime assembles context from:

- System Prompt
- Agent Prompt
- Conversation Memory
- Tool Results
- User Input

Context assembly should be deterministic and testable.

---

# Budget Enforcement

Each agent may define:

- Maximum tokens
- Maximum cost
- Maximum execution time
- Maximum tool invocations

The runtime enforces these policies.

---

# Runtime Policies

Future policy engine should support:

- Model selection policies
- Cost optimization policies
- Safety policies
- Compliance policies
- Routing policies

The architecture must allow policy injection without changing agent logic.

---

# Health Checks

Every provider should expose:

- Ready
- Live
- Healthy

The runtime should avoid unhealthy providers.

Future implementations may support automatic failover.

---

# Event Bus (Future)

Design the runtime so future agents can communicate asynchronously through an event bus.

Examples:

- Azure Service Bus
- Azure Event Grid
- Kafka

Do not implement now.

Only ensure the architecture allows it.

---

# Azure Cloud Architecture

Azure is the primary cloud platform.

The platform must initially deploy entirely on Azure.

Cloud-specific implementations must be isolated from business logic.

Future support for AWS and Google Cloud should be possible through infrastructure abstraction where practical.

---

# Azure AI Foundry Standards

The initial production LLM platform is:

Azure AI Foundry

Requirements:

- Managed Compute
- Scale-to-Zero
- Azure DefaultCredential
- Streaming responses
- Secure authentication
- Infrastructure as Code

Never use API keys for Azure AI Foundry unless no supported identity mechanism exists.

Local development should authenticate using:

az login

Production should authenticate using:

Managed Identity

---

# Infrastructure as Code

Infrastructure must be reproducible.

Supported technologies:

- Bicep
- Azure Developer CLI (azd)

Avoid manual Azure Portal configuration after initial provisioning.

Infrastructure should be deployable using:

az login

↓

az account set

↓

azd up

---

# Azure Resources

The platform should provision:

Resource Group

Azure AI Foundry Project

Managed Compute

Model Deployment

Azure Container Apps

Azure Container Registry

Application Insights

Log Analytics

Key Vault

Container Apps Environment

Storage Account (future)

Azure AI Search (future)

Cosmos DB (future)

Redis (future)

---

# Environment Strategy

Support:

Development

Testing

Staging

Production

Every environment must have:

Independent configuration

Independent resources

Independent secrets

Independent monitoring

---

# Secrets Management

Never store secrets inside:

- source code
- Docker images
- configuration files

Use:

Development

↓

.env

Production

↓

Azure Key Vault

Applications should retrieve secrets through configuration providers.

---

# Authentication

Support:

Azure DefaultCredential

Managed Identity

Service Principal

API Key

OAuth (future)

Never hardcode credentials.

---

# Authorization

Design for future RBAC.

Future users may have roles such as:

Administrator

Developer

Operator

Business User

Viewer

Do not implement authorization now.

Ensure architecture supports it.

---

# API Standards

Every API should follow REST conventions.

Version every public API.

Example:

/api/v1/chat

/api/v1/agents

/api/v1/models

/api/v1/tools

Never expose internal implementation details.

---

# Configuration

Configuration must be validated during application startup.

Invalid configuration should prevent startup.

Support:

Environment Variables

YAML

JSON

Azure App Configuration (future)

---

# Feature Flags

Feature flags should control:

Streaming

Search

Memory

Evaluation

Tracing

Cost Tracking

Individual Tools

Individual Agents

Providers

Future implementation may use:

Azure App Configuration

---

# Observability

Every request must be observable.

Every significant action must be traceable.

Use:

OpenTelemetry

Application Insights

Correlation IDs

Distributed Tracing

Metrics

Structured Logs

---

# Correlation

Generate a unique Correlation ID for every request.

Propagate through:

API

Runtime

Agent

Tool

Provider

Database

Logs

Tracing

This enables complete request tracing.

---

# Logging Standards

Structured logging only.

Every log entry should include:

Timestamp

Correlation ID

Request ID

Session ID

Agent ID

Model

Provider

Latency

Severity

Message

Never log secrets.

Never log sensitive user data.

---

# Metrics

Capture metrics for:

API Requests

Agent Executions

Model Calls

Tool Executions

Memory Operations

Search Requests

Streaming Sessions

Retry Counts

Failures

Timeouts

---

# Health Endpoints

Implement:

/health

/live

/ready

Every infrastructure component should expose health status.

---

# Error Handling

Centralize exception handling.

Never expose internal stack traces.

Return meaningful API errors.

Log complete diagnostic information internally.

---

# Retry Policy

External calls should use configurable retry policies.

Include:

Maximum Retries

Backoff

Timeout

Circuit Breaker (future)

Never retry non-idempotent operations automatically.

---

# Cost Optimization Philosophy

Cost is an architectural concern.

Not merely an operational metric.

Always prefer:

Lower Cost

↓

Same Quality

↓

Lower Latency

↓

Higher Throughput

without sacrificing correctness.

---

# LLM Evaluation Framework

Every model invocation should generate evaluation metadata.

Capture:

Provider

Model

Deployment

Timestamp

Latency

Time to First Token

Prompt Tokens

Completion Tokens

Total Tokens

Estimated Cost

Tool Usage

Retries

Errors

Success

Streaming Enabled

Conversation ID

Session ID

Agent ID

---

# Cost Tracking

Create an abstraction:

EvaluationProvider

Initial implementation:

Structured Logs

Future implementations:

Application Insights

Azure Monitor

Cosmos DB

PostgreSQL

Azure Data Explorer

---

# Model Benchmarking

Design a benchmarking framework.

Compare models using:

Average Latency

Average Cost

Token Usage

Error Rate

Success Rate

Tool Usage

Time to First Token

Future Quality Score

Never tightly couple benchmarking to a provider.

---

# Cost Dashboard (Future)

Architecture should support dashboards showing:

Cost by Provider

Cost by Model

Cost by Agent

Cost by User

Cost by Workflow

Daily Cost

Monthly Cost

Average Response Time

Average Token Usage

No implementation required yet.

---

# Performance Monitoring

Track:

P50 Latency

P95 Latency

P99 Latency

Requests per Second

Concurrent Sessions

Streaming Duration

Queue Time

Provider Latency

Tool Latency

Memory Latency

---

# Security Standards

Always assume zero trust.

Use:

Least Privilege

Managed Identity

RBAC

HTTPS

Secret Rotation

Audit Logging

Never trust client input.

Validate everything.

---

# Compliance

Architecture should support future compliance requirements such as:

GDPR

SOC 2

ISO 27001

HIPAA (where applicable)

Do not implement compliance features now.

Avoid architectural decisions that would prevent them later.

---

# DevOps Standards

Every repository should include:

Docker

Docker Compose

Bicep

Azure Developer CLI

GitHub Actions

pre-commit

Ruff

Black

mypy

pytest

Coverage Reports

Dependabot

Security Scanning

---

# Continuous Integration

Every Pull Request should execute:

Formatting

Linting

Type Checking

Unit Tests

Integration Tests

Security Checks

Docker Build

Bicep Validation

No failing checks should be merged.

---

# Continuous Deployment

Deployment pipeline should support:

Development

Testing

Production

Deployment should be repeatable.

Infrastructure and application deployments should remain independent.

---

# Documentation

Every architectural decision should be documented.

Maintain:

Architecture Decision Records (ADRs)

Deployment Guides

Runbooks

Troubleshooting Guides

API Documentation

Developer Setup Guide

---

# Repository Structure

Organize the repository for long-term maintainability.

Preferred layout:

```
multi-agent-ai-platform/

├── .claude/
├── .github/
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── api/
│   ├── runbooks/
│   └── diagrams/
│
├── infra/
│   ├── bicep/
│   ├── azd/
│   └── scripts/
│
├── src/
│   ├── backend/
│   ├── frontend/
│   ├── shared/
│   └── sdk/
│
├── tests/
│
└── docker/
```

Never place infrastructure, backend and frontend logic in the same directory.

---

# Naming Standards

Prefer descriptive names.

Avoid abbreviations.

Good

AgentRuntime

PromptRegistry

EvaluationProvider

ConversationMemory

Bad

Mgr

Svc

Util

Helper

Thing

---

# Python Standards

Use:

Python 3.12+

Type hints everywhere.

Prefer:

dataclass

Pydantic

Protocols

Enums

Pathlib

Context Managers

Avoid global mutable state.

---

# Async Programming

Use async for:

API calls

Model inference

Streaming

Search

Database operations

Network requests

Do not block the event loop.

---

# Dependency Injection

Never instantiate infrastructure directly inside business logic.

Inject:

Providers

Repositories

Services

Registries

Factories

Configuration

---

# Configuration

Configuration must be centralized.

No scattered environment variable lookups.

Use strongly typed configuration classes.

---

# Prompt Management

Prompts are versioned assets.

Store prompts under:

prompts/

Support:

Version

Variables

Owner

Description

Future A/B testing.

Never embed long prompts in Python files.

---

# Testing Standards

Every feature must include tests.

Minimum:

Unit Tests

Integration Tests

Critical workflows:

End-to-End Tests

Test business logic independently of infrastructure.

---

# Documentation Standards

Every public class should include documentation.

Every interface should explain:

Purpose

Responsibilities

Constraints

Every architectural decision should have an ADR.

---

# API Documentation

Generate OpenAPI automatically.

Document:

Inputs

Outputs

Error codes

Authentication

Examples

---

# Logging Standards

Never use print.

Use structured logging.

Logs should support machine analysis.

---

# Observability

Every new feature must answer:

How will it be monitored?

How will it be traced?

How will failures be diagnosed?

---

# Feature Development Workflow

Every new feature follows:

Architecture

↓

Design

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

Never skip steps.

---

# Code Generation Workflow

Before writing code:

Explain architecture.

Explain assumptions.

Explain trade-offs.

After writing code:

Explain testing.

Explain expected output.

Suggest Git commit message.

Then stop.

---

# Decision Framework

When choosing a library, framework, protocol, or design pattern:

Explain:

Why this option?

What alternatives were considered?

Why is it appropriate for this platform?

Avoid introducing dependencies without justification.

---

# Definition of Done

A task is complete only when:

✓ Code builds

✓ Tests pass

✓ Lint passes

✓ Type checking passes

✓ Documentation updated

✓ Logging implemented

✓ Telemetry included

✓ Configuration externalized

✓ Security considered

✓ Git commit message provided

If any item is missing, the task is incomplete.

---

# Pull Request Expectations

Every Pull Request should include:

Summary

Architecture impact

Testing performed

Configuration changes

Documentation updates

Deployment impact

Risk assessment

Rollback strategy

---

# Backward Compatibility

Avoid breaking public interfaces.

If breaking changes are necessary:

Document them.

Provide migration guidance.

---

# AI Coding Guidelines

Generate production-quality code.

Avoid placeholders except where explicitly requested.

Avoid TODOs for core functionality.

Prefer complete implementations.

If a feature is intentionally deferred, explain why.

---

# Multi-Agent Principles

Agents should remain small.

Agents should specialize.

Agents should collaborate through the Agent Runtime.

Avoid creating "God Agents."

---

# Model Selection Philosophy

Different agents may use different models.

Choose models based on capability, latency, context size, and cost.

Never assume one model fits all use cases.

---

# Cost Optimization

Every architectural decision should consider:

Quality

Latency

Operational Cost

Scalability

Favor solutions that reduce long-term operating costs without sacrificing maintainability.

---

# Future Platform Roadmap

Design the architecture so the platform can later support:

Multi-user authentication

Role-based access control

Agent Marketplace

Tool Marketplace

Model Marketplace

Prompt Marketplace

Workflow Builder

Visual Agent Designer

Scheduled Agents

Background Agents

Long-term Memory

Knowledge Graph

RAG

Vector Databases

Model Context Protocol (MCP)

Human Approval Workflows

Voice

Vision

Documents

Realtime Collaboration

Mobile Clients

Desktop Clients

Multi-cloud deployment

None of these need to be implemented initially.

The architecture should simply avoid preventing them.

---

# Final Rule

Always optimize for:

Enterprise Maintainability

↓

Architecture Quality

↓

Developer Experience

↓

Reliability

↓

Security

↓

Observability

↓

Performance

↓

Cost Optimization

Never sacrifice architecture for short-term convenience.