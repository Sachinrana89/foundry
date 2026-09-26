import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import "./style.css";

const API = "";

function formatBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const csrf = document.cookie.match(/(?:^|; )foundry_csrf=([^;]+)/)?.[1];
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }

  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...options,
    headers,
  });

  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }

  return data;
}

function useMe() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/api/me")
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false));
  }, []);

  return { me, loading };
}

function useAgents() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/api/agents")
      .then((items) => setAgents(Array.isArray(items) ? items : []))
      .catch(() => setAgents([]))
      .finally(() => setLoading(false));
  }, []);

  return { agents, loading };
}

function Shell({ children, me, activeAgentId = "" }) {
  const navigate = useNavigate();
  const { agents } = useAgents();
  const [agentSearch, setAgentSearch] = useState("");

  async function signOut() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      navigate("/login");
      window.location.reload();
    }
  }

  const filteredAgents = agents.filter((agent) =>
    `${agent.short_name} ${agent.name}`.toLowerCase().includes(agentSearch.toLowerCase().trim())
  );

  return (
    <div className="app-shell">
      <aside className="agent-sidebar">
        <div className="sidebar-brand">
          <div className="gemini-mark">✦</div>
          <div className="sidebar-brand-text">
            <strong>Foundry AI</strong>
            <span>Agent workspace</span>
          </div>
        </div>

        <button className="new-chat" onClick={() => navigate("/")}>
          <span>＋</span> New chat
        </button>

        <div className="sidebar-section-title">AI agents</div>
        <div className="agent-search-side">
          <span>⌕</span>
          <input
            value={agentSearch}
            onChange={(e) => setAgentSearch(e.target.value)}
            placeholder="Search agents"
            aria-label="Search agents"
          />
        </div>

        <nav className="agent-list" aria-label="AI agents">
          {filteredAgents.map((agent) => (
            <Link
              key={agent.id}
              to={`/agent/${agent.id}`}
              className={`agent-nav-item ${activeAgentId === agent.id ? "selected" : ""}`}
              title={agent.name}
            >
              <span className={`agent-nav-icon ${agent.accent}`}>{agent.icon || "✦"}</span>
              <span className="agent-nav-name">{agent.short_name}</span>
            </Link>
          ))}
          {!filteredAgents.length && <div className="sidebar-empty">No matching agents</div>}
        </nav>

        <div className="sidebar-bottom">
          {me?.role === "admin" && (
            <Link className="sidebar-bottom-link" to="/admin/users">⚙ User management</Link>
          )}
          <button className="sidebar-bottom-link signout" onClick={signOut}>↪ Sign out</button>
          <div className="user-chip">
            <span className="avatar">{me?.username?.[0]?.toUpperCase() || "U"}</span>
            <div>
              <strong>{me?.username || "User"}</strong>
              <small>{me?.role === "admin" ? "Administrator" : "User"}</small>
            </div>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="workspace-topbar">
          <div className="workspace-title">
            <span className="topbar-spark">✦</span>
            <span>Google Foundry</span>
          </div>
          <div className="topbar-status"><span className="live-dot" /> Secure workspace</div>
        </header>
        {children}
      </main>
    </div>
  );
}

function Login() {
  const navigate = useNavigate();
  const { me, loading } = useMe();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loading && me) return <Navigate to="/" replace />;

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");

    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!data?.ok) throw new Error("Authentication failed.");
      navigate("/");
      window.location.reload();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-shell">
        <div className="login-brand">
          <div className="login-mark">✦</div>
          <div>
            <div className="login-title">Google Foundry</div>
            <div className="login-subtitle">Enterprise AI Agent Portal</div>
          </div>
        </div>

        <div className="login-card">
          <div className="login-icon">G</div>
          <h1>Welcome back</h1>
          <p className="login-description">
            Sign in to access your authorized AI agents and knowledge repositories.
          </p>

          {error && <div className="login-error">⚠ {error}</div>}

          <form onSubmit={submit}>
            <label>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />

            <label>Password</label>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete="current-password"
              required
            />

            <button className="login-button" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <div className="login-security">🔒 Encrypted session · least-privilege access · audit-ready</div>
        </div>
      </div>
    </div>
  );
}

