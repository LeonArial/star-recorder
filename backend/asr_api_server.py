"""
语音识别API服务器
提供RESTful API接口进行音频转录
支持三种识别结果对比：Paraformer + SenseVoice
"""
import os
import sys

# 必须在导入任何库之前设置环境变量
os.environ['TQDM_DISABLE'] = '1'
os.environ['TQDM_MININTERVAL'] = '99999'

import tempfile
import wave
import json
import threading
import numpy as np
import logging
import time
from flask import Flask, request, jsonify, send_file
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

# 禁用 FunASR 和相关库的冗余日志
logging.getLogger('funasr').setLevel(logging.ERROR)
logging.getLogger('modelscope').setLevel(logging.ERROR)
logging.getLogger('torch').setLevel(logging.ERROR)
logging.getLogger('transformers').setLevel(logging.ERROR)
# 完全禁用 werkzeug 的 WebSocket 断开错误日志（AssertionError: write() before start_response）
logging.getLogger('werkzeug').setLevel(logging.CRITICAL)

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

# ==================== 日志工具 ====================

def _short_sid(session_id: str) -> str:
    """取 session_id 后6位作为短标识"""
    return session_id[-6:] if session_id and len(session_id) > 6 else (session_id or '------')

def _log(msg: str, sid: str = None, level: str = 'INFO'):
    """统一日志输出，带可选的会话 ID 前缀
    
    level: INFO / WARN / ERROR / 留空
    """
    prefix = f'[{_short_sid(sid)}]' if sid else '[SYSTEM]'
    tag = {'INFO': ' ', 'WARN': '!', 'ERROR': 'X'}.get(level, ' ')
    print(f'{tag} {prefix} {msg}')

# 断连会话保留（宽限期内可恢复）
# 格式: {original_sid: {'asr': RealtimeASR, 'disconnected_at': float}}
disconnected_sessions = {}
disconnected_sessions_lock = threading.Lock()
SESSION_GRACE_PERIOD = 60  # 断连后保留会话的秒数

def _cleanup_expired_sessions():
    """定期清理超过宽限期的断连会话"""
    while True:
        try:
            now = time.time()
            expired = []
            with disconnected_sessions_lock:
                for sid, info in disconnected_sessions.items():
                    if now - info['disconnected_at'] > SESSION_GRACE_PERIOD:
                        expired.append(sid)
                for sid in expired:
                    del disconnected_sessions[sid]
            if expired:
                _log(f'清理过期断连会话: {len(expired)}个')
        except Exception as e:
            _log(f'清理断连会话失败: {e}', level='WARN')
        time.sleep(10)

# 启动断连会话清理守护线程
_session_cleanup_thread = threading.Thread(target=_cleanup_expired_sessions, daemon=True)
_session_cleanup_thread.start()

# 音频备份目录（用于录音防丢失）
AUDIO_BACKUP_DIR = os.path.join(os.path.dirname(__file__), 'audio_backups')
os.makedirs(AUDIO_BACKUP_DIR, exist_ok=True)

# 备份文件自动清理（保留7天）
BACKUP_EXPIRE_SECONDS = 7 * 24 * 60 * 60

def _cleanup_old_backups():
    """定期清理过期的音频备份文件"""
    while True:
        try:
            now = time.time()
            if os.path.exists(AUDIO_BACKUP_DIR):
                for fname in os.listdir(AUDIO_BACKUP_DIR):
                    fpath = os.path.join(AUDIO_BACKUP_DIR, fname)
                    if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > BACKUP_EXPIRE_SECONDS:
                        os.remove(fpath)
        except Exception as e:
            _log(f'清理备份文件失败: {e}', level='WARN')
        time.sleep(600)  # 每10分钟检查一次

# 启动备份清理守护线程
_cleanup_thread = threading.Thread(target=_cleanup_old_backups, daemon=True)
_cleanup_thread.start()

