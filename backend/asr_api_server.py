"""
语音识别API服务器
提供RESTful API接口进行音频转录
支持三种识别结果对比：Paraformer + SenseVoice + LLM智能合并
"""
import os
import tempfile
import wave
import json
import threading
import numpy as np
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess
import soundfile as sf
import librosa
import requests
import re
import traceback
import emoji

app = Flask(__name__)
app.config['SECRET_KEY'] = 'asr-api-server'
CORS(app)  # 允许跨域请求

# SocketIO 配置（优化长时间录音稳定性）
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    async_handlers=False,
    # 增加 ping 超时时间（默认20秒太短，长时间录音可能超时）
    ping_timeout=120,  # 120秒超时
    ping_interval=30,  # 每30秒发送一次ping
    # 增加最大缓冲区大小（支持更大的音频数据帧）
    max_http_buffer_size=10 * 1024 * 1024,  # 10MB
)

# 全局模型实例
asr_model = None
punc_realtime_model = None  # 实时标点模型
vad_model = None  # VAD语音端点检测模型
sensevoice_model = None

# 全局模型推理锁（threading 模式下避免并发推理导致缓存/内部状态竞争）
asr_model_lock = threading.Lock()
punc_model_lock = threading.Lock()
vad_model_lock = threading.Lock()
sensevoice_model_lock = threading.Lock()

# LLM配置
LLM_API_URL = "http://10.8.75.207:9997/v1/chat/completions"
LLM_API_KEY = "sk-dmowsenrtifmlnpmlhaatxgkxnhbmusjfzgnofvlhtblslwa"
LLM_MODEL = "qwen3:8b"

# 支持的音频格式
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'wma', 'webm'}

# 模型缓存目录（Docker挂载或本地目录）
# 优先使用环境变量，其次使用项目目录下的 models_cache
MODELS_CACHE_DIR = os.environ.get('MODELSCOPE_CACHE', 
    os.path.join(os.path.dirname(__file__), 'models_cache'))
HF_CACHE_DIR = os.environ.get('HF_HOME',
    os.path.join(os.path.dirname(__file__), 'hf_cache'))

# 存储实时录音会话
active_sessions = {}
active_sessions_lock = threading.Lock()

