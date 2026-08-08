# Tools

Developer and operational tooling that is **not** part of the shipped platform.

Nothing here is imported by `src/`. If a script becomes something the platform
depends on, it belongs in a package under `src/`, with tests.

## Not yet populated

Milestone 01 needs no tooling beyond what `uv` and `npm` already provide.

Expected additions:

| Tool | Purpose | Milestone |
| --- | --- | --- |
| `verify-environment.py` | Check a contributor's toolchain versions before first run | 01.5 |
| `benchmark/` | Compare models on latency, cost, token usage and error rate | 05 |
| `load-test/` | Sustained-throughput and streaming-concurrency tests | 08 |
| `prompt-lint.py` | Validate prompt front matter against `PromptAsset` | 03 |

## Rules

1. **Not a dependency.** `src/` must never import from here.
2. **Self-documenting.** Every tool explains its purpose and usage when run with
   `--help`.
3. **Cross-platform.** Contributors are on Windows, macOS and Linux; CI is on
   Linux.
4. **No secrets.** A tool may read a credential from the environment or Key
   Vault. None may contain, log or echo one.
