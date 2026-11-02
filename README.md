# Shade of Doubt

Shade of Doubt audits one question: does a shopping suggestion depend on how this photograph was captured?

A signed-in person consents, submits a real selfie, and the service sends an unmodified baseline plus six one-factor variants to YouCam AI Skin Analysis. It then compares persisted `raw_score` values and a frozen product ranking. Appearance scores are model outputs, not physiological measurements. Shopping suggestions are not safety or efficacy advice.

This repository is **not production-verified**. Live YouCam calls were not made in the environment that built it, because no API key was available. Missing credentials stop the run with a configuration error. They are not replaced with sample scores.

## Layout

- `frontend` — Next.js App Router, TypeScript, Tailwind, Radix, TanStack Query, Recharts.
- `backend` — FastAPI, SQLAlchemy, Alembic, the YouCam adapter, image pipeline, ranking, and the worker. The API and worker share one Docker image.
- Postgres holds the tables and, in production, the photograph bytes. There is no account system. Each browser stores a random session and the API scopes rows to the hash of that session.

## Local API and worker

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.lock
cp .env.example .env
# Fill YouCam values. Leave YOUCAM_UNIT_COST_PER_TASK empty until you confirm the account price.

createdb shade
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# second terminal, same environment
python -m app.worker
```

The worker claims jobs with `FOR UPDATE SKIP LOCKED`, renews a lease with a heartbeat, and returns an expired lease to the queue until `WORKER_MAX_ATTEMPTS`. If a YouCam create call does not return a task id, the variant is marked for reconciliation and is not submitted again until someone checks the YouCam console and calls `POST /v1/experiments/{id}/reconcile` with `attach_task` or `not_created`.

Health: `GET /health` and `GET /ready` on the API, `GET /health` on the worker port (`WORKER_HEALTH_PORT`, default 8001).

## Local web

```bash
cd frontend
npm ci
# NEXT_PUBLIC_* values are read when the dev server starts
npm run dev
```

## Compose

Docker Compose starts Postgres, the API, the worker, and the web app. Copy `.env.example` to `.env` first. The Compose override stores images on a shared volume (`STORAGE_BACKEND=local`). Railway sets `STORAGE_BACKEND=database` so the separate API and worker share photograph bytes through Postgres.

```bash
docker compose up --build
```

API and worker images run `alembic upgrade head` before the process starts.

## Production on Railway

The project graph is `.railway/railway.ts`: Postgres, an API service, a worker service, and the web service. Railway reads that file when you run the CLI. It is not applied by a git push on its own.

```bash
npm install
railway login
railway link
railway config plan
railway config apply
```

After the first apply, open the API and worker services and set `YOUCAM_API_KEY` and `YOUCAM_UNIT_COST_PER_TASK`. The file keeps those with `preserve()`, so a later apply does not wipe them. Leave the unit cost empty until you confirm the figure on your YouCam account. The documented table lists 12 units for an SD task with 5–8 concerns.

`DATABASE_URL` comes from the Postgres plugin. A `postgres://` URL is accepted and rewritten to `postgresql+psycopg://`. `FRONTEND_ORIGIN` and `NEXT_PUBLIC_API_URL` reference the generated public domains. `NEXT_PUBLIC_API_URL` is baked into the browser bundle, so the web service rebuilds when it changes.

The API and worker images run `alembic upgrade head` before the process starts. Photographs are stored in the `stored_objects` table. There is no separate object store and no sign-in page.

A browser that has not visited before creates a session in `localStorage`. History shows audits for that browser only. “Delete this browser’s data” removes those rows and starts a new session.

## Configuration that blocks paid work

`YOUCAM_API_KEY` empty: tasks are refused. `YOUCAM_UNIT_COST_PER_TASK` empty: tasks are refused. The documented unit table (AI Skin Analysis v2.0/v2.1) lists 12 units for an SD task with 5–8 concerns and 16 for HD. The default concern list has seven SD concerns. Set the cost your account actually charges. The status payload used here does not include a per-task charge, so successful tasks stay estimated and `units_confirmed` stays empty.

Daily caps use `QUOTA_TIMEZONE` (default UTC). A reservation is written before submission. Provider errors and local rejections release that task’s estimate. Success keeps it. Ambiguous submissions stay reserved so a possible charge is not forgotten.

## Experiment

