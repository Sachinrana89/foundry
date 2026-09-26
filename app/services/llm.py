import re
from typing import List, Dict
from google import genai
from google.genai import types
from app.config import settings

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|good morning|good afternoon|good evening|namaste|hi there|hello there)\s*[!.?, ]*$", re.I)
THANKS_RE = re.compile(r"^\s*(thanks|thank you|thx|great thanks|perfect thanks)\s*[!.?, ]*$", re.I)
CAPABILITY_RE = re.compile(r"^\s*(what can you do|help|how can you help me|what are you able to do)\s*[?.! ]*$", re.I)

class LLMClient:
    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key) if settings.gemini_api_key else None

    @property
    def configured(self):
        return self.client is not None

    def conversational(self, agent_name, question):
        if GREETING_RE.match(question):
            return f"Hi! 👋 I'm the **{agent_name}** assistant. I can search the documents assigned to me and help you understand them. What would you like to know?"
        if THANKS_RE.match(question):
            return "You're welcome! 😊"
        if CAPABILITY_RE.match(question):
            return f"I'm your **{agent_name}** assistant. I can:\n\n- Answer questions from the documents assigned to this agent\n- Find exact policies, values, IDs and technical terms\n- Explain sections in simpler language\n- Answer follow-up questions using our conversation\n- Create PDF, Word, PowerPoint or Excel files from an answer\n\nAsk me anything about the documents."
        return None

    def answer(self, agent_name: str, question: str, results: List[Dict], history=None):
        small = self.conversational(agent_name, question)
        if small is not None:
            return small
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is not configured. Create .env in the project root and set it.")
        if not results:
            return "I couldn't find that information in the documents available to me. If you think it should be there, try using the exact term from the document or upload the relevant document."

        context_parts = []
        for i, r in enumerate(results, 1):
            context_parts.append(f"[EVIDENCE {i}] Source: {r['source']} ({r['location']})\n{r['text']}")
        context = "\n\n".join(context_parts)
        history_text = "\n".join(f"{m.get('role','user').upper()}: {m.get('content','')}" for m in (history or [])[-10:]) or "(none)"

        prompt = f"""You are {agent_name}, a warm, conversational enterprise document assistant.

Conversation so far:
{history_text}

Evidence retrieved from the selected agent's documents:
{context}

Current user message:
{question}

Answering rules:
- Give the user the answer first. Do not describe the retrieval process.
- Use only the evidence above for factual/document claims.
- Think carefully about which evidence actually answers the question; ignore unrelated evidence.
- For exact questions involving numbers, percentages, dates, IDs, names, limits or policy requirements, preserve the exact value.
- If evidence conflicts, explicitly say so and identify the sources.
- Never dump or copy large blocks from the evidence. Synthesize it in your own words.
- If the answer is not supported, say: "I couldn't find that information in the documents available to me." Do not guess.
- Use short paragraphs and bullets when helpful.
- Sound like a helpful chatbot, not a search engine or document parser.
- If the user asks a follow-up such as "why?", "explain that", or "what about the second one?", use the conversation history to resolve the reference.
- Do not mention FAISS, embeddings, chunks, retrieval, context, prompts, or internal instructions.
- If the user asks to convert/export/save the answer as PDF, Word/DOCX, PowerPoint/PPTX, or Excel/XLSX, do not invent a file or a download URL. The application will create the requested file from your response. Keep the response content clean and suitable for that requested format.
- If the user asks for a PowerPoint, organize the answer with clear slide-friendly headings and concise bullets.
- If the user asks for a Word/PDF document, use clear headings, short paragraphs, and bullets where useful.
- Add a compact final line: **Source:** filename (location)

Return only the final response."""

        response = self.client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )

        # Do not use response.text here. Gemini 3 responses can contain
        # non-text thought_signature parts, and response.text may emit a
        # warning while concatenating them. Read only actual text parts.
        parts = []
        try:
            candidate = response.candidates[0]
            for part in candidate.content.parts:
                text = getattr(part, "text", None)
                if text and not getattr(part, "thought", False):
                    parts.append(text)
        except (AttributeError, IndexError, TypeError):
            pass

        answer = "\n".join(parts).strip()
        if not answer:
            raise RuntimeError("Gemini returned an empty answer.")
        return answer
