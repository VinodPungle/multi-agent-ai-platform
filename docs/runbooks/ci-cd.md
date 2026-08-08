# CI/CD

How changes get verified, and how they reach Azure.

---

## 1. The pipelines

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci.yml` | push to `main` or a feature branch, PR to `main` | Every quality gate, container build + scan, infrastructure validation, security scan |
| `cd.yml` | manual only | Provision, publish images, deploy, smoke test |
| `codeql.yml` | PR, `main`, weekly | Semantic analysis of Python and TypeScript |
| `reusable-test.yml` | called | Backend and frontend gates |
| `reusable-build.yml` | called | Build, verify, scan, optionally publish |

**CI and CD share the same gate definitions.** Duplicated, they drift — and the
drift always favours the release pipeline, because that is the one under time
pressure. A release must not be able to pass checks a pull request would fail.

### CI runs on feature branches, and that is the point

Triggers used to be `main` only. Six milestones of work happened on a long-lived
feature branch with no pull request, so **CI never ran once**. Everything was
verified locally, which is exactly the gap CI exists to close.

A gate nothing reaches is not a gate.

---

## 2. What CI checks

```
quality           ruff · ruff format · black · mypy --strict · pytest
                  prettier · eslint · tsc · vitest · vite build
images            build both · run both · probe /live and /healthz · Trivy scan
infrastructure    bicep build · 4 × bicepparam · azure.yaml · actionlint · preflight scripts
security          Trivy filesystem: vulnerabilities, secrets, misconfiguration
ci                one required check that fails if any of the above did
```

Two details worth knowing:

**Both Python formatters run.** `ruff format` and `black` have disagreed in this
repository before, and the disagreement only appears as a file each rewrites in
turn. One check would never reveal it.

**Images are run, not merely built.** A build proves the image compiles. Starting
it and probing `/live` is what catches a broken entrypoint, a missing runtime
dependency, or a permission error from running as non-root.

### The `ci` summary job

Branch protection requires **one** check: `CI`. Without it, protecting `main`
means listing every job by name and updating that list whenever the pipeline
changes — which is forgotten exactly when a new gate is added, silently making
it optional.

---

## 3. Deploying

Manual, by design:

**Actions → CD → Run workflow → choose an environment.**

Deploy-on-merge is deliberately not configured. This platform bills per model
call and per provisioned throughput, and an accidental production deployment is
not recoverable by reverting a commit.

Stages: quality gates → provision → build and publish images → deploy → smoke
test.

The smoke test checks `/ready`, not `/live`. Liveness passes before the platform
can actually answer, so a liveness-only check produces a green deployment that
serves errors — and nobody investigates a green pipeline.

---

## 4. One-time GitHub setup

### Federated credentials (no secrets)

Azure authentication uses OIDC. There is no service principal secret in this
repository — nothing to store, rotate or leak. The same argument that removed
API keys from the application, applied to the pipeline.

```bash
APP_ID=$(az ad app create --display-name "maap-github-actions" --query appId -o tsv)
az ad sp create --id "$APP_ID"

# One credential per environment. The subject must match exactly — a mismatch
# fails with "no matching federated identity record found", which does not say
# which part did not match.
for ENV in development testing staging production; do
  az ad app federated-credential create --id "$APP_ID" --parameters "{
    \"name\": \"github-$ENV\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"repo:VinodPungle/multi-agent-ai-platform:environment:$ENV\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
done

# Owner, not Contributor: the templates create role assignments, which
# Contributor cannot do.
az role assignment create --assignee "$APP_ID" --role Owner \
  --scope "/subscriptions/<subscription-id>"
```

### Repository secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | the `appId` above |
| `AZURE_TENANT_ID` | `az account show --query tenantId -o tsv` |
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |

### Environments

Settings → Environments, one each for `development`, `testing`, `staging`,
`production`. Per environment:

| Kind | Name | Example |
| --- | --- | --- |
| Variable | `AZURE_ENV_NAME` | `dev`, `test`, `stg`, `prod` |
| Variable | `AZURE_LOCATION` | `centralus` |
| Variable | `PLATFORM_SEARCH_PROVIDER` | `duckduckgo` / `mock` / `tavily` |
| Secret | `TAVILY_API_KEY` | staging and production only |

**Required reviewers on `staging` and `production`.** This is what makes
approval real; the workflow file cannot enforce it. The job pauses before it
runs, and the reviewer sees the target environment and commit.

Also restrict those environments to the `main` branch, so a deployment cannot be
launched from an unreviewed branch.

### Branch protection on `main`

Settings → Rules → Rulesets:

- Require a pull request, 1 approval
- **Require review from Code Owners** — this is what makes `.github/CODEOWNERS`
  a gate rather than a routing hint
- Require status checks: **`CI`** (the summary job)
- Require branches to be up to date before merging
- Block force pushes
- Require conversation resolution

---

## 5. Rollback

### The application

Container Apps keeps revisions, so rollback is a traffic switch and takes
seconds — no rebuild, no redeploy.

```bash
az containerapp revision list -n <app> -g <rg> -o table

