# 星声记 - 智能语音转录系统

基于 FunASR 深度学习模型的现代化语音转录应用，提供实时流式识别与高准确度离线转录服务。

## ✨ 核心特性

### 🎙️ 实时录音模式
- **三模型融合**：Paraformer（实时流式） + SenseVoice（完整识别） + Qwen3（智能纠错）
- **低延迟识别**：Paraformer 600ms 实时流式识别
- **智能纠错**：LLM 自动合并优化识别结果
- **实时反馈**：边说边显示，体验流畅

### 📁 文件上传模式
- **高准确度**：SenseVoice 完整音频识别
- **多格式支持**：wav, mp3, ogg, flac, m4a, aac, wma
- **一键转录**：上传即可，无需等待

### 🎨 现代化界面
- **响应式设计**：完美适配移动端和桌面端
- **优雅动画**：流畅的交互体验
- **音频可视化**：实时波形显示
- **录音下载**：支持保存录音文件

## 🛠️ 技术栈

### 后端
- **框架**：Flask + Flask-SocketIO
- **ASR 模型**：
  - Paraformer (阿里达摩院流式语音识别)
  - SenseVoice (阿里达摩院多语言语音识别)
- **LLM**：Qwen3 (智能文本纠错)
- **音频处理**：librosa, soundfile

### 前端
- **框架**：React 19 + TypeScript
- **构建工具**：Vite
- **样式**：Tailwind CSS
- **实时通信**：Socket.IO Client
- **图标**：Lucide React

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Node.js 16+
- 推荐使用 GPU（CPU 也可运行）

### 1. 克隆项目

```bash
git clone https://github.com/LeonArial/star-recorder.git
cd star-recorder
```

### 2. 安装后端

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate
# 激活虚拟环境（Linux/Mac）
source venv/bin/activate

# 安装依赖
pip install -r requirements_api.txt
```

### 3. 配置后端

编辑 `asr_api_server.py`，配置 LLM API：

```python
LLM_API_URL = "你的LLM API地址"
LLM_API_KEY = "你的LLM API密钥"
```

### 4. 启动后端

```bash
python asr_api_server.py
```

后端将在 `http://localhost:5006` 启动

### 5. 安装前端

```bash
cd frontend
npm install
```

### 6. 配置前端

确保 `frontend/.env.local` 包含：

```env
VITE_API_URL=http://localhost:5006
```

### 7. 启动前端

```bash
npm run dev
```

前端将在 `http://localhost:5173` 启动

## 📖 使用指南

### 实时录音

1. 打开应用，选择"实时录音"标签
2. 允许浏览器访问麦克风
3. 点击麦克风图标开始录音
4. 实时查看识别文本
5. 点击停止按钮结束录音
6. 等待 Qwen3 智能纠错
7. 获得最终优化结果

### 文件上传

1. 选择"上传文件"标签
2. 点击上传区域选择音频文件
3. 点击"开始转写"
4. 等待 SenseVoice 识别
5. 获得高准确度转录结果

## 🔧 API 接口

### REST API

- `GET /api/health` - 健康检查
- `POST /api/asr/transcribe` - 文件转录
- `GET /api/asr/models` - 模型信息
- `GET /api/asr/formats` - 支持格式

### WebSocket

- `connect` - 建立连接
- `start_recording` - 开始录音
- `audio_data` - 发送音频数据
- `stop_recording` - 停止录音
- `transcription` - 接收实时识别
- `recording_stopped` - 录音已停止
- `final_result` - 接收最终结果

详细文档请查看：[API使用指南.md](./API使用指南.md)

## 📁 项目结构

```
star-recorder/
├── asr_api_server.py          # API服务器主程序
├── requirements_api.txt       # 后端依赖
├── API使用指南.md             # API文档
├── frontend/                  # 前端应用
│   ├── components/            # React组件
│   │   ├── RealTimeTranscriber.tsx
│   │   ├── FileTranscriber.tsx
│   │   └── AudioVisualizer.tsx
│   ├── services/              # API服务
│   │   └── asrService.ts
│   ├── App.tsx                # 主应用
│   ├── index.html             # 入口HTML
│   └── package.json           # 前端依赖
└── README.md                  # 本文件
```

## 🎯 核心流程

### 实时录音识别流程

```
用户说话
    ↓
麦克风采集 (16kHz)
    ↓
WebSocket 传输
    ↓
Paraformer 实时识别 (600ms延迟)
    ↓
显示实时文本
    ↓
用户停止录音
    ↓
SenseVoice 完整识别
    ↓
Qwen3 智能合并纠错
    ↓
显示最终优化结果
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [FunASR](https://github.com/alibaba-damo-academy/FunASR) - 阿里达摩院语音识别框架
- [Qwen](https://github.com/QwenLM/Qwen) - 通义千问大语言模型
- [React](https://react.dev/) - 前端框架
- [Tailwind CSS](https://tailwindcss.com/) - CSS 框架

---

**Made with ❤️ by LeonArial**

🌟 如果这个项目对你有帮助，请给一个 Star！
