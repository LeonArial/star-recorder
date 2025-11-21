# 智能语音转录前端

基于 React + TypeScript 的现代化语音转录应用，连接到 FunASR 后端 API。

## 功能特性

- **实时录音转录**: 使用 WebSocket 连接后端，实时流式识别（Paraformer 600ms延迟）
- **三种结果对比**: 展示 Paraformer、SenseVoice、LLM智能合并三种识别结果
- **文件上传转录**: 支持多种音频格式上传，使用 SenseVoice 高准确度识别
- **音频可视化**: 录音时的实时波形显示
- **录音下载**: 可下载录音文件
- **响应式设计**: 适配移动端和桌面端
- **现代化 UI**: 基于 Tailwind CSS 和 Lucide 图标

## 技术栈

- React 19
- TypeScript
- Vite
- Tailwind CSS
- Socket.IO Client (WebSocket)
- Lucide Icons

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 配置环境变量

创建 `.env.local` 文件：

```env
# 后端 API 地址
VITE_API_URL=http://localhost:5006
```

### 3. 启动开发服务器

```bash
npm run dev
```

前端将在 `http://localhost:5173` 启动

### 4. 生产构建

```bash
npm run build
npm run preview
```

## 项目结构

```
frontend/
├── components/
│   ├── AudioVisualizer.tsx      # 音频可视化组件
│   ├── FileTranscriber.tsx      # 文件上传转录组件
│   └── RealTimeTranscriber.tsx  # 实时录音转录组件
├── services/
│   └── asrService.ts            # 后端 API 服务
├── App.tsx                      # 主应用组件
├── types.ts                     # TypeScript 类型定义
└── package.json                 # 依赖配置
```

## 与后端对接

### 实时录音模式（WebSocket）

- **协议**: Socket.IO over WebSocket
- **端口**: 5006
- **事件**:
  - `connect` - 建立连接
  - `start_recording` - 开始录音
  - `audio_data` - 发送音频流（Int16Array）
  - `stop_recording` - 停止录音
  - `transcription` - 接收实时识别结果
  - `final_result` - 接收最终三种对比结果

### 文件上传模式（REST API）

- **接口**: `POST /api/asr/transcribe`
- **参数**: FormData with `file` field
- **响应**: JSON with SenseVoice 识别结果

## 开发说明

### 调试

- 打开浏览器控制台查看 Socket.IO 连接日志
- 检查网络标签页确认 WebSocket 连接状态
- 确保后端服务器在 `localhost:5006` 运行

### 常见问题

**Q: 无法连接到后端？**  
A: 确保后端服务器已启动，并检查 `.env.local` 中的 `VITE_API_URL` 配置。

**Q: 录音没有声音？**  
A: 检查浏览器麦克风权限，确保允许访问麦克风。

**Q: 实时转录不显示？**  
A: 打开控制台查看是否有 WebSocket 连接错误。

## 许可证

MIT
