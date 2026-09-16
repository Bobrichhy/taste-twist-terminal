# Taste Twist Terminal — standalone edition

A live POS, inventory, and stock-ledger system for Taste Twist Grills & Shawarma, running as
your own website — no Claude account needed to use it. This replaces the earlier Claude
Artifact version with a real backend (Node.js + Postgres) so any of your three branches can
open it in Chrome and see the same live data.

## What's in this repo

- `server/` — the backend (Express + Postgres). Serves the API and the frontend.
- `public/index.html` — the entire frontend (one file: HTML, CSS, and JS).
- `taste_twist_stock_manager.py` — the original desktop (Tkinter) version. No longer used, kept for reference.

## Deploying to Render (free tier)

You said you have a GitHub account already — these steps take you from that to a live URL.

### 1. Push this project to GitHub

```bash
cd /home/richard/taste_twist_stock_manager
git add -A
git commit -m "Standalone Taste Twist Terminal (Express + Postgres)"
```
Then create a new **empty** repository on github.com (no README/license — you already have files),
and push:
```bash
git remote add origin https://github.com/Bobrichhy/<your-repo-name>.git
git branch -M main
git push -u origin main
```

### 2. Create a free Postgres database on Render

1. Go to [render.com](https://render.com) and sign up (free, no card needed).
2. **New +** → **PostgreSQL**. Give it any name. Free plan.
3. Once created, copy the **Internal Database URL** (starts with `postgres://`) — you'll need it next.
   - Note: Render's *free* Postgres is deleted after 90 days unless you upgrade. For a business
     system you rely on daily, either upgrade to a paid Postgres later, or point `DATABASE_URL`
     at a database from [neon.tech](https://neon.tech) instead (also free, no 90-day limit).
     Either works — the app doesn't care which Postgres it talks to.

### 3. Create the web service

1. **New +** → **Web Service** → connect your GitHub repo.
2. Root directory: `server`
3. Build command: `npm install`
4. Start command: `npm start`
5. Add an environment variable: `DATABASE_URL` = the connection string from step 2.
6. Deploy.

Render gives you a URL like `https://taste-twist-terminal.onrender.com` — that's the link every
branch opens in their browser. The first time it starts, it creates all the tables and seeds
your items, menu, branches, and logins automatically (same accounts as before: `master`/`admin123`,
`staff`/`1234`, `staff_kilo`/`1234`, `staff_arepo`/`1234` — change these in Settings once you're in).

### Running it locally first (optional, recommended)

```bash
cd server
cp .env.example .env
# edit .env: set DATABASE_URL to any Postgres you have access to
npm install
npm start
```
Then open `http://localhost:3000`.

## What changed from the Claude Artifact version

- **Real accounts, real hosting** — no Claude sign-in required; anyone with the link can use it.
- **Passwords are now hashed** (bcrypt) instead of stored in plain text — a genuine security
  upgrade needed once this left Claude's sandboxed environment and became reachable on the
  open internet.
- **Checkout, purchases, transfers, and voids now run as single database transactions on the
  server**, with row locking — closes a race-condition gap that existed in the read-then-write
  pattern the Artifact version used.
- Live updates across branches now use a simple "something changed, refetch" signal (Server-Sent
  Events) instead of Firestore-style live listeners — functionally the same experience.

## Known limitation carried over

The shared database still holds everything in a handful of tables with no per-business
isolation — this is built for **Taste Twist only**, not as a product other businesses could
sign up for. That would need real multi-tenancy, which is a separate, larger project.