def init_models():
    """初始化 ASR、标点、VAD与复检模型
    
    模型缓存策略：
    - 优先从 MODELSCOPE_CACHE 目录加载已有模型
    - 如果模型不存在则自动下载到缓存目录
    - Docker运行时通过挂载卷持久化模型，避免重复下载
    """
    global asr_model, punc_realtime_model, vad_model, sensevoice_model
    
    if asr_model is None:
        print("🔄 正在加载模型...")
        
        # 设置模型缓存环境变量（确保FunASR使用正确的缓存路径）
        os.environ['MODELSCOPE_CACHE'] = MODELS_CACHE_DIR
        os.environ['HF_HOME'] = HF_CACHE_DIR
        
        # 确保缓存目录存在
        os.makedirs(MODELS_CACHE_DIR, exist_ok=True)
        os.makedirs(HF_CACHE_DIR, exist_ok=True)
        
        print(f"📁 模型缓存目录: {MODELS_CACHE_DIR}")
        print(f"📁 HuggingFace缓存目录: {HF_CACHE_DIR}")
        
        # 检测设备（CUDA GPU > Apple MPS > CPU）
        try:
            import torch
            if torch.cuda.is_available():
                # NVIDIA GPU（Linux/Windows 服务器）
                device = "cuda:0"
                print(f"✅ 检测到 CUDA GPU: {torch.cuda.get_device_name(0)}")
            elif torch.backends.mps.is_available() and torch.backends.mps.is_built():
                # Apple Silicon MPS（M1/M2/M3/M4 Mac）
                device = "mps"
                print("✅ 检测到 Apple Silicon，使用 MPS 加速")
            else:
                device = "cpu"
                print("⚠️ 未检测到 GPU，使用 CPU 模式（性能较低）")
        except Exception as e:
            device = "cpu"
            print(f"⚠️ 设备检测失败，使用 CPU 模式: {e}")
        
        # FunASR 模型名到实际目录名的映射
        MODEL_DIR_MAP = {
            "paraformer-zh-streaming": "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
            "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727": "punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727",
            "fsmn-vad": "speech_fsmn_vad_zh-cn-16k-common-pytorch",
            "iic/SenseVoiceSmall": "SenseVoiceSmall",
        }
        
        def get_model_path(model_name):
            """获取模型本地路径，如果已缓存则返回本地路径，否则返回模型名（触发下载）"""
            actual_name = MODEL_DIR_MAP.get(model_name, model_name.split('/')[-1])
            local_path = os.path.join(MODELS_CACHE_DIR, 'models', 'iic', actual_name)
            if os.path.exists(local_path):
                return local_path, True  # 返回本地路径
            return model_name, False  # 返回模型名触发下载
        
        # 加载中文流式 ASR 模型
        model_name = "paraformer-zh-streaming"
        model_path, is_cached = get_model_path(model_name)
        print(f"  - 加载 ASR 模型: {model_name} {'(已缓存)' if is_cached else '(首次下载)'} (设备: {device})")
        asr_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # 加载实时标点模型（支持流式处理，带缓存）
        model_name = "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727"
        model_path, is_cached = get_model_path(model_name)
        print(f"  - 加载实时标点模型: punc_realtime {'(已缓存)' if is_cached else '(首次下载)'} (设备: {device})")
        punc_realtime_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # 加载VAD语音端点检测模型（实时）
        model_name = "fsmn-vad"
        model_path, is_cached = get_model_path(model_name)
        print(f"  - 加载VAD模型: {model_name} {'(已缓存)' if is_cached else '(首次下载)'} (设备: {device})")
        vad_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # SenseVoice 复检模型（配置VAD）
        model_name = "iic/SenseVoiceSmall"
        model_path, is_cached = get_model_path(model_name)
        vad_path, _ = get_model_path("fsmn-vad")  # VAD 模型路径
        print(f"  - 加载复检模型: SenseVoiceSmall {'(已缓存)' if is_cached else '(首次下载)'} (设备: {device})")
        sensevoice_model = AutoModel(
            model=model_path,
            vad_model=vad_path,
            vad_kwargs={"max_single_segment_time": 30000},
            device=device,
            disable_update=True,
            use_itn=True,
        )
        
        print("✅ 所有模型加载完成！")


