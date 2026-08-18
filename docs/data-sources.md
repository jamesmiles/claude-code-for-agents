# Where Claude Code keeps agent-relevant signals

Claude Code surfaces plenty of state to the *user* through slash commands and the
status bar. Much less of it reaches the *agent*. This is a map of what lives where,
so tools in this repo (and yours) can pick the right source instead of guessing.

Verified against Claude Code 2.1.234 (August 2026).

## Budget signals

| Source | Context window | Rate limits | Reachable by an agent? |
|---|---|---|---|
| Statusline stdin JSON | yes, exact | yes (`five_hour`, `seven_day`) | no — output renders to the UI |
| Hook stdin JSON | no | no | yes, but carries neither |
| Session transcript `.jsonl` | yes, derivable | no | yes |
| OAuth usage endpoint | no | yes | yes |

No single source has both. Anything reporting context *and* limits is joining at
least two of these.

### Statusline stdin

The richest payload, and the **only in-process source of rate limits**. Claude Code
pipes JSON to your statusline command on each render:

```json
{
  "session_id": "...",
  "model": { "display_name": "Opus 5" },
  "context_window": {
    "total_input_tokens": 15500,
    "context_window_size": 200000,
    "used_percentage": 8,
    "remaining_percentage": 92,
    "current_usage": {
      "input_tokens": 8500,
      "cache_creation_input_tokens": 5000,
      "cache_read_input_tokens": 2000,
      "output_tokens": 1200
    }
  },
  "exceeds_200k_tokens": false,
  "rate_limits": {
    "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
    "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 }
  },
  "cost": { "total_cost_usd": 0.01234 }
}
```

Caveats from the docs:

- `rate_limits` appears only for Claude.ai Pro/Max subscribers, and only after the
  first API response of the session. Either window may be independently absent.
  API-key auth gets nothing here.
- `current_usage` is `null` before the first API call, and again after `/compact`
  until the next call repopulates it.
- `used_percentage` is **input-only**: `input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens`. It excludes `output_tokens`. Match this formula if you
  compute your own, or your number will disagree with the status bar.

Since the agent can't read the statusline's output, the trick is to have the
statusline **write the payload to disk** keyed by `session_id`, and let the agent
read that file. That's what `cc4a statusline` does.

### Hook stdin

Every hook receives `session_id`, `prompt_id`, `transcript_path`, `cwd`,
`permission_mode`, `effort`, `hook_event_name`, plus `agent_id` / `agent_type` for
subagents. It does **not** receive context window or rate limit data — confirmed in
the hooks reference. `transcript_path` is the useful one: it points at the source
below.

### Session transcript

`~/.claude/projects/<slugified-cwd>/<session-id>.jsonl`, one JSON object per line.
Assistant lines carry a full `usage` object:

```json
{ "input_tokens": 2, "cache_creation_input_tokens": 11272,
  "cache_read_input_tokens": 22806, "output_tokens": 1116,
  "output_tokens_details": { "thinking_tokens": 789 } }
```

Sum the three input fields for context occupancy. Two caveats: the current turn is
not flushed until it completes, so a mid-turn read lags by one turn; and subagent
lines are marked `isSidechain: true` — filter them out or you'll read a subagent's
context as your own.

The transcript does **not** contain rate limit data.

### OAuth usage endpoint

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <token>
anthropic-beta: oauth-2025-04-20
```

**Undocumented and unsupported** — it can change without notice, and there is an open
request for official programmatic access. Treat a failure as "unknown", never as
"fine".

Returns `five_hour` / `seven_day` objects plus a richer `limits[]` array:

```json
{ "kind": "weekly_scoped", "group": "weekly", "percent": 24,
  "severity": "normal", "resets_at": "...", "is_active": false,
  "scope": { "model": { "display_name": "Fable" } } }
