"""Qwen3.5-0.8B 本地 HTTP API + 对话管理 + 认证 + 分享。"""
import asyncio
import ipaddress
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Lock

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db as database
from auth import Identity, get_current_identity, make_token, validate_username
from infer import chat_messages, load_model, resolve_model_path, stream_chat_messages

tokenizer = None
model = None
DEVICE = "cpu"
PORT = 8000
MODEL_PATH = resolve_model_path(None)
STATIC_DIR = Path(__file__).parent / "static"
GENERATION_LOCK = Lock()


def _is_usable_lan_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return False
    # Clash / Surge 等代理 TUN 模式常用的假 IP 段，不能作为局域网访问地址
    if addr in ipaddress.ip_network("198.18.0.0/15"):
        return False
    return addr.is_private


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if _is_usable_lan_ip(ip):
                return ip
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _is_usable_lan_ip(ip):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


LOCAL_IP = get_local_ip()


class Message(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    prompt: str | None = Field(None)
    messages: list[Message] | None = Field(None)
    enable_thinking: bool = Field(False)
    max_new_tokens: int = Field(512, ge=1, le=4096)


class ChatResponse(BaseModel):
    reply: str


def _resolve_messages(req: ChatRequest) -> list[dict[str, str]]:
    if req.messages:
        return [m.model_dump() for m in req.messages]
    if req.prompt:
        return [{"role": "user", "content": req.prompt}]
    raise HTTPException(status_code=400, detail="prompt 或 messages 至少提供一个")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global tokenizer, model
    database.init_db()
    print(f"正在加载模型: {MODEL_PATH}")
    tokenizer, model = load_model(MODEL_PATH, DEVICE)
    print("模型加载完成，API 已就绪")
    print(f"对话界面(本机):   http://127.0.0.1:{PORT}/")
    print(f"对话界面(局域网): http://{LOCAL_IP}:{PORT}/")
    yield


app = FastAPI(title="Qwen3.5-0.8B Local API", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="static/index.html not found")
    return FileResponse(page)


@app.get("/share/{token}")
def share_page(token: str):
    page = STATIC_DIR / "share.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="share page not found")
    return FileResponse(page)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_PATH,
        "device": DEVICE,
        "local_ip": LOCAL_IP,
        "port": PORT,
        "urls": {
            "localhost": f"http://127.0.0.1:{PORT}/",
            "lan": f"http://{LOCAL_IP}:{PORT}/",
        },
    }


# ── Original chat endpoints ───────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat_api(req: ChatRequest):
    messages = _resolve_messages(req)
    with GENERATION_LOCK:
        reply = chat_messages(
            tokenizer, model, messages,
            enable_thinking=req.enable_thinking,
            max_new_tokens=req.max_new_tokens,
        )
    return ChatResponse(reply=reply)


_STREAM_DONE = object()  # 哨兵：替代 StopIteration 在 executor 中传播


def _next_chunk(gen):
    """在线程池中安全地获取下一个 chunk，避免 StopIteration 穿透 Future。"""
    try:
        return next(gen)
    except StopIteration:
        return _STREAM_DONE


@app.post("/chat/stream")
async def chat_stream_api(req: ChatRequest, request: Request):
    messages = _resolve_messages(req)
    cancel_event = Event()

    async def event_stream():
        loop = asyncio.get_event_loop()

        def generate():
            with GENERATION_LOCK:
                for chunk in stream_chat_messages(
                    tokenizer, model, messages,
                    enable_thinking=req.enable_thinking,
                    max_new_tokens=req.max_new_tokens,
                    cancel_event=cancel_event,
                ):
                    yield chunk

        gen = generate()
        try:
            while True:
                if await request.is_disconnected():
                    cancel_event.set()
                    break
                chunk = await loop.run_in_executor(None, _next_chunk, gen)
                if chunk is _STREAM_DONE:
                    break
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        finally:
            cancel_event.set()
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Auth API ──────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    username: str
    guest_id: str | None = None


@app.post("/api/auth/register")
def auth_register(body: AuthRequest):
    validate_username(body.username)
    existing = database.get_user_by_username(body.username)
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在，请直接登录")
    user = database.create_user(body.username)
    if body.guest_id:
        database.merge_guest_to_user(body.guest_id, user["id"])
    token = make_token(user["id"], user["username"])
    return {"token": token, "username": user["username"], "user_id": user["id"]}


