# WebSocket 实时录音接口文档

## 📖 概述

本文档描述了星声记实时语音转录系统的WebSocket接口规范。通过WebSocket连接，客户端可以实时向服务器发送音频数据，并接收实时识别结果和最终纠错结果。

---

## 🌐 连接信息

### 连接地址
```
ws://localhost:5006/socket.io/
```

### 传输协议
- **协议**：Socket.IO (WebSocket)
- **命名空间**：默认命名空间 `/`
- **传输方式**：`websocket`（推荐）

### 客户端库
- **JavaScript/TypeScript**: `socket.io-client`
- **Python**: `python-socketio`

---

## 🔄 完整工作流程

```
客户端                                 服务器
  │                                      │
  ├──────── connect ─────────────────►  │  建立连接
  │                                      │
  │  ◄──────── connected ───────────────┤  返回session_id
  │                                      │
  ├──────── start_recording ──────────►  │  开始录音会话
  │                                      │
  │  ◄──────── recording_started ───────┤  确认开始录音
  │                                      │
  ├──────── audio_data ───────────────►  │  发送音频数据（循环）
  ├──────── audio_data ───────────────►  │
  ├──────── audio_data ───────────────►  │
  │                                      │
  │  ◄──────── transcription ───────────┤  实时识别结果（600ms延迟）
  │  ◄──────── transcription ───────────┤
  │  ◄──────── transcription ───────────┤
  │                                      │
  ├──────── stop_recording ───────────►  │  停止录音
  │                                      │
  │  ◄──────── recording_stopped ───────┤  开始LLM处理
  │                                      │
  │  ◄──────── final_result ────────────┤  返回最终纠错结果
  │                                      │
  │  ◄──────── disconnect ──────────────┤  断开连接（可选）
  │                                      │
```

---

## 📤 客户端发送事件

### 1. `connect`
**描述**：建立WebSocket连接

**触发时机**：客户端初始化连接时自动触发

**无需参数**

**示例（JavaScript）**：
```javascript
import { io } from 'socket.io-client';

const socket = io('http://localhost:5006', {
  transports: ['websocket']
});

socket.on('connect', () => {
  console.log('连接成功');
});
```

---

### 2. `start_recording`
**描述**：开始录音会话

**触发时机**：客户端准备好麦克风后，开始录音前

**参数**：无

**服务器响应**：`recording_started`

**示例（JavaScript）**：
```javascript
socket.emit('start_recording');
```

**注意事项**：
- 必须在连接成功后调用
- 每次录音前都需要调用
- 会创建一个新的ASR会话

---

### 3. `audio_data`
**描述**：发送音频数据块

**触发时机**：录音过程中持续发送

**参数**：
- **类型**：`ArrayBuffer` 或 `Buffer`
- **格式**：PCM int16 原始音频数据
- **采样率**：16000 Hz
- **声道**：单声道
- **建议大小**：每块 4800-9600 字节（300-600ms）

**服务器响应**：`transcription`（当累积到600ms时）

**示例（JavaScript）**：
```javascript
// 使用Web Audio API获取音频数据
const audioContext = new AudioContext({ sampleRate: 16000 });
const processor = audioContext.createScriptProcessor(4096, 1, 1);

processor.onaudioprocess = (e) => {
  const inputData = e.inputBuffer.getChannelData(0);
  
  // 转换为int16
  const int16Array = new Int16Array(inputData.length);
  for (let i = 0; i < inputData.length; i++) {
    int16Array[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
  }
  
  // 发送到服务器
  socket.emit('audio_data', int16Array.buffer);
};
```

**注意事项**：
- 必须先调用 `start_recording`
- 音频数据必须是16kHz采样率的int16格式
- 建议每300-600ms发送一次
- 字节数必须是偶数（int16 = 2 bytes）

---

### 4. `stop_recording`
**描述**：停止录音并获取最终结果

**触发时机**：用户停止录音时

**参数**：无

**服务器响应**：
1. `recording_stopped` - 立即返回，表示开始处理
2. `final_result` - 处理完成后返回最终结果

**示例（JavaScript）**：
```javascript
socket.emit('stop_recording');
```

**注意事项**：
- 会触发最终识别处理
- 包含Paraformer、SenseVoice和LLM三种结果
- 处理时间取决于录音长度（通常3-10秒）
- 处理完成后会自动清理会话

