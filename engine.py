"""
ai-token-burn — usage aggregation engine.

`compute_claude()` is a clean-room reimplementation of the Claude desktop app's
/stats engine ("What's up next" panel). It has been validated byte-for-byte against
the app's actual extracted code on a frozen snapshot of the logs: Sessions, Messages,
Active days, Total tokens, every per-model in/out/cache figure, Peak hour, both
streaks, first/last session date, Favorite model, and the daily token heatmap all
match exactly. (The app's internal `toolCallCount` is FS-order-dependent and not
shown in the panel, so it is intentionally not reproduced.)

Key fidelity details:
  * tokens reported in the headline EXCLUDE cache (input+output only); cache read/
    creation are tracked separately.
  * a "session" is a non-subagent transcript with >=1 non-sidechain user/assistant
    message, dated by its first message's LOCAL date.
  * subagent transcripts (<session>/subagents/agent-*.jsonl) contribute tokens but
    never sessions/messages/active-days — here we also keep them in a SEPARATE bucket
    so a dashboard can toggle them on/off.
  * lines are split on \\r\\n | \\r | \\n | U+2028 | U+2029 to mirror Node's readline
    (the app silently drops records containing U+2028/U+2029, so we must too).
"""
from __future__ import annotations
import os
import re
import json
from datetime import datetime, timedelta

SYNTHETIC = "<synthetic>"
# Node's readline line boundaries — NOT just \n/\r. U+2028/U+2029 matter (see module docstring).
_LINE_SPLIT = re.compile("\\r\\n|\\r|\\n|\\u2028|\\u2029")


def _parse_jsonl(path: str) -> list[dict]:
    """Read a transcript exactly like the app's `cKr` (Node readline + JSON.parse)."""
    try:
        raw = open(path, encoding="utf-8", errors="replace", newline="").read()
    except OSError:
        return []
    out = []
    for line in _LINE_SPLIT.split(raw):
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _local_date_hour(ts: str) -> tuple[str, int]:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%Y-%m-%d"), dt.hour


def _claude_transcripts(projects_dir: str) -> list[str]:
    """Mirror of the app's `gKr`: project/*.jsonl + project/<session>/subagents/agent-*.jsonl."""
    files: list[str] = []
    try:
        projects = os.listdir(projects_dir)
    except OSError:
        return files
    for proj in projects:
        pdir = os.path.join(projects_dir, proj)
        if not os.path.isdir(pdir):
            continue
        for name in os.listdir(pdir):
            full = os.path.join(pdir, name)
            if os.path.isfile(full) and name.endswith(".jsonl"):
                files.append(full)
            elif os.path.isdir(full):
                sub = os.path.join(full, "subagents")
                if os.path.isdir(sub):
                    files += [
                        os.path.join(sub, x)
                        for x in os.listdir(sub)
                        if x.endswith(".jsonl") and x.startswith("agent-")
                    ]
    return files


def _streaks(active_dates: set[str]) -> dict:
    if not active_dates:
        return {"currentStreak": 0, "longestStreak": 0}
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    cur = 0
    d = today
    while d.strftime("%Y-%m-%d") in active_dates:
        cur += 1
        d -= timedelta(days=1)
    arr = sorted(active_dates)
    longest = run = 1
    for i in range(1, len(arr)):
        p = datetime.strptime(arr[i - 1], "%Y-%m-%d")
        q = datetime.strptime(arr[i], "%Y-%m-%d")
        if round((q - p).total_seconds() / 86400) == 1:
            run += 1
        else:
            longest = max(longest, run)
            run = 1
    return {"currentStreak": cur, "longestStreak": max(longest, run)}


def _new_model_bucket() -> dict:
    return {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}


