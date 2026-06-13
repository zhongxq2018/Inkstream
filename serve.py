"""把 Qwen3.5-0.8B 包装成本地 HTTP API，并提供对话 Web 界面。"""
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from infer import chat_messages, load_model, resolve_model_path, stream_chat_messages

tokenizer = None
model = None
DEVICE = "cpu"
PORT = 8000
MODEL_PATH = resolve_model_path(None)
STATIC_DIR = Path(__file__).parent / "static"
GENERATION_LOCK = Lock()


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


LOCAL_IP = get_local_ip()


class Message(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    prompt: str | None = Field(None, description="单轮用户输入")
    messages: list[Message] | None = Field(None, description="多轮对话历史")
    enable_thinking: bool = Field(False, description="是否开启思考模式")
    max_new_tokens: int = Field(2048, ge=1, le=4096)


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


@app.post("/chat", response_model=ChatResponse)
def chat_api(req: ChatRequest):
    messages = _resolve_messages(req)
    with GENERATION_LOCK:
        reply = chat_messages(
            tokenizer,
            model,
            messages,
            enable_thinking=req.enable_thinking,
            max_new_tokens=req.max_new_tokens,
        )
    return ChatResponse(reply=reply)


@app.post("/chat/stream")
def chat_stream_api(req: ChatRequest):
    messages = _resolve_messages(req)

    def event_stream():
        with GENERATION_LOCK:
            for chunk in stream_chat_messages(
                tokenizer,
                model,
                messages,
                enable_thinking=req.enable_thinking,
                max_new_tokens=req.max_new_tokens,
            ):
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