Pipeline `sod-transform-1`:

- EXIF orientation, sRGB, Lanczos downscale to at most `NORMALIZE_LONG_SIDE`, no upscale, PNG encode.
- Exposure 0.9 and 1.1 in linear RGB after the IEC 61966-2-1 transfer.
- Channel gains 1.03/0.97 and 0.97/1.03 on red/blue, green unchanged. Not a Kelvin measurement.
- Left and right crops of 2% of width, equal windows, Lanczos back to the master size. Digital framing, not head rotation.

Capture checks (decode, size, one frontal face, blur, clipping, lighting balance) are local OpenCV/Pillow heuristics. They are not YouCam certification. A locally rejected variant is stored as a rejection and is not replaced with an easier transform.

`raw_score` deltas are variant minus baseline. UI scores are never copied into those deltas. Finite differences are reported for exposure and red-channel gain only when both endpoints have raw scores. Framing stays a pair of discrete changes.

Ranking formula `explicit-severity-match-v1`: priority-weighted severity over reviewer-confirmed mappings. With the documented direction, severity is `100 - raw_score`. Ties break by match, then same-currency price, then product id. Unknown mappings and missing ingredient lists are not guessed.

Labels:

- `recommendation_changed` — top suggestion changed in at least one valid variant, and coverage meets the configured minimum
- `stable_under_tested_transformations` — unchanged in n tested variants
- `insufficient_evidence` — no baseline, coverage below `MIN_VALID_VARIANTS`, or no eligible products

`MIN_VALID_VARIANTS` is an engineering setting, not a clinical cut-off. “Changed in m of n” is not a probability.

## Routes

Browser-session scoped. The bearer token is the random value stored in this browser, not a user account:

- `POST /v1/consents`, `GET /v1/me`
- `POST /v1/assets`, `GET /v1/assets/{id}`, `GET /v1/assets/{id}/content`
- `POST /v1/experiments/plan`, `POST /v1/experiments` (202 and a job id, `Idempotency-Key` supported)
- `GET /v1/experiments`, `GET /v1/experiments/{id}`, `GET /v1/experiments/{id}/report`
- `POST /v1/experiments/{id}/recaptures`, `POST /v1/experiments/{id}/reconcile`
- `DELETE /v1/experiments/{id}`, `DELETE /v1/account`
- `GET/POST /v1/products`, `POST /v1/products/{id}/confirm`
- `GET/POST /v1/guided-assets` (publish is limited to `OPERATOR_USER_IDS`)

`GET /v1/runtime` is public and contains no secrets. `POST /v1/webhooks/youcam` requires a valid Standard Webhooks signature. Unsigned bodies are refused.

There is no cross-user image cache. A new audit always enqueues new provider tasks.

## Retention, backup, recovery

`RETENTION_DAYS` (default 30) is enforced by a periodic worker job. It deletes finished experiments and their originals, variants, overlays, and score rows. Usage rows remain with the experiment id cleared so the daily cap still has a record. Deleting an account removes that person’s ledger too.

Limits you cannot ignore:

- YouCam documents processed results for about 24 hours and zip result URLs for about 2 hours. Overlays are copied into private storage when a URL is actually returned. A later deletion here does not delete the provider’s copy.
- Database backups are the Railway Postgres backup or PITR plan you enable. This app does not ship a second backup transport. Restore a backup, then run `alembic upgrade head` if the restored schema is older. Photograph bytes live in that same database when `STORAGE_BACKEND=database`.
- Worker crash: an expired lease requeues the job. A provider task id that was already stored is polled, not resubmitted. A submit that crashed before the task id was stored stays `needs_reconciliation`.
- Monitor `GET /ready` (database and worker heartbeat age) and worker `GET /health`. Alert on jobs in `dead` or experiments in `needs_reconciliation`.

## Tests

```bash
cd backend && pytest -q
```

`TEST_DATABASE_URL=postgresql+psycopg://...` enables the SKIP LOCKED claim and lease-recovery test. Other tests use SQLite and do not call YouCam. Synthetic images in those tests are not production data.

## Verification

See `docs/VERIFICATION.md`. Do not describe this deployment as production-verified until a live key has been used, a restart has kept a job, the six charts have been filled from that run, a guided run has made fresh calls, and tenant isolation and deletion have been checked against that deployment.
