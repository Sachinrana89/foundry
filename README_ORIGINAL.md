# Enterprise AI Agent Portal — Gemini + FAISS + Hybrid RAG v8

This version is designed for document-grounded conversational agents.

## What is fixed

- Gemini is the final answer generator; retrieved passages are never shown as the answer.
- FAISS semantic search uses Gemini embeddings.
- Gemini generates multiple search queries.
- Exact/lexical search catches IDs, percentages, acronyms, keys and exact phrases.
- PDF extraction preserves page numbers.
- DOCX/PPTX/XLSX extraction preserves locations.
- Chunks prefer sentence/paragraph boundaries instead of cutting arbitrary text.
- Conversation history supports follow-up questions.
- Greetings and capability questions behave conversationally without unnecessary document search.
- Reindex and index diagnostic endpoints are included.
- No scikit-learn dependency.

## Install

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

Create `.env`:

```env
GEMINI_API_KEY=YOUR_REAL_KEY
GEMINI_MODEL=gemini-3.6-flash
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
```

Run:

```powershell
uvicorn app.main:app --reload
```

## Verify

Open `/health`.

Expected:

```json
{"gemini_configured": true, "faiss": true, "hybrid_retrieval": true, "multi_query": true}
```

Open `/api/gemini/test` to test the Gemini generation API.

Open `/api/agents/smart-center/index-info` to see document/chunk/index status.

If documents were uploaded before a code/model change, use:

```text
POST /api/agents/{agent_id}/reindex
```

## RAG pipeline

User question → conversation handling → Gemini multi-query → Gemini embeddings → FAISS → exact/lexical retrieval → result fusion → Gemini answer → source citation.

Gemini Embedding 2 uses the recommended asymmetric retrieval format: `task: search result | query: ...` for queries and `title: ... | text: ...` for documents.

For scanned PDFs, the next production enhancement is direct Gemini PDF/OCR ingestion or a dedicated OCR pipeline. The current text extraction works best for PDFs with an embedded text layer.


## Authentication and restricted access

This version includes application-level authentication backed by SQLite.

### First-time setup

Set these values in `.env` before starting the server:

```env
SESSION_SECRET=use-a-long-random-secret
ADMIN_USERNAME=admin
ADMIN_PASSWORD=ChangeMe123!
```

On first startup, the configured administrator is created automatically and is granted access to all four agents.

**Change the example admin password before using this outside local development.**

### Roles

- **Administrator**: can access all agents, upload/re-index documents, generate files, and manage users.
- **User**: can only access the agents assigned by an administrator. Users can chat and generate files, but cannot upload or re-index repository documents.

Open **User management** from the top-right menu after signing in as an administrator.

### Security notes

This is suitable as a local/internal prototype. For production enterprise deployment, put the application behind HTTPS and an enterprise identity provider (for example Microsoft Entra ID / Google Cloud Identity), use secure secret storage, set `https_only=True` for the session cookie, and add audit logging/SSO/MFA.


## Agent repositories

The portal includes seven restricted agent repositories:

1. Smart Center (`smart-center`)
2. Google Aarambh (`google-aarambh`)
3. TCS Google Capabilities (`google-capabilities`)
4. TCS Google COE Repository Agents (`coe-repository`)
5. Case Studies (`case-studies`)
6. Deal Repository / Solutions (`deal-repository-solutions`)
7. Learning and Talent Development (`learning-talent-development`)

Administrators automatically have access to all seven. Normal users only see the agents assigned to them in User Management. Existing normal users are not automatically granted the three new repositories; an administrator must explicitly assign them.