def compute_claude(claude_dir: str | None = None, since_days: int | None = None) -> dict:
    """Aggregate Claude Code usage. `since_days` caps history (None = all on disk)."""
    claude_dir = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    projects = os.path.join(claude_dir, "projects")
    floor = None
    if since_days is not None:
        floor = (datetime.now().astimezone() - timedelta(days=since_days)).strftime("%Y-%m-%d")
    sub_marker = f"{os.sep}subagents{os.sep}"

    sessions = messages = 0
    sub_sessions = sub_messages = 0
    first_ts = last_ts = None
    hour_order: list[int] = []
    hour_counts: dict[int, int] = {}
    model_usage: dict[str, dict] = {}        # app-identical (includes subagent tokens)
    model_usage_sub: dict[str, dict] = {}    # subagent-only portion
    daily: dict[str, dict] = {}              # date -> {messages, sessions, subMessages, subSessions}
    daily_model: dict[str, dict] = {}        # date -> {model: in+out}  (app-identical)
    daily_model_sub: dict[str, dict] = {}    # subagent-only

    for path in _claude_transcripts(projects):
        entries = _parse_jsonl(path)
        msgs = [e for e in entries if e.get("type") in ("user", "assistant")]
        if not msgs:
            continue
        is_sub = sub_marker in path
        kept = msgs if is_sub else [e for e in msgs if not e.get("isSidechain")]
        if not kept:
            continue
        ts0 = kept[0].get("timestamp") or ""
        try:
            date, hour = _local_date_hour(ts0)
        except ValueError:
            continue
        if floor is not None and date < floor:
            continue

        day = daily.setdefault(date, {"messages": 0, "sessions": 0, "subMessages": 0, "subSessions": 0})
        if is_sub:
            sub_sessions += 1
            sub_messages += len(kept)
            day["subSessions"] += 1
            day["subMessages"] += len(kept)
        else:
            sessions += 1
            messages += len(kept)
            day["sessions"] += 1
            day["messages"] += len(kept)
            if hour not in hour_counts:
                hour_order.append(hour)
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
            if first_ts is None or ts0 < first_ts:
                first_ts = ts0
            if last_ts is None or ts0 > last_ts:
                last_ts = ts0

        for e in kept:
            if e.get("type") != "assistant":
                continue
            usage = (e.get("message") or {}).get("usage")
            if not usage:
                continue
            model = (e.get("message") or {}).get("model") or "unknown"
            if model == SYNTHETIC:
                continue
            bucket = model_usage.setdefault(model, _new_model_bucket())
            bucket["inputTokens"] += usage.get("input_tokens", 0) or 0
            bucket["outputTokens"] += usage.get("output_tokens", 0) or 0
            bucket["cacheReadInputTokens"] += usage.get("cache_read_input_tokens", 0) or 0
            bucket["cacheCreationInputTokens"] += usage.get("cache_creation_input_tokens", 0) or 0
            burn = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            if burn > 0:
                daily_model.setdefault(date, {})
                daily_model[date][model] = daily_model[date].get(model, 0) + burn
            if is_sub:
                sb = model_usage_sub.setdefault(model, _new_model_bucket())
                sb["inputTokens"] += usage.get("input_tokens", 0) or 0
                sb["outputTokens"] += usage.get("output_tokens", 0) or 0
                sb["cacheReadInputTokens"] += usage.get("cache_read_input_tokens", 0) or 0
                sb["cacheCreationInputTokens"] += usage.get("cache_creation_input_tokens", 0) or 0
                if burn > 0:
                    daily_model_sub.setdefault(date, {})
                    daily_model_sub[date][model] = daily_model_sub[date].get(model, 0) + burn

    peak_hour, best = None, 0
    for h in hour_order:
        if hour_counts[h] > best:
            best, peak_hour = hour_counts[h], h

    def models_list(usage: dict) -> list[dict]:
        total = sum(v["inputTokens"] + v["outputTokens"] for v in usage.values()) or 1
        rows = []
        for m, v in usage.items():
            io = v["inputTokens"] + v["outputTokens"]
            rows.append({
                "model": m, "in": v["inputTokens"], "out": v["outputTokens"],
                "cacheRead": v["cacheReadInputTokens"], "cacheCreation": v["cacheCreationInputTokens"],
                "total": io, "pct": round(100 * io / total, 1),
            })
        return sorted(rows, key=lambda r: -r["total"])

    total_tokens = sum(v["inputTokens"] + v["outputTokens"] for v in model_usage.values())
    models = models_list(model_usage)
    daily_rows = [{
        "date": d,
        "tokens": sum(daily_model.get(d, {}).values()),
        "byModel": daily_model.get(d, {}),
        "messages": daily[d]["messages"],
        "sessions": daily[d]["sessions"],
        "subTokens": sum(daily_model_sub.get(d, {}).values()),
        "subMessages": daily[d]["subMessages"],
        "subSessions": daily[d]["subSessions"],
    } for d in sorted(daily)]

    return {
        "tool": "claude",
        "overview": {
            "sessions": sessions,
            "messages": messages,
            "totalTokens": total_tokens,
            "activeDays": len(daily),
            "peakHour": peak_hour,
            "favoriteModel": models[0]["model"] if models else None,
            "firstSessionDate": first_ts,
            "lastSessionDate": last_ts,
            **_streaks(set(daily)),
        },
        "models": models,
        "daily": daily_rows,
        "hourCounts": {str(h): c for h, c in sorted(hour_counts.items())},
        "subagents": {
            "sessions": sub_sessions,
            "messages": sub_messages,
            "totalTokens": sum(v["inputTokens"] + v["outputTokens"] for v in model_usage_sub.values()),
            "models": models_list(model_usage_sub),
        },
    }


def _codex_rollouts(sessions_dir: str) -> list[str]:
    out: list[str] = []
    for root, _dirs, files in os.walk(sessions_dir):
        for n in files:
            if n.startswith("rollout-") and n.endswith(".jsonl"):
                out.append(os.path.join(root, n))
    return out


