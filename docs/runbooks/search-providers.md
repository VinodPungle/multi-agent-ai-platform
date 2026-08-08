# Search providers

Which backend answers the internet-search tool, and how to change it.

This is a **platform-wide** choice. Agents declare the *tool*
(`internet-search`), never a backend, so switching the provider switches what
every agent searches with — no agent, tool or runtime code is involved.

---

## The three providers

| Provider | Key | Cost | Best at | Weak at |
| --- | --- | --- | --- | --- |
| `duckduckgo` *(default)* | none | free | encyclopaedic questions | current events, ranked pages |
| `tavily` | required | per search | current information, ranked web results with extracted content | nothing much — it costs money |
| `mock` | none | free | CI, offline work, deterministic tests | being real |

`duckduckgo` is the default because a fresh clone with no accounts must still
perform a real search. That is what "local development first" means, and it is
why the keyless provider stays even though Tavily is better.

---

## Switching to Tavily

1. Get a key at [tavily.com](https://tavily.com). Keys begin with `tvly-`.
2. Put it in `.env` — which is git-ignored:

```dotenv
PLATFORM_SEARCH__PROVIDER=tavily
PLATFORM_SEARCH__TAVILY_API_KEY=tvly-...
```

3. Restart the backend.

Optional:

```dotenv
# `advanced` returns better evidence and costs more per search.
PLATFORM_SEARCH__SEARCH_DEPTH=basic

# Every result is spent context in the next prompt, so this is a cost setting
# as much as a quality one.
PLATFORM_SEARCH__MAX_RESULTS=5
```

Selecting `tavily` without a key **stops startup**, naming the missing setting.
That is deliberate: the alternative is a platform that starts happily and fails
the first search with an upstream 401 that explains nothing.

---

## The key is a real secret

Tavily offers no identity-based authentication, so an API key is the only
mechanism available — the narrow exception `CLAUDE.md` allows for Azure AI
Foundry, applied here for the same reason.

It is handled accordingly:

- held as a `SecretStr`, so `repr`, logs and error messages render `**********`
- sent in an `Authorization` header, never a query string (which reaches proxy
  logs) or a request body (which some HTTP middleware echoes)
- never included in an error message, because an upstream body can echo the
  request headers back

Locally it belongs in `.env`. In Azure it belongs in Key Vault. It never belongs
in `.env.example`, a Docker image, or a commit.

---

## Cost

Every Tavily search is billed. Two settings bound what one chat turn can spend:

```dotenv
PLATFORM_AGENT__MAX_TOOL_INVOCATIONS=4
PLATFORM_AGENT__MAX_MODEL_CALLS=4
```

The tool loop checks these *between* iterations, where stopping still saves the
next call.

To stop searching entirely without changing the provider:

```dotenv
PLATFORM_FEATURES__SEARCH=false
```

The tool is then not registered at all, so an agent that declares it simply runs
without it and the turn costs exactly one model call. A real off switch, not a
tool that exists and refuses.

---

## Troubleshooting

**Startup fails: "Search provider is 'tavily' but search.tavily_api_key is not set"**
Working as designed. Set the key or choose another provider.

**"Tavily rejected the API key"**
Check the key in `.env`. Keys begin with `tvly-`.

**"Tavily plan limit reached" / "out of credits"**
The account is out of quota. Switch to `duckduckgo` to keep working.

**Searches return nothing useful on current events, and you are on DuckDuckGo**
Expected. The Instant Answer API returns abstracts, not ranked pages. This is
the case Tavily exists for.

**Health shows the provider healthy but searches fail**
Health reports configuration, not reachability — neither provider probes the
network on a health check. For Tavily that would spend a billed search on every
poll; for DuckDuckGo it would fail this instance for someone else's outage.

---

## Adding another backend

One module implementing `SearchProvider`, one member on the `provider` literal,
one branch in `build_search_provider`. Nothing else changes — not the tool, not
the runtime, not any agent. Tavily was exactly that, and the diff proves it.
