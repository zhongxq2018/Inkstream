"""从 ModelScope 下载 Qwen3.5-0.8B 到本地 models 目录。"""
from modelscope import snapshot_download

MODEL_ID = "Qwen/Qwen3.5-0.8B"
CACHE_DIR = "./models"

if __name__ == "__main__":
    model_dir = snapshot_download(MODEL_ID, cache_dir=CACHE_DIR)
    print(f"模型已下载到: {model_dir}")
