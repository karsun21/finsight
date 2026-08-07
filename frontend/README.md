# Frontend (Phase 3 — not started)

React + TypeScript dashboard: net worth over time, spend by category, asset
allocation, and a chat panel against `POST /chat`.

**Blocked on Node.** This machine has Node v16.15.0; Vite 5+ requires Node 18+.
Upgrade first (`brew install node@22` or nvm), then scaffold:

```bash
npm create vite@latest . -- --template react-ts
npm install recharts
```

The API is already CORS-enabled for `http://localhost:5173` (Vite's default) in
`backend/app/main.py`.

Endpoints to build against — see `http://localhost:8000/docs`:

| View | Endpoint |
|---|---|
| Net worth chart | `GET /net-worth` (returns a dated series; note `includes_cash: false`) |
| Allocation pie | `GET /allocation` |
| Spend by category | `GET /transactions?category=…` |
| Chat panel | `POST /chat` |
