# citsci-api
Citizen Science Application API

## Running locally

Docker is all it needs:

```sh
docker compose up --build
```

That brings up six services: PostgreSQL with PostGIS, Redis, a mail catcher, the API, the
`django-rq` worker and the scheduler — the last three are the same processes supervisord runs in
production (see `deploy.sh`). Migrations are applied on start.

- API: <http://localhost:8000/>
- OpenAPI docs: <http://localhost:8000/api/docs/>
- Admin: <http://localhost:8000/admin/>, with a user created by hand:
  `docker compose exec citsci-api python manage.py createsuperuser`
- Inbox: <http://localhost:8027/>

In development **mail goes to the inbox instead of leaving the machine**, so no AWS SES credentials
are needed to see the platform working, and the activation link of an account registered through
the form is one click away. To stop and delete the data: `docker compose down -v`.

The database starts empty. To fill it with a small sample that **copies nothing from production** —
four projects, six invented accounts and sixty observations built on public records — see
[`LOCAL-DEV.md`](LOCAL-DEV.md).

Two warnings:

- **This is not the production stack**, and does not try to be: production runs on the host under
  supervisord. Here the passwords are in plain sight and the server is Django's development server.
- The code is mounted inside the container, so **a `citsci-api/local.env` on the host is read in
  there too** and overrides whatever the `compose` file says. If the configuration does not add up,
  look at that file first.

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