def allowed_file(filename):
    """检查文件格式是否支持"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _clean_sensevoice_text(text):
    """清理 SenseVoice 输出中的虚假文本
    
    SenseVoice 有时会输出实际语音中不存在的填充词，如 Yeah./Okay./Oh./Hmm. 等
    """
    if not text:
        return text
    
    # 需要移除的虚假文本模式（不区分大小写）
    fake_patterns = [
        r'\bYeah\.?\s*',
        r'\bOkay\.?\s*',
        r'\bOK\.?\s*',
        r'\bOh\.?\s*',
        r'\bHmm\.?\s*',
        r'\bUh\.?\s*',
        r'\bUm\.?\s*',
        r'\bAh\.?\s*',
        r'\bEh\.?\s*',
        r'\bWell\.?\s*',
    ]
    
    cleaned = text
    for pattern in fake_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # 清理多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    return cleaned


def _run_sensevoice(audio_path):
    """使用SenseVoice进行完整音频识别（文件路径）"""
    try:
        with sensevoice_model_lock:
            result = sensevoice_model.generate(
                input=audio_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,  # 合并后的音频片段长度
            )
        
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            # 使用官方的富文本后处理函数清理特殊标记
            clean_text = rich_transcription_postprocess(raw_text)
            # 去除emoji
            clean_text = emoji.replace_emoji(clean_text, replace='')
            # 去除虚假填充词
            clean_text = _clean_sensevoice_text(clean_text)
            return clean_text
        
        return ""
        
    except Exception as e:
        raise Exception(f"SenseVoice识别失败: {str(e)}")


def _run_sensevoice_with_timestamps(audio_path):
    """使用独立VAD模型获取语音段时间戳，再用SenseVoice识别每段
    
    Returns:
        tuple: (full_text, segments)
            - full_text: 完整文本
            - segments: 句级时间戳列表 [{'text': '句子', 'start_ms': 0, 'end_ms': 1000}, ...]
    """
    try:
        # 先使用独立VAD模型检测语音段
        print("🔍 VAD检测语音段...")
        with vad_model_lock:
            vad_result = vad_model.generate(
                input=audio_path,
                cache={},
            )
        
        # 解析VAD结果，格式为 [[start1, end1], [start2, end2], ...]
        vad_segments = []
        if vad_result and len(vad_result) > 0:
            vad_data = vad_result[0].get("value", [])
            if vad_data:
                vad_segments = vad_data
        
        print(f"  📊 VAD检测到 {len(vad_segments)} 个语音段")
        
        # 如果VAD没有检测到分段，使用SenseVoice整体识别
        if not vad_segments:
            print("  ⚠️ VAD未检测到分段，使用整体识别")
            text = _run_sensevoice(audio_path)
            return text, [{'text': text, 'start_ms': 0, 'end_ms': 0}] if text else (text, [])
        
        # 读取音频数据
        audio_data, sr = librosa.load(audio_path, sr=16000, mono=True)
        
        segments = []
        
        # 对每个VAD段进行识别
        for i, (start_ms, end_ms) in enumerate(vad_segments):
            # 转换为采样点
            start_sample = int(start_ms * sr / 1000)
            end_sample = int(end_ms * sr / 1000)
            
            # 提取音频段
            segment_audio = audio_data[start_sample:end_sample]
            
            if len(segment_audio) < sr * 0.1:  # 少于 0.1 秒跳过
                continue
            
            # 保存临时文件用于识别
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_path = temp_file.name
            temp_file.close()
            sf.write(temp_path, segment_audio, sr)
            
            try:
                # 识别该段
                with sensevoice_model_lock:
                    result = sensevoice_model.generate(
                        input=temp_path,
                        cache={},
                        language="auto",
                        use_itn=True,
                    )
                
                if result and len(result) > 0:
                    raw_text = result[0].get("text", "")
                    clean_text = rich_transcription_postprocess(raw_text)
                    clean_text = emoji.replace_emoji(clean_text, replace='')
                    clean_text = _clean_sensevoice_text(clean_text)
                    
                    if clean_text.strip():
                        segments.append({
                            'text': clean_text,
                            'start_ms': int(start_ms),
                            'end_ms': int(end_ms)
                        })
                        print(f"  ✅ 段{i+1}: {start_ms/1000:.1f}s-{end_ms/1000:.1f}s: {clean_text[:30]}...")
            finally:
                os.remove(temp_path)
        
        full_text = ''.join([seg['text'] for seg in segments])
        print(f"✅ 识别完成: {len(full_text)}字, {len(segments)}段")
        return full_text, segments
        
    except Exception as e:
        print(f"⚠️ SenseVoice时间戳识别失败: {str(e)}")
        traceback.print_exc()
        return "", []


def _run_sensevoice_array(audio_array, sample_rate):
    """使用SenseVoice进行完整音频识别（numpy数组）"""
    try:
        # 保存为临时文件
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_path = temp_file.name
        temp_file.close()
        
        sf.write(temp_path, audio_array, sample_rate)
        
        with sensevoice_model_lock:
            result = sensevoice_model.generate(
                input=temp_path,
                cache={},
                language="auto",
                use_itn=True,
                batch_size_s=60,
                merge_vad=True,
                merge_length_s=15,  # 合并后的音频片段长度
            )
        
        # 删除临时文件
        os.remove(temp_path)
        
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            clean_text = rich_transcription_postprocess(raw_text)
            # 去除emoji
            clean_text = emoji.replace_emoji(clean_text, replace='')
            # 去除虚假填充词
            clean_text = _clean_sensevoice_text(clean_text)
            return clean_text
        
        return ""
        
    except Exception as e:
        raise Exception(f"SenseVoice识别失败: {str(e)}")


# ==================== 实时录音处理类 ====================

class RealtimeASR:
    """实时语音识别处理器
    
    优化特性：
    - 使用 fsmn-vad 进行实时语音端点检测
    - 使用实时标点模型进行流式标点恢复
    - 基于 VAD 结果智能分句，提升识别体验
    """
    
    def __init__(self, session_id):
        self.session_id = session_id
        self.sample_rate = 16000
        self.lock = threading.Lock()
        self.is_finalizing = False
        
        # ASR 相关配置
        self.audio_buffer = []  # ASR 音频缓冲区
        self.asr_cache = {}  # 流式 ASR 识别缓存
        self.chunk_size = [0, 10, 5]  # [0, 10, 5] 表示 600ms 实时出字
        self.asr_chunk_stride = self.chunk_size[1] * 960  # 600ms = 9600 采样点
        
        # VAD 相关配置
        self.vad_buffer = []  # VAD 音频缓冲区
        self.vad_cache = {}  # VAD 检测缓存
        self.vad_chunk_size = 200  # VAD 检测粒度 200ms
        self.vad_chunk_stride = int(self.vad_chunk_size * self.sample_rate / 1000)  # 3200 采样点
        self.is_speech_active = False  # 当前是否检测到语音
        self.speech_start_time = 0  # 语音开始时间（毫秒）
        self.total_audio_ms = 0  # 已处理的音频总时长（毫秒）
        
        # 标点相关配置
        self.punc_cache = {}  # 实时标点缓存
        self.all_text = ""  # 累积所有识别文本（无标点）
        self.text_with_punc = ""  # 已添加标点的文本
        self.pending_text = ""  # 等待标点的文本
        self.sentence_buffer = ""  # 当前句子缓冲区（VAD 分句用）
        
        # 完整录音缓存（用于 SenseVoice 最终识别）
        self.full_audio = []
        
        # 实时时间戳跟踪
        self.asr_processed_ms = 0  # ASR 已处理的音频时长（毫秒）
        self.segments = []  # 带时间戳的文本片段列表 [{text, start_ms, end_ms}, ...]
        self.current_segment_start = 0  # 当前片段起始时间
        
    def add_audio(self, audio_data):
        """添加音频数据到缓冲区"""
        try:
            # 确保数据长度是 2 的倍数（int16 = 2 bytes）
            if len(audio_data) % 2 != 0:
                audio_data = audio_data[:-1]
            
            if len(audio_data) == 0:
                return
            
            # 将字节数据转换为 float32 numpy 数组
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            self.audio_buffer.extend(audio_np)
            self.vad_buffer.extend(audio_np)
            self.full_audio.extend(audio_np)  # 保存完整音频用于 SenseVoice
        except Exception as e:
            print(f"❌ 音频数据处理错误: {str(e)}")
    
    def _process_vad(self):
        """处理 VAD 语音端点检测
        
        返回值：
        - None: 没有检测到端点变化
        - {'type': 'start', 'time': ms}: 检测到语音开始
        - {'type': 'end', 'time': ms}: 检测到语音结束
        """
        if len(self.vad_buffer) < self.vad_chunk_stride:
            return None
        
        try:
            # 取出 VAD chunk
            vad_chunk = np.array(self.vad_buffer[:self.vad_chunk_stride], dtype=np.float32)
            
            # VAD 检测
            is_final = False
            try:
                with vad_model_lock:
                    vad_result = vad_model.generate(
                        input=vad_chunk,
                        cache=self.vad_cache,
                        is_final=is_final,
                        chunk_size=self.vad_chunk_size
                    )
            except Exception as e:
                print(f"⚠️ VAD 检测错误 [{self.session_id}]: {str(e)}")
                self.vad_cache = {}
                try:
                    with vad_model_lock:
                        vad_result = vad_model.generate(
                            input=vad_chunk,
                            cache=self.vad_cache,
                            is_final=is_final,
                            chunk_size=self.vad_chunk_size
                        )
                except Exception as e2:
                    print(f"⚠️ VAD 重试失败 [{self.session_id}]: {str(e2)}")
                    self.vad_buffer = self.vad_buffer[self.vad_chunk_stride:]
                    self.total_audio_ms += self.vad_chunk_size
                    return None

            self.vad_buffer = self.vad_buffer[self.vad_chunk_stride:]
            
            self.total_audio_ms += self.vad_chunk_size
            
            if vad_result and len(vad_result) > 0:
                segments = vad_result[0].get("value", [])
                
                # 解析 VAD 输出
                # [[beg, end]]: 完整语音段
                # [[beg, -1]]: 只检测到起始点
                # [[-1, end]]: 只检测到结束点
                # []: 无检测
                
                for seg in segments:
                    if len(seg) >= 2:
                        beg, end = seg[0], seg[1]
                        
                        if beg >= 0 and end == -1:
                            # 检测到语音开始
                            if not self.is_speech_active:
                                self.is_speech_active = True
                                self.speech_start_time = beg
                                return {'type': 'start', 'time': beg}
                        
                        elif beg == -1 and end >= 0:
                            # 检测到语音结束
                            if self.is_speech_active:
                                self.is_speech_active = False
                                return {'type': 'end', 'time': end}
                        
                        elif beg >= 0 and end >= 0:
                            # 完整语音段（开始和结束）
                            return {'type': 'segment', 'start': beg, 'end': end}
            
            return None
            
        except Exception as e:
            print(f"⚠️ VAD 检测错误 [{self.session_id}]: {str(e)}")
            return None
    
    def _apply_realtime_punc(self, text):
        """使用实时标点模型添加标点
        
        实时标点模型支持流式处理，会根据上下文智能添加标点
        """
        if not text or not punc_realtime_model:
            return text
        
        try:
            with punc_model_lock:
                punc_result = punc_realtime_model.generate(
                    input=text,
                    cache=self.punc_cache
                )
            if punc_result and len(punc_result) > 0:
                return punc_result[0].get("text", text)
        except Exception as e:
            print(f"⚠️ 实时标点恢复失败: {str(e)}")
        
        return text
        
    def process_audio(self):
        """处理缓冲区中的音频（流式）
        
        优化逻辑：
        1. 先进行 VAD 检测，获取语音端点信息
        2. 进行流式 ASR 识别
        3. 使用实时标点模型添加标点
        4. 当 VAD 检测到语音结束时，强制输出当前句子
        """
        # 先处理 VAD
        vad_event = self._process_vad()
        
        # 检查是否有足够的音频数据进行 ASR（600ms）
        if len(self.audio_buffer) < self.asr_chunk_stride:
            # 如果有 VAD 事件但没有足够音频，返回 VAD 状态
            if vad_event:
                return {
                    "text": "",
                    "punc_text": "",
                    "full_text": self.text_with_punc + self.pending_text,
                    "is_final": False,
                    "vad_event": vad_event
                }
            return None
        
        try:
            # 取出一个 chunk 的音频
            speech_chunk = np.array(self.audio_buffer[:self.asr_chunk_stride], dtype=np.float32)
            
            # 流式 ASR 识别
            try:
                with asr_model_lock:
                    asr_result = asr_model.generate(
                        input=speech_chunk,
                        cache=self.asr_cache,
                        is_final=False,
                        chunk_size=self.chunk_size,
                        encoder_chunk_look_back=4,
                        decoder_chunk_look_back=1,
                    )
            except Exception as e:
                print(f"❌ 流式识别错误 [{self.session_id}]: {str(e)}")
                self.asr_cache = {}
                try:
                    with asr_model_lock:
                        asr_result = asr_model.generate(
                            input=speech_chunk,
                            cache=self.asr_cache,
                            is_final=False,
                            chunk_size=self.chunk_size,
                            encoder_chunk_look_back=4,
                            decoder_chunk_look_back=1,
                        )
                except Exception as e2:
                    print(f"❌ 流式识别重试失败 [{self.session_id}]: {str(e2)}")
                    self.audio_buffer = self.audio_buffer[self.asr_chunk_stride:]
                    self.asr_processed_ms += 600
                    return None

            self.audio_buffer = self.audio_buffer[self.asr_chunk_stride:]
            
            # 记录当前 chunk 的时间范围
            chunk_start_ms = self.asr_processed_ms
            chunk_end_ms = chunk_start_ms + 600  # 每个 chunk 600ms
            self.asr_processed_ms = chunk_end_ms
            
            text = ""
            punc_text = ""
            current_segment = None
            
            if asr_result and len(asr_result) > 0:
                text = asr_result[0].get("text", "")
                
                if text:
                    # 累积原始文本
                    self.all_text += text
                    self.pending_text += text
                    self.sentence_buffer += text
                    
                    # 检查是否需要进行标点处理
                    # 条件：VAD 检测到语音结束，或累积文本超过阈值
                    should_apply_punc = False
                    
                    if vad_event and vad_event.get('type') == 'end':
                        # VAD 检测到语音结束，强制处理当前句子
                        should_apply_punc = True
                    elif len(self.pending_text) >= 20:
                        # 累积超过 20 字符时处理
                        should_apply_punc = True
                    
                    if should_apply_punc and self.pending_text:
                        # 使用实时标点模型
                        punc_text = self._apply_realtime_punc(self.pending_text)
                        self.text_with_punc += punc_text
                        
                        # 记录带时间戳的片段（实时粗略时间戳）
                        current_segment = {
                            'text': punc_text,
                            'start_ms': self.current_segment_start,
                            'end_ms': chunk_end_ms
                        }
                        self.segments.append(current_segment)
                        
                        # 更新下一个片段的起始时间
                        self.current_segment_start = chunk_end_ms
                        self.pending_text = ""
                        
                        # 如果是 VAD 结束事件，重置句子缓冲区
                        if vad_event and vad_event.get('type') == 'end':
                            self.sentence_buffer = ""
            
            return {
                "text": text,
                "punc_text": punc_text,
                "full_text": self.text_with_punc + self.pending_text,
                "is_final": False,
                "vad_event": vad_event,
                "is_speech_active": self.is_speech_active,
                "segment": current_segment,  # 当前片段的时间戳信息
                "current_time_ms": chunk_end_ms  # 当前音频时间
            }
            
        except Exception as e:
            print(f"❌ 流式识别错误 [{self.session_id}]: {str(e)}")
            return None
    
    def finalize(self):
        """完成识别，生成最终结果"""
        try:
            # 处理最后剩余的音频
            if len(self.audio_buffer) >= 4800:  # 至少 300ms
                speech_chunk = np.array(self.audio_buffer, dtype=np.float32)
                with asr_model_lock:
                    asr_result = asr_model.generate(
                        input=speech_chunk,
                        cache=self.asr_cache,
                        is_final=True,
                        chunk_size=self.chunk_size,
                    )
                
                if asr_result and len(asr_result) > 0:
                    text = asr_result[0].get("text", "")
                    if text:
                        self.all_text += text
                        self.pending_text += text
            
            # 对剩余待处理文本使用实时标点模型
            if self.pending_text:
                punc_text = self._apply_realtime_punc(self.pending_text)
                self.text_with_punc += punc_text
            
            paraformer_text = self.text_with_punc
            print(f"✅ Paraformer完整文本: {paraformer_text} ({len(paraformer_text)}字)")
            
            # 使用 VAD分段 + SenseVoice识别（不再自动调用LLM纠错）
            sensevoice_text = ""
            timestamps = []
            if len(self.full_audio) > 0:
                print(f"🔁 开始VAD分段+SenseVoice识别...")
                try:
                    # 保存临时音频文件
                    audio_array = np.array(self.full_audio, dtype=np.float32)
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
                    temp_path = temp_file.name
                    temp_file.close()
                    sf.write(temp_path, audio_array, self.sample_rate)
                    
                    # 调用不带LLM的SenseVoice识别
                    sensevoice_text, timestamps = _run_sensevoice_with_timestamps(temp_path)
                    os.remove(temp_path)
                    
                    print(f"✅ 完成: SenseVoice文本 {len(sensevoice_text)}字, {len(timestamps)} 个句子")
                except Exception as e:
                    print(f"❌ VAD+SenseVoice识别失败: {str(e)}")
                    # 降级：使用普通识别
                    try:
                        sensevoice_text = _run_sensevoice_array(audio_array, self.sample_rate)
                    except:
                        pass
            
            return {
                'paraformer': paraformer_text,
                'sensevoice': sensevoice_text,
                'paraformer_length': len(paraformer_text),
                'sensevoice_length': len(sensevoice_text),
                'timestamps': timestamps,  # VAD句级时间戳（SenseVoice原始文本）
                'realtime_segments': self.segments,  # 实时粗略时间戳（备用）
            }
            
        except Exception as e:
            print(f"❌ 最终识别错误: {str(e)}")
            return {
                'paraformer': self.text_with_punc + self.pending_text,
                'sensevoice': '',
                'paraformer_length': len(self.text_with_punc + self.pending_text),
                'sensevoice_length': 0,
                'llm_merged_length': 0,
            }


# ==================== WebSocket 事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    session_id = request.sid
    print(f"✅ 客户端连接: {session_id}")
    emit('connected', {'session_id': session_id})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    session_id = request.sid
    with active_sessions_lock:
        active_sessions.pop(session_id, None)
    print(f"❌ 客户端断开: {session_id}")


@socketio.on('start_recording')
def handle_start_recording():
    """开始录音"""
    session_id = request.sid
    with active_sessions_lock:
        active_sessions[session_id] = RealtimeASR(session_id)
    print(f"🎙️ 开始录音: {session_id}")
    emit('recording_started', {'status': 'ok'})


@socketio.on('audio_data')
def handle_audio_data(data):
    """接收音频数据"""
    session_id = request.sid

    with active_sessions_lock:
        asr = active_sessions.get(session_id)
 
    if not asr:
        emit('error', {'message': '会话不存在'})
        return
 
    if getattr(asr, 'is_finalizing', False):
        return
 
    try:
        with asr.lock:
            if asr.is_finalizing:
                return
            asr.add_audio(data)
 
            # 处理音频并返回实时结果
            result = asr.process_audio()
            if result:
                emit('transcription', result)
    except Exception as e:
        print(f"❌ 音频处理错误 [{session_id}]: {str(e)}")
        # 不发送错误，避免中断录音流程


@socketio.on('stop_recording')
def handle_stop_recording():
    """停止录音"""
    session_id = request.sid

    with active_sessions_lock:
        asr = active_sessions.get(session_id)
 
    if not asr:
        emit('error', {'message': '会话不存在'})
        return
 
    asr.is_finalizing = True
    print(f"🛑 停止录音: {session_id}")
     
    # 通知前端录音已停止，开始LLM处理
    emit('recording_stopped', {'message': '录音已停止，开始LLM纠错'})
     
    try:
        # 生成最终结果（可能耗时较长，包含SenseVoice和LLM处理）
        with asr.lock:
            final_result = asr.finalize()
        emit('final_result', final_result)
    except Exception as e:
        print(f"❌ 最终处理错误 [{session_id}]: {str(e)}")
        traceback.print_exc()
        # 返回已有的部分结果
        emit('final_result', {
            'paraformer': asr.text_with_punc + asr.pending_text,
            'sensevoice': '',
            'llm_merged': '',
            'paraformer_length': len(asr.text_with_punc + asr.pending_text),
            'sensevoice_length': 0,
            'llm_merged_length': 0,
            'error': str(e)
         })
    finally:
        # 确保清理会话
        with active_sessions_lock:
            active_sessions.pop(session_id, None)


# ==================== REST API 路由 ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    健康检查接口
    """
    return jsonify({
        "status": "ok",
        "message": "ASR API服务正常运行",
        "models_loaded": asr_model is not None
    }), 200


