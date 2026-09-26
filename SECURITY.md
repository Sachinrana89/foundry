# Production security model

## Authentication

The browser uses a FastAPI server-side session rather than storing bearer tokens
in localStorage. The session cookie is HttpOnly, SameSite=Lax, and must be Secure
in production. `SESSION_SECRET` is mandatory; the application refuses to start
with a default secret.

For an enterprise rollout, put the portal behind your corporate OIDC/SAML
identity provider (Google Workspace/Cloud Identity, Microsoft Entra ID, Okta,
etc.) and map the IdP identity to the existing application user record. Keep the
local password account only as a controlled bootstrap/break-glass administrator.

## Authorization

Authorization is enforced on the server, not just hidden in React:

- `admin` is required for user administration, document upload, reindexing,
  configuration diagnostics, and search debugging.
- Each normal user is restricted to their assigned `agent_ids`.
- Every agent-scoped endpoint checks `has_agent_access(...)`.
- Generated files require an authenticated session.
- React route guards are UX only; they are not security boundaries.

## Browser protections

- CSRF token + Origin validation for state-changing requests.
- Trusted Host validation.
- CSP, HSTS (HTTPS), X-Frame-Options, Referrer-Policy and Permissions-Policy.
- Same-origin production deployment avoids exposing the API to arbitrary browser
  origins.

## Operational controls before go-live

1. Put the service behind HTTPS and a managed reverse proxy/load balancer.
2. Store `SESSION_SECRET`, admin bootstrap credentials and `GEMINI_API_KEY` in a
   cloud secret manager, not in Git or the image.
3. Add IdP SSO + MFA and disable ordinary password login for normal users.
4. Add centralized audit logs for login, logout, agent access, uploads, reindex,
   admin changes and generated-file access.
5. Add proxy/WAF rate limiting on `/api/auth/login`, `/api/chat` and upload routes.
6. Back up the application database and document/index storage.
7. Run dependency, SAST, container and DAST scans before exposing the service.
8. Set `ALLOWED_HOSTS` and `CORS_ORIGINS` to the exact production hostname(s).
