#!/bin/bash
# API deployment on the production server (run ON the server, from this directory).
#
#   ./deploy.sh                    deploys origin/vjorge
#   ./deploy.sh --dry-run          shows what would come in and what it would do, without touching anything
#   ./deploy.sh --with-migrations  allows deploying commits that include migrations (aborts by default)
#
# What it does, in this order (and stops if anything fails):
#   1. Checks that the working tree is clean and that the update is a fast-forward.
#   2. Backup: pg_dump of the database + an archive of the current code (in ~/backups).
#   3. git merge --ff-only  +  manage.py check  (if the check fails it rolls back and restarts nothing).
#   4. Restarts only what is needed with supervisord: citsci-api always; citsci-worker and citsci-scheduler only if
#      tasks (stats/, tasks.py) or the configuration change.
#   5. Verification: citsci-api is RUNNING and a public route returns 200. If not, it rolls back and restarts.
#   6. Records the deploy: git tag prod-YYYY-MM-DD-N (it tries to push it to GitHub) and a line in ~/deploys.log.
#
# Manual rollback:  git reset --hard <previous-commit> && sudo supervisorctl restart citsci-api
set -euo pipefail
cd "$(dirname "$0")"

BRANCH="vjorge"
DB_NAME="${DB_NAME:-geonity_production}"
BACKUPS="$HOME/backups"
LOG="$HOME/deploys.log"
SMOKE_URL="${SMOKE_URL:-https://geonity.ibercivis.es/api/organization/type/}"

DRY_RUN=0
WITH_MIGRATIONS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --with-migrations) WITH_MIGRATIONS=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (use --help)"; exit 2 ;;
  esac
done

say() { echo "▸ $*"; }
die() { echo "✗ $*" >&2; exit 1; }

# 1. Starting state
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || die "The server is not on branch $BRANCH."
[ -z "$(git status --porcelain)" ] || { git status --short; die "There are uncommitted changes on the server. Commit and push them before deploying."; }
git fetch -q --tags origin "$BRANCH"
PREV="$(git rev-parse HEAD)"
NEW="$(git rev-parse "origin/$BRANCH")"
[ "$PREV" != "$NEW" ] || { say "Already deployed: $(git rev-parse --short HEAD). Nothing to do."; exit 0; }
git merge-base --is-ancestor "$PREV" "$NEW" || die "origin/$BRANCH is not a fast-forward of what is on the server."

CHANGED="$(git diff --name-only "$PREV" "$NEW")"
say "Incoming: $(git rev-parse --short "$PREV") → $(git rev-parse --short "$NEW")  ($(echo "$CHANGED" | wc -l | tr -d ' ') files)"
git log --oneline "$PREV..$NEW" | sed 's/^/    /'

# What needs restarting
RESTART="citsci-api"
if echo "$CHANGED" | grep -qE '(^stats/|tasks\.py$|^citsci-api/settings\.py$|^requirements\.txt$)'; then
  RESTART="citsci-api citsci-worker citsci-scheduler"
fi
MIGRATIONS="$(echo "$CHANGED" | grep -E '/migrations/.*\.py$' || true)"
if [ -n "$MIGRATIONS" ] && [ "$WITH_MIGRATIONS" -eq 0 ]; then
  echo "$MIGRATIONS" | sed 's/^/    migration: /'
  die "This deploy includes migrations. Review them and run again with --with-migrations."
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say "Dry run: would back up, merge --ff-only, run manage.py check and restart: $RESTART"
  [ -n "$MIGRATIONS" ] && say "…and would run migrate (--with-migrations)."
  exit 0
fi

# 2. Backup
mkdir -p "$BACKUPS"
STAMP="$(date +%Y%m%d_%H%M)"
DUMP="$BACKUPS/${DB_NAME}_pre-deploy_${STAMP}.dump"
say "Database backup → $DUMP"
sudo -n -u postgres pg_dump -Fc "$DB_NAME" > "$DUMP"
chmod 600 "$DUMP"
git archive --format=tar.gz -o "$BACKUPS/citsci-api-code_$(git rev-parse --short "$PREV").tar.gz" "$PREV"

rollback() {
  echo "↩ Rolling back to $(git rev-parse --short "$PREV")..." >&2
  git reset -q --hard "$PREV"
  sudo -n supervisorctl restart $RESTART >&2 || true
}

# 3. Merge + check
git merge -q --ff-only "origin/$BRANCH"
if ! venv/bin/python manage.py check >/dev/null 2>"$BACKUPS/.check.err"; then
  cat "$BACKUPS/.check.err" >&2
  git reset -q --hard "$PREV"
  die "manage.py check failed: rolled back to $(git rev-parse --short "$PREV"), nothing was restarted."
fi
if [ -n "$MIGRATIONS" ]; then
  say "Running migrations"
  venv/bin/python manage.py migrate --noinput
fi

# 4. Restart
say "Restarting: $RESTART"
sudo -n supervisorctl restart $RESTART
sleep 6

# 5. Verification
for program in $RESTART; do
  sudo -n supervisorctl status "$program" | grep -q RUNNING || { rollback; die "$program is not RUNNING."; }
done
CODE="$(curl -s -o /dev/null -w '%{http_code}' "$SMOKE_URL" || true)"
[ "$CODE" = "200" ] || { rollback; die "The check against $SMOKE_URL returned HTTP $CODE."; }
say "Check passed (HTTP 200)"

# 6. Record
TODAY="$(date -u +%Y-%m-%d)"
N=$(( $(git tag -l "prod-$TODAY-*" | wc -l) + 1 ))
TAG="prod-$TODAY-$N"
git tag -a "$TAG" -m "Production deploy $(git rev-parse --short HEAD)" "$NEW" || true
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) api $(git rev-parse --short "$NEW") tag=$TAG restart='$RESTART' by=$(git config user.name || whoami)" >> "$LOG"
if git push -q origin "$TAG" 2>/dev/null; then say "Tag $TAG pushed to GitHub"; else echo "⚠ Could not push the tag $TAG (run: git push origin $TAG)"; fi
say "Done: $(git rev-parse --short "$NEW") deployed as $TAG. Watch: tail -f /var/log/supervisor/citsci-api.err.log"
