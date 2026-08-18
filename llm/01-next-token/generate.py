"""
generate.py —— 逐词生成，模拟大模型的"打字机效果" --- 循环-next token prediction生成文章
从零开始理解大模型（一）配套代码

用法：
    python generate.py
    python generate.py "Once upon a time"
    python generate.py "The meaning of life is" --temperature 0.3
    python generate.py "The meaning of life is" --temperature 1.5 --max-tokens 40

需要：pip install transformers torch
"""

import os
import sys
import argparse
import time
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import torch

# ==================== 0. 运行环境准备（让 demo 开箱即用） ====================

# (a) Windows 控制台默认 GBK 编码，中文与 █ 等符号会乱码 → 切到 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass  # stdout 被重定向或不是 TextIOWrapper 时忽略

# (b) 国内直连 huggingface.co 常被重置（WinError 10054），改用官方镜像 hf-mirror.com
#     必须在 import transformers 之前设置才生效；用 setdefault 不覆盖用户已设的值
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from transformers import GPT2LMHeadModel, GPT2Tokenizer
import torch

# ==================== 1. 加载模型和分词器 ====================

# 加载模型
print("正在加载模型…")
tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
model = GPT2LMHeadModel.from_pretrained("gpt2")
model.eval()


def generate_step_by_step(prompt, max_tokens=30, temperature=0.8, verbose=True):
    """
    逐个 token 生成文本，展示完整的预测过程。

    参数：
        prompt: 输入文本
        max_tokens: 最多生成多少个 token
        temperature: 控制"创造力"。越高越随机，越低越确定
        verbose: 是否打印每一步的细节
    """
    if verbose:
        print(f"输入: '{prompt}'")
        print(f"Temperature: {temperature}")
        print("=" * 60)

    input_ids = tokenizer.encode(prompt, return_tensors="pt")
    generated_text = prompt

    for step in range(max_tokens):
        with torch.no_grad():
            outputs = model(input_ids)
            next_token_logits = outputs.logits[0, -1, :]

        # Temperature 缩放
        # temperature > 1: 概率更平均 → 输出更随机、更"有创意"
        # temperature < 1: 概率更集中 → 输出更确定、更"保守"
        # temperature = 1: 不做调整
        scaled_logits = next_token_logits / temperature
        probabilities = torch.softmax(scaled_logits, dim=0)

        # 从概率分布中随机采样（而不是总选最高的）
        next_token_id = torch.multinomial(probabilities, 1)
        next_token = tokenizer.decode(next_token_id[0])

        # 这个 token 被选中的概率
        token_prob = probabilities[next_token_id[0]].item() * 100

        if verbose:
            # 同时展示 Top 3 候选，让你看到"没被选中的可能性"
            top3_probs, top3_indices = torch.topk(probabilities, 3)
            alternatives = [
                f"'{tokenizer.decode(top3_indices[j])}' {top3_probs[j].item()*100:.1f}%"
                for j in range(3)
            ]
            chosen_marker = " ✓" if next_token_id[0] in top3_indices else ""
            print(
                f"  Step {step+1:2d}: 选了 '{next_token}' ({token_prob:.1f}%){chosen_marker}"
                f"   | Top 3: {', '.join(alternatives)}"
            )

        # 拼接到输入，继续下一轮
        input_ids = torch.cat([input_ids, next_token_id.unsqueeze(0)], dim=1)
        generated_text += next_token

        # 模拟打字机效果
        if verbose:
            time.sleep(0.05)

        # 遇到句号就停止
        if next_token.strip() in [".", "!", "?"]:
            break

    if verbose:
        print("=" * 60)
        print(f"完整输出: '{generated_text}'")

    return generated_text


def main():
    parser = argparse.ArgumentParser(description="逐词生成文本，模拟大模型的打字机效果")
    parser.add_argument("prompt", nargs="*", default=["The", "meaning", "of", "life", "is"],
                        help="输入文本（默认: 'The meaning of life is'）")
    parser.add_argument("--temperature", "-t", type=float, default=None,
                        help="Temperature 值（默认: 运行对比实验）")
    parser.add_argument("--max-tokens", "-n", type=int, default=25,
                        help="最多生成多少个 token（默认: 25）")
    args = parser.parse_args()

    prompt = " ".join(args.prompt)


    if args.temperature is not None:
        # 指定了 temperature，只跑一次
        generate_step_by_step(prompt, max_tokens=args.max_tokens, temperature=args.temperature)
    else:
        # 没指定 temperature，跑对比实验
        print("实验 1: Temperature = 0.1（保守模式）")
        print()
        generate_step_by_step(prompt, max_tokens=args.max_tokens, temperature=0.1)

        print("\n")
        print("实验 2: Temperature = 1.0（默认模式）")
        print()
        # generate_step_by_step(prompt, max_tokens=args.max_tokens, temperature=1.0)

        print("\n")
        print("实验 3: Temperature = 1.5（奔放模式）")
        print()
        # generate_step_by_step(prompt, max_tokens=args.max_tokens, temperature=1.5)

        print("\n")
        print("-" * 60)
        print("观察要点：")
        print("  1. Temperature 低 → 每步选的词概率高，输出稳定")
        print("  2. Temperature 高 → 低概率的词也会被选中，输出多样")
        print("  3. 多运行几次，低 Temperature 的结果几乎一样，高 Temperature 的每次都不同")


if __name__ == "__main__":
    main()
