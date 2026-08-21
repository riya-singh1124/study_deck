# Study Desk

A minimal shared-board study-card platform: users sign up, create **decks** of study **cards** (question, answer, code, equation), search across accessible content, and share decks with other users.

**Stack**
- **Backend:** FastAPI + JWT auth, backed by Supabase (Postgres) via `psycopg`
- **Frontend:** Vanilla JS + HTML + CSS, JWT stored in `localStorage`

Persistent state lives in Postgres (`users`, `decks`, `cards`, `deck_shares`). All access checks are enforced by SQL predicates in the API layer — see `DECK_VISIBLE_PREDICATE` in `backend/main.py`, which mirrors the previous `deck_visible_to` logic (owner OR shared-with OR public).

## Run locally

### 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Point at your Supabase / Postgres instance:
export DATABASE_URL="postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
# Optional overrides:
#   STUDY_DESK_SECRET       — JWT signing key (change in prod!)
#   STUDY_DESK_INIT_SCHEMA  — set to "0" to skip auto-running backend/schema.sql on startup
#   DB_POOL_MAX             — max pool size (default 10)

uvicorn backend.main:app --reload --port 8000
```

On first startup the backend applies `backend/schema.sql` (idempotent). You can also run it manually:

```bash
psql "$DATABASE_URL" -f backend/schema.sql
```

Interactive API docs: <http://localhost:8000/docs>

### 2. Frontend

Serve the `frontend/` directory with any static server:

```bash
cd frontend
python -m http.server 5500
```

Open <http://localhost:5500> in your browser.

If you host the backend on another URL, set it once from the browser console:

```js
localStorage.setItem("study_desk_api", "https://your-backend.example.com");
```

## API surface

| Method | Path                       | Auth | Description                         |
|--------|----------------------------|------|-------------------------------------|
| POST   | `/auth/signup`             | –    | Create account, returns JWT         |
| POST   | `/auth/login`              | –    | OAuth2 form login, returns JWT      |
| GET    | `/me`                      | ✅   | Current user                        |
| GET    | `/decks`                   | ✅   | Decks I own / shared with / public  |
| POST   | `/decks`                   | ✅   | Create deck                         |
| GET    | `/decks/{id}`              | ✅   | Get deck                            |
| PATCH  | `/decks/{id}`              | ✅   | Owner: update deck                  |
| DELETE | `/decks/{id}`              | ✅   | Owner: delete deck                  |
| POST   | `/decks/{id}/share`        | ✅   | Owner: share with another user      |
| GET    | `/decks/{id}/cards`        | ✅   | List cards                          |
| POST   | `/decks/{id}/cards`        | ✅   | Owner: add card                     |
| PATCH  | `/cards/{id}`              | ✅   | Owner: update card                  |
| DELETE | `/cards/{id}`              | ✅   | Owner: delete card                  |
| GET    | `/search?q=...`            | ✅   | Search accessible decks & cards     |

## Security notes

- Passwords hashed with **bcrypt** (`passlib`).
- Auth via **JWT** (HS256). Override `STUDY_DESK_SECRET` env var in production.
- CORS is wide-open for local dev — tighten `allow_origins` before deploying.
- The frontend never talks to the datastore directly; all access goes through the API which enforces ownership / sharing checks.

## Next session

- Replace bearer-token JWT with Supabase Auth (RLS-enabled) so the DB enforces `deck_visible_to` directly.
- Deploy backend (Fly.io / Render) and frontend (Vercel / Netlify).
