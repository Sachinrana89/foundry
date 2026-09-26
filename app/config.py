from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Load the project-root .env explicitly, regardless of the directory from which
# uvicorn was started. Do not override an already-set process environment variable.
load_dotenv(BASE_DIR / ".env", override=False)
# Also allow a .env in the current working directory as a convenience.
load_dotenv(Path.cwd() / ".env", override=False)

class Settings(BaseSettings):
    app_name: str = "Enterprise AI Agent Portal"

    # Pydantic will read GEMINI_API_KEY from the process environment and the
    # project-root .env. GOOGLE_API_KEY is accepted as a fallback below.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    # Local SentenceTransformers model used for RAG embeddings.
    # Example Windows path: C:\models\all-MiniLM-L6-v2
    local_embedding_model: str = "all-MiniLM-L6-v2"

    session_secret: str = ""
    admin_username: str = "admin"
    admin_password: str = ""

    embedding_dimension: int = 384  # all-MiniLM-L6-v2
    max_upload_mb: int = 25

    # SharePoint / Microsoft Graph (read-only source of truth)
    sharepoint_enabled: bool = False
    sharepoint_tenant_id: str = ""
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_site_url: str = ""
    sharepoint_drive_name: str = "Documents"
    sharepoint_agent_paths: dict = {}
    multi_query_count: int = 4
    retrieval_top_k_per_query: int = 10
    final_context_chunks: int = 10

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

# Parse the agent-to-SharePoint-folder mapping from JSON in .env.
import json as _json
_raw_sp_paths = os.getenv("SHAREPOINT_AGENT_PATHS", "{}").strip()
try:
    settings.sharepoint_agent_paths = _json.loads(_raw_sp_paths) if _raw_sp_paths else {}
    if not isinstance(settings.sharepoint_agent_paths, dict):
        settings.sharepoint_agent_paths = {}
except Exception:
    settings.sharepoint_agent_paths = {}

# Google documents both GEMINI_API_KEY and GOOGLE_API_KEY for Gemini API auth.
# Prefer GEMINI_API_KEY, then GOOGLE_API_KEY.
if not settings.gemini_api_key:
    settings.gemini_api_key = (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )

# If pydantic did not pick up the .env for any reason, read it explicitly once more.
if not settings.gemini_api_key:
    from dotenv import dotenv_values
    for env_path in (BASE_DIR / ".env", Path.cwd() / ".env"):
        if env_path.exists():
            values = dotenv_values(env_path)
            settings.gemini_api_key = (
                str(values.get("GEMINI_API_KEY") or "").strip()
                or str(values.get("GOOGLE_API_KEY") or "").strip()
            )
            if settings.gemini_api_key:
                break

DATA_DIR = BASE_DIR / "data"
DOCUMENT_DIR = DATA_DIR / "documents"
INDEX_DIR = DATA_DIR / "indexes"
GENERATED_DIR = BASE_DIR / "generated"

for path in (DOCUMENT_DIR, INDEX_DIR, GENERATED_DIR):
    path.mkdir(parents=True, exist_ok=True)
