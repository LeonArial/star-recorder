"""
实时语音识别服务器
支持 WebSocket 实时传输音频数据并返回识别结果
"""
import asyncio
import json
import os
import tempfile
import wave
import numpy as np
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from funasr import AutoModel
import threading
import queue
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sensevoice-realtime-asr'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局模型实例
asr_model = None
vad_model = None
punc_model = None
sensevoice_model = None

# SenseVoice 复检相关
sensevoice_queue = queue.Queue()
sensevoice_worker_started = False

# 模型加载锁
model_lock = threading.Lock()

def init_models():
    """初始化 ASR、VAD、标点与复检模型"""
    global asr_model, vad_model, punc_model, sensevoice_model
    
    with model_lock:
        if asr_model is None:
            print("🔄 正在加载模型...")
            
            # 加载中文流式 ASR 模型
            print("  - 加载 ASR 模型: paraformer-zh-streaming")
            asr_model = AutoModel(
                model="paraformer-zh-streaming",
                device="cuda:0",  # 改为 "cuda:0" 使用 GPU
                disable_update=True,
            )
            
            # 加载 VAD 模型（语音端点检测）
            print("  - 加载 VAD 模型: fsmn-vad")
            vad_model = AutoModel(
                model="fsmn-vad",
                device="cuda:0",
                disable_update=True,
            )
            
            # 加载标点恢复模型
            print("  - 加载标点模型: ct-punc")
            punc_model = AutoModel(
                model="ct-punc",
                device="cuda:0",
                disable_update=True,
            )
            
            # SenseVoice 复检模型
            print("  - 加载复检模型: SenseVoiceSmall")
            sensevoice_model = AutoModel(
                model="iic/SenseVoiceSmall",
                trust_remote_code=True,
                device="cuda:0",
                disable_update=True,
            )
            
            print("✅ 所有模型加载完成！")
            _start_sensevoice_worker()


def _start_sensevoice_worker():
    """启动后台 SenseVoice 复检线程"""
    global sensevoice_worker_started
    if sensevoice_worker_started:
        return

    worker = threading.Thread(target=_sensevoice_worker_loop, daemon=True)
    worker.start()
    sensevoice_worker_started = True


def _sensevoice_worker_loop():
    while True:
        task = sensevoice_queue.get()
        if task is None:
            break

        if sensevoice_model is None:
            sensevoice_queue.task_done()
            continue

        try:
            review_text = _run_sensevoice(task["audio"], task["sample_rate"])
            payload = {
                "segment_id": task["segment_id"],
                "text": review_text,
                "preview_text": task.get("preview_text", ""),
            }
            socketio.emit('sensevoice_review', payload, to=task["session_id"])
            print(f"🔁 SenseVoice 复检完成: session={task['session_id']} segment={task['segment_id']}")
        except Exception as exc:
            print(f"❌ SenseVoice 复检失败: {exc}")
        finally:
            sensevoice_queue.task_done()


