import requests
import json
import re
from datetime import datetime

# url = 'https://api.siliconflow.cn/v1/chat/completions'
url = 'http://10.8.75.207:9997/v1/chat/completions'

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer sk-dmowsenrtifmlnpmlhaatxgkxnhbmusjfzgnofvlhtblslwa'
}

data = {
    # "model": "Qwen/Qwen3-8B",
    "model": "qwen3:8b",
    "messages": [
        {
            "role": "system",
            "content": """你是一个专业的语音识别结果校对助手。你的任务是：

1. **对比分析**：对比两个语音识别模型的输出结果
   - Paraformer：实时流式识别结果，速度快但准确度相对较低，可能存在较多错误
   - SenseVoice：完整音频识别结果，准确度高，质量更可靠

2. **纠错合并策略**：
   - 优先采用SenseVoice的结果，它的准确度明显高于Paraformer
   - 在SenseVoice明显有遗漏或不合理的情况下，参考Paraformer进行补充
   - 识别并纠正识别错误（同音字、多字、少字、错别字等）
   - 保持语句通顺、语义连贯

3. **输出要求**：
   - 只输出最终纠正后的文本，不要任何解释说明
   - 保持原文的标点符号
   - 保持原文的语气和表达方式
   - 不要添加不存在的内容

4. **处理原则**：
   - 两个结果一致：直接采用
   - 两个结果有差异：**优先选择SenseVoice的版本（权重约80%）**
   - SenseVoice遗漏内容：可参考Paraformer补充（权重约20%）
   - 根据上下文判断时，倾向于相信SenseVoice的准确性"""
        },
        {
            "role": "user",
            "content": """请检查、纠错并合并以下两个语音识别结果：

**Paraformer识别结果**：
测试试试试一一之一之一。测试二测试二测试二测试二二试。

**SenseVoice识别结果**：
测试一测试二，会议纪要一会议纪要二会议纪要三。

请输出纠正后的最终文本："""
        }
    ],
    "temperature": 0.3,
    "max_tokens": 2000
}

response = requests.post(url, headers=headers, json=data)
result = response.json()
print("=" * 60)
print("原始响应:")
print(result)
print("=" * 60)

# 提取实际回复内容（去除 <think> 标签）
choices = result.get("choices", [])
if choices:
    content = choices[0].get("message", {}).get("content", "")
    
    print("\n原始LLM输出:")
    print(content)
    print("=" * 60)
    
    # 过滤 <think> 标签
    think_pattern = r"<think>.*?</think>"
    actual_reply = re.sub(think_pattern, "", content, flags=re.DOTALL).strip()
    
    print("\n过滤后的最终文本:")
    print(actual_reply)
    print("=" * 60)
    print(f"\n字数: {len(actual_reply)}")