@app.post("/api/auth/login")
def auth_login(body: AuthRequest):
    validate_username(body.username)
    user = database.get_user_by_username(body.username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在，请先注册")
    if body.guest_id:
        database.merge_guest_to_user(body.guest_id, user["id"])
    token = make_token(user["id"], user["username"])
    return {"token": token, "username": user["username"], "user_id": user["id"]}


@app.get("/api/auth/me")
def auth_me(identity: Identity = Depends(get_current_identity)):
    if identity.is_authenticated:
        return {"username": identity.username, "user_id": identity.user_id}
    return {"guest": True}


# ── Conversations API ─────────────────────────────────────────────────────────

def _require_conv(conv_id: str, identity: Identity) -> dict:
    conv = database.get_conversation(
        conv_id,
        user_id=identity.user_id,
        guest_id=identity.guest_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conv


@app.get("/api/conversations")
def list_convs(identity: Identity = Depends(get_current_identity)):
    convs = database.list_conversations(
        user_id=identity.user_id,
        guest_id=identity.guest_id,
    )
    grouped = database.group_conversations_by_time(convs)
    return {"groups": grouped}


@app.post("/api/conversations")
def create_conv(identity: Identity = Depends(get_current_identity)):
    conv = database.create_conversation(
        user_id=identity.user_id,
        guest_id=identity.guest_id,
    )
    return conv


class PatchConvBody(BaseModel):
    title: str


@app.patch("/api/conversations/{conv_id}")
def rename_conv(conv_id: str, body: PatchConvBody, identity: Identity = Depends(get_current_identity)):
    _require_conv(conv_id, identity)
    title = body.title.strip()[:64] or "新对话"
    database.update_conversation_title(conv_id, title)
    return {"ok": True, "title": title}


@app.delete("/api/conversations/{conv_id}")
def delete_conv(conv_id: str, identity: Identity = Depends(get_current_identity)):
    _require_conv(conv_id, identity)
    database.delete_conversation(conv_id)
    return {"ok": True}


@app.get("/api/conversations/{conv_id}")
def get_conv(conv_id: str, identity: Identity = Depends(get_current_identity)):
    conv = _require_conv(conv_id, identity)
    msgs = database.list_messages(conv_id)
    return {**conv, "messages": msgs}


# ── Messages API ──────────────────────────────────────────────────────────────

class AppendMsgBody(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


@app.post("/api/conversations/{conv_id}/messages")
def append_msg(conv_id: str, body: AppendMsgBody, identity: Identity = Depends(get_current_identity)):
    conv = _require_conv(conv_id, identity)

    # 若是首条 user 消息，自动设标题
    if body.role == "user":
        existing = database.list_messages(conv_id)
        user_msgs = [m for m in existing if m["role"] == "user"]
        if not user_msgs and conv["title"] == "新对话":
            database.update_conversation_title(conv_id, database.auto_title_from_content(body.content))

    msg = database.append_message(conv_id, body.role, body.content)
    return msg


class PatchMsgBody(BaseModel):
    content: str


@app.patch("/api/conversations/{conv_id}/messages/{msg_id}")
def update_msg(conv_id: str, msg_id: str, body: PatchMsgBody, identity: Identity = Depends(get_current_identity)):
    _require_conv(conv_id, identity)
    msg = database.get_message(msg_id)
    if not msg or msg["conversation_id"] != conv_id:
        raise HTTPException(status_code=404, detail="消息不存在")
    database.update_message(msg_id, body.content)
    return {"ok": True}


@app.delete("/api/conversations/{conv_id}/messages/from/{msg_id}")
def truncate_from_msg(conv_id: str, msg_id: str, identity: Identity = Depends(get_current_identity)):
    _require_conv(conv_id, identity)
    msg = database.get_message(msg_id)
    if not msg or msg["conversation_id"] != conv_id:
        raise HTTPException(status_code=404, detail="消息不存在")
    database.truncate_messages_from(conv_id, msg["sort_order"])
    return {"ok": True}


# ── Share API ─────────────────────────────────────────────────────────────────

@app.post("/api/conversations/{conv_id}/messages/{msg_id}/share")
def create_share(conv_id: str, msg_id: str, request: Request, identity: Identity = Depends(get_current_identity)):
    _require_conv(conv_id, identity)
    msg = database.get_message(msg_id)
    if not msg or msg["conversation_id"] != conv_id:
        raise HTTPException(status_code=404, detail="消息不存在")
    token = database.create_share(conv_id, msg_id)
    base_url = str(request.base_url).rstrip("/")
    return {"token": token, "url": f"{base_url}/share/{token}"}


@app.get("/api/share/{token}")
def get_share(token: str):
    data = database.get_share_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    return data


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
