# Estadísticas y notificaciones — Plan API (Django)

Objetivo: tres cosas que comparten el mismo cálculo y por eso van juntas en el plan, pero que son
piezas independientes:

1. **Métricas de plataforma** para staff: cuántos proyectos hay, cuántos están vivos, acumulados y
   evolución temporal.
2. **Métricas por creador**: cada creador/administrador ve las de sus proyectos, con el mismo código.
3. **Notificaciones por email**: por evento (proyecto publicado, organización nueva) y un resumen
   periódico (mensual/quincenal) al staff.

La regla que estructura todo: **el cálculo vive en funciones puras** (`stats/metrics.py`) que reciben
un queryset y devuelven un `dict`. Las tres vistas y el email de resumen las llaman con querysets
distintos. Un solo sitio donde arreglar los bugs de conteo.

---

## Bitácora — dónde vamos

| Fecha | Fase | Estado |
|---|---|---|
| 2026-09-10 | Fase 0 — decisiones | **Cerrada.** Vivo = 30 días; email al crear y al publicar; `draft` reversible. Quedan 3 decisiones abiertas (ver el final). |
| 2026-09-10 | Fase 1 — modelo y migraciones | **Desplegada en producción.** |
| 2026-09-10 | Fase 2 — `metrics.py` + `/api/stats/platform/` | **Desplegada en producción.** |
| 2026-09-10 | Fase 3 — stats por creador y por proyecto | **Desplegada en producción.** |
| 2026-09-10 | Fase 4 — avisos por evento | **Desplegada y probada con un envío real.** |
| 2026-09-10 | Fase 5 — scheduler + resumen mensual | **Desplegada.** Primer envío: 1-oct-2026, 08:00 Madrid. |
| 2026-09-10 | Extra — informe mensual por proyecto | **Desplegado.** Primer envío: 1-oct-2026, 09:00 Madrid. |
| 2026-09-10 | Fase 7 — tests | **120 tests**, escritos en cada fase. |
| — | Fase 6 — futuro | Sin empezar, no bloquea nada. |

**Fase 1, detalle del despliegue (2026-09-10):**
- Commits `56cfce9` (código) y `aaf12c4` (este plan), en `vjorge`.
- Migraciones `project/0042_add_published_at_and_status_log` y `stats/0001_initial` aplicadas a
  `geonity_production`.
- Backfill real: 38 filas `created` (exactas, `estimated=False`), 7 `published`
  (`estimated=True`), `published_at` relleno en los 7 proyectos publicados y en ninguno de los 31
  borradores.
- 38 tests OK. Smoke test tras reiniciar `citsci-api` y `citsci-worker`: mismos códigos que el
  baseline, 0 errores en `django_db_logger`.
- Backups previos en `/home/ubuntu/backups/`: `geonity_production_pre-0042_20260910_1258.dump`
  (verificado: 38 proyectos, 1.490 observaciones, 783 usuarios) y `citsci-api-code_20260910_1240.tar.gz`.
- **Todavía no hay ningún comportamiento nuevo**: nadie escribe en `ProjectStatusLog` ni en
  `NotificationLog`. Son tablas vacías esperando a las fases 2-4 (salvo el backfill).

**Fase 2, detalle del despliegue (2026-09-10):**
- Commit `b65af12`. Sin migraciones: no toca modelos.
- `GET /api/stats/platform/` verificado en producción: 401 sin token, 200 con token `is_staff`,
  400 con parámetros inválidos. Caché efectiva: 377 ms la primera llamada, 39 ms la segunda.
- Comprobado en el payload real que no aparece ningún `anonymous_id` ni ningún email.
- 54 tests OK. 16 queries contra los datos reales, sin N+1.
- Números reales del primer día: 38 proyectos (6 publicados, 31 borradores), 1.492 observaciones
  (378 en 30 días, 3 anónimas, **430 con `platform` a NULL**, previas al campo), 783 usuarios,
  12 organizaciones, 42 membresías, **29 invitaciones pendientes que nadie caduca**.
- Dato que valida una decisión: `active_30d` = 12 proyectos, de los que solo 5 están publicados.
  **7 borradores están recogiendo datos activamente** por QR. Contarlos solo si están publicados
  habría dado una foto falsa.

**Fase 3, detalle del despliegue (2026-09-10):**
- Commit `6c0f329`. Sin migraciones.
- Endpoints: `GET /api/stats/me/` y `GET /api/project/<pk>/stats/`.
- Verificado en producción con un proyecto temporal en borrador (invisible en los listados) que se
  borró después, dejando la base exactamente como estaba (38 proyectos, 1.492 observaciones,
  783 usuarios, 45 filas de log):

  | Prueba | Resultado |
  |---|---|
  | `/project/<pk>/stats/` sin token | 401 |
  | idem, usuario ajeno | 403 |
  | idem, creador | 200 |
  | creador pidiendo un proyecto ajeno | 403 |
  | `/stats/me/` sin token | 401 |
  | `/stats/me/`, usuario sin proyectos | 200, total 0 |
  | `top` en cualquiera de los dos | ausente |
  | `anonymous_id` en la respuesta | ausente |

