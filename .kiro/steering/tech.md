# 技术栈

## 核心技术

- **Web 框架**：Flask 2.3+ with Flask-SocketIO 5.3+
- **语音识别引擎**：FunASR 1.0+
- **深度学习框架**：PyTorch + torchaudio
- **模型管理**：ModelScope 1.9+
- **音频处理**：librosa 0.10+, soundfile 0.12+
- **实时通信**：python-socketio 5.9+, eventlet 0.33+
- **推理引擎**：ONNX Runtime 1.15+

## 使用的 AI 模型

- **Paraformer**：阿里达摩院流式语音识别模型
- **SenseVoice**：高精度语音识别复检模型
- **VAD**：语音活动检测模型
- **实时标点模型**：为流式识别添加标点符号
- **Qwen3**：通义千问大语言模型（用于纠错）

## 常用命令

### 本地开发

```bash
cd backend

# 安装依赖（CPU/macOS）
pip install -r requirements.txt

# 安装依赖（GPU 服务器）
pip install -r requirements-gpu.txt

# 预下载模型（可选，首次运行会自动下载）
python download_models.py

# 启动服务（默认端口 5006）
python asr_api_server.py
```

### Docker 部署

```bash
cd backend

# 构建镜像
docker build -t xingshengji-asr:latest .

# 使用 docker-compose 启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

### 测试

```bash
# 测试 REST API
python test_asr_api.py --file test.mp3 --url http://localhost:5006

# 健康检查
curl http://localhost:5006/api/health

# 查看支持的格式
curl http://localhost:5006/api/asr/formats
```

## 环境变量

### 模型缓存配置

- `MODELSCOPE_CACHE`：ModelScope 模型缓存目录（默认：`./models_cache`）
- `HF_HOME`：Hugging Face 模型缓存目录（默认：`./hf_cache`）

### LLM 配置

- `LLM_API_URL`：大语言模型 API 地址
- `LLM_API_KEY`：大语言模型 API 密钥

### 性能配置

- `USE_MPS`：是否使用 Apple Silicon MPS 加速（Mac M 系列）
- `CUDA_VISIBLE_DEVICES`：指定使用的 GPU 设备

## API 接口

### REST API

- `GET /api/health` - 健康检查
- `POST /api/asr/transcribe` - 上传音频文件转写
- `GET /api/asr/models` - 获取当前加载的模型信息
- `GET /api/asr/formats` - 获取支持的音频格式列表
- `GET /api/asr/hotwords` - 获取热词列表
- `POST /api/asr/hotwords` - 更新热词配置

详细 API 规格参见 `openapi.yaml` 或 `openapi.json`

### WebSocket 事件

- `connect` - 建立连接，返回 session_id
- `start_recording` - 开始录音会话
- `audio_data` - 发送音频数据（PCM 16kHz 单声道 int16）
- `stop_recording` - 停止录音
- `transcription` - 服务端推送实时识别结果
- `final_result` - 服务端推送最终结果（包含多模型结果和时间戳）

详细协议参见 `WebSocket接口文档.md`

## 部署建议

### 硬件要求

- **CPU 模式**：至少 4 核 CPU，8GB 内存
- **GPU 模式**：NVIDIA GPU（推荐 8GB+ 显存），CUDA 11.8+

### 生产部署

- 使用 Nginx 反向代理，配置 WebSocket 长连接支持
- 挂载 `models_cache` 和 `hf_cache` 到持久化存储
- 配置日志收集（logs 目录）
- 建议使用 supervisor 或 systemd 管理进程
- 设置合理的超时时间（WebSocket 连接可能较长）

### 性能优化

- 首次启动会下载模型，建议预先运行 `download_models.py`
- GPU 模式下性能显著优于 CPU
- 可通过调整 batch_size 优化吞吐量
- 热词文件支持热更新，无需重启服务