def compute_codex(codex_dir: str | None = None, since_days: int | None = None) -> dict:
    """Aggregate OpenAI Codex CLI usage from ~/.codex/sessions/**/rollout-*.jsonl.

    Codex resends full context each turn, so per-event `last_token_usage` is not a
    clean delta — the authoritative session total is the FINAL `total_token_usage`.
    To stay comparable with Claude's cache-excluded headline:
        in  = input_tokens - cached_input_tokens   (non-cached input)
        out = output_tokens + reasoning_output_tokens
        cacheRead = cached_input_tokens
    """
    codex_dir = codex_dir or os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    sessions_dir = os.path.join(codex_dir, "sessions")
    floor = None
    if since_days is not None:
        floor = (datetime.now().astimezone() - timedelta(days=since_days)).strftime("%Y-%m-%d")

    sessions = messages = 0
    first_ts = last_ts = None
    hour_order: list[int] = []
    hour_counts: dict[int, int] = {}
    model_usage: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    daily_model: dict[str, dict] = {}

    for path in _codex_rollouts(sessions_dir):
        entries = _parse_jsonl(path)
        if not entries:
            continue
        sess_first = None
        model = None
        umsg = amsg = 0
        final_total = None
        for o in entries:
            ts = o.get("timestamp")
            if ts and sess_first is None:
                sess_first = ts
            payload = o.get("payload") or {}
            etype = o.get("type")
            if etype == "turn_context" and model is None and payload.get("model"):
                model = payload["model"]
            elif etype == "session_meta" and model is None:
                model = payload.get("model") or (payload.get("payload") or {}).get("model")
            elif etype == "event_msg":
                pt = payload.get("type")
                if pt == "user_message":
                    umsg += 1
                elif pt == "agent_message":
                    amsg += 1
                elif pt == "token_count":
                    tot = (payload.get("info") or {}).get("total_token_usage")
                    if tot:
                        final_total = tot
        if sess_first is None or (umsg + amsg == 0 and not final_total):
            continue
        try:
            date, hour = _local_date_hour(sess_first)
        except ValueError:
            continue
        if floor is not None and date < floor:
            continue
        model = model or "unknown"

        sessions += 1
        messages += umsg + amsg
        day = daily.setdefault(date, {"messages": 0, "sessions": 0})
        day["sessions"] += 1
        day["messages"] += umsg + amsg
        if hour not in hour_counts:
            hour_order.append(hour)
        hour_counts[hour] = hour_counts.get(hour, 0) + 1
        if first_ts is None or sess_first < first_ts:
            first_ts = sess_first
        if last_ts is None or sess_first > last_ts:
            last_ts = sess_first

        if final_total:
            cached = final_total.get("cached_input_tokens", 0) or 0
            in_nc = max((final_total.get("input_tokens", 0) or 0) - cached, 0)
            out = (final_total.get("output_tokens", 0) or 0) + (final_total.get("reasoning_output_tokens", 0) or 0)
            bucket = model_usage.setdefault(model, _new_model_bucket())
            bucket["inputTokens"] += in_nc
            bucket["outputTokens"] += out
            bucket["cacheReadInputTokens"] += cached
            burn = in_nc + out
            if burn > 0:
                daily_model.setdefault(date, {})
                daily_model[date][model] = daily_model[date].get(model, 0) + burn

    peak_hour, best = None, 0
    for h in hour_order:
        if hour_counts[h] > best:
            best, peak_hour = hour_counts[h], h

    total = sum(v["inputTokens"] + v["outputTokens"] for v in model_usage.values()) or 1
    models = sorted(
        ({
            "model": m, "in": v["inputTokens"], "out": v["outputTokens"],
            "cacheRead": v["cacheReadInputTokens"], "cacheCreation": 0,
            "total": v["inputTokens"] + v["outputTokens"],
            "pct": round(100 * (v["inputTokens"] + v["outputTokens"]) / total, 1),
        } for m, v in model_usage.items()),
        key=lambda r: -r["total"],
    )
    daily_rows = [{
        "date": d,
        "tokens": sum(daily_model.get(d, {}).values()),
        "byModel": daily_model.get(d, {}),
        "messages": daily[d]["messages"],
        "sessions": daily[d]["sessions"],
    } for d in sorted(daily)]

    return {
        "tool": "codex",
        "overview": {
            "sessions": sessions,
            "messages": messages,
            "totalTokens": sum(v["inputTokens"] + v["outputTokens"] for v in model_usage.values()),
            "activeDays": len(daily),
            "peakHour": peak_hour,
            "favoriteModel": models[0]["model"] if models else None,
            "firstSessionDate": first_ts,
            "lastSessionDate": last_ts,
            **_streaks(set(daily)),
        },
        "models": models,
        "daily": daily_rows,
        "hourCounts": {str(h): c for h, c in sorted(hour_counts.items())},
    }
