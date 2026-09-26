# Google Foundry React Enterprise AI Agent Portal

This package uses a React/Vite frontend with the FastAPI/agent/RAG backend and production security middleware. The legacy Jinja/HTML template UI has been removed.

## Local development

### 1. Configure environment
Copy `.env.example` to `.env` and set:
- `GEMINI_API_KEY`
- `SESSION_SECRET` (generate a long random value)
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD` (12+ characters)

### 2. Python backend

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend_main_react:app --reload --host 127.0.0.1 --port 8000
```

### 3. React frontend (development)

In another terminal:

```powershell
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

## Production / single URL

```powershell
npm install
npm run build
uvicorn backend_main_react:app --host 0.0.0.0 --port 8000
```

The FastAPI process serves the compiled React app from `dist/`.

For public deployment, put HTTPS/WAF/load balancing in front of the app and set:
- `SESSION_HTTPS_ONLY=true`
- `ALLOWED_HOSTS` to the actual hostname(s)
- `CORS_ORIGINS` to the actual frontend origin(s), if separate
- a strong `SESSION_SECRET`
- secrets via your cloud secret manager rather than `.env`

## Authentication

The application uses server-side signed sessions, CSRF protection, login throttling, role-based authorization, and per-agent authorization. Admins can manage users and agent access.

For enterprise public access, prefer an external OIDC/SAML identity provider with MFA (Google Workspace/Cloud Identity, Microsoft Entra ID, Okta, etc.) and place the app behind a WAF/reverse proxy.

## Important

No real `.env` or existing `auth.db` is shipped in this production package. A fresh database is created on first startup and the configured admin is created from environment variables.

## Local React development

Run the API on `127.0.0.1:8000` and Vite on `localhost:5173`. The backend explicitly permits both local Vite origins so the CSRF check works through the Vite `/api` proxy. If you set `CORS_ORIGINS` in `.env`, it is additive for local development.

```powershell
uvicorn backend_main_react:app --reload --host 127.0.0.1 --port 8000
npm run dev
```

## SharePoint-only knowledge source

The React portal can use SharePoint Online as the only document source. Local browser uploads are disabled when this build is used; administrators sync each agent from its configured SharePoint folder and the existing Gemini/FAISS RAG pipeline indexes the mirrored files.

### Microsoft Entra / Graph setup

1. Register an application in Microsoft Entra ID.
2. Add Microsoft Graph **Application** permission `Sites.Selected` and grant admin consent. `Sites.Selected` is preferred over tenant-wide `Sites.Read.All` because it lets the app be explicitly assigned to only the SharePoint site it needs.
3. Create a client secret (or, preferably for production, use a certificate/federated credential).
4. Grant the application **Read** access to the target SharePoint site.
5. Put the tenant ID, client ID, secret, site URL and library/folder mapping in `.env`.
6. Start the app and sign in as the local administrator.
7. Open an agent and click **Sync SharePoint**. The files are downloaded to the server only as an indexing cache; SharePoint remains the source of truth.

Example:

```env
SHAREPOINT_ENABLED=true
SHAREPOINT_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SHAREPOINT_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
SHAREPOINT_CLIENT_SECRET=your-secret
SHAREPOINT_SITE_URL=https://contoso.sharepoint.com/sites/GoogleFoundry
SHAREPOINT_DRIVE_NAME=Documents
SHAREPOINT_AGENT_PATHS={"smart-center":"Smart Center","google-aarambh":"Google Aarambh","google-capabilities":"Google Capabilities","coe-repository":"COE Repository","case-studies":"Case Studies","deal-repository-solutions":"Deal Repository","learning-talent-development":"Learning & Talent Development"}
SHAREPOINT_AUTO_SYNC=false
```

The connector uses Microsoft Graph app-only authentication. It is read-only and does not upload, modify, or delete SharePoint content. Graph's `Sites.Selected` permission is designed to restrict an app to selected site collections rather than all SharePoint sites.

## Node.js compatibility

This project is pinned to the Vite 6 toolchain so it works with Node.js 18 as well as newer LTS releases. If you previously installed dependencies with a newer Vite release, remove `node_modules` and `package-lock.json` and run `npm install` again.
# foundry
