# Running Geonity locally

The API, the web app and the admin panel on a laptop, with a small sample of data and
**nothing copied from production**.

Everything here is additive. `Dockerfile` and `compose.yaml` were already in this repository;
what this adds is the dataset: one management command, `project/management/commands/seed_local.py`,
and the public snapshot it plants.

## Why there is no production data in here

The only personal data this application holds lives in three tables — `auth_user`,
`account_emailaddress` and `users_profile`. Projects, field forms, observations, their photographs
and the administrative columns carry nothing about anybody.

That split is what makes a production extract unnecessary rather than merely undesirable:

- **The realistic half can be rebuilt from a public source.** An observation in Geonity is a
  species, a place and a moment, and all three are published as open data. The sample uses real
  GBIF occurrence records — real species, at the coordinates and on the dates they were really
  recorded, in the Ebro valley and across Spain.
- **The half that would have carried personal data is the half that is cheapest to invent.**
  Accounts exist here only as actors: somebody has to own a project and somebody has to have
  contributed, or every screen is empty. Any six made-up people do that as well as six real ones.

So there is nothing to anonymise, because nothing personal is copied in the first place. GDPR does
not come into it.

**The observer's name is never fetched.** A GBIF record also names whoever made the observation —
`recordedBy`, `identifiedBy`, `rightsHolder`, an iNaturalist nickname. `local_dev/fetch_gbif_sample.py`
keeps an allow-list of fields and an assertion that none of those is in it, so the personal fields
are dropped at fetch time and never reach this repository or a local database. The query also asks
GBIF for `license=CC0_1_0` only, so every record in the snapshot is in the public domain.

## What you need

Docker. Node 20+ only if you also want the web app or the admin panel.

## Start it

```sh
docker compose up -d --build
docker compose exec citsci-api python manage.py seed_local
```

That is the whole API: PostgreSQL with PostGIS, Redis, the API, the `django-rq` worker and the
scheduler. Migrations run on start.

- API docs: <http://localhost:8000/api/docs/>
- Django admin: <http://localhost:8000/admin/>

Mail is printed to the API's console (`DEBUG` is on), so nothing leaves the machine and no SES
credentials are needed. To read it: `docker compose logs -f citsci-api`.

## What the sample contains

`seed_local` creates, by default, 4 projects, 6 accounts and 60 observations:

| | |
|---|---|
| **Projects** | *Aves del valle del Ebro* (points on the map, anonymous QR contribution on), *Mariposas y polillas de España* (`fuzzy`, so its map aggregates into H3 cells), *Flora de ribera del Gállego* (published, no observations — the empty states, and something for "Discover projects" to offer), *Anfibios en balsas de riego* (draft). |
| **Observations** | Real GBIF records: species, coordinates and dates as recorded. Every fifth one in the bird project is an anonymous QR contribution with no account behind it. |
| **Field forms** | Between them they use every answer type the screens render: `CHOICE` with `allow_other`, `MCHOICE`, `NUMBER`, `DATE`, `STRING` and `IMAGE`. |
| **Photographs** | Drawn by the command, and they say so on the image. This is the one part that cannot come from a public source: a real species photograph belongs to whoever took it. |
| **People** | One superuser, one staff account that owns everything, four volunteers with profiles, countries and memberships. All invented. |
| **The rest** | One invented organization, administrative columns (`validated`, `status`) with values filled in, likes, memberships, and a project status history. |

Options:

```sh
python manage.py seed_local --observations 120   # up to what the snapshot holds
python manage.py seed_local --no-images          # rows only, no drawn photographs
python manage.py seed_local --dates real         # see below
python manage.py seed_local --reset              # remove what a previous run created
```

Re-running it is safe. It rewrites the projects and their observations in place and leaves
everything else alone; `--reset` deletes the invented accounts, which cascades to the rest.

### About the dates

GBIF publishes with a lag of some weeks, so its newest record is about a month old however recent a
window you ask for. By default `seed_local` slides the whole set forward as a block, keeping the
real intervals between observations, so the newest lands today and the screens that count "this
month" or list recent activity have something to show. `--dates real` keeps GBIF's own dates
instead, at the price of a home page that says the last contribution was weeks ago.

### Refreshing the snapshot

`local_dev/gbif_sample.json` is committed, so seeding never touches the network. It goes stale
slowly — the dates are real, so they age. To rebuild it:

```sh
python3 local_dev/fetch_gbif_sample.py            # last 150 days, both themes
python3 local_dev/fetch_gbif_sample.py --days 60
```

## Accounts

Every account's password is `devpass12345` (`--password` changes it). The addresses are on the
reserved `.invalid` domain, so none of them can reach a mailbox.

| Account | Role |
|---|---|
| `admin@geonity.invalid` | superuser, for `/admin/` |
| `rosa@geonity.invalid` | staff; creates and administers all four projects and the organization |
| `ada@`, `bruno@`, `chiara@`, `dani@geonity.invalid` | volunteers with observations and profiles |

`ACCOUNT_EMAIL_VERIFICATION` stays `'mandatory'` as in production, so the seeded accounts are given
confirmed `EmailAddress` rows and can sign in at once. Each also gets a DRF token, which is what the
API authenticates with.

## The web app and the admin panel

They live in [`Ibercivis/Geonity`](https://github.com/Ibercivis/Geonity), branch `federation`. See
`LOCAL-DEV.md` there; the short version is that both are started with `npm run dev` and both must
reach this API **through their dev server's proxy**, because the API sends no CORS headers and the
browser would block a direct call to `http://localhost:8000` from another origin.

## Known issues, found while setting this up

These are pre-existing, reproduce without any of this tooling, and none of them is fixed here.

1. **The API sends no CORS headers.** `django-cors-headers` is not installed and no middleware adds
   them, so every browser client has to be same-origin with the API or go through a proxy. In
   production the reverse proxy is what makes `geonity.ibercivis.es` and
   `geonity-backend.ibercivis.es` work together; locally, the Vite proxy does the same job.

2. **`POST /api/observations/` returns 500 on a malformed `geoposition`.** The string goes to
   GEOS unguarded, and `ValueError: String input unrecognized as WKT EWKT, and HEXEWKB` escapes as a
   500 instead of a 400. A well-formed `POINT (lon lat)` works; `SRID=4326;POINT (...)` does not,
   although that is the form the API itself returns when reading.

3. **`create_test_project.py` in the repository root** writes 40,000 observations to whatever
   database the settings point at, and looks up a specific real user by email address. It has no
   guard on `DEBUG` and no guard on the host. `seed_local` refuses to run with `DEBUG=False`, and
   refuses a database that holds accounts it did not create unless given `--force`.

4. **Deprecated allauth settings.** `ACCOUNT_AUTHENTICATION_METHOD`, `ACCOUNT_EMAIL_REQUIRED` and
   `ACCOUNT_USERNAME_REQUIRED` print a deprecation warning on every management command. Harmless
   today; they are removed in a future allauth.

## Limits of the local instance

- **Maps need a Mapbox token.** Every screen works without one except the maps themselves, which
  stay blank (the admin panel says so in words). Any token from a free Mapbox account, in
  `VITE_MAPBOX_TOKEN`, fixes it. Nothing in this repository needs one.
- **The mobile client was not exercised.** See `LOCAL-DEV.md` in the Geonity repository for what it
  would take.
- **Re-seeding changes the primary keys**, so `/projects/7` becomes `/projects/11` after a
  `--reset`. The command prints the new ones.
- **Media files are not cleaned up.** `--reset` deletes rows and leaves `media/` alone, so drawn
  photographs from earlier runs accumulate there. `media/` is gitignored; delete it by hand.
