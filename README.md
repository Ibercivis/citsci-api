# citsci-api
Citizen Science Application API

## Arranque local

Solo necesita Docker:

```sh
docker compose up --build
```

Deja en pie cinco servicios: PostgreSQL con PostGIS, Redis, el API, el worker de `django-rq` y el
scheduler — los mismos tres procesos que supervisord corre en produccion (ver `deploy.sh`). Las
migraciones se aplican solas al arrancar.

- API: <http://localhost:8000/>
- Documentacion OpenAPI: <http://localhost:8000/api/docs/>
- Admin: <http://localhost:8000/admin/>, con un usuario creado a mano:
  `docker compose exec citsci-api python manage.py createsuperuser`

En desarrollo `DEBUG` esta activo y **los correos salen por la consola**, asi que no hacen falta
credenciales de AWS SES para ver la plataforma funcionando. Para parar y borrar los datos:
`docker compose down -v`.

La base arranca vacia. Para llenarla con una muestra pequena que **no copia nada de produccion**
—cuatro proyectos, seis cuentas inventadas y sesenta observaciones construidas sobre registros
publicos— ver [`LOCAL-DEV.md`](LOCAL-DEV.md).

Dos avisos:

- **No es la pila de produccion**, y no pretende serlo: produccion corre sobre el host con
  supervisord. Aqui las contrasenas estan a la vista y el servidor es el de desarrollo de Django.
- El codigo va montado dentro del contenedor, asi que **un `citsci-api/local.env` del host tambien
  se lee ahi** y pisa lo que diga el `compose`. Si algo no cuadra con la configuracion, mirar ese
  fichero primero.

## OpenAPI (Swagger)

- UI: `/api/docs/`
- Schema: `/api/schema/`

## Dynamic administrative fields on Observations

Lets project administrators add manageable "columns" to a project's observations (e.g. **Validated** Yes/No, **Status**) without changing the original `Observation` payload or the existing observation endpoints.

### Concepts

- **ProjectObservationField**: defines an administrative column for a project (e.g. `validated`, `status`).
- **ObservationFieldValue**: stores the value of that column for a specific observation.

### Authentication

- Write operations (creating/editing/deleting definitions) and reading/editing values (`/admin-fields/`) need a token in the header:
	- `Authorization: Token <key>`
- `GET` of the definitions (`/api/projects/{project_id}/observation-fields/`) is public (no authentication required, for now).

### Endpoints

#### 1) Define columns (per project)

- `GET /api/projects/{project_id}/observation-fields/`
	- Lists the project's column configuration.

- `POST /api/projects/{project_id}/observation-fields/`
	- Creates a column (project creator/administrators only).
	- Examples:
		- Boolean:
			- `{ "key": "validated", "label": "Validated", "field_type": "bool", "required": false, "order": 10 }`
		- Choice:
			- `{ "key": "status", "label": "Status", "field_type": "choice", "choices": ["Sent","Received","In progress"], "order": 20 }`

- `PATCH /api/projects/{project_id}/observation-fields/{id}/`
	- Edits a definition (creator/administrators only).

- `DELETE /api/projects/{project_id}/observation-fields/{id}/`
	- Deletes a definition (creator/administrators only).

#### 2) Read/edit values (per observation)

- `GET /api/observations/{observation_id}/admin-fields/`
	- Returns all the project's columns and the current value (if any) for that observation.

- `PATCH /api/observations/{observation_id}/admin-fields/`
	- Updates values (project creator/administrators only).
	- Body:
		- `{ "values": { "validated": true, "status": "Received" } }`
	- Response:
		- `{ "updated": ["validated", "status"] }`

#### 3) Read values in bulk (per project)

- `GET /api/projects/{project_id}/observation-admin-values/`
	- Returns the project's column definitions (`fields`) and, for each observation of the project, a `values` map keyed by `key`.
	- Requires authentication and being a project creator/administrator.

## Deployment

Production is deployed with `deploy.sh` (run on the server): it checks the working tree, backs up the database and the code, fast-forwards to `origin/vjorge`, runs `manage.py check`, restarts only what is needed with supervisord, verifies the result, rolls back automatically on failure, and tags the release (`prod-YYYY-MM-DD-N`).
Run `./deploy.sh --help` for the options (`--dry-run`, `--with-migrations`).
The production database name is not stored in the repository: put `DB_NAME=...` in `~/.geonity-deploy.env` on the server.
