# 语音识别API服务文档

## 📋 概述

基于FunASR的智能语音识别RESTful API服务，提供三种识别结果的对比：

| 模型 | 特点 | 适用场景 | 权重 |
|------|------|----------|------|
| **Paraformer** | 实时流式识别，速度快 | 需要快速响应 | 20% |
| **SenseVoice** | 完整音频识别，准确度高 | 需要高准确度 | 80% |
| **LLM智能合并** | 综合两者优点，质量最优 | **推荐使用** | 100% |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install flask flask-cors funasr modelscope soundfile scipy requests
```

### 2. 启动服务

```bash
python asr_api_server.py
```

服务将在 `http://localhost:5006` 启动

### 3. 测试服务

```bash
# 健康检查
curl http://localhost:5006/api/health
```

## 📡 API接口文档

### 基础信息

- **Base URL**: `http://localhost:5006`
- **Content-Type**: `application/json` (响应) / `multipart/form-data` (文件上传)

---

### 1. 健康检查

检查API服务是否正常运行。

**请求**

```
GET /api/health
```

**响应示例**

```json
{
  "status": "ok",
  "message": "ASR API服务正常运行",
  "models_loaded": true
}
```

---

### 2. 音频转录 ⭐

上传音频文件进行转录，返回三种识别结果。

**请求**

```
POST /api/asr/transcribe
Content-Type: multipart/form-data
```

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file | File | ✅ | 音频文件（支持 wav, mp3, ogg, flac, m4a, aac, wma） |
| hotwords | String | ❌ | 专业词汇，多个词汇用逗号分隔，例如：`会议纪要,实时转录,语音识别` |

**响应示例**

```json
{
  "success": true,
  "data": {
    "paraformer": {
      "text": "测试一测试二会议纪要一会议纪要二会议纪要三",
      "length": 22
    },
    "sensevoice": {
      "text": "测试一、测试二，会议纪要一、会议纪要二、会议纪要三。",
      "length": 27
    },
    "llm_merged": {
      "text": "测试一、测试二，会议纪要一、会议纪要二、会议纪要三。",
      "length": 27
    }
  },
  "filename": "test_audio.wav",
  "hotwords": ["会议纪要", "实时转录", "语音识别"]
}
```

**错误响应**

```json
{
  "success": false,
  "error": "不支持的文件格式，支持的格式: wav, mp3, ogg, flac, m4a, aac, wma"
}
```

---

### 3. 获取模型信息

查询当前使用的模型配置。

**请求**

```
GET /api/asr/models
```

**响应示例**

```json
{
  "success": true,
  "data": {
    "asr_model": "paraformer-zh-streaming",
    "punc_model": "ct-punc",
    "sensevoice_model": "iic/SenseVoiceSmall",
    "llm_model": "qwen3:8b",
    "models_loaded": true
  }
}
```

---

### 4. 获取支持的音频格式

查询API支持的音频文件格式。

**请求**

```
GET /api/asr/formats
```

**响应示例**

```json
{
  "success": true,
  "data": {
    "formats": ["wav", "mp3", "ogg", "flac", "m4a", "aac", "wma"],
    "description": "支持的音频文件格式"
  }
}
```

## 💡 使用示例

### Python 示例

```python
import requests

# 音频转录
url = "http://localhost:5006/api/asr/transcribe"
files = {"file": open("test_audio.wav", "rb")}
data = {"hotwords": "会议纪要,实时转录,语音识别"}

response = requests.post(url, files=files, data=data)
result = response.json()

if result["success"]:
    # 推荐使用LLM合并结果
    text = result["data"]["llm_merged"]["text"]
    print(f"识别结果: {text}")
else:
    print(f"错误: {result['error']}")
```

### cURL 示例

```bash
# 基础转录
curl -X POST http://localhost:5006/api/asr/transcribe \
  -F "file=@test_audio.wav"

# 带热词的转录
curl -X POST http://localhost:5006/api/asr/transcribe \
  -F "file=@test_audio.wav" \
  -F "hotwords=会议纪要,实时转录,语音识别"
```

