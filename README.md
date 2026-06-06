# ai-token-burn

A token **burn-rate graph** for your GitHub profile — like the contribution calendar,
but for your **Claude Code** and **Codex** usage. It mirrors the stats the Claude
desktop app shows in its "What's up next" panel (sessions, messages, total tokens,
active days, streaks, peak hour, favorite model, per-model in/out, and the daily token
heatmap) and extends them to Codex.

> **Why local?** Your real usage lives only in local logs. Claude Code (Max/Pro) and
> Codex (ChatGPT) bill via subscription, and the Anthropic/OpenAI *usage APIs* only
> report API-key-billed usage — so a cloud job would render a graph of ~zero. The data
> has to originate from your machine.

## What it reads

| Tool | Source |
|------|--------|
| Claude Code | `~/.claude/projects/**/*.jsonl` (incl. `subagents/agent-*.jsonl`) |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` |

Output (`data/stats.json`) is **aggregates only** — counts, tokens, dates, model names,
hour buckets. No prompt text, no file paths. Safe to publish.

## ⚠️ Claude Code silently deletes your history (`cleanupPeriodDays`)

Claude Code **prunes local transcripts** on a rolling window controlled by the
`cleanupPeriodDays` setting, which **defaults to 30 days** — older
`~/.claude/projects/**/*.jsonl` files are deleted on startup. Since subscription usage
exists *nowhere else* (not in any API), that history is **gone for good**. Codex rotates
its rollouts the same way. This is why a brand-new install of this tool will show only
the last ~month, no matter how long you've actually been using Claude Code.

If you want to keep your full burn history, raise the limit in `~/.claude/settings.json`
**before** the data ages out:

```json
{ "cleanupPeriodDays": 3650 }
```

As a safety net, `collect.py` also **accumulates** (`accumulate.py`): each run merges with
the previously published `stats.json` — union of days, keeping the higher-token row per
day — so a day once captured is never lost even if its raw transcript is later pruned.
Trade-off: accumulated totals can **exceed** what the Claude app shows, because the app
itself only ever sees the un-pruned window.

## Fidelity: reimplement **and** verify

The Claude engine (`engine.py`) is a clean-room reimplementation of the app's `/stats`
computation — *not* a copy of Anthropic's code. It has been validated **byte-for-byte**
against the app's actual extracted code: every displayed metric matches exactly.

(`engine.py` itself stays 1:1 with the app; the *published* `stats.json` then accumulates
across runs — see the retention note above — so the dashboard's all-time totals can exceed
what the app currently displays.)

Rather than depend on the app's minified internals at runtime (the function names change
every release), the installed app is used as a **verification oracle**:

```bash
python3 tools/verify_against_app.py   # extracts the installed app's real EKr, diffs ours
```

If a Claude update ever changes the algorithm, this fails loudly so the engine can be
updated — the graph never silently drifts. (Requires macOS + Claude.app + Node; the
extracted oracle is temp-only and never committed.)

Notable details reproduced: headline **tokens exclude cache** (input+output only); a
session is dated by its first message's local date; subagent transcripts contribute
tokens but not sessions/messages (kept in a separate bucket so the dashboard can toggle
them); line-splitting matches Node's `readline` including **U+2028/U+2029** (which the
app silently drops).

## Usage

```bash
python3 collect.py                 # -> data/stats.json (Claude + Codex), accumulating
python3 collect.py --fresh         # full recompute, ignore the prior snapshot
python3 render_hero.py             # -> assets/overview-{light,dark}.svg
./tools/publish.sh                 # collect -> render -> commit + push (DRY_RUN=1 to preview)
```

A launchd agent (`tools/com.turbokach.aitokenburn.plist`) runs `publish.sh` daily.

## Roadmap

- [x] Validated Claude engine + Codex aggregator → `stats.json`
- [x] Verify-against-installed-app self-test
- [x] Cross-run accumulation so the graph survives log pruning (`accumulate.py`)
- [x] Static hero SVG (combined Claude + Codex: tiles + burn heatmap + split bar), light/dark
- [x] GitHub Pages dashboard: tabs (Claude ⇄ Codex) + All/30d/7d + Overview/Models + subagent toggle
- [x] launchd job: daily `collect.py` → `render_hero.py` → commit + push
- [Live dashboard →](https://turbokach.github.io/ai-token-burn/)