---

### 5. `disconnect`
**描述**：断开WebSocket连接

**触发时机**：客户端主动断开连接时

**参数**：无

**示例（JavaScript）**：
```javascript
socket.disconnect();
```

**注意事项**：
- 会自动清理服务器上的会话数据
- 建议在获取最终结果后断开

---

## 📥 服务器发送事件

### 1. `connected`
**描述**：连接成功确认

**触发条件**：客户端连接成功后

**数据格式**：
```typescript
{
  session_id: string  // 会话ID，唯一标识此连接
}
```

**示例（JavaScript）**：
```javascript
socket.on('connected', (data) => {
  console.log('会话ID:', data.session_id);
});
```

---

### 2. `recording_started`
**描述**：录音会话已创建

**触发条件**：收到 `start_recording` 后

**数据格式**：
```typescript
{
  status: 'ok'  // 状态标识
}
```

**示例（JavaScript）**：
```javascript
socket.on('recording_started', (data) => {
  console.log('录音已开始:', data.status);
  // 开始发送音频数据
});
```

---

### 3. `transcription`
**描述**：实时识别结果（流式）

**触发条件**：每接收约600ms音频数据后

**数据格式**：
```typescript
{
  text: string,           // 本次识别的文本片段
  punc_text: string,      // 添加标点后的文本（每30字符触发一次）
  full_text: string,      // 当前累积的完整文本（带标点）
  is_final: false         // 是否为最终结果
}
```

**示例响应**：
```json
{
  "text": "你好世界",
  "punc_text": "",
  "full_text": "你好世界",
  "is_final": false
}
```

**示例（JavaScript）**：
```javascript
socket.on('transcription', (data) => {
  console.log('实时文本:', data.full_text);
  // 更新UI显示实时识别结果
  setTranscript(data.full_text);
});
```

**注意事项**：
- 延迟约600ms
- `punc_text` 只在累积30字符时有值
- `full_text` 是推荐显示的内容
- 不是每次都会触发（取决于音频长度）

---

### 4. `recording_stopped`
**描述**：录音已停止，开始后处理

**触发条件**：收到 `stop_recording` 后立即发送

**数据格式**：
```typescript
{
  message: string  // 提示信息
}
```

**示例响应**：
```json
{
  "message": "录音已停止，开始LLM纠错"
}
```

**示例（JavaScript）**：
```javascript
socket.on('recording_stopped', (data) => {
  console.log(data.message);
  // 显示加载动画："调用 Qwen3 纠错中..."
  setIsProcessingLLM(true);
});
```

---

### 5. `final_result`
**描述**：最终识别结果（三种模型对比）

**触发条件**：`stop_recording` 处理完成后

**数据格式**：
```typescript
{
  paraformer: string,           // Paraformer流式识别结果
  sensevoice: string,           // SenseVoice完整识别结果
  llm_merged: string,           // LLM智能合并纠错结果（推荐使用）
  paraformer_length: number,    // Paraformer文本长度
  sensevoice_length: number,    // SenseVoice文本长度
  llm_merged_length: number     // LLM合并文本长度
}
```

**示例响应**：
```json
{
  "paraformer": "你好，世界这是一个测试。",
  "sensevoice": "你好，世界！这是一个测试。",
  "llm_merged": "你好，世界！这是一个测试。",
  "paraformer_length": 15,
  "sensevoice_length": 16,
  "llm_merged_length": 16
}
```

**示例（JavaScript）**：
```javascript
socket.on('final_result', (data) => {
  console.log('最终结果:', data);
  
  // 使用LLM合并的结果（推荐）
  setTranscript(data.llm_merged);
  setIsProcessingLLM(false);
  
  // 断开连接
  socket.disconnect();
});
```

**注意事项**：
- `llm_merged` 是最准确的结果，推荐使用
- 处理时间取决于音频长度和LLM响应速度
- 收到此事件后建议断开连接，节省资源

---

### 6. `error`
**描述**：错误信息

**触发条件**：发生错误时

**数据格式**：
```typescript
{
  message: string  // 错误描述
}
```

**示例响应**：
```json
{
  "message": "会话不存在"
}
```

**示例（JavaScript）**：
```javascript
socket.on('error', (data) => {
  console.error('错误:', data.message);
  // 显示错误提示
  setError(data.message);
});
```

