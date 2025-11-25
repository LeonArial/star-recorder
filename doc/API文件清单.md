# API 服务文件清单

## 📁 新创建的文件

### 1. 核心服务器文件

| 文件名 | 说明 | 用途 |
|--------|------|------|
| **asr_api_server.py** | ⭐ API服务器主文件 | 提供RESTful API接口，独立于WebSocket版本 |
| **requirements_api.txt** | API依赖列表 | 安装API服务器所需的Python包 |

### 2. API文档文件

| 文件名 | 格式 | 说明 |
|--------|------|------|
| **openapi.yaml** | YAML | OpenAPI 3.0规范文档（推荐用于Apifox导入） |
| **openapi.json** | JSON | OpenAPI 3.0规范文档（JSON格式） |
| **API_README.md** | Markdown | 详细的API使用文档，包含示例代码 |
| **APIFOX导入指南.md** | Markdown | Apifox导入和使用的完整教程 |
| **API文件清单.md** | Markdown | 本文件，所有API相关文件的索引 |

### 3. 测试工具

| 文件名 | 说明 | 用途 |
|--------|------|------|
| **test_asr_api.py** | Python测试脚本 | 自动化测试所有API接口 |

---

## 🗂️ 原有文件（保持不变）

| 文件名 | 说明 |
|--------|------|
| **realtime_asr_server.py** | WebSocket版本的实时转录服务器 |
| **templates/realtime_asr.html** | WebSocket版本的前端页面 |
| **test_api.py** | LLM API测试脚本 |
| **requirements.txt** | WebSocket版本的依赖 |
| **TODO.md** | 开发日志和任务清单 |

---

## 🚀 快速开始

### 方式一：运行API服务器

```bash
# 1. 安装依赖
pip install -r requirements_api.txt

# 2. 启动服务
python asr_api_server.py

# 3. 测试接口
python test_asr_api.py
```

### 方式二：运行WebSocket服务器

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python realtime_asr_server.py

# 3. 访问前端
浏览器打开 http://localhost:5005
```

---

## 📊 两种服务对比

| 特性 | API服务器 | WebSocket服务器 |
|------|-----------|-----------------|
| **协议** | HTTP/REST | WebSocket |
| **实时性** | 否（上传后处理） | 是（实时流式） |
| **文件** | asr_api_server.py | realtime_asr_server.py |
| **端口** | 5006 | 5005 |
| **前端** | 任意客户端 | templates/realtime_asr.html |
| **适用场景** | 批量处理、第三方集成 | 实时录音转录 |
| **文档** | OpenAPI规范 | HTML页面 |

---

## 📖 文档阅读顺序

如果您是第一次使用，建议按以下顺序阅读：

1. **本文件** (`API文件清单.md`) - 了解文件结构 ✅
2. **API_README.md** - 学习API使用方法
3. **APIFOX导入指南.md** - 导入到Apifox
4. **openapi.yaml** - 查看完整的API规范（可选）

---

## 🔍 文件位置

所有文件位于同一目录：
```
c:\Users\msi\Desktop\code\实时语音转录\
├── asr_api_server.py          # ⭐ API服务器
├── openapi.yaml               # OpenAPI规范（YAML）
├── openapi.json               # OpenAPI规范（JSON）
├── API_README.md              # API文档
├── APIFOX导入指南.md          # Apifox教程
├── API文件清单.md             # 本文件
├── test_asr_api.py            # API测试脚本
├── requirements_api.txt       # API依赖
├── realtime_asr_server.py     # WebSocket服务器
├── templates/
│   └── realtime_asr.html      # WebSocket前端
├── test_api.py                # LLM测试
├── requirements.txt           # WebSocket依赖
└── TODO.md                    # 开发日志
```

---

## ✨ 核心文件说明

### asr_api_server.py

**功能**: RESTful API服务器

**接口列表**:
- `GET /api/health` - 健康检查
- `POST /api/asr/transcribe` - 音频转录
- `GET /api/asr/models` - 模型信息
- `GET /api/asr/formats` - 支持格式

**特点**:
- ✅ 标准REST API
- ✅ 支持文件上传
- ✅ 支持热词
- ✅ 返回三种识别结果
- ✅ CORS支持
- ✅ 完整错误处理

### openapi.yaml / openapi.json

**功能**: OpenAPI 3.0规范文档

**用途**:
- 导入到Apifox
- 导入到Postman
- 导入到Swagger UI
- 自动生成客户端代码
- 自动生成文档

### API_README.md

**功能**: 完整的API使用文档

**内容**:
- 快速开始
- 接口文档
- 使用示例（Python/cURL/JavaScript）
- 配置说明
- 性能参考
- 常见问题

---

## 🎯 使用建议

### 适合使用API服务器的场景

- ✅ 批量音频文件处理
- ✅ 第三方系统集成
- ✅ 移动端APP调用
- ✅ 定时任务处理
- ✅ 需要RESTful接口

### 适合使用WebSocket服务器的场景

- ✅ 实时录音转录
- ✅ 在线演示
- ✅ 需要实时反馈
- ✅ 低延迟要求
- ✅ 浏览器直接使用

---

## 📞 技术支持

如有问题，请查看对应文档：
- API使用问题 → `API_README.md`
- Apifox导入问题 → `APIFOX导入指南.md`
- 代码开发日志 → `TODO.md`
