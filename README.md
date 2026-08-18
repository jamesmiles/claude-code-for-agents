# CC4A (Claude Code for Agents)

A library of tools that makes Claude Code easier to use for agents.

Claude Code exposes a lot of its own state to the *user* — `/usage`, `/context`, the
status bar. Very little of it reaches the *agent*. These tools close that gap: they
are meant to be run by Claude mid-task, not read by a human on a dashboard.

Design rules for anything in here:

- **A script.** A shell command with machine-readable output — not a GUI, not a
  daemon, not an MCP server.
- **No standing footprint.** Nothing registers with Claude Code, nothing sits in the
  system prompt. A tool costs zero context until the moment it is run.
- **Cheap when it does run.** Output is compact; an agent pays context to read it.
- **Honest about gaps.** Unknown is reported as unknown, never guessed.
- **No dependencies.** Stdlib only, so it runs wherever Claude Code runs.

## Tools

Everything is reached through one command, so an agent has one name to remember and
`cc4a --help` to discover the rest:

```
$ cc4a
COMMANDS
  budget    read this session's context window and account rate limits
```

Each subcommand carries its own `--help`.

### `cc4a budget` — read your own context window and rate limits

```
$ cc4a budget
CONTEXT  [##..................]   8.3%  82,572 / 1,000,000 tokens  (claude-opus-5, via transcript)
         note: reflects the last completed turn; current turn is not yet written
session                  [#...................]   4.0%  resets in 3h21m
weekly_all               [########............]  40.0%  resets in 2h31m
weekly_scoped (Fable)    [#####...............]  24.0%  resets in 2h31m
```

`cc4a budget --json` emits the same data machine-readably, for hooks or workflow
gating. `cc4a budget --help` explains how to read the output and what to do about
it — written for an agent, so a model that runs the tool cold can interpret the
result without you having to pre-load any of that into its context.

Context and rate limits live in different places and neither source has both, so
`cc4a budget` joins them:

- **Context window** — from the session transcript, located via
  `$CLAUDE_CODE_SESSION_ID`. Accurate as of the last *completed* turn.
- **Rate limits** — from Anthropic's OAuth usage endpoint, cached for 60s.

#### Optional: exact, live context via the statusline

The transcript lags by one turn. Claude Code's statusline receives an exact live
payload — including rate limits — but its output goes to the UI, where the agent
can't read it. So run `cc4a budget` *as* your statusline: it caches the payload to
disk keyed by session ID, prints a normal status line, and subsequent `cc4a budget`
calls read exact numbers with no network call.

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "~/.claude/tools/cc4a budget --statusline" } }
```

Note that configuring any custom statusline suppresses some built-in footer hints.

## Install

```sh
git clone https://github.com/jamesmiles/claude-code-for-agents
cd claude-code-for-agents && ./install.sh
```

Symlinks `tools/` into `~/.claude/tools/`, so `git pull` picks up updates.
`./install.sh --copy` copies instead. Or skip the installer entirely — these are
standalone scripts, runnable from wherever you cloned them.

## Making an agent aware of a tool

A script the agent doesn't know about is a script the agent won't run. The cheapest
way to fix that is one line in your `CLAUDE.md`:

```md
`~/.claude/tools/cc4a` provides tools for inspecting this session; run it with
`--help` to see them. `cc4a budget` reports remaining context window and rate limits.
```

That's a couple of dozen tokens, and it keeps working as tools are added, because
`cc4a --help` enumerates them and each subcommand's own `--help` carries the detail.
Nothing further sits in context. Deliberately *not* shipped here:

- **A skill** — a skill's name and description load into every session whether or not
  it's ever invoked. That's a poor trade for a tool whose purpose is conserving
  context, and installing one mutates your global skill list as a side effect. Write
  one yourself if you want it; a skill wrapping `cc4a budget` is four lines.
- **An MCP server** — same objection, larger. Tool definitions are standing context.

If you only want it occasionally, add nothing and just ask.

## How this differs from the usage monitors

There are good usage monitors already — [onWatch](https://github.com/onllm-dev/onWatch),
[Claude-Usage-Tracker](https://github.com/hamed-elfayome/Claude-Usage-Tracker),
[usage-monitor-for-claude](https://github.com/jens-duttke/usage-monitor-for-claude),
[ccusage](https://github.com/ryoppippi/ccusage), and a healthy ecosystem of statuslines.

They are **account-level quota displays built for a human to look at**. This is a
**session-level read built for an agent to call**. The practical difference is the
context window: it's per-session state that lives only in that session's transcript
and statusline payload, so an account-wide dashboard structurally cannot report it.
If you want a tray icon showing your weekly burn, use one of those — they're better
at it. If you want Claude to check its own headroom before starting something
expensive, use this.

## Credentials and network

`cc4a budget` reads the Claude OAuth token from the macOS keychain
(`Claude Code-credentials`), falling back to `~/.claude/.credentials.json`. It sends
that token to exactly one host, `api.anthropic.com`, and to no other. Nothing is
uploaded, phoned home, or written outside `~/.claude/cache/`.

## Caveats

- The rate-limit endpoint is **undocumented**. It may change or disappear without
  notice; there is an open request for official programmatic access. Failures are
  reported as `unavailable` rather than assumed healthy.
- Rate limits require a Claude.ai Pro/Max subscription. API-key auth returns nothing.
- Absolute limits are not knowable. Anthropic returns utilization percentage with
  `limit_dollars: null` — there is no denominator to report, which is why `/usage`
  shows percentages too.

## Reference

[`docs/data-sources.md`](docs/data-sources.md) maps every agent-relevant signal in
Claude Code — statusline payload, hook payload, transcript format, session env vars,
credential storage — with the caveats for each. Useful for building your own tools,
and the basis for everything here.

## License

MIT
