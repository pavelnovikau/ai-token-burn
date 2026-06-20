#!/usr/bin/env bash
# Daily token-burn refresh: recompute stats from local logs, re-render the hero
# SVGs, and commit + push if anything changed. Run by the launchd agent
# (com.turbokach.aitokenburn) once a day; safe to run by hand too.
#
#   ./tools/publish.sh            # refresh, commit, push
#   DRY_RUN=1 ./tools/publish.sh  # refresh + show what WOULD be committed, no push
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
  echo "publish: [dry-run] would commit + push:"
  git status --porcelain -- "${FILES[@]}"
  exit 0
fi

# Pathspec commit: commits ONLY these files' current contents, ignoring whatever
# else may be staged in the index — so the daily job never ships unrelated work.
git commit -m "chore: daily token-burn refresh ($(date +%Y-%m-%d))" -- "${FILES[@]}"
git push origin master
echo "publish: pushed daily refresh"
