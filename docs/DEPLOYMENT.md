# Deployment

```
Browser ──► GitHub Pages (static React app, HashRouter)      free
   │
   └──► HTTPS ──► Backend (FastAPI, 1 worker + SQLite on a persistent disk) ──► FreeModel.in
```

GitHub Pages cannot run Python, so the backend is hosted separately. The static site works on its own in **DEMO mode** (no backend, no key).

## 1. Frontend → GitHub Pages (already configured)
`.github/workflows/pages.yml` builds `frontend/` on every push to `main` and publishes it → `https://<user>.github.io/anvaya/`.
To connect it to your backend: *Settings → Secrets and variables → Actions → Variables → `ANVAYA_API_URL` = `https://your-backend`* and re-run the workflow
(or users can paste the URL in the "Backend not connected" screen; it is stored in their browser only). No secret is ever put in the frontend.

## 2. Backend options (evaluated against what ANVAYA needs)
Needs: a long-lived process (background jobs + SSE streams), a **persistent disk** (SQLite + uploads), HTTPS, env-var secrets, ~512 MB RAM. No separate worker/queue/DB is required.

| Option | Fit | Notes |
|---|---|---|
| **Render** (Docker web service + 1 GB disk) | Good — `render.yaml` included | Persistent disks need a paid instance; free instances sleep and have no disk (data would be lost). Verify current pricing. |
| **Railway** | Good | Dockerfile deploy + a Volume at `/data`; usage-based billing. Set the same env vars. |
| **VPS** (Hetzner/DO, ~1–2 GB) | Best value, most control | `docker run -d -p 8000:8000 -v anvaya:/data --env-file .env ghcr.io/…` behind Caddy/nginx for TLS. You own patching/backups. |

SQLite + in-process jobs mean **one instance, one worker**. To scale out later, swap `db.py` for Postgres and move jobs to a queue.

### Render (recommended quick path)
1. Dashboard → New → **Blueprint** → select this repo (uses `render.yaml`).
2. Paste `FREEMODEL_API_KEY` when prompted (stored only in Render).
3. Copy the service URL → set it as the `ANVAYA_API_URL` Pages variable → re-run the Pages workflow.
4. Open the site → Projects → create the first account (it becomes the admin who can change model assignments).

### Required / useful environment variables
`FREEMODEL_API_KEY` (secret) · `ANVAYA_CORS_ORIGINS` (your Pages origin) · `ANVAYA_DATA_DIR=/data` · `ANVAYA_ALLOW_REGISTRATION=false` once your accounts exist ·
`ANVAYA_ADMIN_EMAIL` · `ANVAYA_MAX_LLM_JOBS_PER_DAY` (default 25/user) · `ANVAYA_RPM` (default 50) · `ANVAYA_MAX_AGENTS` / `ANVAYA_MAX_ROUNDS`.

> Public deployments share one API key: keep the per-user daily LLM quota low (or registration closed) so strangers cannot spend your token allowance.

## 3. Local development
```bash
cp .env.example .env           # add FREEMODEL_API_KEY
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn anvaya.main:app --port 8000
cd frontend && npm ci && npm run dev    # http://localhost:5173 , talks to :8000 automatically
```