```

`is_active` marks which window is currently the binding constraint — more useful
than raw percentages when deciding whether to proceed. `severity` escalates as a
window fills.

The `limit_dollars` / `used_dollars` / `remaining_dollars` fields are `null` on
subscription plans. **There is no absolute cap to read** — only utilization
percentage. This is why `/usage` shows percentages too. Don't invent a denominator.

## Aggregating usage across sessions

Every session on the host leaves a transcript under `~/.claude/projects/*/*.jsonl`,
and each assistant line carries both a `timestamp` and a full `usage` object. That
is enough to reconstruct per-session, per-project, per-model or per-day token totals
without any network call.

Two things make it practical and correct:

**Prune by mtime first.** A file containing a message newer than T must itself have
an mtime newer than T, so `os.stat` rejects most of the corpus before you parse a
byte. A 5-hour window touched 21 of 116 files on this machine; a 30-day pass over
1GB still finished in ~1.5s.

**Do not sum the four token counts.** They are not commensurable:

| field | additive? | meaning |
|---|---|---|
| `output_tokens` | yes | tokens generated — the truest measure of work |
| `cache_creation_input_tokens` | yes | context written to cache, paid once |
| `input_tokens` | yes | uncached input, usually tiny |
| `cache_read_input_tokens` | **no** | cached prefix re-counted on *every* turn |

`cache_read` grows with the square of session length: a 200-turn session with a 50k
prefix reports ~10M cache-read tokens having cached 50k once. Measured over 7 days
here it was 3,640,536,773 tokens against 8,633,260 of output — **95.6% of a naive
sum**. Any "total tokens used" figure built by adding all four is mostly a proxy for
session length. Rank by `output`, report the components separately, and label
`cache_read` for what it is.

Note also that `~/.claude/stats-cache.json` already holds `dailyModelTokens` and a
`modelUsage` breakdown — but only by day and by model, never by session, and
`lastComputedDate` typically lags a day behind. Per-session numbers require the scan.
On subscription plans its `costUSD` fields are `0`, so cost is not a usable ranking.

## A blocking call freezes the caller's own context

Context occupancy is written only when an assistant turn *completes*. While a tool
call is executing, the calling session's turn has not completed, so its own context
is frozen for the duration of that call. Sampling it three times over six seconds
inside a single call gives:

```
t=0s  191,346 tokens
t=3s  192,020 tokens   <- the current turn's own record lands
t=6s  192,020 tokens   <- and nothing further, however long you wait
```

This constrains *blocking* designs only. An agent that starts a long-running process
in the background lets its turn complete normally, so its context does advance and a
background watcher observes it fine. The failure mode is specifically a foreground
call waiting on state that only its own completion can change.

Note also that a Claude Code foreground Bash call is capped at 600s, so any wait
longer than ten minutes has to be backgrounded regardless of what it watches.

## Reading a transcript without reading a transcript

Transcripts grow large — 143MB was the biggest on the machine this was written on,
with several over 40MB. Everything a monitor wants (the latest `usage` block) is in
the *last* record, so scan backwards from EOF in chunks instead of parsing forward.
That turns a multi-second read into ~1ms, and makes per-session context across every
session on the host viable: 41 sessions in 0.2s.

Two details matter. Discard the first line of each chunk unless you have reached the
start of the file, since it is usually a partial line. And skip records with
`isSidechain: true`, which belong to subagents rather than the session itself.

## A session's context window size is not recorded

The transcript gives exact token counts but never the window they are measured
against. `message.model` reads `claude-opus-5`, with no marker distinguishing the
200k variant from the 1M one; only the local `settings.json` carries `opus[1m]`, and
that describes *your* session, not the one you are inspecting.

So the percentage is only partly knowable from outside. Above 200k used tokens the
window must be the larger one — the number could not fit otherwise. Below that it is
genuinely ambiguous: 150k could be 75% of 200k or 15% of 1M. Report the token count,
which is exact, and label the percentage as assumed when it rests on a guess. The
statusline sidecar carries `context_window_size` explicitly and settles it, but only
for a session that has one installed.

## Telling a busy session from an idle one

`~/.claude/sessions/<pid>.json` carries a live `status` field, updated as the session
runs:

```
  pid=62460   status=busy     updated=   33s ago  331f014e  external-source-c4
  pid=44046   status=waiting  updated=  112s ago  e35bfb83  worktree-clear-cloud-fa8a-10
  pid=38642   status=idle     updated= 2442s ago  e2f2f822  worktree-green-harbor-a623-c4
```

`busy` means a turn is in flight, `waiting` means it is waiting on the user, `idle`
means neither. Combined with the section above this is enough to distinguish "the
value I am watching has not moved yet" from "the value I am watching cannot move,
because I am the one blocking it": unchanged own-context plus `status: busy` means
the watcher is inside the very turn whose completion it is waiting for.

## Session and account facts

`~/.claude/sessions/<pid>.json` is written per running process and carries most of
what `/status` displays:

```json
{ "pid": 62460, "sessionId": "...", "cwd": "...", "version": "2.1.234",
  "kind": "interactive", "entrypoint": "cli", "name": "external-source-c4",
  "nameSource": "derived", "status": "busy",
  "messagingSocketPath": "/tmp/cc-socks/62460.sock" }
```

Locate it via `$CLAUDE_PID`, or scan the directory for a matching `sessionId`.
Two caveats: `cwd` is where the session started and may not be the live directory,
and `name` is often the *derived* name (`external-source-c4`) even when the UI is
showing an AI-generated title — the title is not written here.

Account identity comes from a second undocumented OAuth endpoint, same auth as the
usage one:

```
GET https://api.anthropic.com/api/oauth/profile
```

Returns `account` (`full_name`, `email`, `has_claude_max`, `has_claude_pro`) and
`organization` (`name`, `organization_type`, `billing_type`). Changes rarely, so
cache it for a day rather than per call. `subscriptionType` is also available
locally in the keychain credential blob, without any network call.

## MCP servers are not fully on disk

`~/.claude.json` holds `mcpServers` globally and per project under
`projects.<cwd>.mcpServers`, plus `enabledMcpjsonServers` / `disabledMcpjsonServers`.

This is **configuration, not state**, and it is incomplete: account-level connectors
provided through your Claude account — Gmail, Google Calendar, Google Drive — appear
in `/status` counts and in the session's tool list while existing in no local file.
Connection status lives only in the running process. Any tool reporting "N connected"
from disk is guessing; report configured servers and say so.

## Session identity

`$CLAUDE_CODE_SESSION_ID` is exported into every Bash tool call, so an agent can
locate its own transcript without being told the path. Also present:
`$CLAUDE_CODE_ENTRYPOINT`, `$CLAUDE_PID`, `$CLAUDE_EFFORT`, `$CLAUDECODE=1`.

## Credential storage

On macOS the Claude OAuth token lives in the **keychain**, under the service name
`Claude Code-credentials`:

```
security find-generic-password -s "Claude Code-credentials" -w
```

`~/.claude/.credentials.json` exists but typically holds only *MCP server* OAuth
tokens — several published monitors read it for the Claude token and silently find
nothing on macOS. On Linux, check the file and the system keyring.

Read the token fresh on each call. Claude Code rotates it, and a cached copy will
start returning 401.
