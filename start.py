"""一键安装依赖、下载模型（若缺失）并启动本地对话服务。"""
from __future__ import annotations

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


def wait_for_health() -> None:
    print(f"等待服务就绪（模型加载可能需要数分钟）: {HEALTH_URL}")
    deadline = time.time() + STARTUP_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
                if response.status == 200:
                    print("服务已就绪。")
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1)
    raise TimeoutError(f"在 {STARTUP_TIMEOUT_SEC} 秒内未能启动服务，请查看上方日志。")


def main() -> int:
    print("=" * 60)
    print("ModelScope 本地对话 — 一键启动")
    print("=" * 60)

    try:
        python = ensure_venv()
        install_dependencies(python)

        if not model_is_ready(python):
            download_model(python)
            if not model_is_ready(python):
                print("模型下载后仍未找到有效本地目录，请检查 download_model.py 输出。", file=sys.stderr)
                return 1

        print(f"\n启动服务: {APP_URL}")
        proc = subprocess.Popen([str(python), str(ROOT / "serve.py")], cwd=ROOT)

        try:
            wait_for_health()
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