function Home({ me }) {
  const { agents } = useAgents();
  const navigate = useNavigate();

  return (
    <Shell me={me}>
      <section className="gemini-home">
        <div className="home-glow" />
        <div className="home-content">
          <div className="home-spark">✦</div>
          <h1>Where should we start?</h1>
          <p>Choose an AI agent from the left to begin a conversation.</p>

          <div className="home-prompt" onClick={() => agents[0] && navigate(`/agent/${agents[0].id}`)}>
            <span className="prompt-plus">＋</span>
            <span className="prompt-placeholder">Ask an agent anything...</span>
            <span className="prompt-model">AI <span>⌄</span></span>
          </div>

          <div className="home-hints">
            <span>✦ Knowledge grounded</span>
            <span>◉ Authorized access</span>
            <span>↗ File generation</span>
          </div>

          <div className="home-agent-count">{agents.length} authorized agents available</div>
        </div>
      </section>
    </Shell>
  );
}

function AgentIllustration({ agent }) {
  switch (agent.id) {
    case "smart-center":
      return <div className="illustration smart">TCS Cloud Unit<small>Smart Center</small></div>;
    case "google-aarambh":
      return <div className="illustration aarambh">Google</div>;
    case "google-capabilities":
      return <div className="illustration capabilities"><i>✦</i><i>◉</i><i>◇</i><i>✓</i><i>⚙</i></div>;
    case "coe-repository":
      return <div className="illustration coe">COE<br /><small>Repository Agents</small></div>;
    case "case-studies":
      return <div className="illustration case-studies">CASE<br /><small>STUDIES</small></div>;
    case "deal-repository-solutions":
      return <div className="illustration deal-repository">DEALS<br /><small>&amp; SOLUTIONS</small></div>;
    case "learning-talent-development":
      return <div className="illustration learning">LEARN<br /><small>&amp; TALENT</small></div>;
    default:
      return <div className={`illustration ${agent.home_class || ""}`}>{agent.short_name}</div>;
  }
}

