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
from funasr.utils.postprocess_utils import rich_transcription_postprocess
import soundfile as sf
import time
import threading
import requests
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sensevoice-realtime-asr'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局模型实例
asr_model = None
punc_model = None
sensevoice_model = None

# LLM配置
LLM_API_URL = "http://10.8.75.207:9997/v1/chat/completions"
LLM_API_KEY = "sk-dmowsenrtifmlnpmlhaatxgkxnhbmusjfzgnofvlhtblslwa"
LLM_MODEL = "qwen3:8b"

# 模型加载锁
model_lock = threading.Lock()

def init_models():
    """初始化 ASR、标点与复检模型"""
    global asr_model, punc_model, sensevoice_model
    
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
            
            # 加载标点恢复模型
            print("  - 加载标点模型: ct-punc")
            punc_model = AutoModel(
                model="ct-punc",
                device="cuda:0",
                disable_update=True,
            )
            
            # SenseVoice 复检模型（配置VAD）
            print("  - 加载复检模型: SenseVoiceSmall")
            sensevoice_model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device="cuda:0",
                disable_update=True,
            )
            
            print("✅ 所有模型加载完成！")


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
            language="auto",  # 自动检测语言
            use_itn=False,     # 使用逆文本正则化
            batch_size_s=60,  # 批处理大小
            merge_vad=True,   # 合并VAD结果
        )
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            # 使用官方的富文本后处理函数清理特殊标记
            clean_text = rich_transcription_postprocess(raw_text)
            return clean_text
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


