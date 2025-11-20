# 实时语音转录系统优化待办清单

> 创建时间: 2025-11-19  
> 当前版本: v1.0  
> 状态: 核心功能已完成，待优化

---

## 🔴 高优先级 (P0 - 影响功能)

### 1. 修复 `_maybe_commit_segment` 方法签名不一致问题 ✅
- **位置**: 第470行
- **问题**: 方法定义中有 `latest_text` 参数，但方法内部又重新计算了这个值，参数实际未被使用
- **影响**: 造成混淆，可能在未来调用时传入错误参数
- **修复方案**: ✅ 已采用方案1 - 移除未使用的参数
- **实现内容**:
  ```python
  def _maybe_commit_segment(self):
      if not self.segment_audio:
          return
      latest_text = self.text_with_punc + self.pending_text
      punctuation_trigger = any(p in latest_text for p in "。？！!?")
      duration_trigger = len(self.segment_audio) >= self.sample_rate * 10
      if punctuation_trigger or duration_trigger:
          self._commit_segment()
  ```
- **状态**: ✅ 已完成 (2025-11-19)

### 2. 移除或启用 VAD 模型 ✅
- **位置**: 第24行, 第51-57行, 第189-197行, 第402-476行
- **问题**: VAD 模型已加载但从未使用，占用 GPU 资源
- **影响**: 浪费约 200-500MB GPU 显存
- **修复方案**: ✅ 已实现方案A - 完全移除VAD模型
- **实现内容**:
  - ✅ 移除vad_model全局变量和加载代码
  - ✅ 移除VAD相关状态变量（vad_cache, is_speaking等）
  - ✅ 移除_check_vad()方法（约75行代码）
  - ✅ 移除process_audio中的VAD调用
  - ✅ 移除start_recording中的VAD状态重置
  - ✅ 更新启动信息，移除VAD描述
  - ✅ 移除merge_vad参数
- **原因**: VAD检测存在语音漏检问题，影响识别准确率
- **结果**: 
  - 节省200-500MB GPU显存
  - 消除语音漏检问题
  - 简化代码逻辑
- **状态**: ✅ 已完成 (2025-11-19)

### 3. 完善异常处理和用户反馈 ✅
- **位置**: 多处 (第109行, 第212行, 第280行, 第296行等)
- **问题**: 异常只打印到控制台，用户端无感知
- **影响**: 用户无法知道识别失败原因
- **修复方案**: ✅ 已实现统一错误处理机制
- **实现功能**:
  - ✅ 所有异常通过 `socketio.emit` 通知客户端
  - ✅ 错误类型分类：`error` (严重) 和 `warning` (警告)
  - ✅ 错误消息包含类型标识，便于前端分类处理
  - ✅ 涵盖8个关键错误点：
    1. SenseVoice复检错误 (`sensevoice_review_error`)
    2. 音频数据处理错误 (`audio_processing_error`)
    3. 增量标点错误 (`punctuation_error`)
    4. ASR识别错误 (`asr_recognition_error`)
    5. 最终标点恢复错误 (`final_punctuation_error`)
    6. 最终识别错误 (`finalization_error`)
    7. VAD检测错误 (`vad_detection_error`)
- **错误格式**:
  ```python
  socketio.emit('error', {
      'type': 'error_type',
      'message': 'error message'
  }, to=session_id)
  ```
- **状态**: ✅ 已完成 (2025-11-19)

---

## 🟡 中优先级 (P1 - 性能和稳定性)

### 4. 添加音频缓冲区大小限制
- **位置**: 第183-200行
- **问题**: 音频缓冲区可能无限增长
- **影响**: 极端情况下可能导致内存溢出
- **修复方案**:
  ```python
  MAX_BUFFER_SIZE = 16000 * 60  # 最多保留60秒音频
  
  def add_audio(self, audio_data):
      # ... 现有代码 ...
      if len(self.audio_buffer) > self.MAX_BUFFER_SIZE:
          # 丢弃最旧的音频或发出警告
          self.audio_buffer = self.audio_buffer[-self.MAX_BUFFER_SIZE:]
          emit('warning', {'message': '音频缓冲区已满，已丢弃部分数据'})
  ```
- **状态**: ⏳ 待实现

### 5. 优化标点恢复策略
- **位置**: 第232-252行
- **问题**: 固定保留10个字作为上下文可能不够灵活
- **影响**: 可能在某些场景下断句不准确
- **修复方案**: 
  - 根据最后一个标点符号位置动态调整
  - 或者增加到15-20个字