def init_models():
    """初始化 ASR、标点、VAD与复检模型
    
    模型缓存策略：
    - 优先从 MODELSCOPE_CACHE 目录加载已有模型
    - 如果模型不存在则自动下载到缓存目录
    - Docker运行时通过挂载卷持久化模型，避免重复下载
    """
    global asr_model, punc_realtime_model, vad_model, sensevoice_model
    
    if asr_model is None:
        print("\n" + "=" * 50)
        print(" 模型加载")
        print("=" * 50)
        
        # 设置模型缓存环境变量（确保FunASR使用正确的缓存路径）
        os.environ['MODELSCOPE_CACHE'] = MODELS_CACHE_DIR
        os.environ['HF_HOME'] = HF_CACHE_DIR
        
        # 确保缓存目录存在
        os.makedirs(MODELS_CACHE_DIR, exist_ok=True)
        os.makedirs(HF_CACHE_DIR, exist_ok=True)
        
        print(f"  缓存目录: {MODELS_CACHE_DIR}")
        
        # 检测设备（CUDA GPU > Apple MPS > CPU）
        try:
            import torch
            if torch.cuda.is_available():
                # NVIDIA GPU（Linux/Windows 服务器）
                device = "cuda:0"
                print(f"  设备: CUDA GPU ({torch.cuda.get_device_name(0)})")
            elif torch.backends.mps.is_available() and torch.backends.mps.is_built():
                # Apple Silicon MPS（M1/M2/M3/M4 Mac）
                device = "mps"
                print("  设备: Apple MPS")
            else:
                device = "cpu"
                print("  设备: CPU（无GPU，性能较低）")
        except Exception as e:
            device = "cpu"
            print(f"  设备: CPU（检测失败: {e}）")
        
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
        print(f"  加载 ASR 模型: {model_name} {'[缓存]' if is_cached else '[下载]'}")
        asr_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # 加载实时标点模型（支持流式处理，带缓存）
        model_name = "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727"
        model_path, is_cached = get_model_path(model_name)
        print(f"  加载标点模型: punc_realtime {'[缓存]' if is_cached else '[下载]'}")
        punc_realtime_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # 加载VAD语音端点检测模型（实时）
        model_name = "fsmn-vad"
        model_path, is_cached = get_model_path(model_name)
        print(f"  加载 VAD 模型: {model_name} {'[缓存]' if is_cached else '[下载]'}")
        vad_model = AutoModel(
            model=model_path,
            device=device,
            disable_update=True,
        )
        
        # SenseVoice 复检模型（配置VAD）
        model_name = "iic/SenseVoiceSmall"
        model_path, is_cached = get_model_path(model_name)
        vad_path, _ = get_model_path("fsmn-vad")  # VAD 模型路径
        print(f"  加载复检模型: SenseVoiceSmall {'[缓存]' if is_cached else '[下载]'}")
        sensevoice_model = AutoModel(
            model=model_path,
            vad_model=vad_path,
            vad_kwargs={"max_single_segment_time": 120000},
            device=device,
            disable_update=True,
            use_itn=True,
            language="zn",
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,  # 合并后的音频片段长度
        )
        
        print("  所有模型加载完成")
        print("=" * 50 + "\n")


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
        r'\bYes\.?\s*',
        r'\bW\.?\s*',
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


