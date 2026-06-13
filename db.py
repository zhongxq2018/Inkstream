"""SQLite 数据层：对话/消息持久化、分享、时间分组。"""
import sqlite3
import secrets
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

DB_DIR = Path(__file__).parent / "data"
DB_PATH = DB_DIR / "chat.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    username   TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL DEFAULT '新对话',
    user_id    TEXT REFERENCES users(id),
    guest_id   TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user    ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_guest   ON conversations(guest_id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    sort_order      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, sort_order);

CREATE TABLE IF NOT EXISTS shares (
    id              TEXT PRIMARY KEY,
    token           TEXT UNIQUE NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_share_token ON shares(token);
"""


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return str(uuid.uuid4())


def init_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Users ────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE username=?", (username,)
        ).fetchone()
        return dict(row) if row else None


def create_user(username: str) -> dict:
    user = {"id": _new_id(), "username": username, "created_at": _now()}
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id, username, created_at) VALUES(?,?,?)",
            (user["id"], user["username"], user["created_at"]),
        )
    return user


# ── Conversations ─────────────────────────────────────────────────────────────

def create_conversation(*, user_id: str | None = None, guest_id: str | None = None, title: str = "新对话") -> dict:
    now = _now()
    conv = {"id": _new_id(), "title": title, "user_id": user_id, "guest_id": guest_id,
            "created_at": now, "updated_at": now}
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations(id,title,user_id,guest_id,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (conv["id"], conv["title"], conv["user_id"], conv["guest_id"], conv["created_at"], conv["updated_at"]),
        )
    return conv


def list_conversations(*, user_id: str | None = None, guest_id: str | None = None) -> list[dict]:
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        elif guest_id:
            rows = conn.execute(
                "SELECT id,title,created_at,updated_at FROM conversations WHERE guest_id=? ORDER BY updated_at DESC",
                (guest_id,),
            ).fetchall()
        else:
            return []
        return [dict(r) for r in rows]


def get_conversation(conv_id: str, *, user_id: str | None = None, guest_id: str | None = None) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id,title,user_id,guest_id,created_at,updated_at FROM conversations WHERE id=?", (conv_id,)
        ).fetchone()
    if not row:
        return None
    conv = dict(row)
    if user_id and conv["user_id"] != user_id:
        return None
    if not user_id and guest_id and conv["guest_id"] != guest_id:
        return None
    return conv


def update_conversation_title(conv_id: str, title: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
            (title, _now(), conv_id),
        )


def touch_conversation(conv_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), conv_id))


def delete_conversation(conv_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))


# ── Messages ──────────────────────────────────────────────────────────────────

def list_messages(conv_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id,role,content,created_at,sort_order FROM messages WHERE conversation_id=? ORDER BY sort_order",
            (conv_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _next_sort_order(conn: sqlite3.Connection, conv_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order),0)+1 FROM messages WHERE conversation_id=?", (conv_id,)
    ).fetchone()
    return row[0]


def append_message(conv_id: str, role: str, content: str) -> dict:
    now = _now()
    with get_conn() as conn:
        sort_order = _next_sort_order(conn, conv_id)
        msg_id = _new_id()
        conn.execute(
            "INSERT INTO messages(id,conversation_id,role,content,created_at,sort_order) VALUES(?,?,?,?,?,?)",
            (msg_id, conv_id, role, content, now, sort_order),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    return {"id": msg_id, "conversation_id": conv_id, "role": role,
            "content": content, "created_at": now, "sort_order": sort_order}


def update_message(msg_id: str, content: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE messages SET content=? WHERE id=?", (content, msg_id))


def get_message(msg_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id,conversation_id,role,content,created_at,sort_order FROM messages WHERE id=?", (msg_id,)
        ).fetchone()
        return dict(row) if row else None


def truncate_messages_from(conv_id: str, from_sort_order: int) -> None:
    """删除 sort_order >= from_sort_order 的所有消息（含该条）。"""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id=? AND sort_order>=?",
            (conv_id, from_sort_order),
        )


def auto_title_from_content(content: str) -> str:
    title = content.strip().replace("\n", " ")
    return title[:24] if len(title) > 24 else title


# ── Shares ────────────────────────────────────────────────────────────────────

def create_share(conv_id: str, message_id: str) -> str:
    """返回 share token；同一 message_id 复用已有 token。"""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT token FROM shares WHERE message_id=?", (message_id,)
        ).fetchone()
        if existing:
            return existing["token"]
        token = secrets.token_urlsafe(16)
        conn.execute(
            "INSERT INTO shares(id,token,conversation_id,message_id,created_at) VALUES(?,?,?,?,?)",
            (_new_id(), token, conv_id, message_id, _now()),
        )
        return token


def get_share_by_token(token: str) -> dict | None:
    """返回 { token, question, answer, created_at } 或 None。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT s.token, s.created_at, s.conversation_id, s.message_id "
            "FROM shares s WHERE s.token=?",
            (token,),
        ).fetchone()
        if not row:
            return None
        share = dict(row)

        # 取助手消息
        asst = conn.execute(
            "SELECT content, sort_order FROM messages WHERE id=?", (share["message_id"],)
        ).fetchone()
        if not asst:
            return None

        # 取紧前一条 user 消息
        user_msg = conn.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND sort_order<? AND role='user' ORDER BY sort_order DESC LIMIT 1",
            (share["conversation_id"], asst["sort_order"]),
        ).fetchone()

        return {
            "token": share["token"],
            "question": user_msg["content"] if user_msg else "",
            "answer": asst["content"],
            "created_at": share["created_at"],
        }


# ── Auth helper ───────────────────────────────────────────────────────────────

def merge_guest_to_user(guest_id: str, user_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversations SET user_id=?, guest_id=NULL WHERE guest_id=?",
            (user_id, guest_id),
        )


# ── Time grouping ─────────────────────────────────────────────────────────────

def group_conversations_by_time(convs: list[dict]) -> dict[str, list[dict]]:
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    groups: dict[str, list[dict]] = {"今天": [], "昨天": [], "过去 7 天": [], "更早": []}
    for c in convs:
        try:
            dt = datetime.fromisoformat(c["updated_at"]).date()
        except Exception:
            dt = today
        if dt == today:
            groups["今天"].append(c)
        elif dt == yesterday:
            groups["昨天"].append(c)
        elif dt > week_ago:
            groups["过去 7 天"].append(c)
        else:
            groups["更早"].append(c)
    return {k: v for k, v in groups.items() if v}