function AgentPage({ me }) {
  const { agentId } = useParams();
  const [agent, setAgent] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [uploadStatus, setUploadStatus] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [sources, setSources] = useState([]);
  const [sourceLinks, setSourceLinks] = useState({});
  const [sharePointStatus, setSharePointStatus] = useState("");
  const [loadingAgent, setLoadingAgent] = useState(true);
  const [agentError, setAgentError] = useState("");

  const loadDocuments = async () => {
    try {
      const docs = await api(`/api/agents/${agentId}/documents`);
      setDocuments(Array.isArray(docs) ? docs : []);
    } catch (err) {
      setDocuments([]);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoadingAgent(true);
    setAgentError("");

    (async () => {
      try {
        const items = await api("/api/agents");
        if (!Array.isArray(items)) {
          throw new Error("The server returned an invalid agent list.");
        }
        const found = items.find((a) => a.id === agentId);
        if (!found) {
          throw new Error("This agent is not available to your account.");
        }
        if (!cancelled) setAgent(found);
        await loadDocuments();
      } catch (err) {
        if (!cancelled) {
          setAgent(null);
          setAgentError(err?.message || "Unable to load this agent.");
        }
      } finally {
        if (!cancelled) setLoadingAgent(false);
      }
    })();

    return () => { cancelled = true; };
  }, [agentId]);

  if (loadingAgent) {
    return <Shell me={me} activeAgentId={agentId}><div className="content">Loading agent…</div></Shell>;
  }
  if (agentError || !agent) {
    return (
      <Shell me={me} activeAgentId={agentId}>
        <section className="content">
          <div className="login-error">⚠ {agentError || "Unable to load this agent."}</div>
          <Link className="chat-back" to="/">← Back to agents</Link>
        </section>
      </Shell>
    );
  }

  const history = messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .slice(-10)
    .map((m) => ({ role: m.role, content: m.text }));

  function newChat() {
    setMessages([]);
    setSources([]);
    setSourceLinks({});
    setQuestion("");
  }

  function useSuggestion(text) {
    setQuestion(text);
  }

  async function sendMessage() {
    const q = question.trim();
    if (!q || busy) return;

    setMessages((prev) => [...prev, { role: "user", text: q }]);
    setQuestion("");
    setBusy(true);

    try {
      const data = await api("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          question: q,
          history,
        }),
      });

      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.answer || "No answer received." },
      ]);
      setSources(data.sources || []);
      setSourceLinks(data.source_links || {});
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: `⚠️ ${err.message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function uploadDocument(file) {
    if (!file) return;
    setUploadStatus(`Uploading ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await api(`/api/documents/upload?agent_id=${encodeURIComponent(agentId)}`, {
        method: "POST",
        body: form,
      });
      setUploadStatus(`✓ ${data.filename} uploaded and indexed.`);
      await loadDocuments();
    } catch (err) {
      setUploadStatus(`✕ ${err.message}`);
    }
  }

  function onFileChange(event) {
    const file = event.target.files?.[0];
    if (file) uploadDocument(file);
    event.target.value = "";
  }

  async function syncSharePoint() {
    setSharePointStatus("Syncing SharePoint and rebuilding the knowledge index…");
    try {
      const data = await api(`/api/agents/${agentId}/sharepoint/sync`, { method: "POST" });
      setSharePointStatus(`✓ ${data.downloaded} SharePoint documents synced and ${data.chunks} chunks indexed.`);
      await loadDocuments();
    } catch (err) {
      setSharePointStatus(`✕ ${err.message}`);
    }
  }

  async function generateFile(kind) {
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");

    const content = lastAssistant?.text || "No answer has been generated yet.";
    const title = `${agent.short_name} — AI Generated ${kind.toUpperCase()}`;

    try {
      const data = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          title,
          content,
          kind,
        }),
      });

      window.location.href = data.download_url;
    } catch (err) {
      window.alert(err.message);
    }
  }

  return (
    <Shell me={me} activeAgentId={agentId}>
      <section className="agent-layout">
        <aside className="knowledge-panel">
          <div className="agent-header">
            <div className={`agent-icon ${agent.accent}`}>✦</div>
            <div>
              <h2>{agent.short_name}</h2>
              <p>{agent.description}</p>
            </div>
          </div>

          <div className="source-grid">
            <div className="upload-box local-source-box">
              <span className="upload-icon">↑</span>
              <strong>Upload documents</strong>
              <small>PDF, DOCX, PPTX, XLSX, TXT, MD or CSV · max {25} MB</small>
              <label className="source-button upload-button">
                Choose file
                <input type="file" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv" onChange={onFileChange} hidden />
              </label>
            </div>

            <div className="upload-box sharepoint-box">
              <span className="upload-icon">◫</span>
              <strong>SharePoint</strong>
              <small>Retrieve and index documents from the connected SharePoint site.</small>
              {me.role === "admin" && (
                <button type="button" className="sharepoint-sync" onClick={syncSharePoint}>
                  ↻ Sync SharePoint
                </button>
              )}
            </div>
          </div>

          <div className="mini-status">{uploadStatus || sharePointStatus}</div>

          <div className="docs-title">Knowledge documents</div>
          <div className="documents">
            {documents.length ? (
              documents.map((doc) => (
                <div className="doc-item" key={doc.path || doc.name}>
                  <span>📄</span>
                  <div>
                    {doc.web_url ? (
                      <a href={doc.web_url} target="_blank" rel="noreferrer"><strong>{doc.name}</strong></a>
                    ) : (
                      <strong>{doc.name}</strong>
                    )}
                    <small>{formatBytes(doc.size)} · {doc.source || "Knowledge source"}</small>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-docs">
                No knowledge documents yet.<br />Upload a file or sync SharePoint to add documents.
              </div>
            )}
          </div>
        </aside>

        <section className="chat-panel">
          <div className="chat-toolbar">
            <Link className="chat-back" to="/">← Back to agents</Link>
            <div className="chat-toolbar-title">
              <span className="chat-live-dot" />
              {agent.short_name} assistant
            </div>
            <button className="new-chat-button" onClick={newChat}>＋ New chat</button>
          </div>

          <div className="messages">
            {messages.length === 0 && (
              <div className="welcome">
                <div className="welcome-mark">✦</div>
                <h1>Ask {agent.short_name}</h1>
                <p>Answers can use documents uploaded here and documents retrieved from SharePoint.</p>
                <div className="suggestions">
                  <button onClick={() => useSuggestion("Summarize the available documents")}>
                    Summarize the available documents
                  </button>
                  <button onClick={() => useSuggestion("What are the key capabilities?")}>
                    What are the key capabilities?
                  </button>
                  <button onClick={() => useSuggestion("What are the important policies?")}>
                    What are the important policies?
                  </button>
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
                {message.role === "assistant" && <div className="bot-avatar">✦</div>}
                <div className="bubble">
                  {message.role === "assistant"
                    ? <Markdown text={message.text} />
                    : <>{message.text}</>}
                </div>
              </div>
            ))}

            {busy && (
              <div className="message assistant typing-message">
                <div className="bot-avatar">✦</div>
                <div className="bubble typing">
                  <span /><span /><span /><em>Thinking…</em>
                </div>
              </div>
            )}
          </div>

          <div className={`source-bar ${sources.length ? "" : "hidden"}`}>
            {sources.length > 0 && (
              <>
                <b>Sources:</b>
                {sources.map((source, index) => (
                  <span key={`${source}-${index}`}>📄 {sourceLinks[source] ? <a href={sourceLinks[source]} target="_blank" rel="noreferrer">{source}</a> : source}</span>
                ))}
              </>
            )}
          </div>

          <div className="composer">
            <textarea
              value={question}
              rows={2}
              placeholder="Ask anything about this agent's documents..."
              disabled={busy}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
            />
            <button
              className="send"
              disabled={busy || !question.trim()}
              onClick={sendMessage}
            >
              {busy ? "…" : "➤"}
            </button>
          </div>

          <div className="generate-row">
            <span>Generate:</span>
            <button onClick={() => generateFile("pdf")}>PDF</button>
            <button onClick={() => generateFile("docx")}>Word</button>
            <button onClick={() => generateFile("pptx")}>PowerPoint</button>
            <button onClick={() => generateFile("xlsx")}>Excel</button>
          </div>
        </section>
      </section>
    </Shell>
  );
}