def _run_sensevoice(audio_samples, sample_rate):
    """调用 SenseVoiceSmall 对音频段进行复检"""
    if audio_samples.size == 0:
        return ""

    temp_path = None
    try:
        temp_path = _save_temp_wav(audio_samples, sample_rate)
        result = sensevoice_model.generate(
            input=temp_path,
            cache={},
            language="auto",
            use_itn=True,
            merge_vad=True,
        )
        if result and len(result) > 0:
            return result[0].get("text", "")
        return ""
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _save_temp_wav(samples, sample_rate):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    audio_int16 = np.clip(samples, -1, 1)
    audio_int16 = (audio_int16 * 32767).astype(np.int16)
    with wave.open(tmp.name, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return tmp.name


def enqueue_sensevoice_task(session_id, segment_id, audio_samples, preview_text, sample_rate=16000):
    """放入 SenseVoice 复检任务队列"""
    if sensevoice_model is None or audio_samples.size == 0:
        return
    task = {
        "session_id": session_id,
        "segment_id": segment_id,
        "audio": audio_samples,
        "preview_text": preview_text,
        "sample_rate": sample_rate,
    }
    sensevoice_queue.put(task)

class RealtimeASR:
    """实时语音识别处理器"""
    
    def __init__(self, session_id):
        self.session_id = session_id
        self.audio_buffer = []
        self.sample_rate = 16000
        self.is_processing = False
        self.last_result = ""
        self.cache = {}  # 流式识别缓存
        self.chunk_size = [0, 10, 5]  # [0, 10, 5] 表示600ms实时出字，300ms未来信息
        self.chunk_stride = self.chunk_size[1] * 960  # 600ms对应的采样点数
        self.all_text = ""  # 累积所有识别文本（无标点）
        self.text_with_punc = ""  # 已添加标点的文本
        self.pending_text = ""  # 等待标点的文本
        self.punc_threshold = 30  # 累积到30字符时做标点
        self.segment_audio = []  # 单段音频缓存
        self.segment_id = 0
        
    def add_audio(self, audio_data):
        """添加音频数据到缓冲区"""
        try:
            # 确保数据长度是 2 的倍数（int16 = 2 bytes）
            if len(audio_data) % 2 != 0:
                # 如果不是偶数，截断最后一个字节
                audio_data = audio_data[:-1]
            
            if len(audio_data) == 0:
                return
            
            # 将字节数据转换为 float32 numpy 数组
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            self.audio_buffer.extend(audio_np)
            self.segment_audio.extend(audio_np)
        except Exception as e:
            print(f"❌ 音频数据处理错误: {e}, 数据长度: {len(audio_data)}")
        
    def process_audio(self):
        """处理缓冲区中的音频（流式）"""
        # 检查是否有足够的音频数据（600ms）
        if len(self.audio_buffer) < self.chunk_stride:
            return None
        
        try:
            # 取出一个 chunk 的音频
            speech_chunk = np.array(self.audio_buffer[:self.chunk_stride], dtype=np.float32)
            
            # 流式 ASR 识别
            asr_result = asr_model.generate(
                input=speech_chunk,
                cache=self.cache,
                is_final=False,
                chunk_size=self.chunk_size,
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
            )
            
            if asr_result and len(asr_result) > 0:
                text = asr_result[0]["text"]
                
                # 累积原始文本
                self.all_text += text
                self.pending_text += text
                
                # 移除已处理的音频
                self.audio_buffer = self.audio_buffer[self.chunk_stride:]
                
                # 增量标点恢复（累积到阈值时处理）
                punc_text = ""
                if len(self.pending_text) >= self.punc_threshold and punc_model:
                    try:
                        # 对待处理文本做标点
                        punc_result = punc_model.generate(input=self.pending_text)
                        if punc_result and len(punc_result) > 0:
                            punc_text = punc_result[0]["text"]
                            
                            # 保留最后10个字作为上下文，避免断句不连贯
                            if len(self.pending_text) > 10:
                                # 已确认的带标点文本
                                confirmed = punc_text[:-10] if len(punc_text) > 10 else ""
                                self.text_with_punc += confirmed
                                
                                # 剩余部分继续等待
                                self.pending_text = self.pending_text[-10:]
                            else:
                                self.text_with_punc += punc_text
                                self.pending_text = ""
                    except Exception as e:
                        print(f"⚠️ 增量标点失败: {e}")
                
                # 返回增量结果
                return {
                    "text": text,  # 原始新增文本
                    "full_text_with_punc": self.text_with_punc + self.pending_text,  # 完整带标点文本
                    "is_final": False,
                }
            else:
                self._maybe_commit_segment(text)
        except Exception as e:
            print(f"❌ 识别错误: {e}")
        except Exception as e:
            print(f"❌ 识别错误: {e}")
            import traceback
            traceback.print_exc()
            
        return None
    
    def finalize(self):
        """处理剩余的音频并返回最终结果"""
        try:
            # 检查是否有剩余音频或缓存内容
            if len(self.audio_buffer) > 0:
                # 有剩余音频：处理剩余音频
                speech_chunk = np.array(self.audio_buffer, dtype=np.float32)
                
                # 最后一个chunk，设置 is_final=True 强制输出缓存
                asr_result = asr_model.generate(
                    input=speech_chunk,
                    cache=self.cache,
                    is_final=True,  # 强制输出最后一个字
                    chunk_size=self.chunk_size,
                    encoder_chunk_look_back=4,
                    decoder_chunk_look_back=1,
                )
            elif self.cache:
                # 没有剩余音频但有缓存：发送一个完整的静音chunk
                speech_chunk = np.zeros(self.chunk_stride, dtype=np.float32)  # 600ms 静音
                
                asr_result = asr_model.generate(
                    input=speech_chunk,
                    cache=self.cache,
                    is_final=True,
                    chunk_size=self.chunk_size,
                    encoder_chunk_look_back=4,
                    decoder_chunk_look_back=1,
                )
            else:
                # 既没有剩余音频也没有缓存：直接返回已有文本
                asr_result = None
            
            if asr_result and len(asr_result) > 0:
                text = asr_result[0]["text"]
                if text:  # 只有非空文本才累积
                    self.all_text += text
                    self.pending_text += text
                    print(f"📝 最终识别: {text}")
            
            # 对剩余待处理文本进行最终标点恢复
            if self.pending_text and punc_model:
                try:
                    punc_result = punc_model.generate(input=self.pending_text)
                    if punc_result and len(punc_result) > 0:
                        self.text_with_punc += punc_result[0]["text"]
                except Exception as e:
                    print(f"⚠️ 最终标点恢复失败: {e}")
                    self.text_with_punc += self.pending_text
            else:
                self.text_with_punc += self.pending_text
            
            final_text = self.text_with_punc
            
            print(f"✅ 完整文本: {final_text}")
            print(f"📊 总字数: {len(final_text)}")
            
            # 清空所有状态
            self.audio_buffer = []
            self.cache = {}
            self.all_text = ""
            self.text_with_punc = ""
            self.pending_text = ""
            self._commit_segment(force=True, final_text=final_text)
            
            return {
                "text": final_text,
                "full_text_with_punc": final_text,
                "is_final": True,
            }
        except Exception as e:
            print(f"❌ 最终识别错误: {e}")
            import traceback
            traceback.print_exc()
            
            # 即使出错，也返回已有的文本
            return {
                "text": self.text_with_punc + self.pending_text,
                "full_text_with_punc": self.text_with_punc + self.pending_text,
                "is_final": True,
            }

    def _maybe_commit_segment(self, latest_text):
        """根据标点或长度触发复检段提交"""
        if not self.segment_audio:
            return
        punctuation_trigger = any(p in latest_text for p in "。？！!?")
        duration_trigger = len(self.segment_audio) >= self.sample_rate * 10
        if punctuation_trigger or duration_trigger:
            self._commit_segment()

    def _commit_segment(self, force=False, final_text=""):
        if not self.segment_audio:
            return
        if not force and len(self.segment_audio) < self.sample_rate:  # 少于1秒不送检
            return
        segment_samples = np.array(self.segment_audio, dtype=np.float32)
        self.segment_audio = []
        segment_id = self.segment_id
        self.segment_id += 1
        preview_text = final_text or (self.text_with_punc + self.pending_text)
        enqueue_sensevoice_task(
            session_id=self.session_id,
            segment_id=segment_id,
            audio_samples=segment_samples,
            preview_text=preview_text,
            sample_rate=self.sample_rate,
        )

# 存储所有会话
sessions = {}

@app.route('/')
def index():
    """主页"""
    return render_template('realtime_asr.html')

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    sid = request.sid
    print(f"✅ 客户端连接: {sid}")
    
    # 确保模型已加载
    if asr_model is None:
        init_models()
    
    # 创建新会话
    sessions[sid] = RealtimeASR(sid)
    emit('connected', {'status': 'ready'})

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    sid = request.sid
    print(f"❌ 客户端断开: {sid}")
    if sid in sessions:
        del sessions[sid]

@socketio.on('start_recording')
def handle_start_recording():
    """开始录音"""
    sid = request.sid
    print(f"🎙️ 开始录音: {sid}")
    if sid in sessions:
        sessions[sid].audio_buffer = []
        sessions[sid].cache = {}
        sessions[sid].all_text = ""
        sessions[sid].text_with_punc = ""
        sessions[sid].pending_text = ""
        emit('recording_started', {'status': 'recording'})

@socketio.on('audio_data')
def handle_audio_data(data):
    """接收音频数据"""
    sid = request.sid
    if sid not in sessions:
        return
    
    session = sessions[sid]
    
    # 添加音频数据
    audio_bytes = data.get('audio')
    if audio_bytes:
        session.add_audio(audio_bytes)
        
        # 处理音频并返回结果
        result = session.process_audio()
        if result:
            emit('transcription', result)

@socketio.on('stop_recording')
def handle_stop_recording():
    """停止录音"""
    sid = request.sid
    print(f"⏹️ 停止录音: {sid}")
    if sid not in sessions:
        return
    
    session = sessions[sid]
    
    # 处理剩余音频
    result = session.finalize()
    if result:
        emit('transcription', result)
    
    emit('recording_stopped', {'status': 'stopped'})

if __name__ == '__main__':
    print("=" * 60)
    print("🎙️ 实时中文语音识别服务器")
    print("=" * 60)
    print("📝 功能:")
    print("  - 实时流式语音识别 (600ms延迟)")
    print("  - 语音端点检测 (VAD)")
    print("  - 自动标点恢复")
    print("  - 中文专用优化")
    print("=" * 60)
    print("🔧 模型:")
    print("  - ASR: paraformer-zh-streaming")
    print("  - VAD: fsmn-vad")
    print("  - 标点: ct-punc")
    print("=" * 60)
    print("🌐 访问地址: http://localhost:5005")
    print("=" * 60)
    
    # 预加载模型
    init_models()
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5005, debug=False)