- 67 tests OK. 0 errores 5xx en el día.

**Fase 4, detalle del despliegue (2026-09-10):**
- Eventos: proyecto creado / publicado / republicado / despublicado / finalizado / reabierto,
  organización nueva, e hitos de 1, 10, 100 y 1000 observaciones.
- Se reinició también `citsci-worker`: la cola necesita el módulo `stats.tasks` nuevo.
- Verificado en producción con la config real (SES, `geonity@ibercivis.es`, los 4 destinatarios)
  pero con el backend en memoria, así que **no se envió ningún correo**. El render sale bien y el
  worker está vivo escuchando `citisciapi`.
- 79 tests OK.
- **Envío real de prueba: hecho** (2026-09-10 13:35). Se apuntó `PLATFORM_NOTIFICATION_EMAILS`
  temporalmente a `frasanz@ibercivis.es`, se encoló un aviso, salió por SES con estado `sent` y sin
  error, y se restauró la lista de cuatro (verificado que el resto del `local.env` quedó idéntico
  al backup). La fila de prueba se borró: `notification_log` vuelve a 0.
- **Bug propio detectado y corregido en el acto:** `manage.py test` estaba encolando trabajos
  **reales en la cola de producción**. Los tests usan su propia base de datos, pero `django_rq` no
  se sustituye solo, y el `record_observation_milestone` que añade esta fase encola sin condiciones.
  Aparecieron 8 jobs `project-milestone` de proyectos que solo existen en la BD de test. Fallaron
  porque el worker aún no tenía `stats.tasks`, pero con la fase ya desplegada la siguiente
  ejecución de la suite habría **enviado correos de verdad a los cuatro destinatarios**. Ahora la
  cola apunta a la DB 15 de Redis cuando `'test' in sys.argv`, con un test que lo vigila. Los 8
  jobs basura se borraron del registro de fallidos.
- Salió al escribir los tests: **el serializer exige más de 10 observaciones para publicar**, así
  que publicar nunca ocurre sobre un proyecto vacío.

**Fase 5, detalle del despliegue (2026-09-10):**
- `rq-scheduler==0.13.1` clavado en `requirements.txt`. **La 0.14 exige `rq>=2`**, que subiría `rq`
  de 1.16.2 a 2.12 y `redis` de 5.0.1 a 8.1 teniendo `django-rq 2.10.2`, de la serie de rq 1.x.
  Verificado tras instalar que `rq`, `redis` y `django-rq` siguen exactamente igual. Copia del
  `pip freeze` previo en `/home/ubuntu/backups/`.
- Program nuevo `citsci-scheduler` en `/etc/supervisor/conf.d/`, RUNNING junto a `citsci-api` y
  `citsci-worker`.
- Registrado en la cola real: `geonity-digest-fortnightly`, `0 8 1,15 * *` →
  `stats.tasks.send_digest['fortnightly']`. **Próxima ejecución: 2026-09-15 06:00 UTC = 08:00 CEST
  en Madrid.**
- Comprobado que reiniciar el scheduler **no duplica** el trabajo periódico.
- `manage.py send_stats_digest --dry-run` verificado con datos reales.
- 94 tests OK.

**Informe por proyecto (2026-09-10), añadido después del plan original:**
- `Project.email_monthly_stats` (migración `project/0043`), activado por defecto y expuesto en el
  serializer. Al revés que `email_on_observation`: aquí el defecto no genera ruido porque el
  informe solo sale si hubo actividad.
- Dos correos según el caso: **informe** si hubo observaciones, **aviso de inactividad** si el
  proyecto está publicado y parado. Un borrador parado no recibe nada (24 borradores sin actividad
  frente a 1 publicado: avisarles a todos sería ruido).
- El aviso lleva `Reply-To: info@ibercivis.es` y pie propio; `base.html` gana un bloque
  `footer_note` que por defecto no cambia nada. Tope de **3 avisos seguidos**.
- Contribuidores **nuevos vs. recurrentes**, que es el dato que el resumen global no da.
- Programado el día 1 a las 09:00 locales, una hora después del de plataforma.
- **El día 1 saldrían 85 correos** a 13 proyectos. Ojo con dos: `Salud en el Partido de Escobar`
  tiene 37 administradores, y `Test-backend` (id 169) parece un proyecto de pruebas que recibiría
  informe. Se arregla con el flag o marcándolo como terminado.
- Probado enviando el informe de Life-Nitrazens **solo a frasanz@ibercivis.es**, no a sus 11
  destinatarios reales: nueve son externos (`@ubu.es`, `@cita-aragon.es`, `@carsa.es`) y no les ha
  avisado nadie de esta funcionalidad.

