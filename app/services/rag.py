from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List
from collections import Counter
import hashlib
import json
import math
import re

import faiss
import numpy as np
from google import genai
from google.genai import types
from sentence_transformers import SentenceTransformer

from app.config import settings, INDEX_DIR
from .extractors import extract_sections


STOPWORDS = {
    "a","an","the","is","are","was","were","be","been","being",
    "of","to","in","on","for","from","with","and","or","as","at",
    "by","this","that","these","those","it","its","what","which",
    "who","when","where","how","why","can","could","should","would",
    "do","does","did","about","please","tell","me","give","explain",
    "according","document","documents","policy","information"
}


@dataclass
class Chunk:
    text: str
    source: str
    location: str
    index: int


class LocalMiniLMHybridFAISS:
    """Production-oriented starter RAG:
    - page/location-aware extraction
    - Local MiniLM embeddings + FAISS
    - exact phrase/key retrieval
    - lexical retrieval
    - Gemini multi-query expansion
    - result fusion
    """

    def __init__(self, agent_id: str, documents_dir: Path):
        self.agent_id = agent_id
        self.documents_dir = documents_dir
        self.index_path = INDEX_DIR / f"{agent_id}.faiss"
        self.meta_path = INDEX_DIR / f"{agent_id}.json"
        self.manifest_path = INDEX_DIR / f"{agent_id}.manifest.json"
        self.chunks: List[Chunk] = []
        self.index = None
        # Embeddings are always produced locally with MiniLM. Gemini is optional
        # and is used only for query expansion / generation elsewhere.
        self.embedding_model_path = settings.local_embedding_model
        self.embedding_model = SentenceTransformer(self.embedding_model_path)
        self.embedding_dimension = self.embedding_model.get_sentence_embedding_dimension()
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None
        self.load()

    @staticmethod
    def normalize(value: str) -> str:
        value = value.lower().replace("–", "-").replace("—", "-")
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    @staticmethod
    def tokens(value: str):
        return re.findall(r"[a-z0-9][a-z0-9%_.:/-]*", value.lower())

    @classmethod
    def meaningful_tokens(cls, value: str):
        return [t for t in cls.tokens(value) if t not in STOPWORDS and (len(t) > 1 or any(c.isdigit() for c in t))]

    def manifest(self):
        items = []
        for path in sorted(self.documents_dir.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                rel = path.relative_to(self.documents_dir).as_posix()
                s = path.stat()
                items.append((rel, s.st_size, s.st_mtime_ns))
        items.append(("embedding_model", str(self.embedding_model_path)))
        items.append(("dimension", self.embedding_dimension))
        return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()

    def _split_section(self, text: str, size=1100, overlap=160):
        # Prefer sentence/paragraph boundaries. Never cut a percentage/key away
        # from its surrounding sentence merely to hit a character count.
        text = re.sub(r"[ \t]+", " ", text).strip()
        if not text:
            return []
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z0-9])", text) if p.strip()]
        chunks = []
        current = ""
        for para in paragraphs:
            if not current:
                current = para
            elif len(current) + 1 + len(para) <= size:
                current += " " + para
            else:
                chunks.append(current.strip())
                tail = current[-overlap:] if overlap else ""
                current = (tail + " " + para).strip()
                if len(current) > size * 1.4:
                    chunks.append(current[:size].strip())
                    current = current[size-overlap:].strip()
        if current:
            chunks.append(current.strip())
        return chunks

    def build_chunks(self):
        chunks = []
        for path in sorted(self.documents_dir.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                sections = extract_sections(path)
            except Exception:
                continue
            idx = 0
            relative = path.relative_to(self.documents_dir).as_posix()
            if relative.startswith("_sharepoint/"):
                source_name = f"SharePoint / {relative[len('_sharepoint/'):]}"
            else:
                source_name = f"Local Upload / {relative}"
            for section in sections:
                for part in self._split_section(section["text"]):
                    chunks.append(Chunk(part, source_name, section["location"], idx))
                    idx += 1
        return chunks

    def embed_documents(self, texts):
        """Embed documents using the local MiniLM model; never Gemini."""
        if not texts:
            return np.empty((0, self.embedding_dimension), dtype="float32")
        vectors = self.embedding_model.encode(
            list(texts),
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype="float32")

    def embed_queries(self, queries):
        """Embed search queries with the same local MiniLM model."""
        return self.embed_documents(queries)

    def rebuild(self):
        self.chunks = self.build_chunks()
        if not self.chunks:
            self.index = None
            self.persist()
            return
        docs = [f"title: {c.source} | text: {c.text}" for c in self.chunks]
        vectors = self.embed_documents(docs)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)
        self.persist()

    def persist(self):
        if self.index is not None:
            faiss.write_index(self.index, str(self.index_path))
        self.meta_path.write_text(json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False), encoding="utf-8")
        self.manifest_path.write_text(self.manifest(), encoding="utf-8")

    def load(self):
        self.chunks = []
        if self.meta_path.exists():
            try:
                self.chunks = [Chunk(**x) for x in json.loads(self.meta_path.read_text(encoding="utf-8"))]
            except Exception:
                self.chunks = []
        if self.index_path.exists():
            try:
                self.index = faiss.read_index(str(self.index_path))
            except Exception:
                self.index = None

    def ensure_fresh(self):
        current = self.manifest()
        stored = self.manifest_path.read_text(encoding="utf-8").strip() if self.manifest_path.exists() else ""
        if current != stored:
            self.rebuild()

    def generate_queries(self, question: str):
        if not self.client:
            return [question]
        prompt = f"""Create {settings.multi_query_count} alternative search queries for this document question.

Original question:
{question}

Rules:
- Preserve every exact key, ID, number, percentage, date, product name and important phrase.
- Include the original question as one of the queries.
- Make variants useful for finding the same answer in a policy/handbook/technical document.
- Do not answer the question.
- Return only one query per line."""
        try:
            response = self.client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=350),
            )
            queries = [question]
            for line in response.text.splitlines():
                q = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
                if q and q.lower() not in {x.lower() for x in queries}:
                    queries.append(q)
            return queries[:settings.multi_query_count + 1]
        except Exception:
            return [question]

    def lexical_score(self, query, chunk: Chunk):
        q = self.normalize(query)
        t = self.normalize(f"{chunk.source} {chunk.text}")
        if not q or not t:
            return 0.0, 0.0
        if q in t:
            return 1.0, 1.0
        q_tokens = self.meaningful_tokens(q)
        if not q_tokens:
            return 0.0, 0.0
        # Rare/exact terms get stronger weight. This is intentionally simple,
        # deterministic, and works well for IDs, percentages and proper nouns.
        hits = 0
        weighted = 0.0
        for token in q_tokens:
            if token in t:
                hits += 1
                weight = 2.0 if any(c.isdigit() for c in token) or len(token) >= 8 else 1.0
                weighted += weight
        total_weight = sum(2.0 if any(c.isdigit() for c in token) or len(token) >= 8 else 1.0 for token in q_tokens)
        token_score = weighted / total_weight if total_weight else 0.0
        phrase_terms = [x for x in q_tokens if len(x) >= 5 or any(c.isdigit() for c in x)]
        phrase_hits = sum(1 for x in phrase_terms if x in t)
        exact = phrase_hits / len(phrase_terms) if phrase_terms else 0.0
        return token_score, exact

    def search(self, question: str, top_k_per_query=None, final_k=None):
        self.ensure_fresh()
        if not self.chunks:
            return []
        if self.index is None:
            raise RuntimeError("The FAISS index is unavailable. Rebuild the local MiniLM index first.")

        top_k_per_query = top_k_per_query or settings.retrieval_top_k_per_query
        final_k = final_k or settings.final_context_chunks
        queries = self.generate_queries(question)
        q_vectors = self.embed_queries(queries)
        k = min(top_k_per_query, len(self.chunks))
        semantic_scores, semantic_ids = self.index.search(q_vectors, k)

        merged = {}
        def ensure(cid):
            return merged.setdefault(cid, {
                "text": self.chunks[cid].text,
                "source": self.chunks[cid].source,
                "location": self.chunks[cid].location,
                "semantic_score": 0.0,
                "lexical_score": 0.0,
                "exact_score": 0.0,
                "query_hits": 0,
            })

        for qi in range(len(queries)):
            for rank, cid_raw in enumerate(semantic_ids[qi]):
                cid = int(cid_raw)
                if cid < 0:
                    continue
                item = ensure(cid)
                item["semantic_score"] = max(item["semantic_score"], float(semantic_scores[qi][rank]))
                item["query_hits"] += 1

        # Exact/lexical search across every chunk. This is critical for policy
        # numbers, percentages, IDs, acronyms, and exact wording.
        for cid, chunk in enumerate(self.chunks):
            lexical, exact = self.lexical_score(question, chunk)
            if lexical > 0:
                item = ensure(cid)
                item["lexical_score"] = max(item["lexical_score"], lexical)
                item["exact_score"] = max(item["exact_score"], exact)

        for item in merged.values():
            # Strongly prefer literal matches while still rewarding semantic matches.
            semantic = max(0.0, item["semantic_score"])
            lexical = item["lexical_score"]
            exact = item["exact_score"]
            hits = min(item["query_hits"], 3) / 3.0
            item["score"] = 0.45 * semantic + 0.30 * lexical + 0.20 * exact + 0.05 * hits

        ranked = sorted(merged.values(), key=lambda x: (x["score"], x["exact_score"], x["lexical_score"]), reverse=True)
        return ranked[:final_k]


class RAGManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.stores = {}

    def store(self, agent_id):
        if agent_id not in self.stores:
            self.stores[agent_id] = LocalMiniLMHybridFAISS(agent_id, self.base_dir / agent_id)
        return self.stores[agent_id]

    def rebuild(self, agent_id):
        store = LocalMiniLMHybridFAISS(agent_id, self.base_dir / agent_id)
        store.rebuild()
        self.stores[agent_id] = store
        return store
