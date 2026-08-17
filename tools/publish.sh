#!/usr/bin/env bash
# Daily token-burn refresh: recompute stats from local logs, re-render the hero
# SVGs, and commit locally if anything changed. Run by the launchd agent
# (com.pavelnovikau.aitokenburn) once a day; safe to run by hand too.
#
# Publishing is OPT-IN. By default the daily job only keeps the local snapshot
# growing — accumulate.py needs a run inside every retention window or pruned days
# are lost forever — and nothing leaves the machine until PUSH=1 is passed.
#
#   ./tools/publish.sh            # refresh + commit locally, no push
#   PUSH=1 ./tools/publish.sh     # ... and publish to origin/master
#   DRY_RUN=1 ./tools/publish.sh  # refresh + show what WOULD be committed, no commit
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Combine all three local Claude environments — pn-main + smartcat + claude-pn — into one
# burn graph (comma-separated; a missing dir is skipped harmlessly). writes data/stats.json
# + docs/data/stats.json
python3 collect.py --claude-dir "$HOME/.claude,$HOME/.claude-smartcat,$HOME/.claude-pn"
python3 render_hero.py     # writes assets/overview-{light,dark}.svg
python3 themes.py          # writes docs/themes.css from the active theme

# Only the generated artifacts — never working notes or stray files.
FILES=(data/stats.json docs/data/stats.json assets/overview-light.svg assets/overview-dark.svg docs/themes.css)

# Compare against HEAD (not just the working tree) so a prior run that staged
# but didn't commit is still detected.
if git diff --quiet HEAD -- "${FILES[@]}"; then
  echo "publish: no changes — nothing to commit"
  exit 0
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "publish: [dry-run] would commit:"
  git status --porcelain -- "${FILES[@]}"
  exit 0
fi

# Pathspec commit: commits ONLY these files' current contents, ignoring whatever
# else may be staged in the index — so the daily job never ships unrelated work.
git commit -m "chore: daily token-burn refresh ($(date +%Y-%m-%d))" -- "${FILES[@]}"

if [[ "${PUSH:-0}" != "1" ]]; then
  echo "publish: committed locally — NOT pushed (PUSH=1 to publish)"
  exit 0
fi
git push origin master
echo "publish: pushed daily refresh"
