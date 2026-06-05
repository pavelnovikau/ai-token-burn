# Token burn-rate graph — plan

Goal: add a Claude Code + Codex token burn-rate visualization to the GitHub profile
(`TurboKach/TurboKach`), replicating the Claude desktop app's "What's up next" /stats
panel, with interactive tabs (Claude ⇄ Codex), All/30d/7d windows, Overview/Models
views, and a subagent show/hide toggle.

## Architecture (locked)

```
~/.claude/projects/**/*.jsonl ─┐
                               ├─▶ collect.py (engine.py)  →  data/stats.json
~/.codex/sessions/**/*.jsonl ──┘
        [launchd, daily on the Mac]  ── git push ──▶ TurboKach/ai-token-burn
                                                      │
        [GitHub Action on push] render hero SVG (light+dark) from stats.json, commit
                                                      │
        ┌─────────────────────────────────────────────┴──────────────┐
        ▼                                                             ▼
  TurboKach/TurboKach README                      GitHub Pages → turbokach.github.io
  static hero Overview + "Open dashboard →"        SPA: tabs + windows + subagent toggle
```

Why local-origin: subscription usage isn't exposed by provider usage APIs; only local
logs have the real numbers. Why a Pages SPA: README can't run JS, so true tabs/windows
live on Pages; README embeds a static hero (light/dark via `<picture>`) linking to it.

## Engine fidelity (DONE)

- `engine.compute_claude()` — clean reimplementation of the app's `EKr`, validated 1:1
  against the installed app's real code (`tools/verify_against_app.py`). All displayed
  metrics match exactly. Only `toolCallCount` differs — not displayed, and
  nondeterministic in the app itself (FS-enumeration-order dependent).
- `engine.compute_codex()` — Codex aggregator. Uses each session's FINAL
  `total_token_usage` (Codex resends context each turn, so per-event `last_token_usage`
  is not a clean delta). in = input − cached, out = output + reasoning, cache tracked
  separately (mirrors Claude's cache-excluded headline).
- Subagent contributions emitted as a separate bucket → dashboard toggle.

## Metric definitions (must stay matched)

Sessions = non-subagent transcripts w/ ≥1 non-sidechain user/assistant msg, dated by
first message local date. Messages = Σ those. Active days = distinct local dates. Peak
hour = most common session-start hour. Streaks = consecutive active days (current up to
today / longest run). Total tokens = Σ(input+output), **cache excluded**. Favorite
model = max by in+out. Heatmap cell = per-day Σ(input+output).

## Remaining steps

1. **Hero SVG renderer** (`render_hero.py`): stats.json → `assets/overview-{light,dark}.svg`
   — 8 stat tiles + 7×53 token calendar heatmap + Gatsby fun-fact (`totalTokens/62000`).
   Wire into the profile README via `<picture>`.
2. **Pages SPA** (`docs/`): `index.html` + `app.js` + `styles.css`. Tabs Claude/Codex,
   window toggle All/30d/7d (client-side filter over `daily[]`), Overview/Models views,
   subagent on/off (uses the `subagents` bucket). Enable Pages → serve `/docs` on `master`.
   Copy/symlink `stats.json` under `docs/data/` so the SPA can fetch it.
3. **GitHub Action** (`.github/workflows/render.yml`): on push touching `data/stats.json`,
   run the renderer, commit updated SVGs.
4. **launchd** (`com.turbokach.aitokenburn.plist`): daily → `collect.py` → commit + push.
   Runs when the Mac is on (inherent tradeoff of local-origin subscription data).
5. **Profile README** in `TurboKach/TurboKach`: embed hero + "Open dashboard →".

## Decisions log

- Repo: `TurboKach/ai-token-burn`, public (needed for Pages + image embedding).
- Engine strategy: reimplement + verify (not runtime-extract; minified names are
  unstable, and shipping/executing proprietary code in a public repo is a no-go).
- Layout: interactive tabs requested → Pages SPA (READMEs can't run JS).
- Views: everything (Overview + Models + All/30d/7d) + subagent toggle.