@app.route('/api/asr/transcribe', methods=['POST'])
def transcribe_audio():
    """
    音频文件转录接口
    上传音频文件，使用SenseVoice进行识别，并生成精确时间戳
    支持参数：
    - file: 音频文件
    - generate_timestamps: 是否生成时间戳（默认true）
    """
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({
                "success": False,
                "error": "未找到上传的文件，请使用 'file' 字段上传音频文件"
            }), 400
        
        file = request.files['file']
        generate_ts = request.form.get('generate_timestamps', 'true').lower() == 'true'
        
        # 检查文件名
        if file.filename == '':
            return jsonify({
                "success": False,
                "error": "文件名为空"
            }), 400
        
        # 检查文件格式
        if not allowed_file(file.filename):
            return jsonify({
                "success": False,
                "error": f"不支持的文件格式，支持的格式: {', '.join(ALLOWED_EXTENSIONS)}"
            }), 400
        
        # 保存上传的文件到临时位置
        temp_upload = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1])
        temp_upload_path = temp_upload.name
        file.save(temp_upload_path)
        temp_upload.close()
        
        # 将音频转换为WAV格式（确保所有格式都能被正确处理）
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_path = temp_wav.name
        temp_wav.close()
        
        try:
            print(f"📁 开始处理文件: {file.filename}")
            
            # 使用librosa读取并转换为WAV格式
            print("🔄 转换音频格式...")
            audio_data, sr = librosa.load(temp_upload_path, sr=16000, mono=True)
            sf.write(temp_path, audio_data, sr)
            print(f"✅ 格式转换完成: 16kHz, 单声道")
            
            # 计算音频时长（毫秒）
            audio_duration_ms = int(len(audio_data) / sr * 1000)
            
            # 删除上传的临时文件
            os.remove(temp_upload_path)
            
            # 使用SenseVoice识别（带VAD句级时间戳）
            print("✨ SenseVoice识别中...")
            if generate_ts:
                sensevoice_text, timestamps = _run_sensevoice_with_timestamps(temp_path)
                print(f"✅ SenseVoice完成: {len(sensevoice_text)}字, {len(timestamps)} 个句子")
            else:
                sensevoice_text = _run_sensevoice(temp_path)
                timestamps = []
                print(f"✅ SenseVoice完成: {len(sensevoice_text)}字")
            
            # 返回完整结果
            return jsonify({
                "success": True,
                "data": {
                    "text": sensevoice_text,
                    "length": len(sensevoice_text),
                    "model": "SenseVoice",
                    "timestamps": timestamps,
                    "duration_ms": audio_duration_ms
                },
                "filename": file.filename,
                "mode": "file_upload"
            }), 200
            
        finally:
            # 删除临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
        
    except Exception as e:
        print(f"❌ 处理错误: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/asr/models', methods=['GET'])
def get_models_info():
    """
    获取模型信息
    """
    return jsonify({
        "success": True,
        "data": {
            "asr_model": "paraformer-zh-streaming",
            "punc_model": "ct-punc",
            "sensevoice_model": "iic/SenseVoiceSmall",
            "llm_model": LLM_MODEL,
            "models_loaded": asr_model is not None
        }
    }), 200


@app.route('/api/asr/formats', methods=['GET'])
def get_supported_formats():
    """
    获取支持的音频格式
    """
    return jsonify({
        "success": True,
        "data": {
            "formats": list(ALLOWED_EXTENSIONS),
            "description": "支持的音频文件格式"
        }
    }), 200


if __name__ == '__main__':
    print("=" * 60)
    print("📣 语音识别API服务器")
    print("=" * 60)
    print("📝 支持模式:")
    print("  1. 实时录音模式（WebSocket）:")
    print("     - Paraformer 实时流式识别")
    print("     - SenseVoice 完整音频识别（带VAD时间戳）")
    print("  2. 文件上传模式（REST API）:")
    print("     - SenseVoice 识别（带VAD时间戳）")
    print("=" * 60)
    print("🔧 REST API接口:")
    print("  - GET  /api/health              健康检查")
    print("  - POST /api/asr/transcribe      文件转录（SenseVoice+VAD时间戳）")
    print("  - GET  /api/asr/models          模型信息")
    print("  - GET  /api/asr/formats         支持格式")
    print("")
    print("🔌 WebSocket接口:")
    print("  - connect                    建立连接")
    print("  - start_recording            开始录音")
    print("  - audio_data                 发送音频数据")
    print("  - stop_recording             停止录音")
    print("  - transcription              接收实时识别")
    print("  - recording_stopped          录音已停止，开始LLM处理")
    print("  - final_result               接收最终结果")
    print("=" * 60)
    print("🌐 访问地址: http://localhost:5006")
    print("=" * 60)
    
    # 初始化模型
    init_models()
    
    # 启动服务（使用socketio.run支持WebSocket）
    socketio.run(app, host='0.0.0.0', port=5006, debug=False, allow_unsafe_werkzeug=True)
