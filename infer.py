"""Qwen3-0.6B 本地推理示例（CPU 友好）。"""
import argparse
from collections.abc import Iterator
from pathlib import Path
from threading import Thread

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

MODEL_ID = "Qwen/Qwen3-0.6B"
MODELS_ROOT = Path("./models/Qwen")


def resolve_model_path(model_path: str | None) -> str:
    if model_path:
        return model_path

    # ModelScope 下载后目录名中的 "." 会变成 "___"
    candidates = [
        MODELS_ROOT / "Qwen3-0.6B",
        MODELS_ROOT / "Qwen3-0___6B",
    ]
    for candidate in candidates:
        if (candidate / "config.json").exists():
            return str(candidate)

    if MODELS_ROOT.exists():
        for candidate in MODELS_ROOT.iterdir():
            if candidate.is_dir() and (candidate / "config.json").exists():
                return str(candidate)

    return MODEL_ID


def load_model(model_path: str, device: str):
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    dtype = torch.float32 if device == "cpu" else "auto"
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        torch_dtype=dtype,
        device_map=device if device != "cpu" else None,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    if device == "cpu":
        model = model.to("cpu")
    model.eval()
    return tokenizer, model


def _build_generation_inputs(tokenizer, model, messages, enable_thinking: bool):
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    return tokenizer([text], return_tensors="pt").to(model.device)


def _generation_kwargs(inputs, max_new_tokens: int, streamer=None):
    kwargs = {
        **inputs,
        "max_new_tokens": max_new_tokens,
        "do_sample": True,
        "temperature": 0.7,
        "top_p": 0.8,
    }
    if streamer is not None:
        kwargs["streamer"] = streamer
    return kwargs


def chat_messages(
    tokenizer,
    model,
    messages: list[dict[str, str]],
    *,
    enable_thinking: bool = False,
    max_new_tokens: int = 512,
) -> str:
    inputs = _build_generation_inputs(tokenizer, model, messages, enable_thinking)

    with torch.no_grad():
        output_ids = model.generate(**_generation_kwargs(inputs, max_new_tokens))

    generated = output_ids[0][len(inputs.input_ids[0]) :].tolist()
    return tokenizer.decode(generated, skip_special_tokens=True)


def stream_chat_messages(
    tokenizer,
    model,
    messages: list[dict[str, str]],
    *,
    enable_thinking: bool = False,
    max_new_tokens: int = 512,
) -> Iterator[str]:
    inputs = _build_generation_inputs(tokenizer, model, messages, enable_thinking)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

    thread = Thread(
        target=lambda: _generate_with_stream(model, inputs, max_new_tokens, streamer),
    )
    thread.start()
    for chunk in streamer:
        if chunk:
            yield chunk
    thread.join()


def _generate_with_stream(model, inputs, max_new_tokens, streamer):
    with torch.no_grad():
        model.generate(**_generation_kwargs(inputs, max_new_tokens, streamer=streamer))


def chat(
    tokenizer,
    model,
    prompt: str,
    *,
    enable_thinking: bool = False,
    max_new_tokens: int = 512,
) -> str:
    return chat_messages(
        tokenizer,
        model,
        [{"role": "user", "content": prompt}],
        enable_thinking=enable_thinking,
        max_new_tokens=max_new_tokens,
    )


def main():
    parser = argparse.ArgumentParser(description="Qwen3-0.6B 本地推理")
    parser.add_argument("--model-path", default=None, help="本地模型目录，默认自动查找 ./models/Qwen/")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="推理设备")
    parser.add_argument("--prompt", default="用三句话介绍一下你自己。", help="用户问题")
    parser.add_argument("--thinking", action="store_true", help="开启思考模式（更慢，适合复杂问题）")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    model_path = resolve_model_path(args.model_path)
    print(f"加载模型: {model_path} (device={args.device})")
    tokenizer, model = load_model(model_path, args.device)

    print(f"\n用户: {args.prompt}\n")
    answer = chat(
        tokenizer,
        model,
        args.prompt,
        enable_thinking=args.thinking,
        max_new_tokens=args.max_new_tokens,
    )
    print(f"助手: {answer}")


if __name__ == "__main__":
    main()
