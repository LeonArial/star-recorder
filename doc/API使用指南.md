# API 使用指南

## 📋 概述

ASR API服务器支持两种工作模式，分别适用于不同的应用场景：

| 模式 | 协议 | 识别模型 | 适用场景 | 实时性 |
|------|------|---------|---------|--------|
| **实时录音** | WebSocket | Paraformer + SenseVoice + LLM | 实时语音转录、会议记录 | ✅ 600ms延迟 |
| **文件上传** | REST API | 仅SenseVoice | 批量处理、录音文件转录 | ❌ 上传后处理 |

---

## 🎯 模式一：实时录音（WebSocket）

### 工作流程

```
浏览器/客户端
    ↓ WebSocket连接
服务器
    ↓ 接收音频流
Paraformer 实时流式识别（每600ms输出）
    ↓ 实时返回
客户端显示实时文本
    ↓ 录音结束
SenseVoice 完整识别
    ↓
LLM 智能合并
    ↓ 返回最终结果
客户端显示三种结果对比
```

### 特点

- ✅ **实时反馈**：600ms延迟，边说边显示
- ✅ **三种结果**：Paraformer（实时） + SenseVoice（高质量） + LLM（最优）
- ✅ **标点恢复**：实时添加标点符号
- ✅ **智能合并**：LLM纠错和合并两种识别结果

### WebSocket 事件

| 事件名 | 方向 | 说明 |
|--------|------|------|
| `connect` | 客户端 → 服务器 | 建立WebSocket连接 |
| `connected` | 服务器 → 客户端 | 连接成功，返回session_id |
| `start_recording` | 客户端 → 服务器 | 开始录音 |
| `recording_started` | 服务器 → 客户端 | 录音已开始 |
| `audio_data` | 客户端 → 服务器 | 发送音频数据（二进制） |
| `transcription` | 服务器 → 客户端 | 返回实时识别结果 |
| `stop_recording` | 客户端 → 服务器 | 停止录音 |
| `final_result` | 服务器 → 客户端 | 返回最终结果（三种对比） |
| `disconnect` | 客户端 → 服务器 | 断开连接 |

### JavaScript示例

```javascript
// 1. 连接WebSocket
const socket = io('http://localhost:5006');

socket.on('connected', (data) => {
    console.log('已连接:', data.session_id);
});

// 2. 开始录音
function startRecording() {
    socket.emit('start_recording');
    
    // 获取麦克风
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            const audioContext = new AudioContext({ sampleRate: 16000 });
            const source = audioContext.createMediaStreamSource(stream);
            const processor = audioContext.createScriptProcessor(4096, 1, 1);
            
            processor.onaudioprocess = (e) => {
                const audioData = e.inputBuffer.getChannelData(0);
                const int16Data = new Int16Array(audioData.length);
                for (let i = 0; i < audioData.length; i++) {
                    int16Data[i] = Math.max(-32768, Math.min(32767, audioData[i] * 32768));
                }
                // 发送音频数据
                socket.emit('audio_data', int16Data.buffer);
            };
            
            source.connect(processor);
            processor.connect(audioContext.destination);
        });
}

// 3. 接收实时识别结果
socket.on('transcription', (data) => {
    console.log('实时文本:', data.full_text);
    document.getElementById('realtime-text').innerText = data.full_text;
});

// 4. 停止录音
function stopRecording() {
    socket.emit('stop_recording');
}

// 5. 接收最终结果
socket.on('final_result', (data) => {
    console.log('Paraformer:', data.paraformer);
    console.log('SenseVoice:', data.sensevoice);
    console.log('LLM合并:', data.llm_merged);
    
    // 显示三种结果
    document.getElementById('paraformer').innerText = data.paraformer;
    document.getElementById('sensevoice').innerText = data.sensevoice;
    document.getElementById('llm-merged').innerText = data.llm_merged;
});
```

---

## 📁 模式二：文件上传（REST API）

