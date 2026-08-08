# Milestone 05 – Azure AI Foundry & Gemma 4 Integration

## Executive Summary
Integrate the platform with Azure AI Foundry using Azure DefaultCredential and a Gemma 4 deployment hosted on Managed Compute with Scale-to-Zero. This milestone replaces the mock LLM provider with the first production provider while preserving the provider abstraction.

## Objectives
- Implement Azure AI Foundry provider
- Authenticate using Azure DefaultCredential
- Support Azure CLI locally and Managed Identity in Azure
- Integrate Model Registry and Provider Registry
- Enable streaming responses
- Capture LLM telemetry and estimated cost
- Validate configuration at startup

## Business Value
Delivers the first production-ready AI capability while preserving the provider-agnostic architecture for future models.

## In Scope
- AzureFoundryProvider
- ProviderFactory integration
- Model registration
- Azure DefaultCredential
- Streaming
- Health checks
- Provider telemetry
- Feature flags
- Configuration validation
- End-to-end testing

## Out of Scope
- Azure OpenAI
- Claude
- Gemini
- DeepSeek
- Multi-provider routing
- Automatic failover

## Prerequisites
- Azure subscription
- Azure AI Foundry project
- Gemma 4 deployment
- Managed Compute (Scale-to-Zero)
- `az login` completed for local development

## Repository Changes
Backend:
- providers/azure_foundry/
- provider configuration
- health service
- streaming adapter

Configuration:
- .env.example additions
- model registry entries

Documentation:
- Azure setup guide
- Local authentication guide

## Configuration
Required settings:
- Azure Subscription ID
- Resource Group
- AI Foundry Project
- Endpoint
- Deployment Name
- API Version (if applicable)
- Default Model
- Streaming Enabled

## Implementation Tasks
1. Implement AzureFoundryProvider.
2. Wire ProviderFactory.
3. Register Gemma 4 in Model Registry.
4. Configure DefaultAzureCredential.
5. Implement provider health checks.
6. Enable streaming.
7. Capture latency, tokens and estimated cost.
8. Add integration tests.
9. Update documentation.

## Acceptance Criteria
- Chat uses Azure AI Foundry.
- Gemma 4 responds successfully.
- Streaming works.
- Local auth uses Azure CLI.
- Azure deployment uses Managed Identity.
- Health endpoint verifies provider connectivity.
- Telemetry records provider metrics.

## Test Cases
- Valid authentication
- Invalid authentication
- Missing deployment
- Streaming response
- Health endpoint
- Startup configuration validation
- Provider timeout

## Risks
- Authentication failures
- Deployment configuration mismatch
- Network latency

Mitigation:
- Startup validation
- Health checks
- Clear diagnostics
- Retry policy

## Definition of Done
- Azure AI Foundry provider operational
- Gemma 4 integrated
- Streaming operational
- Tests passing
- Documentation complete

## Suggested Commits
- feat(provider): implement Azure AI Foundry provider
- feat(model): register Gemma 4
- feat(auth): integrate Azure DefaultCredential
- test(provider): add integration tests

## Exit Criteria
Platform is ready for Milestone 06 (Infrastructure as Code with Bicep and Azure Developer CLI).
