# Contribución anónima por QR — Plan API (Django)

Objetivo: un proyecto puede activar el flag **contribución anónima**. Se genera un QR con una URL
pública; quien lo escanea puede enviar observaciones a ese proyecto **sin cuenta**. Las observaciones
quedan asociadas a un identificador anónimo del navegador (`anonymous_id`, UUID generado en cliente).

Contraparte front: `react/ANONYMOUS_CONTRIBUTION_PLAN.md`.

---

## Estado actual (investigado 2026-09-07)

Lo que ya encaja:
- `Observation.creator` ya es `null=True` (`markers/models.py:17`). `__str__` muestra "deleted user" y
  `markers/tasks.py:49` guarda `if observation.creator`. Una observación sin creador no rompe nada.
- La participación **no requiere membresía** en proyectos públicos: `ObservationListCreate.create` solo
  comprueba `ProjectMembership` si `project.is_private` (`markers/api/views.py:99`).
- Precedente de endpoint público por flag: `public_map` → `PublicMapView` (`markers/api/views.py:963`)
  y `PublicObservationDetailView` (`:1115`). Construyen a mano meta del proyecto + preguntas para
  consumidores sin sesión. Es la plantilla a copiar.
- Precedente de token firmado: `django.core.signing` en `users/api/views.py:104-140`.

Lo que bloquea hoy:
- `ObservationListCreate.get_permissions` devuelve `[IsAuthenticated(), HasClientApiKey()]` en POST
  (`markers/api/views.py:70-73`). Línea 158 fija `'creator': request.user.id`.
- Todo `field_forms` es `IsAuthenticated` (`field_forms/api/views.py:11,23,33,45,62`). Un anónimo no
  puede leer la definición del formulario.
- **No hay throttling** en toda la API (ningún `DEFAULT_THROTTLE_*` ni `throttle_classes`).
- `Project` se identifica solo por PK entero. No hay slug ni UUID. La URL del QR sería adivinable.
- `HasClientApiKey` (`markers/api/permissions.py`) compara con `CLIENT_API_KEY_WEB/MOBILE`, pero la
  clave web viaja en el bundle público (`VITE_OBSERVATIONS_API_KEY`). No es un secreto real.
- No hay `django-cors-headers`; el cruce geonity.ibercivis.es → api.ibercivis.es se resuelve en nginx.
  Mientras la página anónima viva en el react actual, no hay que tocar CORS.
- No hay ninguna librería QR en `requirements.txt`. No hace falta: el QR se genera en cliente.

---

## Fase 1 — Modelo y migraciones
- [x] `Project.anonymous_contribution = BooleanField(default=False)` junto a `public_map`
      (`project/models.py:51`).
- [x] `Project.anonymous_token = UUIDField(default=uuid.uuid4, unique=True, editable=False)`.
      Va en la URL del QR en vez del PK. Regenerarlo invalida los QRs impresos.
- [x] `Observation.anonymous_id = UUIDField(null=True, blank=True, db_index=True)`.
- [x] Opcional: `Observation.anonymous_source = CharField(max_length=64, null=True, blank=True)`
      para el parámetro `?src=` del QR (varios carteles por proyecto).
- [x] Migraciones: `project/0041_*` y `markers/0013_*`. La migración de `anonymous_token` necesita
      un `RunPython` para poblar UUIDs en filas existentes antes de añadir `unique=True`.

## Fase 2 — Serializers de proyecto
- [x] Añadir `anonymous_contribution` y `anonymous_token` (read-only) a
      `ProjectSerializerCreateUpdate.Meta.fields` (`project/api/serializers.py:103`) y a
      `ProjectListSerializer.Meta.fields` (`:404`).
- [x] Validación: rechazar `anonymous_contribution=True` si `is_private=True`. Primera iteración:
      no mezclamos anónimo con privado.
- [x] Endpoint `POST /api/project/<pk>/regenerate-anonymous-token/` con `IsCreatorOrAdminOrReadOnly`
      (reusar la clase de `project/api/views.py:46`). Devuelve el token nuevo.

## Fase 3 — Endpoints públicos
Prefijo `/api/anonymous/<uuid:token>/`. Ambos `permission_classes = [AllowAny]`,
`authentication_classes = []`. Devuelven **404** (no 403) si el proyecto no existe, no tiene el flag
activo, es privado o está `ended`. Así no se filtra la existencia del proyecto.
Los borradores **sí** aceptan contribución anónima (ver nota abajo).