**常见错误**：
- `会话不存在` - 未调用 `start_recording` 或会话已过期
- `音频数据处理错误` - 音频格式不正确
- `流式识别错误` - ASR模型处理异常

---

### 7. `disconnect`
**描述**：连接断开通知

**触发条件**：
- 客户端主动断开
- 服务器主动断开
- 网络异常

**无数据返回**

**示例（JavaScript）**：
```javascript
socket.on('disconnect', () => {
  console.log('连接已断开');
  // 清理资源
  setIsRecording(false);
});
```

---

## 💻 完整示例代码

### JavaScript/TypeScript 客户端

```typescript
import { io, Socket } from 'socket.io-client';

class RealtimeASRClient {
  private socket: Socket;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  
  constructor(serverUrl: string) {
    // 建立连接
    this.socket = io(serverUrl, {
      transports: ['websocket']
    });
    
    // 监听事件
    this.setupListeners();
  }
  
  private setupListeners() {
    // 连接成功
    this.socket.on('connected', (data) => {
      console.log('✅ 已连接，会话ID:', data.session_id);
    });
    
    // 录音开始确认
    this.socket.on('recording_started', (data) => {
      console.log('🎙️ 录音已开始');
    });
    
    // 实时识别结果
    this.socket.on('transcription', (data) => {
      console.log('📝 实时文本:', data.full_text);
      // 更新UI
      this.onTranscription(data.full_text);
    });
    
    // 录音停止通知
    this.socket.on('recording_stopped', (data) => {
      console.log('🛑 ' + data.message);
      this.onProcessing(true);
    });
    
    // 最终结果
    this.socket.on('final_result', (data) => {
      console.log('✅ 最终结果:', data.llm_merged);
      this.onFinalResult(data.llm_merged);
      this.onProcessing(false);
      
      // 断开连接
      this.socket.disconnect();
    });
    
    // 错误处理
    this.socket.on('error', (data) => {
      console.error('❌ 错误:', data.message);
      this.onError(data.message);
    });
    
    // 断开连接
    this.socket.on('disconnect', () => {
      console.log('⚠️ 连接已断开');
    });
  }
  
  async startRecording() {
    // 开始录音会话
    this.socket.emit('start_recording');
    
    // 获取麦克风
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true
      }
    });
    
    // 创建音频处理器
    this.audioContext = new AudioContext({ sampleRate: 16000 });
    const source = this.audioContext.createMediaStreamSource(stream);
    this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
    
    // 处理音频数据
    this.processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0);
      
      // 转换为int16
      const int16Array = new Int16Array(inputData.length);
      for (let i = 0; i < inputData.length; i++) {
        const s = Math.max(-1, Math.min(1, inputData[i]));
        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      
      // 发送音频数据
      this.socket.emit('audio_data', int16Array.buffer);
    };
    
    source.connect(this.processor);
    this.processor.connect(this.audioContext.destination);
  }
  
  stopRecording() {
    // 停止录音
    this.socket.emit('stop_recording');
    
    // 清理音频处理器
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
  }
  
  // 回调函数（需要实现）
  onTranscription(text: string) {
    // 更新实时文本显示
  }
  
  onProcessing(isProcessing: boolean) {
    // 显示/隐藏处理动画
  }
  
  onFinalResult(text: string) {
    // 显示最终结果
  }
  
  onError(message: string) {
    // 显示错误信息
  }
}

// 使用示例
const client = new RealtimeASRClient('http://localhost:5006');

// 开始录音
await client.startRecording();

// 停止录音
client.stopRecording();
```

---

### Python 客户端