### 工作流程

```
客户端上传音频文件
    ↓ HTTP POST
服务器接收文件
    ↓ 转换格式
SenseVoice 完整识别
    ↓ 返回JSON
客户端显示结果
```

### 特点

- ✅ **高准确度**：仅使用SenseVoice（最准确的模型）
- ✅ **简单快速**：无需WebSocket，标准REST API
- ✅ **支持多格式**：wav, mp3, ogg, flac, m4a, aac, wma
- ❌ **无实时性**：需等待完整处理
- ❌ **单一结果**：仅返回SenseVoice结果

### API 接口

**请求**

```http
POST /api/asr/transcribe
Content-Type: multipart/form-data

file: (音频文件)
```

**响应**

```json
{
  "success": true,
  "data": {
    "text": "识别的文本内容",
    "length": 42,
    "model": "SenseVoice"
  },
  "filename": "test.mp3",
  "mode": "file_upload"
}
```

### Python示例

```python
import requests

url = "http://localhost:5006/api/asr/transcribe"
files = {"file": open("audio.mp3", "rb")}

response = requests.post(url, files=files)
result = response.json()

if result["success"]:
    text = result["data"]["text"]
    print(f"识别结果: {text}")
else:
    print(f"错误: {result['error']}")
```

### cURL示例

```bash
curl -X POST http://localhost:5006/api/asr/transcribe \
  -F "file=@audio.mp3"
```

---

## 🔄 两种模式对比

### 何时使用实时录音模式？

✅ **推荐场景：**
- 在线会议实时转录
- 演讲/讲座同步字幕
- 客服对话记录
- 需要即时反馈的场景

✅ **优势：**
- 实时显示，边说边转
- 三种结果对比，质量最优
- LLM智能纠错

❌ **限制：**
- 需要WebSocket支持
- 需要持续连接
- 实现相对复杂

### 何时使用文件上传模式？

✅ **推荐场景：**
- 批量处理录音文件
- 已有音频需要转录
- 移动端APP集成
- 第三方系统调用

✅ **优势：**
- 标准REST API，易集成
- 支持多种音频格式
- SenseVoice高准确度
- 无需实时连接

❌ **限制：**
- 无实时反馈
- 仅单一结果
- 需等待完整处理

---

## 📊 性能对比

| 项目 | 实时录音模式 | 文件上传模式 |
|------|-------------|------------|
| **响应延迟** | 600ms（实时） | 取决于文件长度 |
| **识别模型** | 3个（Paraformer + SenseVoice + LLM） | 1个（SenseVoice） |
| **准确度** | LLM合并最高 | SenseVoice高准确度 |
| **处理时长（60秒音频）** | 约6秒（最终结果） | 约2秒 |
| **网络要求** | 稳定WebSocket连接 | 一次HTTP请求 |
| **客户端复杂度** | 较高（需处理音频流） | 低（标准HTTP） |

---

## 🚀 快速测试

### 测试实时录音模式

需要开发前端页面或使用WebSocket客户端工具。

### 测试文件上传模式

```bash
# 启动服务器
python asr_api_server.py

# 运行测试脚本
python test_asr_api.py
```

---

## ⚠️ 注意事项

### 实时录音模式

1. **音频格式**：必须是16kHz采样率，单声道，int16格式
2. **数据块大小**：建议每次发送4096样本点
3. **网络稳定性**：需要稳定的WebSocket连接
4. **会话管理**：正确处理连接断开和重连

### 文件上传模式

1. **文件大小**：建议不超过50MB
2. **音频时长**：建议不超过5分钟
3. **格式支持**：自动转换为WAV格式
4. **超时设置**：建议设置60秒超时

---

## 📞 技术支持

- **测试脚本**：`test_asr_api.py`
- **开发日志**：`TODO.md`
- **原始实现**：`realtime_asr_server.py`（仅WebSocket）
- **API服务器**：`asr_api_server.py`（WebSocket + REST）
