# 项目结构

## 目录组织

```
星纪ASR服务端/
├── backend/                         # ASR 服务端核心代码
│   ├── asr_api_server.py            # 主服务入口（Flask + SocketIO）
│   ├── download_models.py           # 模型预下载脚本
│   ├── test_asr_api.py              # API 测试脚本
│   ├── test.mp3                     # 测试音频文件
│   ├── hotwords.json                # 热词配置文件
│   ├── requirements.txt             # CPU/macOS 依赖
│   ├── requirements-gpu.txt         # GPU 服务器依赖
│   ├── Dockerfile                   # Docker 镜像构建配置
│   ├── docker-compose.yml           # Docker 编排配置
│   ├── .dockerignore                # Docker 构建忽略文件
│   ├── openapi.yaml                 # REST API OpenAPI 规格（YAML）
│   ├── openapi.json                 # REST API OpenAPI 规格（JSON）
│   ├── WebSocket接口文档.md         # WebSocket 协议文档
│   ├── README.md                    # 服务说明文档
│   ├── models_cache/                # ModelScope 模型缓存目录
│   ├── hf_cache/                    # Hugging Face 模型缓存目录
│   └── logs/                        # 运行日志目录
│
└── doc/                             # 项目文档
    └── ...                          # 其他文档
```

## 核心文件说明

### asr_api_server.py

主服务文件，包含以下核心功能：

- **模型初始化**：`init_models()` 加载 Paraformer、SenseVoice、VAD 等模型
- **REST API 路由**：
  - `/api/health` - 健康检查
  - `/api/asr/transcribe` - 文件转写
  - `/api/asr/models` - 模型信息
  - `/api/asr/formats` - 支持格式
  - `/api/asr/hotwords` - 热词管理
- **WebSocket 事件处理**：
  - `handle_connect` - 连接处理
  - `handle_start_recording` - 开始录音
  - `handle_audio_data` - 音频数据接收
  - `handle_stop_recording` - 停止录音
- **音频处理**：音频格式转换、重采样、VAD 分段
- **多模型融合**：Paraformer 流式 + SenseVoice 复检 + LLM 纠错
- **时间戳生成**：句级时间戳计算和对齐

### download_models.py

模型预下载脚本，用于在首次部署时提前下载所需模型：

- Paraformer 流式模型
- SenseVoice 模型
- VAD 模型
- 实时标点模型

### hotwords.json

热词配置文件，JSON 格式：

```json
{
  "hotwords": [
    "专有名词1",
    "专有名词2"
  ]
}
```

支持通过 API 热更新，无需重启服务。

### test_asr_api.py

API 测试脚本，用于验证服务功能：

```bash
python test_asr_api.py --file test.mp3 --url http://localhost:5006
```

## 数据流程

### 实时识别流程（WebSocket）

1. 客户端连接 WebSocket，获得 session_id
2. 发送 `start_recording` 事件开始会话
3. 持续发送 `audio_data` 事件（PCM 音频数据）
4. 服务端实时返回 `transcription` 事件（Paraformer 结果）
5. 客户端发送 `stop_recording` 事件结束会话
6. 服务端进行 SenseVoice 复检和 LLM 纠错
7. 返回 `final_result` 事件（最终结果 + 时间戳）

### 离线转写流程（REST API）

1. 客户端上传音频文件到 `/api/asr/transcribe`
2. 服务端读取音频，进行格式转换和重采样
3. 使用 SenseVoice 模型进行识别
4. 生成句级时间戳
5. 返回识别结果和时间戳

## 模型缓存机制

- 首次运行时自动从 ModelScope 下载模型
- 模型缓存在 `models_cache/` 和 `hf_cache/` 目录
- Docker 部署时建议挂载这些目录到宿主机
- 可通过环境变量 `MODELSCOPE_CACHE` 和 `HF_HOME` 自定义缓存路径

## 日志管理

- 运行日志输出到 `logs/` 目录
- 包含模型加载、API 调用、错误信息等
- Docker 部署时建议挂载 logs 目录便于查看

## 配置文件

- `requirements.txt`：CPU/macOS 环境依赖
- `requirements-gpu.txt`：GPU 环境依赖（包含 CUDA 相关包）
- `docker-compose.yml`：容器编排配置，包含环境变量和挂载点
- `Dockerfile`：镜像构建配置，基于 Python 3.10
