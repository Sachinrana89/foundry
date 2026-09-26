# Go-live deployment

The React UI is now the primary frontend. In production it can be built into
`dist/` and served by the same FastAPI origin, which keeps session cookies and
CSRF protection simple.

## Local production smoke test

```bash
npm install
npm run build
```

Then place the existing application `app/` package, data directories and its
normal Python dependencies beside `backend_main_react.py`, configure `.env`, and
run:

```bash
uvicorn backend_main_react:app --host 0.0.0.0 --port 8000 --proxy-headers
```

## Recommended cloud topology

Browser → HTTPS Load Balancer / WAF → FastAPI container → persistent DB + document
storage + Gemini API.

Use a managed identity provider for SSO/MFA and a managed secret store. For a
multi-instance deployment, use a shared database and shared persistent storage;
replace any in-memory operational state with shared infrastructure.

## Important

This package is deployable but cannot publish itself to your cloud account. A
real live URL requires your cloud/project credentials, domain, DNS and secret
manager configuration.
