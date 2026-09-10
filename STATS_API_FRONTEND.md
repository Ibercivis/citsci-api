# API de estadísticas — guía para el front

Tres endpoints, ya desplegados en producción (2026-09-10). Devuelven JSON listo para pintar: los
conteos, las series temporales y los rankings vienen calculados del servidor, el front no tiene que
agregar nada.

Base: `https://geonity.ibercivis.es/api/`

---

## Autenticación

Toda la API usa **`TokenAuthentication`**, no sesión:

```
Authorization: Token <clave>
```

| Endpoint | Quién puede |
|---|---|
| `GET /api/stats/platform/` | Solo usuarios con **`is_staff`** |
| `GET /api/stats/me/` | Cualquier usuario autenticado |
| `GET /api/project/<pk>/stats/` | **Creador y administradores** de ese proyecto |

Hoy tienen `is_staff`: `fran`, `jbarba`, `dlisbona`, `Germán`, `fran67`, `fran33`. Ojo con `dlisbona`
y `Germán`: **tienen también una cuenta personal de gmail en la plataforma que NO es staff**. Si
entran con esa, el panel les dará 403.

Errores:

| Código | Cuándo |
|---|---|
| `401` | Sin cabecera `Authorization` o token inválido |
| `403` | Autenticado pero sin permiso (usuario normal en `/platform/`, ajeno a un proyecto) |
| `404` | El proyecto no existe |
| `400` | Parámetros mal (`{"detail": "..."}`) |
| `429` | Más de 30 peticiones por minuto y usuario |

---

## Parámetros comunes

Los tres endpoints aceptan lo mismo:

| Parámetro | Valores | Por defecto |
|---|---|---|
| `from` | `YYYY-MM-DD` | 12 meses antes de `to` |
| `to` | `YYYY-MM-DD` (**exclusivo**) | ahora |
| `granularity` | `month` \| `week` | `month` |
| `refresh` | `1` \| `true` | — |

La respuesta se cachea **10 minutos**. El campo `cached` dice si viene de caché; `?refresh=1` la
salta. Para un panel normal no hace falta: si el usuario pulsa "actualizar", ahí sí.

`Accept-Language` decide el idioma de los nombres de proyecto (`es`, `en`, …).

---

## `GET /api/stats/platform/`

Métricas globales. **Es el único nivel que compara proyectos entre sí** (el bloque `top`); esa
información no aparece en los otros dos endpoints, a propósito.

```jsonc
{
  "generated_at": "2026-09-10T14:07:19.623002Z",
  "period": { "from": "2025-09-15", "to": "2026-09-10", "granularity": "month" },

  "projects": {
    "total": 38,
    "published": 6,            // ni borrador ni terminado
    "draft": 31,
    "ended": 1,
    "private": 4,
    "anonymous_enabled": 2,    // con contribución anónima por QR activada
    "public_map": 12,
    "with_observations": 31,
    "active_30d": 12,          // ojo: incluye BORRADORES, ver más abajo
    "active_30d_published": 5, // el subconjunto que además está publicado
    "abandoned": 1             // publicado y >90 días sin observaciones
  },

  "observations": {
    "total": 1492,
    "last_30d": 378,
    "anonymous": 3,
    "by_platform": { "mobile": 928, "web": 134, "unknown": 430 },
    "with_images": 925,
    "with_audio": 5
  },

  "users": { "total": 784, "active": 784, "new_30d": 136, "with_observations": 373 },
  "organizations": { "total": 12 },
  "engagement": { "memberships": 42, "invitations_pending": 29, "likes": 148 },

  "series": {
    "projects_created": [ { "period": "2025-09-01", "count": 0 }, … ],
    "projects_created_cumulative": [ … ],
    "projects_published": [ … ],
    "projects_published_cumulative": [ … ],
    "observations": [ … ],
    "observations_cumulative": [ … ],
    "users": [ … ],
    "users_cumulative": [ … ]
  },

  "top": {
    "projects_by_observations": [
      { "id": 172, "name": "Life-Nitrazens", "observations": 621, "published": true }
    ],
    "creators_by_observations": [
      { "id": 138, "username": "Germán", "observations": 775, "projects": 2 }
    ]
  },

  "last_digest_sent_at": null,   // null si aún no ha salido ningún resumen mensual
  "cached": false
}
```

## `GET /api/stats/me/`

Lo mismo pero **solo sobre los proyectos que el usuario crea o administra**, más un desglose por
proyecto. **No trae `top`.**

