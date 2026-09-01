# Frontend

**The chat client is not in this directory.** It lives at
`backend/app/static/index.html` and is served by the API at `GET /`.

## Why it lives in the backend

It is a single self-contained HTML file — one input, one message list, one
`fetch` to `POST /chat` — so a framework and a build step would cost more than
they return. Serving it from the API also means the whole app is still one
`docker compose up`, with no second process and no CORS.

Putting it here instead is not free. `docker-compose.yml` sets `build: ./backend`,
so Docker's build context is `backend/` and a `COPY` cannot reach outside it —
shipping a file from `frontend/` in the image would mean changing the build
context to the repo root and rewriting every `COPY` path in the Dockerfile. The
compose file also mounts only `./backend` and `./inbox`, so this directory is not
visible to the running container. Under `backend/app/static/`, `COPY . .` picks
the file up for free and the existing bind mount live-reloads it.

## What this directory is reserved for

The Phase 3 React dashboard, if it happens: net worth over time, spend by
category, and asset allocation charts. That *is* a separate build artifact with
its own toolchain, and it earns a top-level directory in a way one HTML file does
not.

**Blocked on Node.** This machine has Node v16.15.0; Vite 5+ requires Node 18+.
Upgrade first (`brew install node@22` or nvm), then scaffold:

```bash
npm create vite@latest . -- --template react-ts
npm install recharts
```

`backend/app/main.py` still has `CORSMiddleware` allowing `http://localhost:5173`
(Vite's default) for that eventuality. It does nothing today — the current client
is same-origin.

Endpoints to build against — see `http://localhost:8000/docs`:

| View | Endpoint |
|---|---|
| Net worth chart | `GET /net-worth` (returns a dated series; note `includes_cash: false`) |
| Allocation pie | `GET /allocation` |
| Spend by category | `GET /transactions?category=…` |
| Chat panel | `POST /chat` |
