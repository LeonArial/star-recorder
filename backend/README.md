# 星纪 · ASR 后端服务

> 目录定位：`/Users/leon/Documents/code/星纪/backend`

该目录包含星声记项目的语音识别（ASR）后端，基于 **Flask + Flask-SocketIO**，整合 **FunASR** 的 Paraformer 流式模型、SenseVoice 复检模型、VAD 端点检测与 LLM 纠错逻辑。服务同时提供 REST API（文件转写）与 WebSocket（实时录音）两种接入方式。

---

## 功能概览

- **实时录音识别（WebSocket）**：

  - 使用 Paraformer + 实时标点模型即时出字。
  - 自动 VAD 分段，SenseVoice 全量复检。
  - 调用 LLM（Qwen3）进行结果纠错与合并。
- **离线文件转写（REST API）**：

  - 支持 `wav/mp3/ogg/flac/m4a/aac/wma/webm` 等格式。
  - 默认返回 SenseVoice 结果与句级时间戳。
- **热词系统**：

  - `hotwords.json` 可配置专有名词。
  - 通过 API 热更新，无需重启服务。
- **模型缓存**：

  - `MODELSCOPE_CACHE`、`HF_HOME` 环境变量可自定义缓存目录，减少重复下载。
- **开放文档**：

  - `openapi.yaml / openapi.json` 给出 REST API 描述。
  - `WebSocket接口文档.md` 说明实时协议。

---

## 目录结构

```
backend/
├── asr_api_server.py        # 主服务入口（Flask + SocketIO）
├── requirements.txt         # CPU/Mac 依赖
├── requirements-gpu.txt     # GPU 服务器依赖
├── docker-compose.yml       # 容器编排示例
├── Dockerfile               # 服务镜像构建配置
├── download_models.py       # 预下载 FunASR 模型脚本
├── hotwords.json            # 热词配置
├── openapi.(yaml|json)      # REST API 规格
├── WebSocket接口文档.md     # WebSocket 事件与示例
└── logs/、models_cache/     # 运行期日志与模型缓存（可挂载）
```

---

## 运行依赖

### 必备

- Python 3.10+
- FFmpeg（librosa 读取部分格式时需要）
- (可选) CUDA 11.8+ / ROCm / Apple Silicon MPS

### Python 依赖

```bash
# CPU / macOS
pip install -r requirements.txt

# GPU 服务器
pip install -r requirements-gpu.txt
```

> 若使用 GPU，请根据显卡环境预先安装匹配版本的 `torch / torchaudio`。

### FunASR 模型缓存

- 默认缓存目录：`backend/models_cache`、`backend/hf_cache`
- 可设置环境变量：
  - `MODELSCOPE_CACHE=/data/funasr_cache`
  - `HF_HOME=/data/hf_cache`

---

## 本地开发

```bash
cd /Users/leon/Documents/code/星声记/backend

# 1. 安装依赖
pip install -r requirements.txt

# 2.（可选）预下载模型
python download_models.py

# 3. 启动服务（默认端口 5006）
python asr_api_server.py
```

启动后控制台会打印：

- 模型加载情况（Paraformer / SenseVoice / VAD）。
- API & WebSocket 列表。
- 服务访问地址：`http://localhost:5006`

---

## Docker & Compose

### 构建镜像

```bash
docker build -t xingshengji-asr:latest .
```

### docker-compose（示例）

```bash
docker-compose up -d
```

默认挂载：

- `./models_cache` → `/app/models_cache`
- `./logs` → `/app/logs`
- 可在 compose 文件中配置 `MODELSCOPE_CACHE`、`HF_HOME`、`LLM_API_URL` 等环境变量。

---

## REST API

| 方法 | 路径                         | 描述             |
| ---- | ---------------------------- | ---------------- |
| GET  | `/api/health`              | 服务健康检查     |
| POST | `/api/asr/transcribe`      | 上传音频文件识别 |
| GET  | `/api/asr/models`          | 当前模型信息     |
| GET  | `/api/asr/formats`         | 支持的音频格式   |

更多字段说明参见 `openapi.yaml`。

### 上传示例

```bash
curl -X POST http://localhost:5006/api/asr/transcribe \
  -F "file=@test.mp3" \
  -F "generate_timestamps=true"
```

响应字段关键项：

- `data.text`：SenseVoice 文本
- `data.timestamps`：句级时间戳（毫秒）
- `filename`：原始文件名
- `duration_ms`：音频时长

---

## WebSocket 接入

服务端地址：`ws://<host>:5006/socket.io/?EIO=4&transport=websocket`

事件流程（详见 `WebSocket接口文档.md`）：

1. `connect` → 服务返回 `session_id`
2. `start_recording`
3. `audio_data`（持续发送 PCM 16kHz 单声道 int16 字节）
4. 服务端推送 `transcription`（实时文本 + VAD 状态）
5. `stop_recording`
6. 服务端依次发送 `recording_stopped`、`final_result`

`final_result` 结构：

- `paraformer` / `sensevoice` / `llm_merged`
- `timestamps`：经过 LLM 纠错的句级时间戳
- `realtime_segments`：流式粗时间戳（备用）


## 测试脚本

- `test_asr_api.py`：简单的 API 调用示例（上传音频并打印结果）。
- `test.mp3`：示例音频，可用于快速验证。

运行示例：

```bash
python test_asr_api.py --file test.mp3 --url http://localhost:5006
```

---

## 常见问题

1. **模型下载缓慢 / 失败**

   - 确认已设置正确的 `MODELSCOPE_CACHE`、`HF_HOME`
   - 可提前运行 `download_models.py` 离线下载。
2. **Mac M 系列性能**

   - FunASR 会优先尝试 MPS，若不稳定可手动设置 `USE_MPS=0`。
3. **LLM 调用失败**

   - 检查 `LLM_API_URL`、`LLM_API_KEY`
   - 失败时后备策略：直接返回 SenseVoice 结果。
4. **WebSocket 断线**

   - SocketIO 已调高 `ping_timeout`、`ping_interval`，若仍断线可检查反向代理超时配置。

---

## 部署建议

- 建议使用 Nginx / Traefik 等反向代理，并放行 `/socket.io/` 长连接。
- 使用 Docker 时，将 `models_cache`、`hf_cache` 目录挂载到宿主机，避免每次重建镜像重新下载模型。
- 可通过 `gunicorn + eventlet` 运行，但当前脚本直接使用 `socketio.run`，部署时可结合 `supervisor`、`systemd` 管理进程。

---

如需扩展或联调，可重点关注 `asr_api_server.py` 中：

- 模型初始化：`init_models()`
- REST 路由：`/api/asr/transcribe` 等函数
- WebSocket 事件：`handle_start_recording` / `handle_audio_data` / `handle_stop_recording`

欢迎依据实际业务需求进行二次开发。