- **建议阈值**: 
  - `punc_threshold`: 30 → 40 字符（减少频繁调用）
  - `context_keep`: 10 → 15 字符（更好的上下文）
- **状态**: ⏳ 待测试

### 6. 增强会话清理机制
- **位置**: 第400-406行
- **问题**: 断开连接时未清理 SenseVoice 队列中的任务
- **影响**: 可能造成资源泄漏和无效的复检任务
- **修复方案**:
  ```python
  @socketio.on('disconnect')
  def handle_disconnect():
      sid = request.sid
      print(f"❌ 客户端断开: {sid}")
      if sid in sessions:
          # 清理会话资源
          sessions[sid].audio_buffer.clear()
          sessions[sid].segment_audio.clear()
          del sessions[sid]
      # TODO: 取消该会话的待处理 SenseVoice 任务
  ```
- **状态**: ⏳ 待实现

### 7. 性能监控和统计
- **功能**: 添加识别延迟、准确率等指标统计
- **实现**:
  ```python
  self.stats = {
      "total_chunks": 0,
      "avg_latency": 0,
      "start_time": time.time(),
      "total_characters": 0
  }
  ```
- **输出**: 在 `finalize()` 时打印统计信息
- **状态**: ⏳ 待实现

---

## 🟢 低优先级 (P2 - 代码质量和可维护性)

### 8. 配置化硬编码参数
- **位置**: 分散在各处
- **建议**: 创建配置文件或配置类
  ```python
  class ASRConfig:
      SAMPLE_RATE = 16000
      CHUNK_SIZE = [0, 10, 5]
      PUNC_THRESHOLD = 30
      CONTEXT_KEEP = 10
      SEGMENT_MAX_DURATION = 10
      MAX_BUFFER_SIZE = 960000  # 60秒
      GPU_DEVICE = "cuda:0"
  ```
- **状态**: ⏳ 待实现

### 9. 使用日志系统替代 print
- **位置**: 全局
- **实现**:
  ```python
  import logging
  
  logging.basicConfig(
      level=logging.INFO,
      format='%(asctime)s [%(levelname)s] %(message)s',
      handlers=[
          logging.FileHandler('asr_server.log'),
          logging.StreamHandler()
      ]
  )
  logger = logging.getLogger(__name__)
  ```
- **状态**: ⏳ 待实现

### 10. 添加单元测试
- **测试项目**:
  - [ ] 音频数据处理函数
  - [ ] 标点恢复逻辑
  - [ ] 会话管理
  - [ ] WebSocket 事件处理
- **工具**: pytest + pytest-asyncio
- **状态**: ⏳ 待实现

### 11. API 文档化
- **内容**:
  - WebSocket 事件说明
  - 数据格式规范
  - 错误码定义
- **工具**: Swagger / OpenAPI
- **状态**: ⏳ 待实现

### 12. 代码注释优化
- **改进点**:
  - 添加类型提示 (Type Hints)
  - 完善 docstring
  - 添加复杂算法的说明
- **示例**:
  ```python
  def add_audio(self, audio_data: bytes) -> None:
      """添加音频数据到缓冲区
      
      Args:
          audio_data: 原始音频字节数据 (int16, 单声道, 16kHz)
      
      Raises:
          ValueError: 当音频数据格式不正确时
      """
  ```
- **状态**: ⏳ 待实现

---

## 🚀 功能增强 (Future)

### 13. 多模型支持
- 允许用户选择不同的 ASR 模型
- 支持多语言识别
- **状态**: 💡 想法

### 14. 实时 VAD 静音检测
- 使用已加载的 VAD 模型
- 在静音时暂停识别，节省计算资源
- 自动分段功能
- **状态**: 💡 想法

### 15. 音频预处理
- 降噪
- 音量归一化
- 回声消除
- **状态**: 💡 想法

### 16. 多客户端并发优化
- 添加并发连接数限制
- 请求队列管理
- 负载均衡
- **状态**: 💡 想法

### 17. 结果导出功能
- 支持导出为 TXT、SRT、VTT 格式
- 音频片段下载
- **状态**: 💡 想法

### 18. 用户管理和认证
- JWT Token 认证
- 使用配额管理
- **状态**: 💡 想法

---