```jsonc
{
  "generated_at": "…",
  "period": { … },
  "projects": { … },        // mismas claves que arriba
  "observations": { … },
  "contributors": { "registered": 31, "anonymous": 2, "total": 33 },
  "series": { "observations": [ … ], "observations_cumulative": [ … ] },
  "per_project": [
    {
      "id": 172,
      "name": "Life-Nitrazens",
      "published": true,
      "draft": false,
      "ended": false,
      "created_at": "2026-03-01T09:00:00Z",
      "published_at": "2026-03-05T12:00:00Z",   // null si nunca se publicó
      "observations": 621,
      "last_observation": "2026-09-09T18:22:00Z",
      "active_30d": true
    }
  ],
  "cached": false
}
```

Un usuario sin proyectos recibe **200** con `projects.total = 0` y `per_project: []`. No es un error.

## `GET /api/project/<pk>/stats/`

Un solo proyecto. **No trae `top`.**

```jsonc
{
  "generated_at": "…",
  "period": { … },
  "project": {
    "id": 172, "name": "Life-Nitrazens", "published": true, "draft": false, "ended": false,
    "created_at": "…", "published_at": "…"
  },
  "observations": { … },
  "contributors": { "registered": 31, "anonymous": 2, "total": 33 },
  "span": { "first_observation": "…", "last_observation": "…" },  // null si no hay ninguna
  "series": { "observations": [ … ], "observations_cumulative": [ … ] },
  "cached": false
}
```

---

## Cosas que hay que entender antes de pintar nada

**`active_30d` incluye borradores, y es intencionado.** En producción hay 12 proyectos activos pero
solo 5 publicados: **7 borradores están recogiendo datos** por QR. Si el panel enseña solo los
publicados, la plataforma parecerá mucho más muerta de lo que está. Usa `active_30d` para "actividad
real" y `active_30d_published` si necesitas el subconjunto.

**`projects_published` son PRIMERAS publicaciones.** Un proyecto puede volver a borrador y
publicarse otra vez; la fecha de publicación no se reescribe. La serie mide crecimiento, no
transiciones. Si algún día hace falta el histórico completo de idas y venidas, está en la tabla
`ProjectStatusLog`, pero hoy no se expone por API.

**`by_platform.unknown` son 430 observaciones (29%)** anteriores a que existiera el campo `platform`.
No las escondáis en un "otros" minúsculo: son casi un tercio. O se etiquetan como "sin registrar", o
se acota el gráfico a fechas posteriores.

**Las series ya vienen con los huecos rellenos a 0** y ordenadas. `period` es la fecha de inicio del
cubo (`YYYY-MM-DD`); con `granularity=week`, el lunes. Un rango vacío devuelve `[]`, no un error.

**Los acumulados arrancan de lo que había antes de `from`.** Por eso el primer punto de
`observations_cumulative` no es igual al primero de `observations`: si no, parecería que la
plataforma nació el primer día del rango pedido.

**Nunca sale ningún `anonymous_id` ni ningún email.** Los contribuidores anónimos aparecen solo como
cardinalidad, y los creadores por `username`. Es una regla del backend, no la rodeéis pidiendo esos
datos por otro sitio.

**`total` vs `active` en usuarios**: hoy coinciden (784/784) porque no hay nadie desactivado. No
asumáis que siempre será así.

---

## Sugerencia de panel

Con lo que hay, un panel de staff que se lea de un vistazo sería:

1. **Cuatro cifras arriba**: observaciones totales, proyectos publicados, usuarios, activos en 30
   días. Con la variación respecto al periodo anterior si os apetece calcularla en cliente (el
   backend ya la calcula para el correo; si la queréis por API, se añade).
2. **Un gráfico de líneas** con `observations` y `observations_cumulative`, selector de rango.
3. **Barras** de `users` y `projects_created`.
4. **Un donut** de `by_platform`, con `unknown` etiquetado con honestidad.
5. **Dos tablas**: `top.projects_by_observations` y `top.creators_by_observations`.
6. **Un aviso** cuando `projects.abandoned > 0`: son proyectos publicados que llevan más de 90 días
   parados y alguien debería mirarlos.

Para el panel del creador (`/stats/me/`), lo mismo sin `top` y con la tabla `per_project` como
elemento principal, marcando los que tienen `active_30d: false`.

---

## Lo que aún no hay, por si lo pedís

- Variación respecto al periodo anterior **por API** (existe, pero solo dentro del email mensual).
- Nombres de los proyectos abandonados por API (ídem: hoy solo en el email).
- Estadísticas por pregunta del formulario, o sea la distribución de respuestas. Es lo más pedido y
  lo más caro: `Observation.data` es un JSONField con pares `{key, value}`. Está anotado como fase
  futura en `STATS_PLAN.md`.
- Export a CSV/XLSX del panel.

Preguntad antes de calcular algo en cliente: casi todo lo que falta es más barato de añadir al
serializer que de agregar en el navegador.