## Hallazgos ajenos a este trabajo (anotados, no tocados)
- **`POST /api/project/invitations/<id>/accept/` devuelve 500 de forma recurrente.** 45 de los 54
  errores 500 del log de producción entre el 14-jul y el 8-sep-2026 son de ese endpoint, y son los
  más recientes. Alguien que acepta una invitación a un proyecto se está comiendo un error. Merece
  su propia sesión.
- 430 observaciones (29%) tienen `platform` a NULL. No se esconden: salen como `unknown`.
- 29 invitaciones de proyecto llevan en `pending` sin que nada las marque como `expired`.
- **El handler `mail_admins` de `LOGGING` tiene el backend clavado a SMTP**
  (`'email_backend': 'django.core.mail.backends.smtp.EmailBackend'`), así que **se salta el backend
  en memoria que Django activa durante los tests** y manda correos reales a `ADMINS` por el postfix
  local en cada error de una prueba. Comentado con el equipo el 2026-09-10 y **decidido dejarlo
  así**: los errores de las pruebas también interesan.
- **13 trabajos fallidos antiguos en la cola de rq** (14-mar a 8-sep-2026), todos de `markers`:
  11 de `send_post_observation_email` y 2 de `send_observation_email`. Los errores son de tres
  tipos: `MessageRejected` de SES, `ImportError: cannot import name 'FullResultSet' from
  django.core.exceptions` (incompatibilidad de versión, jobs encolados con un Django anterior) y un
  `TemplateSyntaxError: 'get_current_language' requires 'as variable'`. Se dejaron donde estaban:
  son correos que alguien esperaba y no llegaron.

## Cómo se trabaja en esto (importante, el servidor es producción)

**Dónde se escribe el código:** en el clon `/home/ubuntu/citsci-api-dev`, rama `stats`. Nunca
directamente en `/home/ubuntu/citsci-api`, que es el checkout que sirve producción bajo supervisord
con `autorestart=true`: un crash mientras editamos ahí levantaría código a medio escribir.

**El clon aísla el código, NO los datos.** `local.env` apunta a `geonity_production` también desde el
clon: cualquier `migrate` o `shell` que escriba toca producción. Los tests sí van a otra base.

```bash
# tests (el usuario citsci no puede crear bases, de ahí --keepdb)
cd /home/ubuntu/citsci-api-dev
/home/ubuntu/citsci-api/venv/bin/python manage.py test --keepdb

# apuntar un comando a la base de test en vez de a producción
DB_NAME=test_geonity_production /home/ubuntu/citsci-api/venv/bin/python manage.py migrate project 0041

# desplegar a producción
cd /home/ubuntu/citsci-api
git fetch /home/ubuntu/citsci-api-dev stats && git merge --ff-only FETCH_HEAD
venv/bin/python manage.py migrate          # ojo: `migrate app1 app2` NO existe, o `migrate` o una app por llamada
sudo supervisorctl restart citsci-api citsci-worker

# smoke test (nginx sirve con server_name geonity.ibercivis.es; desde la máquina hay que resolver a mano)
curl -s -o /dev/null -w "%{http_code}\n" -k --resolve geonity.ibercivis.es:443:127.0.0.1 \
  https://geonity.ibercivis.es/api/project/
```

**Backup antes de cada migración:**
```bash
PGPASSFILE=<fichero 0600 con host:port:db:user:pass> pg_dump -h localhost -U citsci -Fc \
  -f /home/ubuntu/backups/geonity_production_$(date +%Y%m%d_%H%M).dump geonity_production
```

**Al revertir, el orden importa: primero el código, después la migración.** Al revés, el modelo tiene
`published_at`, la columna ya no existe y revienta toda escritura de proyecto.

**Pendiente de infraestructura, no bloquea:** este servidor **no puede subir a GitHub** (no hay clave
privada en `~/.ssh`, `git@github.com` da `Permission denied (publickey)`). Hay commits sin subir desde
el 7-sep y el código de dos años no tiene copia fuera de esta máquina. Hace falta generar una clave y
darla de alta como deploy key con escritura en `Ibercivis/citsci-api`.


---

## Estado actual (investigado 2026-09-10)

### Infraestructura (ya montada, no hay que tocarla)
- **Supervisord** (`supervisor.service`, enabled, arriba desde 2026-07-10) lanza todo:
  `citsci-api` (uwsgi) y `citsci-worker` (`manage.py rqworker citisciapi`), ambos con
  `autostart=true, autorestart=true` en `/etc/supervisor/conf.d/`. Un proceso nuevo son ocho líneas
  de `.conf` más `supervisorctl reread && supervisorctl update`.
