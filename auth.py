"""简单 HMAC 签名 Token 认证（stdlib only，无额外依赖）。"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

from fastapi import Header, HTTPException

SECRET_FILE = Path(__file__).parent / "data" / ".secret"
_USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fff]{2,32}$")


def _load_secret() -> bytes:
    if key := os.environ.get("CHAT_SECRET_KEY"):
        return key.encode()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    key = secrets.token_hex(32).encode()
    SECRET_FILE.write_bytes(key)
    return key


SECRET_KEY: bytes = _load_secret()


# ── Token ─────────────────────────────────────────────────────────────────────

def make_token(user_id: str, username: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"user_id": user_id, "username": username}).encode()
    ).decode()
    sig = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def decode_token(token: str) -> dict | None:
    try:
        payload, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(payload).decode())
    except Exception:
        return None


# ── Identity ──────────────────────────────────────────────────────────────────

class Identity:
    def __init__(self, *, user_id: str | None = None, username: str | None = None, guest_id: str | None = None):
        self.user_id = user_id
        self.username = username
        self.guest_id = guest_id

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None


def get_current_identity(
    authorization: str | None = Header(default=None),
    x_guest_id: str | None = Header(default=None),
) -> Identity:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        data = decode_token(token)
        if data:
            return Identity(user_id=data["user_id"], username=data["username"])
    return Identity(guest_id=x_guest_id)


# ── Validation ────────────────────────────────────────────────────────────────

def validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="用户名需 2-32 字符，仅限字母/数字/下划线/中文")