function Markdown({ text }) {
  const html = String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((\/api\/generated\/[A-Za-z0-9._-]+)\)/g, '<a href="$2">$1</a>')
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h2>$1</h2>")
    .replace(/^[-•] (.*)$/gm, "<li>$1</li>")
    .replace(/\n\n/g, "<br/><br/>")
    .replace(/\n/g, "<br/>");

  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function AdminUsers({ me }) {
  const [users, setUsers] = useState([]);
  const [agents, setAgents] = useState({});
  const [message, setMessage] = useState("");

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [selected, setSelected] = useState([]);

  async function load() {
    const [u, a] = await Promise.all([
      api("/api/admin/users"),
      api("/api/admin/agents"),
    ]);
    setUsers(u);
    setAgents(Object.fromEntries(a.map((x) => [x.id, x])));
  }

  useEffect(() => { load().catch((e) => setMessage(e.message)); }, []);

  async function createUser(e) {
    e.preventDefault();
    try {
      await api("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          role,
          active: true,
          agent_ids: selected,
        }),
      });
      setUsername("");
      setPassword("");
      setRole("user");
      setSelected([]);
      setMessage("User created successfully.");
      load();
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function toggleUser(user) {
    try {
      await api(`/api/admin/users/${user.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: !user.active }),
      });
      load();
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function resetPassword(user) {
    const next = window.prompt(`Enter a new password for ${user.username}:`);
    if (!next) return;
    try {
      await api(`/api/admin/users/${user.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: next }),
      });
      setMessage("Password reset successfully.");
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function deleteUser(user) {
    if (!window.confirm(`Delete user ${user.username}?`)) return;
    try {
      await api(`/api/admin/users/${user.id}`, { method: "DELETE" });
      load();
    } catch (e) {
      setMessage(e.message);
    }
  }

  return (
    <Shell me={me}>
      <section className="admin-page">
        <div className="admin-heading">
          <div>
            <h1>Restricted user access</h1>
            <p>Create users and decide which agents they can access.</p>
          </div>
          <Link className="back-button" to="/">← Portal</Link>
        </div>

        {message && <div className="admin-message success">{message}</div>}

        <div className="admin-grid">
          <section className="admin-card">
            <h2>Create user</h2>
            <form onSubmit={createUser}>
              <label>Username</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} required />

              <label>Password</label>
              <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" minLength={8} required />

              <label>Role</label>
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="user">User</option>
                <option value="admin">Administrator</option>
              </select>

              <label>Allowed agents</label>
              <div className="agent-checks">
                {Object.values(agents).map((agent) => (
                  <label className="check-row" key={agent.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(agent.id)}
                      onChange={(e) => {
                        setSelected((prev) =>
                          e.target.checked
                            ? [...prev, agent.id]
                            : prev.filter((id) => id !== agent.id)
                        );
                      }}
                    />
                    <span>{agent.short_name}</span>
                  </label>
                ))}
              </div>

              <button className="primary-button" type="submit">Create user</button>
            </form>
          </section>

          <section className="admin-card">
            <h2>Users</h2>
            <div>
              {users.map((user) => (
                <div className="user-row" key={user.id}>
                  <div>
                    <strong>{user.username}</strong>
                    <small>{user.role} · {user.active ? "Active" : "Disabled"}</small>
                    <div className="user-agents">
                      {user.agents?.map((id) => (
                        <span key={id}>{agents[id]?.short_name || id}</span>
                      ))}
                    </div>
                  </div>
                  <div className="user-actions">
                    <button onClick={() => resetPassword(user)}>Reset password</button>
                    <button onClick={() => toggleUser(user)}>
                      {user.active ? "Disable" : "Enable"}
                    </button>
                    <button className="danger" onClick={() => deleteUser(user)}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>
    </Shell>
  );
}

function Protected({ children, me, loading }) {
  if (loading) return <div className="content">Loading…</div>;
  if (!me) return <Navigate to="/login" replace />;
  return children;
}

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="content" style={{ padding: 40 }}>
          <h2>Unable to open this page</h2>
          <p>{this.state.error?.message || "Unexpected application error."}</p>
          <a href="/">← Back to agents</a>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const { me, loading } = useMe();

  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route
        path="/"
        element={
          <Protected me={me} loading={loading}>
            <Home me={me} />
          </Protected>
        }
      />

      <Route
        path="/agent/:agentId"
        element={
          <Protected me={me} loading={loading}>
            <AgentPage me={me} />
          </Protected>
        }
      />

      <Route
        path="/admin/users"
        element={
          <Protected me={me} loading={loading}>
            {me?.role === "admin" ? <AdminUsers me={me} /> : <Navigate to="/" replace />}
          </Protected>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </BrowserRouter>
);