- Cola **django-rq** `citisciapi` (`settings.py:288`), Redis DB 0. Patrón de encolado con try/except
  para que un Redis caído no rompa el request: `markers/api/views.py:167` y `:932`.
- **Caché Redis** DB 1 (`settings.py:280`), `TIMEOUT` global 24 h → hay que pasar `timeout` explícito.
- **Email por SES** (`django_ses.SESBackend`, `settings.py:243`), `DEFAULT_FROM_EMAIL` por env,
  `EMAIL_SUBJECT_PREFIX = '[Geonity]'`. Plantillas en `templates/email/`, base en `base.html`.
- **Sin cron**: crontab de usuario vacío, nada en `/etc/cron.d` salvo paquetes del sistema.
- Servidor y Django en **UTC** (`TIME_ZONE = "UTC"`, `USE_TZ = True`).

### Datos actuales (2026-09-10)
```
proyectos     38   (draft 31, ended 1, privados 4)
observaciones 1490 (anónimas 3)
usuarios      783
organizaciones 12
```
Volumen ridículo: agregados ORM en caliente + caché corta. **Nada de tablas de agregación,
snapshots diarios ni vistas materializadas.** Si algún día esto crece un orden de magnitud, el sitio
donde meter la precomputación es `metrics.py`, sin tocar las vistas.

### Lo que encaja
- `Project.last_observation` (`project/models.py:60`) ya lo mantiene el signal
  `update_project_last_observation` (`markers/signals.py:16`). Es la base de "proyecto activo".
- `Project.draft`, `ended`, `is_private`, `anonymous_contribution`, `public_map`: los flags para
  clasificar ya existen.
- `Observation.platform` (`mobile`/`web`, nullable), `anonymous_id`, `created_at`, `timestamp`.
- Precedente de log de emails con estado: `ObservationEmailLog` (`markers/models.py:139`), con
  `status pending/sent/failed` y `error`. Es la plantilla para el log de notificaciones.
- Precedente de throttle declarado vista a vista: `markers/api/throttles.py` + los `scope` en
  `settings.py:212`.

### Lo que bloquea o hay que vigilar
- **No hay `published_at`.** Solo `created_at` y `updated_at` (`auto_now`, inútil para histórico).
  Hoy no se puede responder "cuántos proyectos se publicaron en marzo". Ver Fase 1.
- **"Proyecto vivo" no existe como concepto.** 31 de 38 proyectos son `draft`: un endpoint que
  responda "38 proyectos" miente. Hay que definir y devolver los tres números (Fase 0).
- **`Project.contributions`** (`project/models.py:100`) hace un `count()` por proyecto. Usarla en un
  bucle es N+1. En stats hay que anotar con `Count('fieldform__observations')` — `FieldForm` es
  `OneToOneField` (`field_forms/models.py:8`), así que el reverse es `fieldform`.
- `DEFAULT_PERMISSION_CLASSES` está **dos veces** en el dict `REST_FRAMEWORK`
  (`settings.py:192` `AllowAny` y `settings.py:201` `IsAuthenticated`). Gana la segunda, así que el
  default efectivo es `IsAuthenticated`. No es urgente, pero conviene borrar la primera en este PR
  para que nadie lea la equivocada.
- Auth por defecto es solo `TokenAuthentication` (sin sesión): el dashboard de admin tendrá que
  autenticarse con el token de un usuario `is_staff`. **Confirmar con el front antes de empezar.**
- `ProjectInvitation.expires_at` existe pero nadie marca las invitaciones como `expired`
  (`is_expired()` se calcula al vuelo). Candidato para el scheduler, ver Fase 6.

---

## Fase 0 — Decisiones (tomadas 2026-09-10)
- [x] **"Proyecto vivo" = actividad en 30 días.** `active_30d` = con observaciones en los últimos 30
      días. Se devuelven además `published` (`not draft and not ended`), `draft` y `ended` por
      separado; ningún campo se llama "vivo".
      - **Se calcula con `Observation.created_at`, no con `Project.last_observation`.** Motivo:
        `last_observation` se alimenta de `Observation.timestamp`, que **lo manda el cliente**
        (`markers/api/views.py:98`, `request.data.get("timestamp")`, sin validar contra futuro) y el
        signal solo lo sube si es mayor (`markers/signals.py:16`). Un móvil con el reloj mal puesto
        dejaría un proyecto "activo" para siempre. `created_at` es `auto_now_add`, servidor.
        `last_observation` se queda como está para lo que ya hace en el front; los dos números pueden
        no coincidir y es esperado.
      - `active_30d` se calcula sobre **todos** los proyectos, borradores incluidos: con la
        contribución anónima por QR, un borrador puede estar recogiendo datos activamente. Se
        devuelve también cruzado con `published`.