### JavaScript 示例

```javascript
const formData = new FormData();
formData.append('file', audioFile);
formData.append('hotwords', '会议纪要,实时转录,语音识别');

fetch('http://localhost:5006/api/asr/transcribe', {
  method: 'POST',
  body: formData
})
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      const text = data.data.llm_merged.text;
      console.log('识别结果:', text);
    }
  });
```

## 📥 导入到Apifox

### 方式一：导入YAML文件

1. 打开Apifox
2. 点击 **项目设置** → **导入数据**
3. 选择 **OpenAPI/Swagger**
4. 上传 `openapi.yaml` 文件
5. 点击确认导入

### 方式二：导入JSON文件

1. 打开Apifox
2. 点击 **项目设置** → **导入数据**
3. 选择 **OpenAPI/Swagger**
4. 上传 `openapi.json` 文件
5. 点击确认导入

### 方式三：在线URL导入

如果您的API已部署到服务器，可以直接使用URL导入：

```
http://your-server:5006/api/openapi.yaml
```

## 🔧 配置说明

### LLM配置

在 `asr_api_server.py` 中修改LLM配置：

```python
# LLM配置
LLM_API_URL = "http://10.8.75.207:9997/v1/chat/completions"
LLM_API_KEY = "your-api-key"
LLM_MODEL = "qwen3:8b"
```

### 端口配置

修改启动端口（默认5006）：

```python
app.run(host='0.0.0.0', port=5006, debug=False)
```

### 支持格式配置

添加更多音频格式支持：

```python
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'wma'}
```

## ⚠️ 注意事项

### 1. 音频文件要求

- **格式**: 支持 wav, mp3, ogg, flac, m4a, aac, wma（自动转换为WAV）
- **采样率**: 自动重采样到16kHz
- **声道**: 自动转换为单声道
- **时长**: 建议不超过5分钟（过长会增加处理时间）
- **大小**: 建议不超过50MB

### 2. 热词使用建议

- 热词应该是**专业术语**或**特定场景词汇**
- 多个热词用**逗号**分隔
- 热词数量建议**不超过20个**
- 示例：`会议纪要,实时转录,语音识别,FunASR,深度学习`

### 3. 性能优化

- **首次请求**较慢（需要加载模型，约10-20秒）
- **后续请求**速度快（模型已驻留内存）
- 建议使用**GPU**加速（需要配置CUDA）

### 4. 结果选择

- **需要最高准确度**: 使用 `llm_merged` 结果 ✅
- **需要快速响应**: 使用 `paraformer` 结果
- **需要高可靠性**: 使用 `sensevoice` 结果

## 📊 响应时间参考

| 音频时长 | Paraformer | SenseVoice | LLM合并 | 总耗时 |
|----------|-----------|------------|---------|--------|
| 10秒 | ~0.2秒 | ~0.5秒 | ~1秒 | **~1.7秒** |
| 30秒 | ~0.5秒 | ~1秒 | ~2秒 | **~3.5秒** |
| 60秒 | ~1秒 | ~2秒 | ~3秒 | **~6秒** |

*注：实际时间受硬件配置影响*

## 🐛 常见问题

### Q1: 模型加载失败？

**A**: 首次运行需要下载模型文件，请确保网络连接正常。如果下载失败，可以手动下载模型到 modelscope 缓存目录。

### Q2: 识别结果不准确？

**A**: 
- 确保音频质量良好（无杂音、清晰）
- 使用热词功能添加专业词汇
- 优先使用 `llm_merged` 结果

### Q3: 内存占用过高？

**A**: 
- 模型会驻留内存（约4-6GB）
- 可以考虑使用CPU版本（速度会变慢）
- 处理完音频后临时文件会自动清理

### Q4: 支持实时流式识别吗？

**A**: 当前API版本不支持流式，如需实时流式识别，请使用 `realtime_asr_server.py`（WebSocket版本）

## 📞 技术支持

如有问题，请查看：
- 项目文档: `README.md`
- 开发日志: `TODO.md`
- 测试脚本: `test_api.py`

## 📄 许可证

MIT License