```python
import socketio
import numpy as np
import sounddevice as sd
from queue import Queue

class RealtimeASRClient:
    def __init__(self, server_url='http://localhost:5006'):
        self.sio = socketio.Client()
        self.server_url = server_url
        self.audio_queue = Queue()
        self.is_recording = False
        
        # 设置事件监听
        self.setup_listeners()
    
    def setup_listeners(self):
        @self.sio.on('connected')
        def on_connected(data):
            print(f"✅ 已连接，会话ID: {data['session_id']}")
        
        @self.sio.on('recording_started')
        def on_recording_started(data):
            print("🎙️ 录音已开始")
        
        @self.sio.on('transcription')
        def on_transcription(data):
            print(f"📝 实时文本: {data['full_text']}")
        
        @self.sio.on('recording_stopped')
        def on_recording_stopped(data):
            print(f"🛑 {data['message']}")
        
        @self.sio.on('final_result')
        def on_final_result(data):
            print(f"✅ 最终结果: {data['llm_merged']}")
            self.sio.disconnect()
        
        @self.sio.on('error')
        def on_error(data):
            print(f"❌ 错误: {data['message']}")
    
    def audio_callback(self, indata, frames, time, status):
        """音频回调函数"""
        if status:
            print(f"音频状态: {status}")
        
        # 转换为int16并发送
        audio_int16 = (indata * 32767).astype(np.int16)
        self.sio.emit('audio_data', audio_int16.tobytes())
    
    def start_recording(self):
        """开始录音"""
        # 连接服务器
        self.sio.connect(self.server_url, transports=['websocket'])
        
        # 发送开始录音事件
        self.sio.emit('start_recording')
        
        # 开始音频流
        self.is_recording = True
        with sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype='float32',
            callback=self.audio_callback
        ):
            print("正在录音，按Ctrl+C停止...")
            while self.is_recording:
                self.sio.sleep(0.1)
    
    def stop_recording(self):
        """停止录音"""
        self.is_recording = False
        self.sio.emit('stop_recording')

# 使用示例
if __name__ == '__main__':
    client = RealtimeASRClient()
    
    try:
        client.start_recording()
    except KeyboardInterrupt:
        client.stop_recording()
        print("\n录音已停止")
```

---

## 🔧 技术细节

### 音频参数要求

| 参数 | 值 | 说明 |
|------|-----|------|
| 采样率 | 16000 Hz | 必须精确为16kHz |
| 位深度 | 16-bit | int16格式 |
|声道 | 单声道 | Mono |
| 编码 | PCM | 原始PCM数据 |
| 字节序 | 小端序 | Little-endian |

### 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 实时识别延迟 | 600ms | Paraformer流式识别 |
| 建议发送频率 | 300-600ms | 每次audio_data间隔 |
| 最大会话时长 | 无限制 | 受内存限制 |
| 并发连接数 | 取决于服务器配置 | 建议不超过10个 |

### 网络要求

- **带宽**：约 32 KB/s（16kHz * 16bit * 1channel）
- **延迟**：< 100ms 推荐
- **协议**：WebSocket（HTTP升级）

---

## ⚠️ 注意事项

### 1. 会话管理
- 每个连接有唯一的 `session_id`
- 会话在 `stop_recording` 后自动清理
- 不要重复发送 `start_recording`

### 2. 音频格式
- 必须严格按照16kHz、int16、单声道格式
- 字节数必须是偶数
- 建议使用AudioContext或sounddevice库

### 3. 错误处理
- 始终监听 `error` 事件
- 网络断开时自动重连
- 超时时间设置合理值（建议30秒）

### 4. 资源释放
- 录音结束后及时断开连接
- 清理AudioContext等资源
- 避免内存泄漏

### 5. 安全性
- 生产环境使用WSS（WebSocket Secure）
- 添加认证机制（Token/JWT）
- 限制单个连接的数据量

---

## 🐛 常见问题

### Q1: 为什么没有收到 `transcription` 事件？
**A**: 
- 检查音频格式是否正确（16kHz, int16）
- 确认已发送足够长度的音频（至少600ms）
- 查看服务器日志是否有错误

### Q2: `final_result` 处理时间过长？
**A**:
- 正常情况下3-10秒
- 取决于录音长度和LLM响应速度
- 可以通过 `recording_stopped` 事件显示加载动画

### Q3: 如何实现断线重连？
**A**:
```javascript
socket.on('disconnect', () => {
  // 等待3秒后重连
  setTimeout(() => {
    socket.connect();
  }, 3000);
});
```

### Q4: 可以同时发起多个录音会话吗？
**A**: 
- 一个连接对应一个会话
- 需要多个会话请建立多个连接
- 注意服务器性能限制

---

## 📚 相关文档

- [REST API 文档](./API使用指南.md)
- [热词配置说明](./热词配置说明.md)
- [项目 README](../README.md)

---

## 📞 技术支持

如有问题，请：
1. 查看服务器日志
2. 检查网络连接
3. 验证音频格式
4. 提交Issue到GitHub仓库

---

**最后更新**: 2025-11-25  
**版本**: v1.0.0  
**作者**: LeonArial