- [x] **Email al crear Y al publicar**, dejando explícita la transición creado → publicado.
      Se retira la objeción del ruido: el ritmo real de creación es de ~4-8 proyectos al mes
      (abr-2026: 8, may: 4, jul: 4, ago: 8), perfectamente asumible.
- [x] **Un proyecto publicado puede volver a borrador.** Esto condiciona el modelo, ver Fase 1.
- [x] Destinatarios del staff: setting nuevo `PLATFORM_NOTIFICATION_EMAILS` (lista por env), no
      `ADMINS` — eso lo usa Django para tracebacks y mezclarlo es pedir problemas.
- [ ] Confirmar con el front cómo se autentica el dashboard (token de usuario `is_staff`).

## Fase 1 — Modelo y migraciones ✅ (desplegada 2026-09-10)

**`draft` es reversible**, y eso rompe un `published_at` nullable a secas: no sabría si significa la
primera publicación o la última, si se pone a `null` al despublicar, el email se dispararía en cada
ida y vuelta y la serie "publicados por mes" quedaría ambigua. Se resuelve con un log de
transiciones, que además hace correcta la idempotencia de los emails.

- [x] `ProjectStatusLog` (app `project`), ~15 líneas y una migración; a 38 proyectos el coste es cero:
```python
class ProjectStatusLog(models.Model):
    project = FK(Project, related_name='status_log')
    event   = CharField(choices=['created','published','unpublished','ended','reopened'])
    at      = DateTimeField(auto_now_add=True, db_index=True)
    by      = FK(User, null=True, on_delete=SET_NULL)
```
- [x] `Project.published_at = DateTimeField(null=True, blank=True, db_index=True)` junto a
      `last_observation` (`project/models.py:60`) = **primera publicación, inmutable**. No se
      sobrescribe en publicaciones posteriores ni se pone a `null` al despublicar. La serie
      "proyectos publicados por mes" es por tanto **primeras publicaciones**, que es la métrica de
      crecimiento que interesa, y despublicar no reescribe el histórico.
- [x] El **estado actual sigue siendo `draft`/`ended`**, sin cambios. El log no es la fuente de
      verdad del estado, es el histórico — y es lo que permite responder "cuántos proyectos estaban
      publicados en marzo", imposible en cuanto alguien despublica.
- [x] Migración `project/0042_add_published_at_and_status_log` con `RunPython` de backfill:
      `published_at = created_at` y una fila `created` en el log para los proyectos con `draft=False`.
      **El commit debe decir que el histórico anterior a esta migración es una estimación**, no un
      dato real: `updated_at` es `auto_now` y no sirve para reconstruir nada.
- [x] App nueva `stats` en `INSTALLED_APPS`, con un único modelo:
      `NotificationLog(event, period_key, recipients, status, error, created_at, sent_at)` con
      `unique_together = ('event', 'period_key')`. Migración `stats/0001_initial`.
      El log vive aquí y no en una app `notifications` propia para no crear dos apps de golpe; si las
      notificaciones crecen (preferencias por usuario, más canales), se mueve entonces.

## Fase 2 — `stats/metrics.py` y endpoint de plataforma ✅ (desplegada 2026-09-10)
Estructura:
```
stats/
  metrics.py          # funciones puras, sin DRF: reciben queryset, devuelven dict
  api/views.py        # vistas finas
  api/urls.py
  tasks.py            # jobs de rq (Fase 5)
  management/commands/
  tests.py
```
- [x] `metrics.py`: `project_metrics(qs)`, `observation_metrics(qs)`, `user_metrics(qs)`,
      `timeseries(qs, field, granularity)`, `top_projects(qs, n)`, `top_creators(qs, n)`.
      Cada bloque en **una sola query** con `Count('id', filter=Q(...))`; nada de un `count()` por
      métrica. Los acumulados se suman en Python (con 1.500 filas no compensa una window function).
- [x] `GET /api/stats/platform/` — `permission_classes = [IsAdminUser]` (`is_staff`), explícito:
      el default global es `IsAuthenticated` y no basta.
      Params: `?from=&to=&granularity=month|week`. Payload:
```json
{
  "generated_at": "...",
  "period": {"from": "...", "to": "...", "granularity": "month"},
  "projects": {"total": 38, "published": 6, "draft": 31, "ended": 1, "private": 4,
               "with_observations": 12, "active_30d": 3, "abandoned": 2,
               "anonymous_enabled": 2, "public_map": 5},
  "observations": {"total": 1490, "last_30d": 87, "anonymous": 3,
                   "by_platform": {"mobile": 1200, "web": 287, "unknown": 3},
                   "with_images": 900, "with_audio": 12},
  "users": {"total": 783, "with_observations": 210, "new_30d": 14},
  "organizations": {"total": 12},
  "engagement": {"memberships": 0, "invitations_pending": 0, "likes": 0},
  "series": {"projects_published": [], "projects_cumulative": [],
             "observations": [], "observations_cumulative": [], "users": []},
  "top": {"projects_by_observations": [], "creators_by_observations": []},
  "last_digest_sent_at": "..."
}
```
- [x] Caché Redis con `timeout=600` explícito y clave `stats_platform_{from}_{to}_{granularity}`.
      `?refresh=1` la salta (solo staff, que es quien llega aquí).
