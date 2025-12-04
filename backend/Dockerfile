# 星声记 ASR API 服务器 Docker 镜像
# 基于CUDA镜像以支持GPU加速

FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# 设置环境变量
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    MODELSCOPE_CACHE=/root/.cache/modelscope \
    HF_HOME=/root/.cache/huggingface

# 设置工作目录
WORKDIR /app

# 使用阿里云镜像源加速（可选，根据网络情况调整）
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

# 安装系统依赖（只保留必要的）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libsndfile1 \
    ffmpeg \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 配置pip使用国内镜像源加速
RUN pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip3 config set install.trusted-host mirrors.aliyun.com

# 升级pip
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# 先安装PyTorch（支持CUDA 11.8）
RUN pip3 install --no-cache-dir \
    torch==2.1.0+cu118 \
    torchaudio==2.1.0+cu118 \
    --index-url https://download.pytorch.org/whl/cu118

# 先安装numpy和基础科学计算库（确保版本兼容）
RUN pip3 install --no-cache-dir \
    "numpy>=1.24.0,<2.0.0" \
    "scipy>=1.10.0"

# 复制依赖文件
COPY requirements.txt /app/

# 安装其他Python依赖
RUN pip3 install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY asr_api_server.py /app/
COPY hotwords.json /app/

# 创建模型缓存目录
RUN mkdir -p /root/.cache/modelscope /root/.cache/huggingface

# 暴露端口
EXPOSE 5006

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:5006/api/health || exit 1

# 启动命令
CMD ["python3", "asr_api_server.py"]
