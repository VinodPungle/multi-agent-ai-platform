# Milestone 07 – DevSecOps, CI/CD & GitHub Actions

## Executive Summary
Establish a production-ready DevSecOps pipeline that automates code quality, testing, security validation, container builds, infrastructure validation, and deployments across environments.

## Objectives
- Implement GitHub Actions CI/CD
- Automate quality gates
- Add security scanning
- Build and publish Docker images
- Validate Bicep
- Prepare environment-based deployments

## Business Value
Provides reliable, repeatable software delivery with automated validation and security checks, reducing deployment risk and improving engineering productivity.

## In Scope
- GitHub Actions workflows
- Branch protection recommendations
- Ruff, Black, mypy
- pytest, Vitest
- Docker build validation
- Bicep validation
- Dependency scanning
- Secret scanning
- Container image scanning
- ACR publishing
- Environment deployment stages
- Release tagging guidance

## Out of Scope
- Blue/Green deployments
- Canary deployments
- Multi-region releases

## Repository Changes

.github/workflows/
- ci.yml
- cd.yml
- reusable-build.yml
- reusable-test.yml

.github/
- CODEOWNERS
- pull_request_template.md

## Pipeline Stages

1. Checkout
2. Dependency Restore
3. Backend Lint & Format Check
4. Type Checking
5. Backend Tests
6. Frontend Tests
7. Docker Build
8. Bicep Validation
9. Security Scans
10. Publish Images
11. Deploy (environment specific)

## Security Controls
- Dependabot
- GitHub Secret Scanning
- CodeQL
- Container vulnerability scanning
- Least-privilege GitHub permissions

## Implementation Tasks
1. Create reusable workflows.
2. Configure CI pipeline.
3. Configure CD pipeline.
4. Add environment variables and secrets.
5. Configure Docker image publishing.
6. Validate infrastructure templates.
7. Configure deployment approvals.
8. Document rollback process.

## Acceptance Criteria
- Pull requests execute CI successfully.
- Docker images build successfully.
- Bicep validates.
- Security scans execute.
- Images publish to Azure Container Registry.
- Deployment workflow supports Dev/Test/Staging/Production.

## Test Cases
- Successful PR
- Failing lint
- Failing tests
- Invalid Bicep
- Failed image build
- Deployment approval flow

## Risks
- Secret misconfiguration
- Pipeline failures
- Environment drift

Mitigations
- Environment protection rules
- Required reviewers
- Infrastructure validation
- Automated quality gates

## Definition of Done
- CI operational
- CD templates ready
- Security scans enabled
- Documentation updated
- Rollback documented

## Suggested Commits
- ci: add GitHub Actions workflows
- security: enable CodeQL and dependency scanning
- feat(devops): add deployment pipeline
- docs: add CI/CD guide

## Exit Criteria
Platform is ready for Milestone 08 (Production Hardening & Operational Readiness).
