import os
import json
import re
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, field_validator
from google.genai import types

from app.agents import AGENTS, ensure_agent_directories, get_agent
from app.auth import (
    init_db, ensure_admin, authenticate, current_user, require_user,
    require_admin, has_agent_access, allowed_agents, list_users, create_user,
    update_user, delete_user, ALL_AGENT_IDS
)
from app.config import DOCUMENT_DIR, GENERATED_DIR, settings
from app.services.extractors import SUPPORTED
from app.services.generators import generate
from app.services.llm import LLMClient
from app.services.rag import RAGManager
from app.services.sharepoint import SharePointError, sharepoint


app = FastAPI(title=settings.app_name)

# React/Vite runs on port 5173 during development. Production is same-origin
# after `npm run build`, so the browser never needs a cross-origin API.
# Always permit the local Vite development origins. A CORS_ORIGINS value in
# .env can add production/frontend origins, but must not accidentally remove
# the local UI origin used by the Vite proxy.
configured_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()]
allowed_origins = list(dict.fromkeys(configured_origins + [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]))
allowed_hosts = [x.strip() for x in os.getenv(
    "ALLOWED_HOSTS", "localhost,127.0.0.1"
).split(",") if x.strip()]

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # FastAPI's generated Swagger/ReDoc HTML uses inline initialization
        # code and loads versioned assets from jsDelivr. Do not attach the
        # application's strict CSP to these generated documentation pages;
        # otherwise Swagger renders partially and Chrome reports CSP errors.
        # The application itself keeps the strict policy in the else branch.
        if request.url.path in {"/docs", "/docs/oauth2-redirect", "/redoc"}:
            pass
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self' http://localhost:5173 http://127.0.0.1:5173; "
                "font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

app.add_middleware(SecurityHeadersMiddleware)

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        _check_csrf(request)
        response = await call_next(request)
        _ensure_csrf(request, response)
        return response

app.add_middleware(CSRFMiddleware)

BASE_APP = Path(__file__).parent
# Signed, HttpOnly session cookie. In production SESSION_SECRET must be a long,
# random secret supplied through the environment/secret manager.
session_secret = settings.session_secret or os.getenv("SESSION_SECRET")
if not session_secret:
    raise RuntimeError("SESSION_SECRET must be configured; refusing to start with a default secret.")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="foundry_session",
    max_age=int(os.getenv("SESSION_MAX_AGE", str(60 * 60 * 8))),
    same_site=os.getenv("SESSION_SAME_SITE", "lax"),
    https_only=os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true",
)

ensure_agent_directories(DOCUMENT_DIR)
init_db()
ensure_admin(settings.admin_username, settings.admin_password)

rag = RAGManager(DOCUMENT_DIR)
llm = LLMClient()

if sharepoint.configured() and os.getenv("SHAREPOINT_AUTO_SYNC", "false").lower() == "true":
    for _agent_id in AGENTS:
        try:
            sharepoint.sync_agent(_agent_id)
            rag.rebuild(_agent_id)
        except Exception as _exc:
            print(f"SharePoint startup sync failed for {_agent_id}: {_exc}")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)




@app.post("/api/auth/login")
async def auth_login(request: Request, payload: LoginRequest):
    _check_login_rate_limit(request)
    user = authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password, or the account is disabled.")

    _clear_login_rate_limit(request)
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = user["role"]
    return {
        "ok": True,
        **user,
        "allowed_agents": allowed_agents(user["id"]),
    }


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
async def me(request: Request):
    user = require_user(request)
    return {
        **user,
        "allowed_agents": allowed_agents(user["id"]),
    }


class ChatRequest(BaseModel):
    agent_id: str
    question: str
    history: list[dict] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    agent_id: str
    title: str
    content: str
    kind: str