def _run_sensevoice_with_timestamps(audio_path, progress_callback=None, sid=None):
    """使用独立VAD模型获取语音段时间戳，再用SenseVoice识别每段（优化版）
    
    Args:
        audio_path: 音频文件路径
        progress_callback: 进度回调函数，接收 (current, total)
        sid: 会话 ID（用于日志前缀）
    
    Returns:
        tuple: (full_text, segments)
    """
    try:
        # 先使用独立VAD模型检测语音段
        _log('SenseVoice: VAD 分段中...', sid)
        if progress_callback:
            progress_callback(5, 100)
        
        with vad_model_lock:
            vad_result = vad_model.generate(
                input=audio_path,
                cache={},
            )
        
        if progress_callback:
            progress_callback(15, 100)
        
        # 解析VAD结果
        vad_segments = []
        if vad_result and len(vad_result) > 0:
            vad_data = vad_result[0].get("value", [])
            if vad_data:
                vad_segments = vad_data
        
        # 合并短段
        MIN_SEGMENT_DURATION_MS = 60000
        if vad_segments:
            merged_segments = []
            current_segment = None
            
            for start_ms, end_ms in vad_segments:
                if current_segment is None:
                    current_segment = [start_ms, end_ms]
                else:
                    current_duration = current_segment[1] - current_segment[0]
                    if current_duration < MIN_SEGMENT_DURATION_MS:
                        current_segment[1] = end_ms
                    else:
                        merged_segments.append(current_segment)
                        current_segment = [start_ms, end_ms]
            
            if current_segment is not None:
                merged_segments.append(current_segment)
            
            _log(f'SenseVoice: VAD {len(vad_segments)}段 -> 合并为 {len(merged_segments)}段', sid)
            vad_segments = merged_segments
        else:
            _log(f'SenseVoice: VAD {len(vad_segments)}段', sid)
        
        if progress_callback:
            progress_callback(20, 100)
        
        # 如果VAD没有检测到分段
        if not vad_segments:
            _log('SenseVoice: VAD 无分段，使用整体识别', sid, level='WARN')
            text = _run_sensevoice(audio_path)
            if progress_callback:
                progress_callback(100, 100)
            return text, [{'text': text, 'start_ms': 0, 'end_ms': 0}] if text else (text, [])
        
        # 读取音频
        audio_data, sr = librosa.load(audio_path, sr=16000, mono=True)
        
        audio_segments = []
        for start_ms, end_ms in vad_segments:
            start_sample = int(start_ms * sr / 1000)
            end_sample = int(end_ms * sr / 1000)
            segment_audio = audio_data[start_sample:end_sample]
            
            if len(segment_audio) >= sr * 1:
                audio_segments.append({
                    'audio': segment_audio,
                    'start_ms': int(start_ms),
                    'end_ms': int(end_ms)
                })
        
        segments = []
        total_segs = len(audio_segments)
        _log(f'SenseVoice: 识别 {total_segs} 段...', sid)
        
        # 批量处理
        with sensevoice_model_lock:
            for i, seg_info in enumerate(audio_segments):
                result = sensevoice_model.generate(
                    input=seg_info['audio'],
                    cache={},
                )
                
                if result and len(result) > 0:
                    raw_text = result[0].get("text", "")
                    clean_text = rich_transcription_postprocess(raw_text)
                    clean_text = emoji.replace_emoji(clean_text, replace='')
                    clean_text = _clean_sensevoice_text(clean_text)
                    
                    if clean_text.strip():
                        segments.append({
                            'text': clean_text,
                            'start_ms': seg_info['start_ms'],
                            'end_ms': seg_info['end_ms']
                        })
                
                # 更新进度：从 20% 到 95%
                if progress_callback:
                    current_progress = 20 + int((i + 1) / total_segs * 75)
                    progress_callback(current_progress, 100)
        
        full_text = ''.join([seg['text'] for seg in segments])
        
        if progress_callback:
            progress_callback(100, 100)
            
        return full_text, segments
    except Exception as e:
        _log(f'SenseVoice 识别失败: {str(e)}', sid, level='ERROR')
        traceback.print_exc()
        return "", []

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
        self.start_time = time.time()  # 录音开始时间
        
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
            _log(f'音频数据处理错误: {str(e)}', self.session_id, level='ERROR')
    
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
                _log(f'VAD 检测错误: {str(e)}', self.session_id, level='WARN')
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
                    _log(f'VAD 重试失败: {str(e2)}', self.session_id, level='WARN')
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
            _log(f'VAD 检测异常: {str(e)}', self.session_id, level='WARN')
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
            _log(f'实时标点恢复失败: {str(e)}', self.session_id)
        
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
                _log(f'流式识别错误: {str(e)}', self.session_id, level='ERROR')
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
                    _log(f'流式识别重试失败: {str(e2)}', self.session_id, level='ERROR')
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
            _log(f'流式识别异常: {str(e)}', self.session_id, level='ERROR')
            return None
    
    def finalize(self, progress_callback=None):
        """完成识别，生成最终结果"""
        try:
            finalize_start = time.time()
            recording_duration = finalize_start - self.start_time
            audio_size_mb = len(self.full_audio) * 4 / 1024 / 1024  # float32 = 4 bytes
            
            _log(f'录音统计: 时长 {recording_duration:.1f}s, 音频 {audio_size_mb:.1f}MB', self.session_id)
            
            if progress_callback:
                progress_callback(2, 100) # 开始处理
            
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
            paraformer_time = time.time() - finalize_start
            _log(f'Paraformer: {len(paraformer_text)}字 ({paraformer_time:.1f}s)', self.session_id)
            
            if progress_callback:
                progress_callback(5, 100) # Paraformer 处理完成
            
            # 使用 VAD分段 + SenseVoice识别
            sensevoice_text = ""
            timestamps = []
            backup_audio_id = None
            
            if len(self.full_audio) > 0:
                sensevoice_start = time.time()
                _log('SenseVoice 复检开始...', self.session_id)
                try:
                    # 保存音频文件（同时用于 SenseVoice 识别和备份）
                    audio_array = np.array(self.full_audio, dtype=np.float32)
                    
                    # 生成备份文件名
                    backup_audio_id = f"{self.session_id}_{int(time.time())}"
                    backup_path = os.path.join(AUDIO_BACKUP_DIR, f"{backup_audio_id}.wav")
                    sf.write(backup_path, audio_array, self.sample_rate)
                    
                    audio_duration_s = len(audio_array) / self.sample_rate
                    _log(f'音频备份: {_short_sid(backup_audio_id)}.wav ({audio_duration_s:.1f}s)', self.session_id)
                    
                    # 调用SenseVoice识别（使用备份文件）
                    sensevoice_text, timestamps = _run_sensevoice_with_timestamps(backup_path, progress_callback=progress_callback, sid=self.session_id)
                    
                    sensevoice_time = time.time() - sensevoice_start
                    _log(f'SenseVoice: {len(sensevoice_text)}字, {len(timestamps)}段 ({sensevoice_time:.1f}s)', self.session_id)
                except Exception as e:
                    _log(f'SenseVoice 复检失败: {str(e)}', self.session_id, level='ERROR')
            
            total_time = time.time() - finalize_start
            _log(f'总处理耗时: {total_time:.1f}s', self.session_id)
            
            if progress_callback:
                progress_callback(100, 100)
            
            result = {
                'paraformer': paraformer_text,
                'sensevoice': sensevoice_text,
                'paraformer_length': len(paraformer_text),
                'sensevoice_length': len(sensevoice_text),
                'timestamps': timestamps,  # VAD句级时间戳（SenseVoice原始文本）
                'realtime_segments': self.segments,  # 实时粗略时间戳（备用）
            }
            
            # 返回备份音频 ID，前端可用于下载服务端完整音频
            if backup_audio_id:
                result['backup_audio_id'] = backup_audio_id
            
            return result
            
        except Exception as e:
            _log(f'最终识别错误: {str(e)}', self.session_id, level='ERROR')
            return {
                'paraformer': self.text_with_punc + self.pending_text,
                'sensevoice': '',
                'paraformer_length': len(self.text_with_punc + self.pending_text),
                'sensevoice_length': 0,
            }


