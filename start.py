"""一键安装依赖、下载模型（若缺失）并启动本地对话服务。"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
PORT = 8000
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
APP_URL = f"http://127.0.0.1:{PORT}/"
STARTUP_TIMEOUT_SEC = 600

def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_pip() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "pip.exe"
    return VENV_DIR / "bin" / "pip"


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True)


def ensure_venv() -> Path:
    python = _venv_python()
    if not python.exists():
        print(f"创建虚拟环境: {VENV_DIR}")
        venv.create(VENV_DIR, with_pip=True)
    return python


def install_dependencies(python: Path) -> None:
    if not REQUIREMENTS.exists():
        raise FileNotFoundError(f"未找到依赖文件: {REQUIREMENTS}")
    pip = _venv_pip()
    _run([str(pip), "install", "-r", str(REQUIREMENTS)])


def model_is_ready(python: Path) -> bool:
    script = """
from infer import MODEL_ID, resolve_model_path
from pathlib import Path

path = resolve_model_path(None)
if path == MODEL_ID:
    raise SystemExit(1)
if not Path(path).joinpath("config.json").exists():
    raise SystemExit(1)
print(path)
"""
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        model_path = (result.stdout or "").strip()
        print(f"检测到本地模型，跳过下载: {model_path}")
        return True
    return False


def download_model(python: Path) -> None:
    print("未检测到本地模型，开始从 ModelScope 下载（体积较大，请耐心等待）...")
    _run([str(python), str(ROOT / "download_model.py")])


def _parse_health_payload(raw: bytes) -> dict | None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("status") != "ok":
        return None
    if not data.get("model"):
        return None
    if data.get("port") != PORT:
        return None
    return data


def fetch_health() -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            if response.status != 200:
                return None
            return _parse_health_payload(response.read())
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def service_is_running() -> bool:
    return fetch_health() is not None


def port_is_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def describe_port_blocker() -> str:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{PORT}" not in line or "LISTENING" not in line:
                    continue
                pid = line.split()[-1]
                tasklist = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                name = tasklist.stdout.strip().strip('"') or f"PID {pid}"
                return name
        except (subprocess.SubprocessError, OSError, ValueError):
            pass
    else:
        for cmd in (
            ["ss", "-ltnp", f"sport = :{PORT}"],
            ["lsof", "-i", f":{PORT}", "-sTCP:LISTEN"],
        ):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                lines = [line for line in result.stdout.splitlines() if line.strip()]
                if lines:
                    return lines[-1]
            except (subprocess.SubprocessError, OSError, FileNotFoundError):
                continue
    return f"未知进程（端口 {PORT}）"


def ensure_port_free_for_startup() -> None:
    if not port_is_in_use():
        return
    blocker = describe_port_blocker()
    raise RuntimeError(
        f"端口 {PORT} 已被其他程序占用: {blocker}\n"
        f"请关闭占用进程，或修改 serve.py / start.py 中的 PORT 后重试。"
    )


def wait_for_health(proc: subprocess.Popen[str] | None = None) -> None:
    print(f"等待服务就绪（模型加载可能需要数分钟）: {HEALTH_URL}")
    deadline = time.time() + STARTUP_TIMEOUT_SEC
    while time.time() < deadline:
        if proc is not None:
            exit_code = proc.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f"服务进程已退出（退出码 {exit_code}），"
                    f"常见原因是端口 {PORT} 被占用。请查看上方 serve.py 日志。"
                )
        if service_is_running():
            print("服务已就绪。")
            return
        time.sleep(1)
    raise TimeoutError(f"在 {STARTUP_TIMEOUT_SEC} 秒内未能启动服务，请查看上方日志。")


def main() -> int:
    print("=" * 60)
    print("ModelScope 本地对话 — 一键启动")
    print("=" * 60)

    try:
        if service_is_running():
            print(f"\n检测到服务已在运行: {APP_URL}")
            webbrowser.open(APP_URL)
            print(f"已在浏览器打开: {APP_URL}")
            print("关闭首次启动时打开的命令行窗口可停止服务。\n")
            return 0

        ensure_port_free_for_startup()

        python = ensure_venv()
        install_dependencies(python)

        from config import config_source_label, estimate_memory_gb, load_config

        cfg = load_config()
        mem_gb = estimate_memory_gb(cfg.inference_workers)
        print(
            f"\n推理并行 ({config_source_label()}): {cfg.inference_workers} 路, "
            f"预估内存 ~{mem_gb:.1f}GB"
        )
        print("提示: 编辑 config.json 可调整 inference_workers\n")

        if not model_is_ready(python):
            download_model(python)
            if not model_is_ready(python):
                print("模型下载后仍未找到有效本地目录，请检查 download_model.py 输出。", file=sys.stderr)
                return 1

        print(f"\n启动服务: {APP_URL}")
        proc = subprocess.Popen([str(python), str(ROOT / "serve.py")], cwd=ROOT)

        try:
            wait_for_health(proc)
            webbrowser.open(APP_URL)
            print(f"已在浏览器打开: {APP_URL}")
            print("关闭本窗口或按 Ctrl+C 可停止服务。\n")
            return proc.wait()
        except KeyboardInterrupt:
            print("\n正在停止服务...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 0
        except Exception:
            proc.terminate()
            raise
    except subprocess.CalledProcessError as exc:
        print(f"\n命令执行失败，退出码: {exc.returncode}", file=sys.stderr)
        return exc.returncode or 1
    except Exception as exc:
        print(f"\n启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