# Natural-language file-generation commands understood in chat.
# The actual document content comes from Gemini's response; these helpers
# only decide which output format the user requested and create the binary file.
_EXPORT_PATTERNS = [
    ("pdf", re.compile(r"\b(?:convert|export|save|download|generate|make|create)\b.*\bpdf\b|\bpdf\b.*\b(?:convert|export|save|download|generate|make|create)\b", re.I | re.S)),
    ("docx", re.compile(r"\b(?:convert|export|save|download|generate|make|create)\b.*\b(?:word|docx|document)\b|\b(?:word|docx)\b.*\b(?:convert|export|save|download|generate|make|create)\b", re.I | re.S)),
    ("pptx", re.compile(r"\b(?:convert|export|save|download|generate|make|create)\b.*\b(?:powerpoint|pptx|presentation|slides?)\b|\b(?:powerpoint|pptx|presentation|slides?)\b.*\b(?:convert|export|save|download|generate|make|create)\b", re.I | re.S)),
    ("xlsx", re.compile(r"\b(?:convert|export|save|download|generate|make|create)\b.*\b(?:excel|xlsx|spreadsheet)\b|\b(?:excel|xlsx|spreadsheet)\b.*\b(?:convert|export|save|download|generate|make|create)\b", re.I | re.S)),
]

def detect_export_kind(text: str):
    for kind, pattern in _EXPORT_PATTERNS:
        if pattern.search(text or ""):
            return kind
    return None

def latest_assistant_content(history):
    for message in reversed(history or []):
        if str(message.get("role", "")).lower() == "assistant":
            content = str(message.get("content", "")).strip()
            if content:
                return content
    return ""


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    role: str = "user"
    active: bool = True
    agent_ids: list[str] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value not in {"user", "admin"}:
            raise ValueError("Role must be user or admin.")
        return value