# ==================== WebSocket 事件处理 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    session_id = request.sid
    now = time.strftime('%m-%d %H:%M:%S')
    print(f'\n─── [{_short_sid(session_id)}] 连接 {now} ' + '─' * 9)
    emit('connected', {'session_id': session_id})


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开
    
    如果断开时会话正在录音中（未 finalizing），则将会话移入 disconnected_sessions
    保留宽限期（60s），等待客户端重连恢复。超时后自动清理。
    """
    session_id = request.sid
    asr = None
    with active_sessions_lock:
        asr = active_sessions.pop(session_id, None)
    
    # 如果会话正在录音且未进入 finalize，保留到宽限区
    if asr and not asr.is_finalizing:
        with disconnected_sessions_lock:
            disconnected_sessions[session_id] = {
                'asr': asr,
                'disconnected_at': time.time(),
            }
        now = time.strftime('%m-%d %H:%M:%S')
        print(f'─── [{_short_sid(session_id)}] 断开(保留{SESSION_GRACE_PERIOD}s) {now} ' + '─' * 2)
    else:
        now = time.strftime('%m-%d %H:%M:%S')
        print(f'─── [{_short_sid(session_id)}] 断开 {now} ' + '─' * 9)


@socketio.on('resume_recording')
def handle_resume_recording(data):
    """恢复断连的录音会话
    
    客户端重连后发送此事件，携带原始 session_id。
    从 disconnected_sessions 中恢复 RealtimeASR 实例，绑定到新 socket。
    """
    new_sid = request.sid
    original_sid = data.get('original_session_id') if isinstance(data, dict) else None
    
    if not original_sid:
        emit('resume_result', {'success': False, 'reason': '缺少 original_session_id'})
        return
    
    # 从宽限区查找会话
    asr = None
    with disconnected_sessions_lock:
        info = disconnected_sessions.pop(original_sid, None)
        if info:
            asr = info['asr']
    
    if not asr:
        _log(f'恢复失败: 原会话 {_short_sid(original_sid)} 不存在或已过期', new_sid, level='WARN')
        emit('resume_result', {'success': False, 'reason': '会话已过期'})
        return
    
    # 更新会话的 session_id 为新 socket ID
    old_short = _short_sid(original_sid)
    asr.session_id = new_sid
    
    # 绑定到新 socket
    with active_sessions_lock:
        active_sessions[new_sid] = asr
    
    gap_seconds = time.time() - asr.start_time
    _log(f'会话恢复成功 (原 {old_short}, 已录 {gap_seconds:.0f}s)', new_sid)
    
    emit('resume_result', {
        'success': True,
        'current_text': asr.text_with_punc + asr.pending_text,
        'duration_s': gap_seconds,
    })


@socketio.on('start_recording')
def handle_start_recording():
    """开始录音"""
    session_id = request.sid
    with active_sessions_lock:
        active_sessions[session_id] = RealtimeASR(session_id)
    _log('录音开始', session_id)
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
        _log(f'音频处理错误: {str(e)}', session_id, level='ERROR')
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
    _log('录音停止，开始处理...', session_id)
     
    # 通知前端录音已停止
    try:
        emit('recording_stopped', {'message': '录音已停止'})
    except:
        pass  # 客户端可能已断开，忽略错误
     
    def progress_callback(current, total):
        try:
            progress = int(current / total * 100)
            socketio.emit('processing_progress', {'progress': progress}, room=session_id)
        except:
            pass

    try:
        # 生成最终结果
        with asr.lock:
            final_result = asr.finalize(progress_callback=progress_callback)
        try:
            emit('final_result', final_result)
        except:
            _log('无法发送结果（客户端已断开）', session_id, level='WARN')
    except Exception as e:
        _log(f'最终处理错误: {str(e)}', session_id, level='ERROR')
        traceback.print_exc()
        # 尝试返回已有的部分结果
        try:
            emit('final_result', {
                'paraformer': asr.text_with_punc + asr.pending_text,
                'sensevoice': '',
                'paraformer_length': len(asr.text_with_punc + asr.pending_text),
                'sensevoice_length': 0,
                'error': str(e)
             })
        except:
            pass  # 客户端已断开
    finally:
        # 确保清理会话
        with active_sessions_lock:
            active_sessions.pop(session_id, None)
        _log('会话结束', session_id)


# ==================== REST API 路由 ====================

@app.route('/api/asr/backup-audio/<backup_id>', methods=['GET'])
def download_backup_audio(backup_id):
    """下载服务端备份的完整录音音频
    
    当前端 MediaRecorder 因浏览器节流等原因丢失数据时，
    前端可通过此接口获取 ASR 服务端保存的完整音频（WAV 格式）。
    备份文件保留 2 小时后自动清理。
    """
    # 安全检查：防止路径遍历
    safe_id = os.path.basename(backup_id)
    backup_path = os.path.join(AUDIO_BACKUP_DIR, f"{safe_id}.wav")
    
    if not os.path.exists(backup_path):
        return jsonify({"success": False, "error": "备份音频不存在或已过期"}), 404
    
    return send_file(
        backup_path,
        mimetype='audio/wav',
        as_attachment=True,
        download_name=f"{safe_id}.wav"
    )


@app.route('/api/asr/backup-audio/<backup_id>', methods=['DELETE'])
def delete_backup_audio(backup_id):
    """前端成功保存录音后，主动删除备份文件释放空间"""
    safe_id = os.path.basename(backup_id)
    backup_path = os.path.join(AUDIO_BACKUP_DIR, f"{safe_id}.wav")
    
    if os.path.exists(backup_path):
        os.remove(backup_path)
    
    return jsonify({"success": True})


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
        session_id = request.form.get('session_id')
        
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
            _log(f'文件转录: {file.filename}', session_id)
            
            # 使用librosa读取并转换为WAV格式
            audio_data, sr = librosa.load(temp_upload_path, sr=16000, mono=True)
            sf.write(temp_path, audio_data, sr)
            
            # 计算音频时长（毫秒）
            audio_duration_ms = int(len(audio_data) / sr * 1000)
            
            # 删除上传的临时文件
            os.remove(temp_upload_path)
            
            # 定义进度回调
            def progress_callback(current, total):
                if session_id:
                    try:
                        progress = int(current / total * 100)
                        socketio.emit('processing_progress', {'progress': progress}, room=session_id)
                    except:
                        pass

            # 使用SenseVoice识别（带VAD句级时间戳）
            if generate_ts:
                sensevoice_text, timestamps = _run_sensevoice_with_timestamps(temp_path, progress_callback=progress_callback, sid=session_id)
                _log(f'文件转录完成: {len(sensevoice_text)}字, {len(timestamps)}段', session_id)
            else:
                if progress_callback:
                    progress_callback(10, 100)
                sensevoice_text = _run_sensevoice(temp_path)
                if progress_callback:
                    progress_callback(100, 100)
                timestamps = []
                _log(f'文件转录完成: {len(sensevoice_text)}字', session_id)
            
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
        _log(f'文件转录错误: {str(e)}', session_id, level='ERROR')
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
    print("\n" + "=" * 50)
    print(" 语音识别 API 服务器")
    print("=" * 50)
    print(" REST   POST /api/asr/transcribe  文件转录")
    print("        GET  /api/health          健康检查")
    print(" WS     start_recording -> audio_data -> stop_recording")
    print(" 地址   http://localhost:5006")
    print("=" * 50)
    print("")
    print(" 日志格式: [级别] [会话ID后6位] 消息")
    print("   ' '=INFO  '!'=WARN  'X'=ERROR")
    print("=" * 50)
    
    # 初始化模型
    init_models()
    
    # 启动服务（使用socketio.run支持WebSocket）
    socketio.run(app, host='0.0.0.0', port=5006, debug=False, allow_unsafe_werkzeug=True)