- [x] Throttle propio: `StatsThrottle(scope='stats')` en `stats/api/throttles.py` y
      `'stats': '30/min'` en `DEFAULT_THROTTLE_RATES` (`settings.py:212`). Son las queries más caras
      de la API y `DEFAULT_THROTTLE_CLASSES` sigue vacío a propósito.
- [x] Borrar el `DEFAULT_PERMISSION_CLASSES` duplicado de `settings.py:192`.
- [x] `last_digest_sent_at` sale de `NotificationLog`: sirve de chivato para ver desde el dashboard
      que el resumen periódico sigue saliendo, sin entrar por ssh.

## Fase 3 — Estadísticas por creador y por proyecto ✅ (desplegada 2026-09-10)

**Tres niveles de visibilidad.** Importante: el nivel público **ya existe hoy**, no lo estrenamos
aquí. `ProjectListSerializer` (`project/api/serializers.py:440`) expone `contributions`,
`total_likes`, `last_observation` y `has_observations`, y `GET /api/project/` es
`IsAuthenticatedOrReadOnly`, o sea legible sin token. El número de observaciones de un proyecto no
es secreto y el endpoint de stats no debe fingir que lo es.

| Nivel | Quién | Qué |
|---|---|---|
| Público | cualquiera | total de observaciones, likes, última observación (ya público) |
| Proyecto | creador + `administrators` | series temporales, contribuidores únicos, anónimas vs registradas, split mobile/web, ritmo, abandono |
| Plataforma | `is_staff` | comparación entre proyectos: rankings, tops, agregados globales |

El nivel de plataforma es el realmente sensible: comparar proyectos ajenos entre sí es información
que hoy no tiene nadie salvo por el admin de Django. Los `top` de la Fase 2 **no** se filtran hacia
los niveles inferiores.

- [x] `GET /api/stats/me/` — `IsAuthenticated`. Nivel de proyecto sobre
      `Project.objects.filter(Q(creator=u) | Q(administrators=u)).distinct()`, con desglose por
      proyecto. Reutiliza `metrics.py` tal cual.
- [x] `GET /api/project/<pk>/stats/` — nivel de proyecto. Usar el helper que ya existe,
      `_is_project_admin(user, project)` (`markers/api/views.py:39`): devuelve `True` para creador y
      para `administrators`, que es exactamente el criterio que queremos. No escribir una tercera
      variante de esta comprobación.
- [x] **Miembros del proyecto** (`ProjectMembership`): **no** acceden al nivel de proyecto.
      Ya tienen el nivel público y sus propias observaciones vía `/observations/my/`. (Decidido en
      Fase 0 si se cambia de opinión.)
- [x] **Privacidad, no negociable:** `anonymous_id` no se expone nunca (regla ya establecida en el
      plan del QR: solo truncado a 8 caracteres en la descarga). Nada de listar emails de
      contribuidores. Respetar `fuzzy` y `private_data` si alguna métrica llega a tocar geometría.

## Fase 4 — Notificaciones por evento ✅ (desplegada 2026-09-10)
- [x] Task `stats/tasks.py: notify_platform_event(status_log_id, lang)`, encolada en `citisciapi`
      dentro de try/except, como `markers/api/views.py:167`.
- [x] Eventos de salida: **proyecto creado**, **proyecto publicado**, **proyecto despublicado**,
      **organización nueva**, e hitos del proyecto (primera observación, y al cruzar 10 / 100 / 1000).
- [x] `PLATFORM_NOTIFICATION_EMAILS` y `PLATFORM_NOTIFICATION_TIMEZONE` ya están en `settings.py` y
      en el `local.env` de producción y del clon (commiteado sin desplegar: todavía no los lee nadie).
      Si la lista viene vacía, el envío se registra como `failed` en `NotificationLog` con el motivo,
      en vez de reventar la tarea.
- [x] **Idempotencia: la fila de `ProjectStatusLog` es la clave.**
      `period_key = f'project-status-{log.id}'`. Un reintento de rq no duplica el correo, y una
      segunda publicación **sí** manda el suyo porque es otra fila. Sin el log habría que inventarse
      una clave por número de publicación, que es justo donde salen los bugs.
- [x] Escribir la fila del log **explícitamente** en el update de la vista/serializer cuando cambia
      `draft`, y encolar ahí. Explícito y testeable; se descarta el `post_save` comparando estado
      previo, que es más frágil y se dispara cuatro veces con los cuatro workers de uwsgi.
