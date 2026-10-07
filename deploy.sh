#!/bin/bash
# Despliegue del API en el servidor de producción (se ejecuta EN el servidor, en este directorio).
#
#   ./deploy.sh                    despliega origin/vjorge
#   ./deploy.sh --dry-run          enseña qué entraría y qué haría, sin tocar nada
#   ./deploy.sh --with-migrations  permite desplegar commits que incluyen migraciones (por defecto se aborta)
#
# Qué hace, en este orden (y para si algo falla):
#   1. Comprueba que el árbol está limpio y que el avance es un fast-forward.
#   2. Copia de seguridad: pg_dump de la base de datos + archivo del código actual (en ~/backups).
#   3. git merge --ff-only  +  manage.py check  (si el check falla, vuelve atrás y no reinicia nada).
#   4. Reinicia solo lo necesario con supervisord: citsci-api siempre; citsci-worker y citsci-scheduler solo si
#      cambian tareas (stats/, tasks.py) o la configuración.
#   5. Comprobación: citsci-api en RUNNING y una ruta pública en 200. Si falla, vuelve atrás y reinicia.
#   6. Deja constancia: etiqueta de git prod-AAAA-MM-DD-N (se intenta subir a GitHub) y una línea en ~/deploys.log.
#
# Marcha atrás manual:  git reset --hard <commit-anterior> && sudo supervisorctl restart citsci-api
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
    *) echo "Opción desconocida: $arg (usa --help)"; exit 2 ;;
  esac
done

say() { echo "▸ $*"; }
die() { echo "✗ $*" >&2; exit 1; }

# 1. Estado de partida
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || die "El servidor no está en la rama $BRANCH."
[ -z "$(git status --porcelain)" ] || { git status --short; die "Hay cambios sin commitear en el servidor. Commitéalos y súbelos antes de desplegar."; }
git fetch -q origin "$BRANCH"
PREV="$(git rev-parse HEAD)"
NEW="$(git rev-parse "origin/$BRANCH")"
[ "$PREV" != "$NEW" ] || { say "Ya está desplegado $(git rev-parse --short HEAD). No hay nada que hacer."; exit 0; }
git merge-base --is-ancestor "$PREV" "$NEW" || die "origin/$BRANCH no es un avance de lo que hay en el servidor (no sería fast-forward)."

CHANGED="$(git diff --name-only "$PREV" "$NEW")"
say "Entra: $(git rev-parse --short "$PREV") → $(git rev-parse --short "$NEW")  ($(echo "$CHANGED" | wc -l | tr -d ' ') ficheros)"
git log --oneline "$PREV..$NEW" | sed 's/^/    /'

# Qué hay que reiniciar
RESTART="citsci-api"
if echo "$CHANGED" | grep -qE '(^stats/|tasks\.py$|^citsci-api/settings\.py$|^requirements\.txt$)'; then
  RESTART="citsci-api citsci-worker citsci-scheduler"
fi
MIGRATIONS="$(echo "$CHANGED" | grep -E '/migrations/.*\.py$' || true)"
if [ -n "$MIGRATIONS" ] && [ "$WITH_MIGRATIONS" -eq 0 ]; then
  echo "$MIGRATIONS" | sed 's/^/    migración: /'
  die "El despliegue incluye migraciones. Revísalas y repite con --with-migrations."
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say "Dry run: haría copia de seguridad, merge --ff-only, manage.py check y reiniciar: $RESTART"
  [ -n "$MIGRATIONS" ] && say "…y ejecutaría migrate (--with-migrations)."
  exit 0
fi

# 2. Copia de seguridad
mkdir -p "$BACKUPS"
STAMP="$(date +%Y%m%d_%H%M)"
DUMP="$BACKUPS/${DB_NAME}_pre-deploy_${STAMP}.dump"
say "Copia de la base de datos → $DUMP"
sudo -n -u postgres pg_dump -Fc "$DB_NAME" > "$DUMP"
chmod 600 "$DUMP"
git archive --format=tar.gz -o "$BACKUPS/citsci-api-code_$(git rev-parse --short "$PREV").tar.gz" "$PREV"

rollback() {
  echo "↩ Volviendo a $(git rev-parse --short "$PREV")..." >&2
  git reset -q --hard "$PREV"
  sudo -n supervisorctl restart $RESTART >&2 || true
}

# 3. Merge + check
git merge -q --ff-only "origin/$BRANCH"
if ! venv/bin/python manage.py check >/dev/null 2>"$BACKUPS/.check.err"; then
  cat "$BACKUPS/.check.err" >&2
  git reset -q --hard "$PREV"
  die "manage.py check falla: vuelto a $(git rev-parse --short "$PREV"), no se ha reiniciado nada."
fi
if [ -n "$MIGRATIONS" ]; then
  say "Ejecutando migraciones"
  venv/bin/python manage.py migrate --noinput
fi

# 4. Reinicio
say "Reiniciando: $RESTART"
sudo -n supervisorctl restart $RESTART
sleep 6

# 5. Comprobación
for program in $RESTART; do
  sudo -n supervisorctl status "$program" | grep -q RUNNING || { rollback; die "$program no está RUNNING."; }
done
CODE="$(curl -s -o /dev/null -w '%{http_code}' "$SMOKE_URL" || true)"
[ "$CODE" = "200" ] || { rollback; die "La comprobación $SMOKE_URL devolvió HTTP $CODE."; }
say "Comprobación correcta (HTTP 200)"

# 6. Constancia
TODAY="$(date -u +%Y-%m-%d)"
N=$(( $(git tag -l "prod-$TODAY-*" | wc -l) + 1 ))
TAG="prod-$TODAY-$N"
git tag -a "$TAG" -m "Despliegue de producción $(git rev-parse --short HEAD)" "$NEW" || true
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) api $(git rev-parse --short "$NEW") tag=$TAG restart='$RESTART' by=$(git config user.name || whoami)" >> "$LOG"
if git push -q origin "$TAG" 2>/dev/null; then say "Etiqueta $TAG subida a GitHub"; else echo "⚠ No se pudo subir la etiqueta $TAG (haz: git push origin $TAG)"; fi
say "Hecho: $(git rev-parse --short "$NEW") desplegado como $TAG. Vigila: tail -f /var/log/supervisor/citsci-api.err.log"
