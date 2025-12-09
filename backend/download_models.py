#!/usr/bin/env python3
"""
模型预下载脚本

用于在本地预先下载 ASR 模型到 models_cache 目录，
这样在 Docker 运行时可以直接挂载使用，避免重复下载。

使用方法：
    python download_models.py

模型将下载到 ./models_cache 目录
"""

import os
import sys

# 设置模型缓存目录
MODELS_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'models_cache')
HF_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'hf_cache')

# 设置环境变量（必须在导入 funasr 之前）
os.environ['MODELSCOPE_CACHE'] = MODELS_CACHE_DIR
os.environ['HF_HOME'] = HF_CACHE_DIR


def download_models():
    """下载所有需要的模型"""
    
    # 创建缓存目录
    os.makedirs(MODELS_CACHE_DIR, exist_ok=True)
    os.makedirs(HF_CACHE_DIR, exist_ok=True)
    
    print("=" * 60)
    print("📦 ASR 模型预下载工具")
    print("=" * 60)
    print(f"📁 模型缓存目录: {MODELS_CACHE_DIR}")
    print(f"📁 HuggingFace缓存目录: {HF_CACHE_DIR}")
    print("=" * 60)
    
    try:
        from funasr import AutoModel
    except ImportError:
        print("❌ 错误: 未安装 funasr 库")
        print("请先运行: pip install funasr")
        sys.exit(1)
    
    models_to_download = [
        {
            "name": "paraformer-zh-streaming",
            "description": "中文流式 ASR 模型",
            "kwargs": {"model": "paraformer-zh-streaming", "disable_update": True}
        },
        {
            "name": "ct-punc",
            "description": "标点恢复模型（离线）",
            "kwargs": {"model": "ct-punc", "disable_update": True}
        },
        {
            "name": "punc_ct-transformer_zh-cn-common-vad_realtime",
            "description": "实时标点恢复模型（流式）",
            "kwargs": {
                "model": "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727",
                "disable_update": True
            }
        },
        {
            "name": "fsmn-vad",
            "description": "VAD 语音端点检测模型（实时）",
            "kwargs": {"model": "fsmn-vad", "disable_update": True}
        },
        {
            "name": "SenseVoiceSmall",
            "description": "SenseVoice 复检模型 + VAD",
            "kwargs": {
                "model": "iic/SenseVoiceSmall",
                "vad_model": "fsmn-vad",
                "vad_kwargs": {"max_single_segment_time": 30000},
                "disable_update": True,
                "use_itn": True
            }
        }
    ]
    
    success_count = 0
    
    for i, model_info in enumerate(models_to_download, 1):
        print(f"\n[{i}/{len(models_to_download)}] 下载 {model_info['name']}")
        print(f"    描述: {model_info['description']}")
        print("    状态: 下载中...")
        
        try:
            # 使用 CPU 设备加载以避免 GPU 依赖
            AutoModel(device="cpu", **model_info["kwargs"])
            print(f"    ✅ 下载完成!")
            success_count += 1
        except Exception as e:
            print(f"    ❌ 下载失败: {str(e)}")
    
    print("\n" + "=" * 60)
    print(f"📊 下载结果: {success_count}/{len(models_to_download)} 个模型成功")
    
    if success_count == len(models_to_download):
        print("✅ 所有模型下载完成!")
        print("\n💡 提示: 构建 Docker 镜像后，运行容器时挂载 models_cache 目录:")
        print("    docker run -v ./models_cache:/root/.cache/modelscope ...")
    else:
        print("⚠️ 部分模型下载失败，请检查网络连接后重试")
    
    print("=" * 60)
    
    return success_count == len(models_to_download)


if __name__ == '__main__':
    success = download_models()
    sys.exit(0 if success else 1)