# Send all traffic to the previous revision.
az containerapp ingress traffic set -n <app> -g <rg> \
  --revision-weight <previous-revision>=100
```

Then reactivate it if it was deactivated:

```bash
az containerapp revision activate -n <app> -g <rg> --revision <previous-revision>
```

**Redeploying an older commit is the slower alternative** — it rebuilds images
and takes as long as the original deployment. Prefer the traffic switch when the
site is broken now.

Images are tagged with the commit SHA, so what a revision runs is always
traceable to a commit.

### Infrastructure

There is no automatic rollback, and this is the honest part: `azd provision`
applies a desired state, so undoing it means committing the previous templates
and provisioning again.

```bash
git revert <commit>
azd provision
```

Two things do not come back this way:

- **A deleted resource is gone.** Key Vault has soft-delete; most resources do
  not.
- **Data is gone.** No resource here holds persistent data yet, which is the only
  reason this is currently survivable. That changes in Milestone 08.

### Deciding which

| Symptom | Action |
| --- | --- |
| Errors after a deploy | Revision traffic switch. Seconds |
| Bad configuration in the app | Fix the environment variable, `azd provision` |
| Bad infrastructure change | Revert the commit, `azd provision` |
| Wrong environment deployed to | Roll back the revision, then work out how the environment was selected |

---

## 6. Security scanning

| Tool | Finds | When |
| --- | --- | --- |
| Trivy (filesystem) | Vulnerable dependencies, committed secrets, misconfiguration | Every CI run |
| Trivy (images) | CVEs in the built images, including base-image packages | Every CI run |
| CodeQL | Injection paths, unsafe deserialisation, secrets in logs — in our own code | PR, `main`, weekly |
| Dependabot | Outdated dependencies | Weekly |
| GitHub secret scanning | Committed credentials | Continuous, once enabled in settings |

**Image scanning is not redundant with filesystem scanning.** A filesystem scan
cannot see a vulnerable package that arrived in a base image, which is where
most container CVEs come from.

**`ignore-unfixed` is set on the failing gates.** A CVE nobody can remediate
otherwise stops every build indefinitely and teaches people to bypass the gate,
which costs more security than it buys.

**The weekly CodeQL run earns its place.** Its queries are updated continuously,
so code that was clean when merged can be reported later without anyone changing
it. A pull-request-only schedule never revisits merged code.

---

## 7. Troubleshooting

**`no matching federated identity record found`**
The credential's subject does not match. For an environment deployment it must
be `repo:<owner>/<repo>:environment:<environment>` exactly — including the
environment name's case.

**`AuthorizationFailed` during provision**
The service principal needs Owner or User Access Administrator. Contributor
creates resources but cannot grant access to them.

**CI passes, deployment fails**
Usually configuration rather than code: the platform validates settings at
startup and refuses `debug=true` in production, wildcard CORS, or the mock
provider in a production-like environment. Read the container log stream.

**The deployed frontend cannot reach the API**
Check what the bundle was built with. Vite bakes `VITE_API_BASE_URL` in at build
time; built outside the CD pipeline, it defaults to `http://localhost:8000`.

**A workflow change behaves unexpectedly**
`actionlint` runs in CI and catches undefined expressions and bad `needs`
references, but it cannot catch a logic error. Test with `workflow_dispatch` on
a branch before merging.

---

## 8. What is not here

- **No deploy-on-merge.** Deliberate, for cost reasons. Reconsider for
  development once there is an environment cheap enough to redeploy carelessly.
- **No blue/green or canary.** Container Apps revisions make both possible;
  nothing orchestrates them. Out of scope for Milestone 07.
- **No release tagging automation.** Tag manually: `git tag -a v0.2.0 -m "..."`.
- **No dependency licence checking.**
- **No performance regression gate.** Milestone 08.