- [x] `GET /api/anonymous/<token>/` → nombre, descripción, cover, `post_observation_message`,
      preguntas del `FieldForm` resueltas por `Accept-Language` (mismo formato que devuelve
      `GET /field_forms/<id>/` para que el front reutilice `ObservationField`). Copiar estructura de
      `PublicMapView`.
- [x] `POST /api/anonymous/<token>/observations/` → `parser_classes = (MultiPartParser, FormParser)`.
      Mismo body que `POST /observations/` (`field_form` implícito por el token, `geoposition`,
      `timestamp`, `data`, ficheros `image_<qid>` / `audio_<qid>`).
  - Cabecera obligatoria `X-Anonymous-Id: <uuid>`. Si falta o no es UUID válido → 400.
  - `creator=None`, `anonymous_id` de la cabecera, `platform='web'`,
    `anonymous_source` de `?src=` o campo `source` (saneado, máx 64 chars).
  - Respetar `allowed_platforms`: si el proyecto es solo `mobile`, rechazar (la contribución
    anónima cuenta como `web`).
- [x] Refactorizar el cuerpo de `ObservationListCreate.create` (`markers/api/views.py:75-198`) a una
      función `create_observation(project, field_form, request_data, files, *, creator, anonymous_id,
      platform, source)` compartida por la vista autenticada y la anónima. **No** relajar la vista
      autenticada: `POST /observations/` sigue exigiendo login + API key.
- [x] Opcional: `GET /api/anonymous/<token>/observations/mine/` filtrando por `X-Anonymous-Id`, para
      que el navegador vea lo que ha enviado. Solo lectura; sin edición ni borrado anónimo.

## Fase 4 — Throttling (mismo PR que la Fase 3, no negociable)
- [x] Añadir a `REST_FRAMEWORK` en `settings.py`: `DEFAULT_THROTTLE_CLASSES` vacío (para no afectar al
      resto) y `DEFAULT_THROTTLE_RATES` con scopes `anon_form` y `anon_submit`.
- [x] Throttle por IP (`AnonRateThrottle` con scope) en ambos endpoints. Orientativo:
      `anon_form: 60/min`, `anon_submit: 20/hour` por IP.
- [x] Throttle adicional por `anonymous_id` en el POST (subclase de `SimpleRateThrottle` que usa la
      cabecera como `ident`). Orientativo: `10/hour`.
- [x] Límite de tamaño de ficheros en el POST anónimo (p. ej. 10 MB por imagen, 3 imágenes).
- [x] Throttle funciona sobre la caché Redis ya configurada; comprobar que el `cache` por defecto
      es el que usa DRF.
- [ ] Futuro si hay abuso: Cloudflare Turnstile en el POST. No de salida.

## Fase 5 — Efectos colaterales de `creator=None`
- [x] `ObservationRetrieveUpdateDestroy.update/delete` comparan `observation.creator != request.user`
      (`markers/api/views.py:218,227`). Con `None` devuelven 403 para todos salvo admin. Es lo deseado;
      confirmar que el admin del proyecto sí puede borrar anónimas.
- [x] `ObservationWithPublicAdminSerializer.get_is_mine` (`serializers.py:247-251`) es por usuario.
      Devolver `False` para anónimas. Añadir campo `is_anonymous` al serializer de observación.
- [x] `MyProjectsView` (`project/api/views.py:212-229`) infiere participación por `Observation.creator`.
      Las anónimas no aparecen ahí. Correcto.
- [x] Descarga de observaciones (`project/<id>/download_observations/`): columna `creator` vacía y
      columna nueva `anonymous_id` (truncado a 8 chars) + `anonymous_source`.
- [x] Email `email_on_observation` (`markers/tasks.py`): el texto debe decir "Contribución anónima"
      en vez del nombre de usuario.
- [x] Señales de caché (`markers/signals.py:13-24`): ya se disparan por `post_save` de Observation,
      no dependen del creador. Verificar.

## Fase 6 — Reclamar observaciones (iteración posterior, no en el primer PR)
- [ ] `POST /api/observations/claim/` autenticado, body `{anonymous_id}`: asigna `creator=request.user`
      a las observaciones con ese `anonymous_id` y `creator IS NULL`. Idempotente.
