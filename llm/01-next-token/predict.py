"""
predict.py —— 亲眼看到"下一个词预测"   next token prediction
从零开始理解大模型（一）配套代码

用法：
    python predict.py
    python predict.py "The president of the United States is"
    python predict.py "Once upon a time"

需要：pip install transformers torch
"""

import os
import sys

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

print("正在加载模型（首次运行会下载约 500MB）…")
tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
model = GPT2LMHeadModel.from_pretrained("gpt2")
model.eval()

# ==================== 2. 输入一句话 ====================

prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Thank you very"
print(f"\n输入: '{prompt}'")

#   step1、    把文字变成模型能懂的数字（token ID）
input_ids = tokenizer.encode(prompt, return_tensors="pt")
tokens = [tokenizer.decode(id) for id in input_ids[0]]
print(f"Token IDs: {input_ids.tolist()[0]}")
print(f"对应的 tokens: {tokens}")
print(f"Token 数量: {len(tokens)}")

# ==================== 3. 模型预测下一个词 ====================

with torch.no_grad():
    outputs = model(input_ids)
    #   step2、    预测下一个词   outputs.logits 的形状: [1, token数量, 词表大小(50257)]
    # 我们只关心最后一个位置的预测（即"下一个词"）
    next_token_logits = outputs.logits[0, -1, :]

print(f"\n词表大小: {next_token_logits.shape[0]} 个 token")

# ==================== 4. 看看模型觉得哪些词最可能 ====================

probabilities = torch.softmax(next_token_logits, dim=0)

top_k = 10
#  预测top10   top10概率以及对应的token
top_probs, top_indices = torch.topk(probabilities, top_k)

print(f"\n模型预测 '{prompt}' 后面最可能的 {top_k} 个词：")
print("-" * 50)
for i in range(top_k):
    token = tokenizer.decode(top_indices[i])
    prob = top_probs[i].item() * 100
    bar = "█" * int(prob / 2)
    print(f"  {i+1:2d}. '{token}' \t {prob:5.1f}%  {bar}")

# ==================== 5. 选择概率最高的词 ====================

best_token = tokenizer.decode(top_indices[0])
print(f"\n选择概率最高的: '{best_token}'")
print(f"拼接后: '{prompt}{best_token}'")

# ==================== 6. 额外信息 ====================

# 看看概率分布的集中程度
top1_prob = top_probs[0].item()
top5_prob = top_probs[:5].sum().item()
top10_prob = top_probs[:10].sum().item()

print(f"\n概率分布统计:")
print(f"  Top 1 占: {top1_prob*100:.1f}%")
print(f"  Top 5 占: {top5_prob*100:.1f}%")
print(f"  Top 10 占: {top10_prob*100:.1f}%")
print(f"  剩余 {next_token_logits.shape[0] - 10} 个 token 共占: {(1-top10_prob)*100:.1f}%")
