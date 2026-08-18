# CC4A (Claude Code for Agents)

A library of tools that makes Claude Code easier to use for agents.

Claude Code exposes a lot of its own state to the *user* — `/usage`, `/context`, the
status bar. Very little of it reaches the *agent*. These tools close that gap: they
are meant to be run by Claude mid-task, not read by a human on a dashboard.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/jamesmiles/claude-code-for-agents/main/install.sh | bash
```

Copies `cc4a` into `~/.claude/tools/` and, if that is not on your `PATH`, links it
into the first writable directory that is (`~/.local/bin`, `~/bin`, `/usr/local/bin`
— or `CC4A_BIN`). If none qualifies it prints the `export PATH=` line to add. Update
later with `cc4a update`.

If you would rather read the code before running it — a fair instinct for anything
that touches your OAuth token — clone and install from there instead:

```sh
git clone https://github.com/jamesmiles/claude-code-for-agents
cd claude-code-for-agents && ./install.sh
```

From a clone the installer symlinks rather than copies, so `git pull` updates in
place. `./install.sh --copy` forces a copy. Or skip the installer entirely — these
are standalone scripts, runnable from wherever you cloned them.

Both paths honour `CC4A_DEST` (install directory), `CC4A_BIN` (directory to link
into, used verbatim whether or not it is on `PATH`) and `CC4A_REF` (branch or tag).
Setting `CC4A_DEST` marks the install as isolated: it will not link into a shared
`bin` directory unless you also set `CC4A_BIN`, so a sandboxed install cannot
disturb a real one.

The installer refuses to write anything that does not look like cc4a, so a 404 page
or a truncated download cannot land as an executable. It also refuses to replace an
existing **symlink** that points somewhere else — that is usually a clone you develop
in, and overwriting it with a copy silently detaches your edits from what actually
runs. Pass `--force` if replacing it is what you want.

## Tools

Subcommands are named after the slash commands they mirror. `/usage` and `/context`
already mean something specific to anyone using Claude Code, and the tools mean the
same thing — no new vocabulary to learn or to put in an agent's context.

```
$ cc4a
COMMANDS
  status      session, account and config facts    (mirrors /status)
  context     this session's context window        (local, always available)
  usage       account rate limits                  (network, may be unavailable)
  stats       token totals per session on this host (local, mirrors /stats)
  wait        block until a usage or context threshold is crossed
  statusline  sidecar mode; see `cc4a statusline --help`
  update      install the latest version from the repo
```

### `cc4a status` — session, account and configuration facts

```
$ cc4a status
version       2.1.234
session       331f014e-e03d-439d-a947-dc7da0334c6c  (interactive cli)
name          external-source-c4  (derived)
started       Tue Aug 18 01:10:43 2026
cwd           /Users/jimmy/external-source
peer          uds:/tmp/cc-socks/62460.sock
model         opus[1m]  (claude-opus-5)
effort        high
account       James <you@example.com>  (max)
organization  your organization
settings      user, user (local)
mcp           4 configured: chrome-devtools, circleci-mcp-server, figma, mcp-atlassian
              configured only; live connection state is in-process (see /mcp)
