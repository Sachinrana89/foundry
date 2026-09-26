# Local MiniLM embeddings

The RAG index now uses a local SentenceTransformers MiniLM model. Gemini is **not** used to create document or query embeddings.

## Configure your local model

In the project `.env`, set:

```env
LOCAL_EMBEDDING_MODEL=C:\models\all-MiniLM-L6-v2
```

Use the actual folder containing your local MiniLM model. If the model is already available under that path, no internet download is required by SentenceTransformers.

If `LOCAL_EMBEDDING_MODEL` is not set, the default is `all-MiniLM-L6-v2`; SentenceTransformers may attempt to download it.

## Install

```powershell
pip install -r requirements.txt
```

## Rebuild the index

Existing FAISS indexes made with Gemini embeddings are incompatible with MiniLM. The application detects the embedding model/dimension change and rebuilds the index. You can also trigger the existing agent rebuild operation from the application.

MiniLM query embeddings and document embeddings use the same local model and normalized vectors.

Gemini remains available for the LLM and optional multi-query expansion; it is not used for embeddings.