- [ ] Rate limit fuerte y registrar en log; un `anonymous_id` ajeno solo se puede adivinar si es
      público, y no lo es.

## Fase 7 — Tests
- [x] 404 si flag apagado / proyecto `ended` / token inexistente. Los `draft` devuelven 200.
- [x] POST sin `X-Anonymous-Id` → 400. Con UUID inválido → 400.
- [x] POST correcto crea observación con `creator=None`, `anonymous_id` y `platform='web'`.
- [x] `allowed_platforms='mobile'` → rechazado.
- [x] Validación de `data` (mandatory, CHOICE, MCHOICE) idéntica a la vista autenticada (comparte
      código, pero un test de regresión).
- [x] Throttling: N+1 peticiones → 429.
- [x] `is_private=True` + `anonymous_contribution=True` → 400 en PATCH del proyecto.
- [x] Regenerar token: el token viejo pasa a 404.

---

## Decisiones tomadas
- **QR generado en cliente**, la API solo expone `anonymous_token`. Sin librería QR en Django.
- **Vistas nuevas**, no relajar `POST /observations/`. Superficie pública acotada a dos endpoints.
- **404 en vez de 403** cuando el flag está apagado.
- **Anónimo + privado no se permite** en la primera versión. Si algún día hace falta, el token del QR
  actúa como la contraseña del proyecto.
- **Sin edición ni borrado anónimo**. Solo alta y, opcionalmente, lectura de lo propio.
- **No guardar IP** junto a la observación. El throttle usa la IP solo en caché con TTL corto.

## Privacidad
`anonymous_id` es un pseudónimo persistente: técnicamente dato personal (RGPD), riesgo mínimo si no
se guarda nada más junto a él. Hay que mencionarlo en la política de privacidad y en un aviso corto
en la landing del QR. No requiere banner de consentimiento (estrictamente necesario para el servicio).

## Estimación
~1 día: modelo + migraciones + dos vistas + throttling + tests. La Fase 6 aparte.

---

## Implementado (2026-09-07)

Fases 1 a 5 y 7. La Fase 6 (reclamar observaciones) queda para otra iteración, como decía el plan.

Endpoints nuevos:
- `GET  /api/anonymous/<uuid:token>/` — proyecto + formulario (landing del QR).
- `POST /api/anonymous/<uuid:token>/observations/` — alta anónima. Cabecera `X-Anonymous-Id`
  obligatoria, `?src=` opcional. Máx. 3 imágenes y 10 MB por archivo.
- `GET  /api/anonymous/<uuid:token>/observations/mine/` — lo enviado por ese navegador.
- `POST /api/project/<pk>/regenerate-anonymous-token/` — creador o admin.

Ficheros tocados: `project/models.py`, `markers/models.py`, migraciones `project/0041` y
`markers/0013`, `project/api/{serializers,views,urls}.py`, `markers/api/{views,serializers,urls}.py`,
`markers/api/throttles.py` (nuevo), `citsci-api/settings.py`, `markers/tasks.py`,
`templates/email/observation_admin_notification.html`, `markers/tests.py` (26 tests).

Detalles que se decidieron sobre la marcha:
- `anonymous_id` **no** aparece en ningún serializer: entra por parámetro a `create_observation`
  y sale solo truncado a 8 caracteres en la descarga de observaciones. Si saliera en la API,
  cualquiera podría reclamar observaciones ajenas cuando se implemente la Fase 6.
- Se añade `is_anonymous` (booleano) a `ObservationSerializer`, así que lo heredan todas las
  vistas de observación.
- `ObservationRetrieveUpdateDestroy.delete` ahora deja borrar a los administradores del proyecto
  **solo** las observaciones anónimas: sin dueño, si no nadie podría borrarlas. Sobre las de
  usuarios registrados no cambia nada.
- **`draft` sí acepta contribución anónima**, al revés de lo que decía el plan. Se cambió al
  probarlo en producción: publicar exige más de 10 observaciones, así que el borrador es justo la
  fase en la que hace falta el QR para reunirlas. Con la regla original el flujo se quedaba
  bloqueado. No expone nada: el token es un UUID que no se adivina y el borrador sigue sin
  listarse en ningún sitio.
- Los tests requieren `--keepdb` en este servidor: el usuario `citsci` no puede crear bases de
  datos ni la extensión postgis. La BD `test_geonity_production` ya existe con postgis instalado:
  `python manage.py test markers --keepdb`.