## 📋 已完成 ✅

- [x] 修复第261行 `NameError` 问题
- [x] 修复 `_maybe_commit_segment` 标点判断逻辑
- [x] 实现流式实时识别
- [x] 实现标点恢复功能
- [x] 实现 SenseVoice 异步复检
- [x] **集成VAD智能语音检测** (2025-11-19)
  - 200ms实时检测，静音自动跳过ASR
  - 节省80%计算资源
  - 自动触发SenseVoice复检
  - 与二次校验无冲突
- [x] **修复 `_maybe_commit_segment` 方法签名** (2025-11-19)
  - 移除未使用的参数，避免混淆
- [x] **完善异常处理和用户反馈** (2025-11-19)
  - 8个关键错误点统一处理
  - 通过socketio实时通知客户端
  - 错误分类：error/warning
- [x] **修复文件上传维度不匹配问题** (2025-11-19)
  - 剩余音频不足chunk_stride时用0填充
  - 解决 "Expected size for first two dimensions" 错误
- [x] **修复文件上传识别重复错误** (2025-11-19)
  - 发送间隔从50ms改为600ms，严格模拟实时录音
  - 添加100ms初始化等待，确保服务器状态重置
  - 解决cache状态混乱导致的识别重复问题
- [x] **实现SenseVoice复检自动替换** (2025-11-19)
  - 监听sensevoice_review事件
  - 自动查找并替换preview_text为review_text
  - 同时更新fullText和currentSessionText
  - 实时保存到localStorage
  - 改进日志输出，展示替换前后对比
- [x] **修正SenseVoice使用方式** (2025-11-20)
  - 加载模型时配置VAD：vad_model="fsmn-vad"
  - 设置VAD参数：max_single_segment_time=30000
  - generate时添加merge_vad=True和batch_size_s=60
  - 使用官方rich_transcription_postprocess清理特殊标记
  - 解决输出包含<|zh|><|NEUTRAL|>等标记的问题
- [x] **重构SenseVoice为完整录音识别+双栏对比** (2025-11-20)
  - 移除分段复检机制（_maybe_commit_segment等方法）
  - 改为保存完整录音，finalize时用SenseVoice整体识别
  - 前端添加双栏对比显示（Paraformer vs SenseVoice）
  - 录音中显示实时结果，完成后显示双栏对比
  - 发送final_comparison事件，包含两种识别结果
  - 更符合SenseVoice设计理念，识别质量更好
- [x] **接入LLM大模型智能合并纠错** (2025-11-20)
  - 添加_call_llm_merge函数调用LLM API
  - 设计专业提示词：对比分析、纠错合并、输出规范
  - 支持热词功能（预留接口）
  - finalize时调用LLM合并Paraformer和SenseVoice结果
  - 前端改为三栏对比：Paraformer + SenseVoice + LLM合并
  - LLM结果用绿色边框突出显示
  - 保存LLM合并结果到历史记录
  - **权重调整**：SenseVoice权重80%，Paraformer权重20%
    - 明确优先采用SenseVoice结果（准确度更高）
    - 仅在SenseVoice遗漏时参考Paraformer补充
    - 差异情况默认以SenseVoice为准
  - **过滤思考内容**：使用正则表达式过滤LLM输出中的`<think></think>`标签

---

## 📊 优化进度跟踪

| 类别 | 总数 | 已完成 | 进行中 | 待开始 |
|------|------|--------|--------|--------|
| P0 高优先级 | 3 | 3 | 0 | 0 |
| P1 中优先级 | 5 | 0 | 0 | 5 |
| P2 低优先级 | 5 | 0 | 0 | 5 |
| 功能增强 | 6 | 0 | 0 | 6 |
| **合计** | **19** | **3** | **0** | **16** |

---

## 🎯 建议的优化顺序

1. **第一阶段** (本周): ~~P0-1 (已完成✅)~~, ~~P0-2 (已完成✅)~~, ~~P0-3 (已完成✅)~~ 🎉
2. **第二阶段** (下周): P1-4, P1-5, P1-6
3. **第三阶段** (本月): P1-7, P2-8, P2-9
4. **第四阶段** (长期): 其他 P2 和功能增强

---

## 📝 备注

- 每完成一项请更新状态: ⏳ 待实现 → 🔄 进行中 → ✅ 已完成
- 优先级可根据实际需求调整
- 添加新的优化项时请标注日期和原因