class UpdateUserRequest(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    role: str | None = None
    agent_ids: list[str] | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        if value is not None and value not in {"user", "admin"}:
            raise ValueError("Role must be user or admin.")
        return value


def _csrf_cookie_name():
    return "foundry_csrf"

def _ensure_csrf(request: Request, response):
    token = request.cookies.get(_csrf_cookie_name())
    if not token:
        token = uuid4().hex + uuid4().hex
        response.set_cookie(
            _csrf_cookie_name(), token, httponly=False, secure=os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true",
            samesite=os.getenv("SESSION_SAME_SITE", "lax"), max_age=60 * 60 * 8, path="/"
        )
    return token

def _check_csrf(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # Same-origin browser requests carry Origin. Reject cross-site state changes.
    # During local development React/Vite runs on :5173 and the API on :8000,
    # so the browser Origin is intentionally http://localhost:5173.
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins:
        raise HTTPException(403, "Cross-origin request rejected.")
    token = request.headers.get("x-csrf-token")
    cookie_token = request.cookies.get(_csrf_cookie_name())
    if not token or not cookie_token or token != cookie_token:
        raise HTTPException(403, "CSRF validation failed.")


_login_attempts: dict[str, list[float]] = {}

def _check_login_rate_limit(request: Request):
    import time
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    recent = [t for t in _login_attempts.get(ip, []) if now - t < 900]
    if len(recent) >= 8:
        raise HTTPException(429, "Too many login attempts. Try again later.")
    recent.append(now)
    _login_attempts[ip] = recent

def _clear_login_rate_limit(request: Request):
    ip = request.client.host if request.client else "unknown"
    _login_attempts.pop(ip, None)


@app.get("/api/agents")
async def list_agents(request: Request):
    user = require_user(request)
    result = []
    for agent_id, agent in AGENTS.items():
        if not has_agent_access(user["id"], agent_id):
            continue
        docs = list((DOCUMENT_DIR / agent_id).rglob("*"))
        result.append({
            "id": agent_id,
            **agent,
            "document_count": len([d for d in docs if d.is_file() and not d.name.startswith(".")]),
        })
    return result


@app.get("/api/agents/{agent_id}/documents")
async def list_documents(request: Request, agent_id: str):
    user = require_user(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    if not has_agent_access(user["id"], agent_id):
        raise HTTPException(403, "You do not have access to this agent.")

    folder = DOCUMENT_DIR / agent_id
    metadata = {}
    metadata_file = folder / ".sharepoint.json"
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8")).get("files", {})
        except Exception:
            metadata = {}

    result = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        rel = p.relative_to(folder).as_posix()
        info = metadata.get(rel, {})
        is_sharepoint = rel == "_sharepoint" or rel.startswith("_sharepoint/")
        result.append({
            "name": info.get("name", p.name),
            "path": rel,
            "size": p.stat().st_size,
            "web_url": info.get("web_url", ""),
            "source": "SharePoint" if is_sharepoint else "Local Upload",
        })
    return result


@app.get("/api/sharepoint/status")
async def sharepoint_status(request: Request):
    require_admin(request)
    return sharepoint.status()


@app.post("/api/agents/{agent_id}/sharepoint/sync")
async def sync_sharepoint_agent(request: Request, agent_id: str):
    require_admin(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        result = sharepoint.sync_agent(agent_id)
        store = rag.rebuild(agent_id)
        result["chunks"] = len(store.chunks)
        return {"ok": True, **result}
    except SharePointError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"SharePoint sync/index failed: {exc}") from exc


@app.post("/api/sharepoint/sync-all")
async def sync_all_sharepoint(request: Request):
    require_admin(request)
    if not sharepoint.configured():
        raise HTTPException(503, "SharePoint is not configured.")
    results = []
    for agent_id in AGENTS:
        try:
            result = sharepoint.sync_agent(agent_id)
            store = rag.rebuild(agent_id)
            result["chunks"] = len(store.chunks)
            results.append({"ok": True, **result})
        except Exception as exc:
            results.append({"ok": False, "agent_id": agent_id, "error": str(exc)})
    return {"ok": all(r.get("ok") for r in results), "results": results}


@app.post("/api/documents/upload")
async def upload_document(request: Request, agent_id: str, file: UploadFile = File(...)):
    # Local upload is available to authenticated users for agents they can access.
    # SharePoint remains a separate, read-only source and is never overwritten by
    # a local upload or vice versa.
    user = require_user(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    if not has_agent_access(user["id"], agent_id):
        raise HTTPException(403, "You do not have access to this agent.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, "Unsupported file type. Use PDF, DOCX, PPTX, XLSX, TXT, MD or CSV.")

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB.")

    safe_name = Path(file.filename or "").name
    if not safe_name or safe_name in {".", ".."} or safe_name.startswith("."):
        raise HTTPException(400, "Invalid filename.")

    destination = DOCUMENT_DIR / agent_id / safe_name
    # Do not allow a local upload to write into the reserved SharePoint mirror.
    if destination.parent.name == "_sharepoint":
        raise HTTPException(400, "Invalid upload location.")
    destination.write_bytes(content)

    try:
        store = rag.rebuild(agent_id)
    except Exception as exc:
        try:
            destination.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(500, f"Document saved, but indexing failed: {exc}") from exc

    return {
        "ok": True,
        "filename": safe_name,
        "agent_id": agent_id,
        "source": "Local Upload",
        "chunks": len(store.chunks),
        "message": "Document uploaded and indexed.",
    }


@app.post("/api/chat")
async def chat(request: Request, payload: ChatRequest):
    user = require_user(request)
    if not has_agent_access(user["id"], payload.agent_id):
        raise HTTPException(403, "You do not have access to this agent.")

    agent = get_agent(payload.agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    question = payload.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty.")

    # ---------------------------------------------------------------
    # Natural-language export from the chat.
    #
    # Example: "convert this to pdf", "make this a Word document",
    # "turn the answer into a PowerPoint", or "export this to Excel".
    # The content is the previous Gemini answer supplied in conversation
    # history. The binary PDF/DOCX/PPTX/XLSX is created server-side.
    # ---------------------------------------------------------------
    export_kind = detect_export_kind(question)
    if export_kind:
        content = latest_assistant_content(payload.history)
        if not content:
            raise HTTPException(400, "There is no previous assistant response to convert. Ask your question first, then say e.g. 'convert this to PDF'.")

        title = f"{agent['short_name']} — Gemini Response"
        try:
            output = generate(
                kind=export_kind,
                title=title,
                content=content,
                output_dir=GENERATED_DIR,
            )
            if output.exists():
                unique = f"{output.stem}_{uuid4().hex[:8]}{output.suffix}"
                new_path = output.with_name(unique)
                output.rename(new_path)
                output = new_path
        except Exception as exc:
            raise HTTPException(500, f"File generation failed: {exc}") from exc

        label = {
            "pdf": "PDF",
            "docx": "Word document",
            "pptx": "PowerPoint",
            "xlsx": "Excel",
        }[export_kind]

        return {
            "agent_id": payload.agent_id,
            "answer": f"Done — I converted the previous Gemini response to a {label}.\n\n[Download {label}](/api/generated/{output.name})",
            "sources": [],
            "source_links": {},
            "matches": [],
            "file": {
                "kind": export_kind,
                "filename": output.name,
                "download_url": f"/api/generated/{output.name}",
                "label": label,
            },
        }

    quick = llm.conversational(agent["name"], question)
    if quick is not None:
        return {"agent_id": payload.agent_id, "answer": quick, "sources": [], "matches": []}

    if not llm.configured:
        raise HTTPException(
            503,
            "Gemini is not configured on the server. Please contact the administrator."
        )

    store = rag.store(payload.agent_id)
    try:
        results = store.search(
            question,
            top_k_per_query=settings.retrieval_top_k_per_query,
            final_k=settings.final_context_chunks,
        )
        answer = llm.answer(agent["name"], question, results, payload.history)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    sources = []
    source_links = {}
    metadata_file = DOCUMENT_DIR / payload.agent_id / ".sharepoint.json"
    if metadata_file.exists():
        try:
            meta_files = json.loads(metadata_file.read_text(encoding="utf-8")).get("files", {})
            source_links = {}
            for rel, v in meta_files.items():
                url = v.get("web_url", "")
                if not url:
                    continue
                name = v.get("name", Path(rel).name)
                source_links[name] = url
                source_links[f"SharePoint / {rel.replace('_sharepoint/', '', 1)}"] = url
        except Exception:
            source_links = {}
    for r in results:
        if r["source"] not in sources:
            sources.append(r["source"])

    return {
        "agent_id": payload.agent_id,
        "answer": answer,
        "sources": sources,
        "source_links": source_links,
        "matches": [
            {
                "source": r["source"],
                "score": round(r["score"], 4),
                "semantic_score": round(r.get("semantic_score", 0), 4),
                "lexical_score": round(r.get("lexical_score", 0), 4),
                "exact_score": round(r.get("exact_score", 0), 4),
                "query_hits": r.get("query_hits", 0),
            }
            for r in results
        ],
    }


@app.get("/api/debug/search/{agent_id}")
async def debug_search(request: Request, agent_id: str, q: str):
    user = require_admin(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        results = rag.store(agent_id).search(q, top_k_per_query=8, final_k=10)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
    return {"query": q, "results": results}


@app.post("/api/agents/{agent_id}/reindex")
async def reindex_agent(request: Request, agent_id: str):
    require_admin(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    try:
        store = rag.rebuild(agent_id)
        return {"ok": True, "agent_id": agent_id, "chunks": len(store.chunks)}
    except Exception as exc:
        raise HTTPException(500, f"Reindex failed: {exc}") from exc


@app.get("/api/agents/{agent_id}/index-info")
async def index_info(request: Request, agent_id: str):
    user = require_user(request)
    if not get_agent(agent_id):
        raise HTTPException(404, "Agent not found")
    if not has_agent_access(user["id"], agent_id):
        raise HTTPException(403, "You do not have access to this agent.")

    store = rag.store(agent_id)
    return {
        "agent_id": agent_id,
        "documents": len([p for p in (DOCUMENT_DIR / agent_id).iterdir() if p.is_file()]),
        "chunks": len(store.chunks),
        "faiss_ready": store.index is not None,
        "gemini_configured": bool(settings.gemini_api_key),
    }


@app.get("/api/config/status")
async def config_status(request: Request):
    require_admin(request)
    key = settings.gemini_api_key.strip()
    env_file = Path(__file__).resolve().parent.parent / ".env"
    return {
        "gemini_configured": bool(key),
        "gemini_model": settings.gemini_model,
        "embedding_model": settings.local_embedding_model,
        "project_root": str(Path(__file__).resolve().parent.parent),
        "env_file_exists": env_file.exists(),
        "key_preview": (key[:6] + "..." + key[-4:]) if len(key) >= 10 else "",
        "message": (
            "Gemini key loaded successfully."
            if key else
            "Gemini key was not found. Put GEMINI_API_KEY=... in the project-root .env "
            "or set GEMINI_API_KEY in the PowerShell environment."
        ),
    }


@app.get("/api/gemini/test")
async def gemini_test(request: Request):
    require_admin(request)
    if not llm.configured:
        raise HTTPException(503, "GEMINI_API_KEY is not configured.")
    try:
        response = llm.client.models.generate_content(
            model=settings.gemini_model,
            contents="Reply with exactly: Gemini connection successful.",
            config=types.GenerateContentConfig(
                max_output_tokens=100,
            ),
        )
        parts = []
        try:
            for part in response.candidates[0].content.parts:
                text = getattr(part, "text", None)
                if text and not getattr(part, "thought", False):
                    parts.append(text)
        except (AttributeError, IndexError, TypeError):
            pass
        return {"ok": True, "model": settings.gemini_model, "response": "\n".join(parts).strip()}
    except Exception as exc:
        raise HTTPException(502, f"Gemini API call failed: {exc}") from exc


@app.get("/", response_class=HTMLResponse)
async def root():
    """Simple API landing page for opening the backend directly in a browser."""
    return HTMLResponse(
        """<!doctype html><html><head><title>Google Foundry API</title>"
        "<meta name="viewport" content="width=device-width,initial-scale=1">"
        "</head><body style="font-family:system-ui;max-width:720px;margin:60px auto;padding:0 20px">"
        "<h1>Google Foundry API</h1><p>FastAPI backend is running.</p>"
        "<ul><li><a href="/docs">Swagger UI / API Docs</a></li>"
        "<li><a href="/redoc">ReDoc</a></li><li><a href="/health">Health</a></li></ul>"
        "</body></html>"""
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "gemini_configured": bool(settings.gemini_api_key),
        "gemini_model": settings.gemini_model,
        "embedding_model": settings.local_embedding_model,
        "faiss": True,
        "hybrid_retrieval": True,
        "multi_query": True,
    }


@app.post("/api/generate")
async def generate_file(request: Request, payload: GenerateRequest):
    user = require_user(request)
    if not has_agent_access(user["id"], payload.agent_id):
        raise HTTPException(403, "You do not have access to this agent.")

    kind = payload.kind.lower()
    if kind not in {"pdf", "docx", "pptx", "xlsx"}:
        raise HTTPException(400, "Use pdf, docx, pptx or xlsx.")

    output = generate(
        kind=kind,
        title=payload.title,
        content=payload.content,
        output_dir=GENERATED_DIR
    )
    if output.exists():
        unique = f"{output.stem}_{uuid4().hex[:8]}{output.suffix}"
        new_path = output.with_name(unique)
        output.rename(new_path)
        output = new_path

    return {"ok": True, "filename": output.name, "download_url": f"/api/generated/{output.name}"}


@app.get("/api/generated/{filename}")
async def download_generated(request: Request, filename: str):
    require_user(request)
    path = GENERATED_DIR / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Generated file not found.")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


# ---------------- Admin user management ----------------

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    require_admin(request)
    return list_users()


@app.post("/api/admin/users")
async def admin_create_user(request: Request, payload: CreateUserRequest):
    require_admin(request)
    unknown_agents = sorted(set(payload.agent_ids) - set(ALL_AGENT_IDS))
    if unknown_agents:
        raise HTTPException(400, f"Unknown agent IDs: {', '.join(unknown_agents)}")
    try:
        user = create_user(
            payload.username,
            payload.password,
            payload.role,
            payload.active,
            payload.agent_ids,
        )
        return {"ok": True, "user": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(request: Request, user_id: int, payload: UpdateUserRequest):
    admin = require_admin(request)
    if user_id == admin["id"] and payload.active is False:
        raise HTTPException(400, "You cannot disable your own account.")

    if payload.agent_ids is not None:
        unknown_agents = sorted(set(payload.agent_ids) - set(ALL_AGENT_IDS))
        if unknown_agents:
            raise HTTPException(400, f"Unknown agent IDs: {', '.join(unknown_agents)}")
    try:
        user = update_user(
            user_id,
            active=payload.active,
            password=payload.password,
            role=payload.role,
            agent_ids=payload.agent_ids,
        )
        return {"ok": True, "user": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(request: Request, user_id: int):
    admin = require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot delete your own account.")
    if not current_user(request):
        raise HTTPException(401, "Authentication required.")
    delete_user(user_id)
    return {"ok": True}


@app.get("/api/admin/agents")
async def admin_agents(request: Request):
    require_admin(request)
    return [
        {"id": agent_id, **agent}
        for agent_id, agent in AGENTS.items()
    ]


# Production SPA: serve the compiled React app from the same FastAPI origin.
# API/auth routes above always take precedence.
SPA_DIST = BASE_APP / "dist"
if SPA_DIST.exists():
    assets_dir = SPA_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="react-assets")

    @app.get("/{path:path}", response_class=HTMLResponse)
    async def react_spa(path: str):
        if path.startswith(("api/", "static/", "assets/")):
            raise HTTPException(404, "Not found")
        index = SPA_DIST / "index.html"
        return HTMLResponse(index.read_text(encoding="utf-8"))
