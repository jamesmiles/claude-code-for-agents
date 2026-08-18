#!/usr/bin/env python3
"""Regression suite for cc4a. Stdlib only; run with `python3 tests/run.py`.

Every test here corresponds to a defect that reached a user. The tool talks to a
rate-limited endpoint and reads real session state, so nothing in here touches
either: HOME is redirected at a temp directory and the usage endpoint is replaced
with a local stub. If a test ever sends traffic to api.anthropic.com, that is a bug
in the test.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "tools", "cc4a")
SID = "11111111-2222-3333-4444-555555555555"
OTHER_SID = "99999999-8888-7777-6666-555555555555"

RESULTS = []


def compact(obj):
    """Claude Code writes transcripts as compact JSON; fixtures must match."""
    return json.dumps(obj, separators=(",", ":"))


def test(name):
    def deco(fn):
        RESULTS.append((name, fn))
        return fn
    return deco


class Stub:
    """Local stand-in for the usage endpoint. Serves a queue of scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.count = 0
        self._lock = threading.Lock()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                with outer._lock:
                    outer.count += 1
                    reply = (outer.replies.pop(0) if len(outer.replies) > 1
                             else outer.replies[0])
                code, headers, body = reply
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def log_message(self, *a):
                pass

        class S(http.server.ThreadingHTTPServer):
            daemon_threads = True

        self.server = S(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


OK_BODY = json.dumps({"limits": [
    {"kind": "session", "group": "session", "percent": 4, "severity": "normal",
     "resets_at": None, "scope": None, "is_active": True}]}).encode()


class Env:
    """A throwaway HOME plus a cc4a patched to talk to the stub instead of Anthropic."""

    def __init__(self, replies=None):
        self.dir = tempfile.mkdtemp(prefix="cc4a-test-")
        self.stub = Stub(replies) if replies else None
        for sub in ("projects/-fake", "sessions", "cache"):
            os.makedirs(os.path.join(self.dir, ".claude", sub), exist_ok=True)
        self.tool = os.path.join(self.dir, "cc4a")
        src = open(SRC).read()
        # Never consult the real keychain: it would put a live OAuth token into a
        # test process and make results depend on the developer's machine.
        src = src.replace('    if sys.platform == "darwin":', '    if False:')
        # Redirect every outbound endpoint, not just the one a given test exercises.
        port = self.stub.port if self.stub else 9        # port 9 refuses instantly
        src = src.replace('USAGE_URL = "https://api.anthropic.com/api/oauth/usage"',
                          'USAGE_URL = "http://127.0.0.1:%d/usage"' % port)
        src = src.replace('PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"',
                          'PROFILE_URL = "http://127.0.0.1:%d/profile"' % port)
        for leak in ('"https://api.anthropic.com/api/oauth/usage"',
                     '"https://api.anthropic.com/api/oauth/profile"'):
            assert leak not in src, "endpoint not stubbed: %s" % leak
        json.dump({"claudeAiOauth": {"accessToken": "test-token-not-real"}},
                  open(os.path.join(self.dir, ".claude", ".credentials.json"), "w"))
        open(self.tool, "w").write(src)
        os.chmod(self.tool, 0o755)

    def transcript(self, sid=SID, tokens=100_000, model="claude-opus-5", extra_lines=0,
                   age_seconds=0):
        path = os.path.join(self.dir, ".claude", "projects", "-fake", sid + ".jsonl")
        with open(path, "w") as f:
            for i in range(extra_lines):
                f.write(compact({"type": "user", "n": i}) + "\n")
            f.write(compact({
                "type": "assistant", "sessionId": sid, "cwd": "/fake",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                           time.gmtime(time.time() - age_seconds)),
                "message": {"model": model, "usage": {
                    "input_tokens": 0, "cache_read_input_tokens": tokens,
                    "cache_creation_input_tokens": 0, "output_tokens": 10}}}) + "\n")
        return path

    def session_record(self, sid=SID, pid=None, status="busy", name="fake"):
        pid = pid if pid is not None else os.getpid()
        path = os.path.join(self.dir, ".claude", "sessions", "%d.json" % pid)
        json.dump({"pid": pid, "sessionId": sid, "cwd": "/fake", "version": "2.1.234",
                   "kind": "interactive", "entrypoint": "cli", "name": name,
                   "nameSource": "derived", "status": status,
                   "procStart": "Mon Jan  1 00:00:00 2026",
                   "messagingSocketPath": "/tmp/nope.sock"}, open(path, "w"))
        return path

    def settings(self, model="opus[1m]"):
        json.dump({"model": model},
                  open(os.path.join(self.dir, ".claude", "settings.json"), "w"))

    def run(self, *args, sid=SID, timeout=90):
        env = dict(os.environ, HOME=self.dir, CLAUDE_CODE_SESSION_ID=sid)
        env.pop("CLAUDE_PID", None)
        p = subprocess.run([self.tool] + list(args), capture_output=True, text=True,
                           env=env, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    def module(self):
        """Import cc4a in-process against this HOME, for unit-level checks."""
        os.environ["HOME"] = self.dir
        ns = {"__name__": "cc4a_under_test"}
        exec(compile(open(self.tool).read(), self.tool, "exec"), ns)
        return ns

    def close(self):
        if self.stub:
            self.stub.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


# ---- wait: exit codes -------------------------------------------------------

@test("gate: condition met exits 0")
def t_gate_met(e):
    rc, out, _ = e.run("wait", "--usage-below=99", "--timeout=0s")
    assert rc == 0, rc
    assert "met" in out


@test("gate: condition not met exits 3")
def t_gate_unmet(e):
    rc, _, _ = e.run("wait", "--usage-above=99", "--timeout=0s")
    assert rc == 3, rc


@test("unreadable at timeout is inconclusive (5), not 'did not fire' (3)")
def t_blind_timeout(e):
    rc, _, _ = e.run("wait", "--usage-above=90", "--timeout=3s", "--interval=1s")
    assert rc == 5, rc


@test("unreadable gate is inconclusive (5), not 'did not fire' (3)")
def t_blind_gate(e):
    rc, _, _ = e.run("wait", "--usage-above=90", "--timeout=0s")
    assert rc == 5, rc


@test("--json reaches stdout on a negative outcome")
def t_json_stdout(e):
    rc, out, _ = e.run("wait", "--usage-above=90", "--timeout=0s", "--json")
    assert rc == 5, rc
    doc = json.loads(out)                      # must parse from stdout alone
    assert doc["result"] == "inconclusive", doc["result"]


@test("an unreadable value serialises as null, never false")
def t_null_not_false(e):
    _, out, _ = e.run("wait", "--usage-above=90", "--timeout=0s", "--json")
    cond = json.loads(out)["conditions"][0]
    assert cond["met"] is None, cond["met"]
    assert cond["available"] is False, cond["available"]


@test("interval longer than timeout still waits the full timeout")
def t_no_overshoot(e):
    start = time.time()
    rc, _, _ = e.run("wait", "--usage-above=99", "--timeout=4s", "--interval=60s")
    elapsed = time.time() - start
    assert rc == 3, rc
    assert elapsed >= 3.5, "gave up after %.1fs" % elapsed


@test("permanent failure exits 1 at once rather than waiting")
def t_permanent(e):
    start = time.time()
    rc, _, err = e.run("wait", "--usage-above=90", "--timeout=1h")
    assert rc == 1, rc
    assert time.time() - start < 20
    assert "http-401" in err, err


@test("blocking on own context exits 4 instead of hanging")
def t_stall(e):
    e.transcript()
    e.session_record(status="busy")
    rc, _, err = e.run("wait", "--context-above=99", "--stall-timeout=2s",
                       "--interval=1s", "--timeout=60s")
    assert rc == 4, rc
    assert "blocking your own turn" in err, err


@test("each context condition targets its own session")
def t_per_condition_target(e):
    e.transcript(SID, tokens=100_000)
    e.transcript(OTHER_SID, tokens=900_000)
    rc, out, _ = e.run("wait", "--context-above=50@" + OTHER_SID,
                       "--context-above=99@" + SID, "--any", "--timeout=0s", "--json")
    doc = json.loads(out)
    assert rc == 0, rc
    met = [c for c in doc["conditions"] if c["met"]]
    assert len(met) == 1 and OTHER_SID[:8] in met[0]["condition"], doc["conditions"]


# ---- usage: not amplifying a rate limit ------------------------------------

@test("a failed fetch is cached, so the next call sends nothing")
def t_failure_cached(e):
    e.run("usage")
    e.run("usage")
    e.run("usage")
    assert e.stub.count == 1, "%d requests for 3 calls" % e.stub.count


@test("Retry-After is obeyed over our own backoff guess")
def t_retry_after(e):
    e.run("usage")
    rec = json.load(open(os.path.join(e.dir, ".claude", "cache", "cc4a-limits-fail.json")))
    assert rec["retry_after_header"] == 5, rec
    assert 3 < rec["retry_at"] - time.time() <= 5.5, rec


@test("concurrent callers send one request, not one each")
def t_stampede(e):
    env = dict(os.environ, HOME=e.dir, CLAUDE_CODE_SESSION_ID=SID)
    procs = [subprocess.Popen([e.tool, "usage"], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, env=env) for _ in range(12)]
    for p in procs:
        p.wait()
    assert e.stub.count == 1, "%d requests for 12 concurrent callers" % e.stub.count


@test("a successful read clears the backoff state")
def t_backoff_cleared(e):
    e.run("usage")                                   # 429
    fail = os.path.join(e.dir, ".claude", "cache", "cc4a-limits-fail.json")
    assert os.path.exists(fail)
    rec = json.load(open(fail))
    rec["retry_at"] = time.time() - 1                # pretend the window elapsed
    json.dump(rec, open(fail, "w"))
    rc, out, _ = e.run("usage")                      # now 200
    assert rc == 0, rc
    assert not os.path.exists(fail), "backoff state survived a successful read"


# ---- argument handling ------------------------------------------------------

@test("every command rejects an unknown option instead of ignoring it")
def t_unknown_options(e):
    e.transcript()
    for cmd in ("context", "usage", "status", "stats", "sessions", "update", "wait"):
        rc, _, err = e.run(cmd, "--definitely-not-a-flag=1")
        assert rc == 2, "%s exited %s for a bogus flag" % (cmd, rc)
        assert "unknown option" in err, (cmd, err)


@test("a misspelled --session is rejected, not silently ignored")
def t_session_typo(e):
    e.transcript(SID, tokens=100_000)
    e.transcript(OTHER_SID, tokens=900_000)
    rc, _, err = e.run("context", "--sesion=" + OTHER_SID)
    assert rc == 2, "typo accepted, would have reported the wrong session"
    assert "unknown option" in err


# ---- reading session state --------------------------------------------------

@test("context reads the newest record from a large transcript")
def t_tail_read(e):
    e.settings()
    e.transcript(tokens=250_000, extra_lines=40_000)
    start = time.time()
    rc, out, _ = e.run("context", "--json")
    assert rc == 0, rc
    ctx = json.loads(out)["context"]
    assert ctx["used_tokens"] == 250_000, ctx
    assert time.time() - start < 10


@test("window size is inferred above 200k and flagged as assumed below it")
def t_window_inference(e):
    e.settings("opus[1m]")
    e.transcript(tokens=250_000)
    ctx = json.loads(e.run("context", "--json")[1])["context"]
    assert ctx["window_source"] == "inferred" and ctx["window_size"] == 1_000_000, ctx
    e.transcript(tokens=50_000)
    ctx = json.loads(e.run("context", "--json")[1])["context"]
    assert ctx["window_source"] == "assumed", ctx


@test("a stale busy flag is not reported as active")
def t_stale_busy(e):
    ns = e.module()
    e.transcript(age_seconds=3600)                    # last message an hour ago
    e.session_record(status="busy")
    ns["live_pids"] = lambda pids: set(pids)          # pretend the process is alive
    rows = ns["build_sessions"]()
    assert rows and rows[0]["status"] == "busy", rows
    assert rows[0]["status_stale"] is True, rows[0]
    assert ns["build_sessions"](active_only=True) == [], "stale busy counted as active"


@test("stats ranks by output, not by re-counted cache reads")
def t_stats_ranking(e):
    ns = e.module()
    path = os.path.join(e.dir, ".claude", "projects", "-fake", "s.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    with open(path, "w") as f:
        for sid, out_tok, cache in (("aaa", 100, 10_000_000), ("bbb", 5_000, 10)):
            f.write(compact({
                "type": "assistant", "sessionId": sid, "cwd": "/fake", "timestamp": now,
                "message": {"usage": {"input_tokens": 0, "output_tokens": out_tok,
                                      "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": cache}}}) + "\n")
    st = ns["build_stats"](3600, "session")
    assert st["rows"][0]["key"] == "bbb", [r["key"] for r in st["rows"]]
    assert st["totals"]["cache_read"] == 10_000_010, st["totals"]


# ---- reported from the field ------------------------------------------------

@test("an 8-char prefix from `sessions` output resolves")
def t_prefix_resolves(e):
    e.transcript(OTHER_SID, tokens=300_000)
    rc, out, _ = e.run("context", "--session=" + OTHER_SID[:8], "--json")
    assert rc == 0, rc
    assert json.loads(out)["session_id"] == OTHER_SID


@test("an unresolvable session id fails immediately, not as 'unavailable'")
def t_unresolvable_fails_fast(e):
    e.transcript()
    start = time.time()
    # Short subprocess timeout: if this regresses the call blocks for hours, and a
    # suite that hangs is nearly as unhelpful as one that passes wrongly.
    try:
        rc, _, err = e.run("wait", "--context-above=75@nosuchid", "--timeout=8h",
                           timeout=15)
    except subprocess.TimeoutExpired:
        raise AssertionError("did not reject the id; an armed watch monitors nothing")
    assert rc == 2, "exited %s; an armed watch would have monitored nothing" % rc
    assert "unresolvable session id" in err, err
    assert time.time() - start < 15, "did not fail fast"


@test("an ambiguous session prefix is rejected, not guessed")
def t_ambiguous_prefix(e):
    e.transcript("abc11111-0000-0000-0000-000000000000")
    e.transcript("abc22222-0000-0000-0000-000000000000")
    rc, _, err = e.run("context", "--session=abc")
    assert rc == 2, rc
    assert "ambiguous session id" in err, err


@test("one unreadable condition does not abort readable ones")
def t_blind_does_not_abort(e):
    e.transcript(OTHER_SID, tokens=100_000)
    start = time.time()
    rc, _, _ = e.run("wait", "--usage-above=85", "--context-above=99@" + OTHER_SID,
                     "--any", "--unavailable-timeout=1s", "--interval=1s", "--timeout=6s")
    elapsed = time.time() - start
    assert elapsed >= 5, "gave up after %.1fs; readable conditions were still live" % elapsed
    assert rc == 5, rc


@test("LAST reflects the newest message, not later non-message writes")
def t_last_active_ignores_file_writes(e):
    ns = e.module()
    path = e.transcript(age_seconds=6 * 86400)  # last message six days ago
    # ...then the records Claude Code keeps appending long afterwards, which move
    # the file's mtime to now without anything being said
    with open(path, "a") as f:
        f.write(compact({"type": "system", "note": "written later"}) + "\n")
        f.write(compact({"type": "file-history-snapshot"}) + "\n")
    e.session_record(status="idle")
    ns["live_pids"] = lambda pids: set(pids)
    row = ns["build_sessions"]()[0]
    days = row["last_active_seconds_ago"] / 86400
    assert 5.5 < days < 6.5, "reported %.2f days idle; mtime would have said ~0" % days


@test("stats counts a repeated message.id once")
def t_stats_dedupe(e):
    ns = e.module()
    path = os.path.join(e.dir, ".claude", "projects", "-fake", "s.jsonl")
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    rec = {"type": "assistant", "sessionId": "aaa", "cwd": "/fake", "timestamp": now,
           "message": {"id": "msg_1", "usage": {
               "input_tokens": 0, "output_tokens": 1000,
               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}
    with open(path, "w") as f:
        for _ in range(3):                       # same message written three times
            f.write(compact(rec) + "\n")
    st = ns["build_stats"](3600, "session")
    assert st["totals"]["output"] == 1000, "summed to %s" % st["totals"]["output"]
    assert st["rows"][0]["messages"] == 1, st["rows"][0]["messages"]


@test("usage --json marks a failure explicitly, not just an empty array")
def t_usage_json_marks_failure(e):
    rc, out, _ = e.run("usage", "--json")
    doc = json.loads(out)
    assert rc != 0, "throttled read exited 0"
    assert doc["ok"] is False, doc
    assert doc.get("error"), doc
    ok_doc = json.loads(e.run("usage", "--json")[1])   # still throttled, still false
    assert ok_doc["ok"] is False


# ---- runner -----------------------------------------------------------------

SETUP = {
    "gate: condition met exits 0": [(200, {}, OK_BODY)],
    "gate: condition not met exits 3": [(200, {}, OK_BODY)],
    "unreadable at timeout is inconclusive (5), not 'did not fire' (3)": [(429, {}, b"")],
    "unreadable gate is inconclusive (5), not 'did not fire' (3)": [(429, {}, b"")],
    "--json reaches stdout on a negative outcome": [(429, {}, b"")],
    "an unreadable value serialises as null, never false": [(429, {}, b"")],
    "interval longer than timeout still waits the full timeout": [(200, {}, OK_BODY)],
    "permanent failure exits 1 at once rather than waiting": [(401, {}, b"")],
    "each context condition targets its own session": [(200, {}, OK_BODY)],
    "a failed fetch is cached, so the next call sends nothing": [(429, {}, b"")],
    "Retry-After is obeyed over our own backoff guess": [(429, {"Retry-After": "5"}, b"")],
    "concurrent callers send one request, not one each": [(200, {}, OK_BODY)],
    "a successful read clears the backoff state": [(429, {}, b""), (200, {}, OK_BODY)],
    "every command rejects an unknown option instead of ignoring it": [(200, {}, OK_BODY)],
    "an unresolvable session id fails immediately, not as 'unavailable'": [(200, {}, OK_BODY)],
    "one unreadable condition does not abort readable ones": [(429, {}, b"")],
    "usage --json marks a failure explicitly, not just an empty array": [(429, {}, b"")],
}


def main():
    real_home = os.environ.get("HOME")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    failed = passed = 0
    for name, fn in RESULTS:
        if only and only not in name:
            continue
        e = Env(SETUP.get(name))
        try:
            fn(e)
            print("  PASS  %s" % name)
            passed += 1
        except AssertionError as exc:
            print("  FAIL  %s\n          %s" % (name, exc))
            failed += 1
        except Exception as exc:
            print("  ERROR %s\n          %r" % (name, exc))
            failed += 1
        finally:
            e.close()
            if real_home:
                os.environ["HOME"] = real_home
    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