- [x] El asunto y el cuerpo **dejan clara la transición**: "Proyecto publicado: X — creado el 3 de
      marzo, publicado hoy (11 días)". Una segunda publicación se marca como **republicado**, no
      como estreno.
- [x] Registro de usuario nuevo: **no** por evento (783 usuarios, sería ruido). Va al resumen.
- [x] Plantilla `templates/email/platform_notification.html` extendiendo `base.html`.
- [x] Cada envío escribe en `NotificationLog` con su `status`/`error`, igual que
      `ObservationEmailLog` (`markers/models.py:139`).

## Fase 5 — Resumen periódico y scheduler ✅ (desplegada 2026-09-10)
Supervisord mantiene vivo, **no planifica**. Y `rqworker --with-scheduler` no vale: el scheduler
interno de RQ cubre `enqueue_at`/`enqueue_in`, no repeticiones tipo cron. Hace falta el paquete
`rq-scheduler` y su proceso.
- [x] Instalar `rq-scheduler` y **verificar compatibilidad** con `rq 1.16.2` / `django-rq 2.10.2`
      antes de nada. Añadir a `requirements.txt`.
- [x] Comando `manage.py run_scheduler`: **registra los jobs con id fijo y luego arranca el bucle.**
```python
scheduler.cron('0 6 1,15 * *', func='stats.tasks.send_digest', args=['fortnightly'],
               id='digest-fortnightly', queue_name='citisciapi')
```
      El id fijo hace el registro idempotente (no se duplica al reiniciar) y, si alguien vacía Redis
      o se migra de máquina, un `supervisorctl restart` reconstruye el calendario. **Así el
      calendario efectivo vive en git, y Redis es solo estado.**
- [x] `/etc/supervisor/conf.d/citsci-scheduler.conf`, calcado de `citsci-worker.conf`:
```ini
[program:citsci-scheduler]
command=/home/ubuntu/citsci-api/venv/bin/python manage.py run_scheduler
directory=/home/ubuntu/citsci-api
user=ubuntu
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/citsci-scheduler.err.log
stdout_logfile=/var/log/supervisor/citsci-scheduler.out.log
```
- [x] **Zona horaria — OJO, el plan original estaba equivocado.** Poner `environment=TZ=...` en el
      program de supervisord **no funciona**: Django sobrescribe el `TZ` del proceso con su
      `TIME_ZONE` (`"UTC"`) al cargar los settings, llamando a `time.tzset()`, y lo pisa antes de
      que rq-scheduler mire la hora local. Comprobado: con `TZ` solo en supervisord el cron sale a
      las 08:00 **UTC**, o sea las 10:00 en Madrid.
      La solución es re-fijarlo **después** de que Django cargue, en el `handle()` del comando
      (`apply_scheduler_timezone()`), más `use_local_timezone=True` al registrar el cron. Entonces
      sale a las 08:00 locales todo el año: 06:00 UTC en verano, 07:00 UTC en invierno. Hay tests
      de las dos mitades del año. `TIME_ZONE` de Django sigue en UTC y no se toca.
- [x] "Quincenal" = **días 1 y 15** (periodos de 13-16 días); ni cron ni rq-scheduler saben expresar
      "cada 14 días". El email debe indicar el **rango de fechas exacto** que cubre, no "últimos 15
      días".
- [x] `stats/tasks.py: send_digest(period)` solo orquesta; el trabajo real en
      `manage.py send_stats_digest --period=month|fortnightly [--dry-run]`, para poder lanzarlo a
      mano, reenviar el de un mes pasado y testearlo sin tocar Redis.
- [x] **La ventana la calcula el comando**, desde el último `NotificationLog` correcto hasta ahora.
      Nada de `now - 15 días`: si el worker estuvo parado el día 1, el envío del 15 cubre el hueco en
      vez de dejar un agujero que nadie va a notar.
- [x] `period_key` del resumen = `digest-2026-09` / `digest-2026-09-2`. Con el `unique_together`, ni
      un reintento ni un disparo manual duplican el correo.
- [x] Envío directo por SES desde el job (son pocos correos, segundos). Dejar `--enqueue` como
      opción para cuando crezca la lista de destinatarios, pero no construirlo ahora.
- [x] Aviso de operación a documentar: el scheduler solo **encola**; ejecuta `citsci-worker`. Si el
      worker está caído a esa hora el job espera en cola y sale al volver (bien). Si se cae el
      scheduler, el disparo se pierde en silencio — de ahí `last_digest_sent_at` en el endpoint.

## Fase 6 — Futuro, fuera del primer PR
- [ ] Estadísticas **por pregunta** (distribución de respuestas). `Observation.data` es un JSONField
      con lista de pares `{key, value}` donde `key` es el id de la `Question`: agregar eso es caro y
      muy específico de cada proyecto. Probablemente con `jsonb_array_elements` en SQL crudo.
