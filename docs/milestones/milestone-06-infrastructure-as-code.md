# Milestone 06 – Infrastructure as Code (Bicep + Azure Developer CLI)

## Executive Summary
Provision the complete Azure foundation for the Enterprise Multi-Agent AI Platform using Infrastructure as Code. All infrastructure must be reproducible, environment-aware, and deployable with Azure Developer CLI (`azd`).

## Objectives
- Provision Azure resources with Bicep
- Configure Azure Developer CLI
- Support Development, Test, Staging and Production
- Externalize configuration
- Prepare deployment for Container Apps

## Business Value
Ensures repeatable, auditable and automated infrastructure provisioning without relying on manual Azure Portal configuration.

## In Scope
- azd project
- Bicep modules
- Resource Group
- Azure AI Foundry Project
- Managed Compute
- Azure Container Apps
- Container Apps Environment
- Azure Container Registry
- Azure Key Vault
- Application Insights
- Log Analytics
- Managed Identity
- Environment parameterization

## Out of Scope
- GitHub deployment automation
- Blue/Green deployment
- Multi-region deployment

## Repository Changes
infra/
  azd/
  bicep/
    main.bicep
    ai-foundry.bicep
    container-apps.bicep
    acr.bicep
    keyvault.bicep
    monitoring.bicep
    identities.bicep
    outputs.bicep

## Implementation Tasks
1. Initialize azd project.
2. Create modular Bicep templates.
3. Parameterize environments.
4. Configure Managed Identity.
5. Provision Azure AI Foundry resources.
6. Configure Container Apps and ACR.
7. Configure Application Insights and Log Analytics.
8. Validate deployments.
9. Document deployment process.

## Deployment Flow
az login

↓

az account set --subscription

↓

azd up

## Acceptance Criteria
- Infrastructure deploys successfully using azd.
- All required Azure resources are provisioned.
- Managed Identity configured.
- Application Insights connected.
- Environment-specific parameters supported.
- No manual portal configuration required after initial setup.

## Test Cases
- Fresh deployment
- Redeployment (idempotent)
- Environment switching
- Parameter validation
- Resource naming validation

## Risks
- Azure quota limitations
- Naming collisions
- Missing permissions

Mitigations:
- Validation scripts
- Naming conventions
- Pre-flight checks

## Definition of Done
- Bicep modules complete
- azd configuration complete
- Deployment guide updated
- Infrastructure validated

## Suggested Commits
- feat(infra): add modular Bicep templates
- feat(azd): initialize Azure Developer CLI project
- docs(infra): deployment guide

## Exit Criteria
Platform is ready for Milestone 07 (CI/CD & GitHub Actions).
