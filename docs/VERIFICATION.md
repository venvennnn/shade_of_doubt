# Verification notes

Checked through 2 November 2026, 12:35 AM (Asia/Calcutta). This application is **not production-verified**.

## Live YouCam

No `YOUCAM_API_KEY` was available in the build environment. No task was submitted. There is no redacted task id, measured provider latency, or observed unit charge to record. The API returns `youcam_unconfigured` or `pricing_unconfigured` instead of substituting scores. Do not treat the test suite as a live provider run.

Official references used while writing the adapter:

- https://docs.perfectcorp.com/reference/ai_skin_analysis/v2.1
- Task status schema, including `raw_score`, `ui_score`, and `mask_urls`
- Integration guide file registration: `POST /s2s/v2.0/file`, then PUT, then `src_file_id`
- Unit table: SD 5–8 concerns documented as 12 units; HD 5–8 as 16. The cost is still a required setting.
- Score direction: a higher raw score is documented as a healthier-looking result, not a larger physical trait.
- Result retention about 24 hours; zip URLs about 2 hours. Polling example about every 10 seconds. Units are documented as consumed on success only.

## What was run

- `pytest` in `backend`: 24 passed, and the Postgres-only queue test skipped when `TEST_DATABASE_URL` is unset. A separate run of `tests/test_queue_postgres.py` against local Postgres 16 passed (SKIP LOCKED claim and expired-lease recovery).
- `alembic upgrade head` applied `20261101_0001` on Postgres 16.
- `npm run build` in `frontend` succeeded on Next.js 15.5.28.
- Docker Compose was not executed here because Docker was not available. The manifests are in `docker-compose.yml` and `render.yaml`.
- Browser, signed in with a local test token and no YouCam key: Capture shows the missing-key and empty-unit-cost configuration errors. Requesting the plan returns `youcam_unconfigured` with the text “YouCam credentials are not configured, so no analysis task can be submitted. Set YOUCAM_API_KEY from the YouCam API console. The API will not substitute saved or example scores.” Audit, History, and Compare recaptures stay empty. No chart, product, or score is drawn. At a narrow window the brand sits on its own row and “Compare recaptures” stays on one line.

## Still required before a production label

1. A consented live baseline and six variants, with redacted task ids, observed latency, and the account’s unit ledger.
2. A worker restart while a job is leased, showing the job resumes without a second paid create when the task id is already stored.
3. All six charts populated only from that run.
4. A guided run that submits new tasks, or a recorded refusal because no rights-cleared guided photograph is published.
5. Two accounts proving one cannot read the other’s photographs, and a deletion that removes stored objects.