- [ ] Aprovechar el scheduler para lo que ya hace falta: marcar `ProjectInvitation` y
      `organizations.Invitation` caducadas como `expired`, purgar `ObservationEmailLog` antiguo,
      recordatorio a borradores parados.
- [ ] Export del panel a CSV/XLSX reutilizando los helpers de `DownloadObservationsCSV`
      (`markers/api/views.py:846-898`).

## Fase 7 — Tests ✅ (escritos sobre la marcha en cada fase)
Los tests requieren `--keepdb` en este servidor: el usuario `citsci` no puede crear bases de datos ni
la extensión postgis. `venv/bin/python manage.py test stats --keepdb`.
- [x] `metrics.py` con datos sembrados: conteos correctos con draft/ended/privados mezclados.
- [x] `/api/stats/platform/` → 403 para usuario normal, 401 sin token, 200 para `is_staff`.
- [x] `/api/stats/me/` no incluye proyectos ajenos; el administrador ve los que administra.
- [x] `anonymous_id` no aparece en ninguna respuesta de stats.
- [x] Series: rangos vacíos devuelven listas vacías, no huecos ni error.
- [x] Número de queries acotado (`assertNumQueries`) para que nadie reintroduzca el N+1 de
      `Project.contributions`.
- [x] `send_stats_digest --dry-run` no envía y calcula la ventana desde el último log.
- [x] Idempotencia: dos ejecuciones seguidas del mismo periodo → un solo email.
- [x] Publicar un proyecto encola exactamente una notificación; guardarlo otra vez ya publicado, cero.
- [x] **Ciclo draft → publicado → draft → publicado**: cuatro filas en `ProjectStatusLog`, tres
      emails (publicado, despublicado, republicado) y `published_at` **inalterado** desde la primera.
- [x] `active_30d` usa `Observation.created_at`: una observación con `timestamp` en el futuro no
      marca el proyecto como activo.

---

## Decisiones abiertas
1. Si el dashboard de admin necesita algo más que estos tres endpoints — conviene enseñarle el
   payload de la Fase 2 al front antes de implementarlo.
2. `fran33` / `frasanz@gg.com` (id 434) es superusuario, nunca ha entrado y su dominio no existe.
   Con la Fase 2 tendría acceso al endpoint de plataforma. Pendiente decidir si se le quita
   `is_superuser`/`is_staff` o se desactiva. Aparte de este trabajo.

## Decisiones cerradas el 2026-09-10 (segunda tanda)
- [x] **Zona horaria de los envíos: `Europe/Madrid`**, no un desfase fijo. Madrid es UTC+2 en verano
      pero UTC+1 en invierno: un cron fijo a las 06:00 UTC saldría a las 08:00 en verano y a las
      07:00 en invierno. `TIME_ZONE` del proyecto **sigue siendo UTC** y no se toca; esto es solo
      para los envíos. Setting `PLATFORM_NOTIFICATION_TIMEZONE`, por defecto `Europe/Madrid`.
- [x] **Sí se manda email al despublicar** un proyecto.
- [x] **Destinatarios** en `PLATFORM_NOTIFICATION_EMAILS` (`local.env`), lista explícita:
      `frasanz@ibercivis.es`, `jbarba@ibercivis.es`, `dlisbona@ibercivis.es`,
      `germangil@ibercivis.es`. **Todos reciben todo**: avisos de proyecto y resumen quincenal.
      No se derivan de `is_staff` a propósito: entre los superusuarios hay cuentas de prueba con
      dominios inexistentes (`frasanz@gg.com`) y cada rebote cuenta contra la reputación de SES.
- [x] `is_staff=True` (sin `is_superuser`) para `Germán` (id 138) y `dlisbona` (id 168), sus cuentas
      `@ibercivis.es`. Ojo: los dos tienen además una cuenta personal de gmail en la plataforma
      (ids 415 y 495) que **no** es staff; para el dashboard tienen que entrar con la de ibercivis.

---

## Organizaciones — decidido: de momento, no

**El creador o administrador de una organización NO ve las estadísticas de los proyectos de esa
organización.** Decisión tomada el 2026-09-10; se revisará más adelante.

Es además lo coherente con el código actual: un proyecto referencia `organizations` (M2M) y
`Organization` tiene `creator`/`administrators`/`members` (`organizations/models.py:15`), pero
`_is_project_admin` (`markers/api/views.py:39`) solo mira creador y administradores **del proyecto**.
Darles acceso sería una ampliación de permisos que hoy no existe en ninguna parte y que afectaría a
bastantes más endpoints que las estadísticas. Cuando se retome, va en su propio PR y no colgando de
este.

En el nivel de plataforma (`is_staff`) las organizaciones sí aparecen como agregado
(`organizations.total`, y en su caso proyectos por organización): eso es otra cosa y no da acceso a
nadie a los proyectos ajenos.
