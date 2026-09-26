from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "auth.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ALL_AGENT_IDS = [
    "smart-center",
    "google-aarambh",
    "google-capabilities",
    "coe-repository",
    "case-studies",
    "deal-repository-solutions",
    "learning-talent-development",
]


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_agents (
                user_id INTEGER NOT NULL,
                agent_id TEXT NOT NULL,
                PRIMARY KEY (user_id, agent_id),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def ensure_admin(username: str, password: str):
    if not username or not password:
        return

    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()

        if row:
            # The configured administrator credentials are authoritative.
            # This keeps first-time/local setup simple: changing ADMIN_PASSWORD
            # in .env also updates the configured admin password on startup.
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            conn.execute(
                "UPDATE users SET password_hash = ?, role = 'admin', active = 1 WHERE id = ?",
                (password_hash, row["id"]),
            )
            conn.executemany(
                "INSERT OR IGNORE INTO user_agents (user_id, agent_id) VALUES (?, ?)",
                [(row["id"], agent_id) for agent_id in ALL_AGENT_IDS],
            )
            return

        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        cur = conn.execute(
            """
            INSERT INTO users (username, password_hash, role, active)
            VALUES (?, ?, 'admin', 1)
            """,
            (username, password_hash),
        )
        user_id = cur.lastrowid

        conn.executemany(
            "INSERT OR IGNORE INTO user_agents (user_id, agent_id) VALUES (?, ?)",
            [(user_id, agent_id) for agent_id in ALL_AGENT_IDS],
        )


def authenticate(username: str, password: str):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username.strip(),),
        ).fetchone()

    if not row:
        return None

    try:
        valid = bcrypt.checkpw(
            password.encode("utf-8"),
            row["password_hash"].encode("utf-8"),
        )
    except ValueError:
        valid = False

    if not valid:
        return None

    return user_dict(row)


def user_dict(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "active": bool(row["active"]),
    }


def get_user(user_id: int):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return user_dict(row) if row else None


def get_user_by_username(username: str):
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return user_dict(row) if row else None


def allowed_agents(user_id: int):
    user = get_user(user_id)
    if not user or not user["active"]:
        return []

    if user["role"] == "admin":
        return ALL_AGENT_IDS.copy()

    with _conn() as conn:
        rows = conn.execute(
            "SELECT agent_id FROM user_agents WHERE user_id = ? ORDER BY agent_id",
            (user_id,),
        ).fetchall()

    return [r["agent_id"] for r in rows]


def has_agent_access(user_id: int, agent_id: str) -> bool:
    user = get_user(user_id)
    if not user or not user["active"]:
        return False
    if user["role"] == "admin":
        return True
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM user_agents
            WHERE user_id = ? AND agent_id = ?
            """,
            (user_id, agent_id),
        ).fetchone()
    return row is not None


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = get_user(int(user_id))
    if not user:
        request.session.clear()
        return None
    return user


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return user


def create_user(username: str, password: str, role: str, active: bool, agent_ids):
    username = username.strip()
    if not username or not password:
        raise ValueError("Username and password are required.")
    if role not in {"user", "admin"}:
        raise ValueError("Role must be user or admin.")
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")

    if role == "admin":
        agent_ids = ALL_AGENT_IDS
    else:
        agent_ids = [a for a in agent_ids if a in ALL_AGENT_IDS]

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    with _conn() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (username, password_hash, role, active)
                VALUES (?, ?, ?, ?)
                """,
                (username, password_hash, role, 1 if active else 0),
            )
        except sqlite3.IntegrityError:
            raise ValueError("That username already exists.")

        user_id = cur.lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO user_agents (user_id, agent_id) VALUES (?, ?)",
            [(user_id, agent_id) for agent_id in agent_ids],
        )

    return get_user(user_id)


def update_user(user_id: int, active=None, password=None, role=None, agent_ids=None):
    user = get_user(user_id)
    if not user:
        raise ValueError("User not found.")

    fields = []
    values = []

    if active is not None:
        fields.append("active = ?")
        values.append(1 if active else 0)

    if role is not None:
        if role not in {"user", "admin"}:
            raise ValueError("Invalid role.")
        fields.append("role = ?")
        values.append(role)

    if password:
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters.")
        fields.append("password_hash = ?")
        values.append(
            bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        )

    with _conn() as conn:
        if fields:
            values.append(user_id)
            conn.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
                values,
            )

        if agent_ids is not None:
            if role == "admin":
                agent_ids = ALL_AGENT_IDS
            agent_ids = [a for a in agent_ids if a in ALL_AGENT_IDS]
            conn.execute("DELETE FROM user_agents WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO user_agents (user_id, agent_id) VALUES (?, ?)",
                [(user_id, a) for a in agent_ids],
            )

    return get_user(user_id)


def list_users():
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, username, role, active, created_at FROM users ORDER BY username"
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["active"] = bool(item["active"])
        item["agents"] = allowed_agents(row["id"])
        result.append(item)
    return result


def delete_user(user_id: int):
    with _conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def login_redirect_detail():
    return "Authentication required. Please sign in."