def _call_llm_merge(paraformer_text, sensevoice_text, hotwords=None):
    """调用LLM对两个识别结果进行检查、纠错、合并"""
    
    # 构建系统提示词
    system_prompt = """你是一个专业的语音识别结果校对助手。你的任务是：

1. **对比分析**：对比两个语音识别模型的输出结果
   - Paraformer：实时流式识别结果，速度快但准确度相对较低，可能存在较多错误
   - SenseVoice：完整音频识别结果，准确度高，质量更可靠

2. **纠错合并策略**：
   - 优先采用SenseVoice的结果，它的准确度明显高于Paraformer
   - 在SenseVoice明显有不合理的情况下，参考Paraformer进行补充
   - 识别并纠正识别错误（同音字、多字、少字、错别字、标点符号等）
   - 保持语句通顺、语义连贯

3. **输出要求**：
   - 只输出最终纠正后的文本，不要任何解释说明
   - 不要添加不存在的内容
"""

    # 如果有热词，添加到提示词中
    if hotwords and len(hotwords) > 0:
        hotword_list = "、".join(hotwords)
        system_prompt += f"\n\n5. **专业词汇**（优先使用这些词汇）：\n{hotword_list}"
    
    # 构建用户输入
    user_content = f"""请检查、纠错并合并以下两个语音识别结果：

**Paraformer识别结果**：
{paraformer_text}

**SenseVoice识别结果**：
{sensevoice_text}

请输出纠正后的最终文本："""
    
    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {LLM_API_KEY}'
        }
        
        data = {
            "model": LLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_content
                }
            ],
            "temperature": 0.3,  # 较低温度，保持结果稳定
            "max_tokens": 2000
        }
        
        print(f"🤖 正在调用LLM合并结果...")
        response = requests.post(LLM_API_URL, headers=headers, json=data, timeout=30)
        result = response.json()
        
        if "choices" in result and len(result["choices"]) > 0:
            merged_text = result["choices"][0]["message"]["content"].strip()
            
            # 过滤掉 <think> 标签及其内容
            think_pattern = r"<think>.*?</think>"
            merged_text = re.sub(think_pattern, "", merged_text, flags=re.DOTALL).strip()
            
            print(f"✅ LLM合并完成")
            return merged_text
        else:
            raise Exception(f"LLM响应格式错误: {result}")
            
    except Exception as e:
        error_msg = f"LLM调用失败: {str(e)}"
        print(f"❌ {error_msg}")
        # 如果LLM失败，返回SenseVoice结果作为后备
        return sensevoice_text if sensevoice_text else paraformer_text


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
        self.full_audio = []  # 完整录音缓存（用于SenseVoice）
        
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
            self.full_audio.extend(audio_np)  # 保存完整音频用于最后的SenseVoice识别
        except Exception as e:
            error_msg = f"音频数据处理错误: {str(e)}, 数据长度: {len(audio_data)}"
            print(f"❌ {error_msg}")
            socketio.emit('error', {
                'type': 'audio_processing_error',
                'message': error_msg
            }, to=self.session_id)
        
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
                        error_msg = f"增量标点失败: {str(e)}"
                        print(f"⚠️ {error_msg}")
                        socketio.emit('warning', {
                            'type': 'punctuation_error',
                            'message': error_msg
                        }, to=self.session_id)
                
                # 返回增量结果
                return {
                    "text": text,  # 原始新增文本
                    "full_text_with_punc": self.text_with_punc + self.pending_text,  # 完整带标点文本
                    "is_final": False,
                }
            else:
                self.audio_buffer = self.audio_buffer[self.chunk_stride:]
        except Exception as e:
            error_msg = f"ASR识别错误: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            socketio.emit('error', {
                'type': 'asr_recognition_error',
                'message': error_msg
            }, to=self.session_id)
            
        return None
    
    def finalize(self):
        """处理剩余的音频并返回最终结果"""
        try:
            # 检查是否有剩余音频或缓存内容
            if len(self.audio_buffer) > 0:
                # 有剩余音频：需要填充到chunk_stride以保持维度一致
                remaining_len = len(self.audio_buffer)
                
                # 如果剩余音频不足一个chunk，用0填充
                if remaining_len < self.chunk_stride:
                    padding_len = self.chunk_stride - remaining_len
                    padded_audio = np.concatenate([
                        np.array(self.audio_buffer, dtype=np.float32),
                        np.zeros(padding_len, dtype=np.float32)
                    ])
                    speech_chunk = padded_audio
                else:
                    # 剩余音频超过一个chunk，只取chunk_stride长度
                    speech_chunk = np.array(self.audio_buffer[:self.chunk_stride], dtype=np.float32)
                
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
                    error_msg = f"最终标点恢复失败: {str(e)}"
                    print(f"⚠️ {error_msg}")
                    socketio.emit('warning', {
                        'type': 'final_punctuation_error',
                        'message': error_msg
                    }, to=self.session_id)
                    self.text_with_punc += self.pending_text
            else:
                self.text_with_punc += self.pending_text
            
            paraformer_text = self.text_with_punc
            
            print(f"✅ Paraformer完整文本: {paraformer_text}")
            print(f"📊 总字数: {len(paraformer_text)}")
            
            # 使用SenseVoice对完整音频进行识别
            sensevoice_text = ""
            if len(self.full_audio) > 0:
                print(f"🔁 开始SenseVoice完整识别...")
                try:
                    audio_array = np.array(self.full_audio, dtype=np.float32)
                    sensevoice_text = _run_sensevoice(audio_array, self.sample_rate)
                    print(f"✅ SenseVoice完整文本: {sensevoice_text}")
                    print(f"📊 SenseVoice字数: {len(sensevoice_text)}")
                except Exception as e:
                    error_msg = f"SenseVoice完整识别失败: {str(e)}"
                    print(f"❌ {error_msg}")
                    socketio.emit('warning', {
                        'type': 'sensevoice_full_error',
                        'message': error_msg
                    }, to=self.session_id)
            
            # 调用LLM合并纠错（如果两个结果都有内容）
            llm_merged_text = ""
            if paraformer_text or sensevoice_text:
                llm_merged_text = _call_llm_merge(paraformer_text, sensevoice_text)
                print(f"✅ LLM合并文本: {llm_merged_text}")
                print(f"📊 LLM字数: {len(llm_merged_text)}")
            
            # 发送三种结果到前端
            socketio.emit('final_comparison', {
                'paraformer': paraformer_text,
                'sensevoice': sensevoice_text,
                'llm_merged': llm_merged_text,
                'paraformer_length': len(paraformer_text),
                'sensevoice_length': len(sensevoice_text),
                'llm_merged_length': len(llm_merged_text),
            }, to=self.session_id)
            
            # 清空所有状态
            self.audio_buffer = []
            self.cache = {}
            self.all_text = ""
            self.text_with_punc = ""
            self.pending_text = ""
            self.full_audio = []
            
            return {
                "text": paraformer_text,
                "full_text_with_punc": paraformer_text,
                "is_final": True,
            }
        except Exception as e:
            error_msg = f"最终识别错误: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            socketio.emit('error', {
                'type': 'finalization_error',
                'message': error_msg
            }, to=self.session_id)
            
            # 即使出错，也返回已有的文本
            return {
                "text": self.text_with_punc + self.pending_text,
                "full_text_with_punc": self.text_with_punc + self.pending_text,
                "is_final": True,
            }
    

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
        sessions[sid].full_audio = []  # 清空完整录音缓存
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
    print("📣 实时中文语音识别服务器")
    print("=" * 60)
    print("📝 功能:")
    print("  - 实时流式语音识别 (Paraformer, 600ms延迟)")
    print("  - 自动标点恢复")
    print("  - SenseVoice完整录音识别")
    print("  - LLM智能合并纠错")
    print("  - 三栏对比显示识别结果")
    print("  - 支持热词增强（后续版本）")
    print("  - 中文专用优化")
    print("=" * 60)
    print("🔧 模型:")
    print("  - ASR: paraformer-zh-streaming")
    print("  - 标点: ct-punc")
    print("  - 复检: SenseVoiceSmall")
    print("=" * 60)
    print("🌐 访问地址: http://localhost:5005")
    print("=" * 60)
    
    # 预加载模型
    init_models()
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=5005, debug=False)