```

Most of it is free, from `~/.claude/sessions/<pid>.json` and the environment. Name,
email, organization and plan need one network call, cached 24h; `--local` skips it.

Two fields in `/status` are **not** reproducible outside the running process, and
cc4a says so rather than printing a plausible number:

- **MCP connection state.** cc4a lists servers found in configuration. `/status`
  also counts servers needing auth and disabled ones — including account-level
  connectors that appear nowhere on disk — so its totals are usually higher. `/mcp`
  has the live state.
- **The session's display name.** Claude Code shows an AI-generated title once one
  exists; on disk the name is often still the derived one, so cc4a reports that and
  tags it with its `nameSource`.

### `cc4a context` — this session's context window

```
$ cc4a context
CONTEXT  [##..................]  10.7%  106,679 / 1,000,000 tokens  (claude-opus-5, via transcript)
         note: reflects the last completed turn; current turn is not yet written
```

Read from the session transcript, located via `$CLAUDE_CODE_SESSION_ID` — which
Claude Code exports into every Bash call, so an agent runs this with no arguments
and no knowledge of where it lives. Local file read: no network, no credentials,
always available.

### `cc4a usage` — account rate limits

```
$ cc4a usage
session                  [#...................]   5.0%  resets in 3h16m
weekly_all               [########............]  40.0%  resets in 2h26m
weekly_scoped (Fable)    [#####...............]  24.0%  resets in 2h26m
```

Read from Anthropic's OAuth usage endpoint, cached 60s. Unlike `context` this one
is a network call against an **undocumented** endpoint, so it can fail; it exits 1
and says so rather than reporting a healthy-looking guess.

The two are deliberately separate because they have opposite cost and failure
profiles. For both, run them together — one shell call, one round trip:

```sh
cc4a usage; cc4a context
```

Every command takes `--json` for hooks and workflow gating, and `--help` written for
an agent — so a model that runs one cold can interpret the result without any of
that guidance sitting in its context beforehand. Exit codes are `0` data reported,
`1` data unavailable, `2` bad invocation.

### `cc4a stats` — token totals per session on this host

```
$ cc4a stats
last 5h: 4 sessions, 778 messages

SESSION       OUTPUT  SHARE   CACHE-WRITE   MSGS  PROJECT
e2f2f822     228,732  28.7%       438,877    290  worktree-green-harbor-a623
331f014e     224,623  28.2%       723,546    191  external-source
e35bfb83     174,584  21.9%       332,941    109  worktree-clear-cloud-fa8a

totals  output 795,835 · cache-write 1,818,756 · input 1,556
        cache-read 94,078,998 — re-counted every turn, not additive consumption
```

Aggregates every transcript on the host. `--by=session` (default), `project`,
`model`, or `day`; `--since=` takes `<n>m`, `<n>h` or `<n>d` and defaults to `5h`,
the rate-limit window. The table is the summary form and `--json` the detailed one:
it returns every row with full session ids, not just the top N.

Scanning is cheap because a file holding messages after time T must have an mtime
after T, so the window prunes the corpus before any parsing — 5h touched 21 of 116
files here, and even a 30-day pass over 1GB of transcripts takes ~1.5s.

**Why it ranks by output.** Each assistant message records four token counts, and
only three are additive over a session. `cache_read` is the cached prefix re-read on
*every* turn, so it grows quadratically with session length. Over 7 days on this
machine that was 3.64 **billion** tokens against 8.6M of output — **95.6% of a naive
total**. Summing all four mostly measures how long your sessions were, not what they
consumed, so cc4a ranks by `output`, shows `cache-write` beside it, and prints
`cache-read` separately under a label saying what it is.

**`SHARE` is share of the window, not of your quota.** Anthropic publishes no token
denominator for the 5h or 7d limits (see `cc4a usage`), so "this session used X% of
your limit" is not a computable number and cc4a does not imply one.

### `cc4a wait` — block until a threshold is crossed

```sh
cc4a wait --usage-above=90                          # 5h window hits 90%
cc4a wait --usage-below=5 --timeout=6h              # wait out a window reset
cc4a wait --usage-above=90 --context-above=75@<id> --any
cc4a wait --context-above=80@<worker-a> --context-above=80@<worker-b> --any
```

Conditions are `--usage-above/below=N` (add `--window=seven_day` for the weekly cap)
and `--context-above/below=N`; `cc4a wait --help` carries worked examples for each
shape. A context condition may name its own target with
`@<session-id>`, so one call can watch several sessions at different thresholds;
a bare `--session=` sets the default for conditions without an `@target`. Exit `0`
when met, `3` on timeout, `4` when watching your own state from a call that blocks
it. `--timeout=0s` evaluates once and exits, turning `wait` into a gate:
`cc4a wait --usage-below=80 --timeout=0s || echo deferring`.

**What it is actually for.** The case that justifies a wait is one where you cannot
predict the crossing and polling would cost a tool call each time:

- *An orchestrator watching workers.* Background one call watching every worker
  session and get woken by whichever fills first — the point of per-condition
  `@targets`.
- *Rate limits.* These move through other sessions' activity and through window
  resets, both invisible to you. `--usage-below=5 --timeout=6h` waits out a reset.

Watching **your own** context is the weakest case, and worth being honest about: you
are the only thing growing it, so a plain `cc4a context` at a natural checkpoint
usually tells you what you need. A background wait is worth it only in long
autonomous runs, where it replaces repeated polling with a single wake near the
compaction threshold — one tool call instead of N.

**Composition is built in, because `&&` cannot do it.** `a && b` runs `b` only after
`a` returns, so two waits chained that way are sequential, not concurrent. Instead
pass every condition to one `wait`: they are evaluated together on each poll, with
`--any` returning on the first met (default) and `--all` when they hold
simultaneously.

**Watching your own context requires backgrounding.** A session's context only
advances when a turn *completes*. If `wait` is blocking your own turn, your turn
cannot complete, so your own context is frozen and the threshold never arrives —
measured directly, sampling own context across 6s inside one blocking call gives
`191,346 → 192,020 → 192,020`: it moves once as the current turn's own record lands,
then never again.

Started with `run_in_background`, the turn completes normally, context advances, and
the wait works as you would expect. So cc4a allows it and detects the bad case
instead of guessing: if own context is unchanged while `~/.claude/sessions/<pid>.json`
still reports `status: busy`, it exits `4` with an explanation after
`--stall-timeout` (default 5m) rather than hanging for the full timeout.

Watching *another* session with `--session=<id>` has no such constraint.

**Long waits must run in the background anyway.** A foreground Bash call in Claude
Code is capped at 600s, so waiting out a 5-hour window has to be backgrounded
regardless; the agent is re-invoked when the command exits, which is the wakeup you
wanted. Default timeout is 1h.

### `cc4a update` — install the latest version

```sh
cc4a update            # replace this file with the latest from the repo
cc4a update --check    # report whether an update is available, change nothing
cc4a update --ref=v2   # install from a branch or tag
```

Verifies the download looks like cc4a before atomically replacing itself. If cc4a
is running from a git clone it refuses and points at `git pull` instead, rather
than overwriting a file git is tracking; `--force` overrides.

### `cc4a statusline` — optional, for exact live numbers

The transcript lags by one turn. Claude Code's statusline receives an exact live
payload — including rate limits — but its output goes to the UI, where the agent
can't read it. So put cc4a *in* your status line: it caches that payload to disk
keyed by session id and prints a normal status line. `cc4a context` then reports
exact live numbers with no one-turn lag, and `cc4a usage` reads the cached payload
instead of the undocumented endpoint.

```jsonc
// ~/.claude/settings.json
{ "statusLine": { "type": "command", "command": "~/.claude/tools/cc4a statusline" } }
```

Note that configuring any custom statusline suppresses some built-in footer hints.

## Making an agent aware of a tool

A script the agent doesn't know about is a script the agent won't run. The cheapest
way to fix that is one line in your `CLAUDE.md`:

```md
`~/.claude/tools/cc4a` inspects this session: `cc4a context` for remaining context
window, `cc4a usage` for rate limits. Run `cc4a --help` for the rest.
```

That's a couple of dozen tokens, and it keeps working as tools are added, because
`cc4a --help` enumerates them and each subcommand's own `--help` carries the detail.
Nothing further sits in context. Deliberately *not* shipped here:

- **A skill** — a skill's name and description load into every session whether or not
  it's ever invoked. That's a poor trade for a tool whose purpose is conserving
  context, and installing one mutates your global skill list as a side effect. Write
  one yourself if you want it; a skill wrapping `cc4a` is four lines.
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

## Design rules

Every tool in here is expected to hold to these, and `cc4a` is the reference
implementation of them:

- **A script.** A shell command with machine-readable output — not a GUI, not a
  daemon, not an MCP server.
- **No standing footprint.** Nothing registers with Claude Code, nothing sits in the
  system prompt. A tool costs zero context until the moment it is run.
- **Cheap when it does run.** Output is compact; an agent pays context to read it.
- **Honest about gaps.** Unknown is reported as unknown, never guessed.
- **No dependencies.** Stdlib only, so it runs wherever Claude Code runs.

## Credentials and network

`cc4a usage` reads the Claude OAuth token from the macOS keychain
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
