"""
语音识别API服务器
提供RESTful API接口进行音频转录
支持三种识别结果对比：Paraformer + SenseVoice + LLM智能合并
"""
import os
import tempfile
import wave
import json
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

app = Flask(__name__)
app.config['SECRET_KEY'] = 'asr-api-server'
CORS(app)  # 允许跨域请求

# SocketIO 配置（优化长时间录音稳定性）
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    # 增加 ping 超时时间（默认20秒太短，长时间录音可能超时）
    ping_timeout=120,  # 120秒超时
    ping_interval=30,  # 每30秒发送一次ping
    # 增加最大缓冲区大小（支持更大的音频数据帧）
    max_http_buffer_size=10 * 1024 * 1024,  # 10MB
)

# 全局模型实例
asr_model = None
punc_model = None
punc_realtime_model = None  # 实时标点模型
vad_model = None  # VAD语音端点检测模型
sensevoice_model = None
timestamp_model = None  # 时间戳预测模型

# LLM配置
LLM_API_URL = "http://10.8.75.207:9997/v1/chat/completions"
LLM_API_KEY = "sk-dmowsenrtifmlnpmlhaatxgkxnhbmusjfzgnofvlhtblslwa"
LLM_MODEL = "qwen3:8b"

# 支持的音频格式
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'wma'}

# 热词配置文件路径
HOTWORDS_FILE = os.path.join(os.path.dirname(__file__), 'hotwords.json')

# 模型缓存目录（Docker挂载或本地目录）
# 优先使用环境变量，其次使用项目目录下的 models_cache
MODELS_CACHE_DIR = os.environ.get('MODELSCOPE_CACHE', 
    os.path.join(os.path.dirname(__file__), 'models_cache'))
HF_CACHE_DIR = os.environ.get('HF_HOME',
    os.path.join(os.path.dirname(__file__), 'hf_cache'))

# 热词缓存
hotwords_cache = []

# 存储实时录音会话
active_sessions = {}


def init_models():
    """初始化 ASR、标点、VAD与复检模型
    
    模型缓存策略：
    - 优先从 MODELSCOPE_CACHE 目录加载已有模型
    - 如果模型不存在则自动下载到缓存目录
    - Docker运行时通过挂载卷持久化模型，避免重复下载
    """
    global asr_model, punc_model, punc_realtime_model, vad_model, sensevoice_model, timestamp_model
    
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
        
        # 检查模型是否已缓存
        def check_model_cached(model_name):
            """检查模型是否已在缓存中"""
            # ModelScope模型通常缓存在 hub/模型名 目录下
            model_path = os.path.join(MODELS_CACHE_DIR, 'hub', model_name.replace('/', '--'))
            if os.path.exists(model_path):
                return True
            # 也检查直接的模型名目录
            model_path_alt = os.path.join(MODELS_CACHE_DIR, 'hub', model_name)
            return os.path.exists(model_path_alt)
        
        # 加载中文流式 ASR 模型
        model_name = "paraformer-zh-streaming"
        cached = "(已缓存)" if check_model_cached(f"iic/{model_name}") else "(首次下载)"
        print(f"  - 加载 ASR 模型: {model_name} {cached} (设备: {device})")
        asr_model = AutoModel(
            model=model_name,
            device=device,
            disable_update=True,
        )
        
        # 加载标点恢复模型（离线，用于最终结果）
        model_name = "ct-punc"
        cached = "(已缓存)" if check_model_cached(f"iic/{model_name}") else "(首次下载)"
        print(f"  - 加载标点模型: {model_name} {cached} (设备: {device})")
        punc_model = AutoModel(
            model=model_name,
            device=device,
            disable_update=True,
        )
        
        # 加载实时标点模型（支持流式处理，带缓存）
        model_name = "iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727"
        cached = "(已缓存)" if check_model_cached(model_name) else "(首次下载)"
        print(f"  - 加载实时标点模型: punc_realtime {cached} (设备: {device})")
        punc_realtime_model = AutoModel(
            model=model_name,
            device=device,
            disable_update=True,
        )
        
        # 加载VAD语音端点检测模型（实时）
        model_name = "fsmn-vad"
        cached = "(已缓存)" if check_model_cached(f"iic/{model_name}") else "(首次下载)"
        print(f"  - 加载VAD模型: {model_name} {cached} (设备: {device})")
        vad_model = AutoModel(
            model=model_name,
            device=device,
            disable_update=True,
        )
        
        # SenseVoice 复检模型（配置VAD）
        model_name = "iic/SenseVoiceSmall"
        cached = "(已缓存)" if check_model_cached(model_name) else "(首次下载)"
        print(f"  - 加载复检模型: SenseVoiceSmall {cached} (设备: {device})")
        sensevoice_model = AutoModel(
            model=model_name,
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=device,
            disable_update=True,
            use_itn=True,
        )
        
        # 时间戳预测模型（用于生成字级时间戳）
        model_name = "fa-zh"
        cached = "(已缓存)" if check_model_cached(f"iic/{model_name}") else "(首次下载)"
        print(f"  - 加载时间戳模型: {model_name} {cached} (设备: {device})")
        timestamp_model = AutoModel(
            model=model_name,
            device=device,
            disable_update=True,
        )
        
        print("✅ 所有模型加载完成！")


def load_hotwords():
    """从JSON文件加载热词列表"""
    global hotwords_cache
    
    try:
        if os.path.exists(HOTWORDS_FILE):
            with open(HOTWORDS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                hotwords_cache = data.get('hotwords', [])
                print(f"📝 已加载 {len(hotwords_cache)} 个热词")
                return hotwords_cache
        else:
            print(f"⚠️ 热词文件不存在: {HOTWORDS_FILE}")
            hotwords_cache = []
            return []
    except Exception as e:
        print(f"❌ 加载热词失败: {str(e)}")
        hotwords_cache = []
        return []


def reload_hotwords():
    """重新加载热词（可用于运行时更新热词）"""
    return load_hotwords()


def allowed_file(filename):
    """检查文件格式是否支持"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _run_paraformer(audio_path):
    """使用Paraformer进行完整音频识别"""
    try:
        # 读取已转换的WAV音频文件（16kHz, 单声道）
        audio, sample_rate = sf.read(audio_path)
        
        # Paraformer识别
        result = asr_model.generate(
            input=audio,
            cache={},
            is_final=True,
            chunk_size=[0, 10, 5],
        )
        
        raw_text = ""
        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
        
        # 标点恢复
        if raw_text and punc_model:
            punc_result = punc_model.generate(input=raw_text)
            if punc_result and len(punc_result) > 0:
                return punc_result[0]["text"]
        
        return raw_text
        
    except Exception as e:
        raise Exception(f"Paraformer识别失败: {str(e)}")


def _run_sensevoice(audio_path):
    """使用SenseVoice进行完整音频识别（文件路径）"""
    try:
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
            return clean_text
        
        return ""
        
    except Exception as e:
        raise Exception(f"SenseVoice识别失败: {str(e)}")


def _run_sensevoice_array(audio_array, sample_rate):
    """使用SenseVoice进行完整音频识别（numpy数组）"""
    try:
        # 保存为临时文件
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_path = temp_file.name
        temp_file.close()
        
        sf.write(temp_path, audio_array, sample_rate)
        
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
            return clean_text
        
        return ""
        
    except Exception as e:
        raise Exception(f"SenseVoice识别失败: {str(e)}")


def _generate_timestamps(audio_array, sample_rate, text):
    """使用 fa-zh 模型生成精确的字级时间戳
    
    Args:
        audio_array: numpy float32 音频数组
        sample_rate: 采样率
        text: 要对齐的文本
    
    Returns:
        list: 时间戳列表 [{'char': '字', 'start_ms': 0, 'end_ms': 100}, ...]
    """
    if not timestamp_model or not text:
        return []
    
    try:
        # 保存音频为临时文件
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_audio_path = temp_audio.name
        temp_audio.close()
        sf.write(temp_audio_path, audio_array, sample_rate)
        
        # 保存文本为临时文件
        temp_text = tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w', encoding='utf-8')
        temp_text_path = temp_text.name
        # 移除标点符号，只保留文字（fa-zh 模型需要纯文本）
        clean_text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)
        temp_text.write(clean_text)
        temp_text.close()
        
        # 调用时间戳模型
        result = timestamp_model.generate(
            input=(temp_audio_path, temp_text_path),
            data_type=("sound", "text")
        )
        
        # 清理临时文件
        os.remove(temp_audio_path)
        os.remove(temp_text_path)
        
        if not result or len(result) == 0:
            return []
        
        # 解析时间戳结果
        # fa-zh 输出格式: [{'text': '字', 'timestamp': [[start_s, end_s], ...]}]
        timestamps = []
        raw_result = result[0]
        
        if 'timestamp' in raw_result:
            # fa-zh 输出格式: timestamp 已经是毫秒级 [[380, 560], [560, 800], ...]
            chars = list(clean_text)
            ts_list = raw_result['timestamp']
            for i, ts in enumerate(ts_list):
                if i < len(chars) and len(ts) >= 2:
                    timestamps.append({
                        'char': chars[i],
                        'start_ms': int(ts[0]),  # 已经是毫秒，不需要 * 1000
                        'end_ms': int(ts[1])
                    })
        elif 'value' in raw_result:
            # 其他可能的格式
            for item in raw_result['value']:
                if isinstance(item, dict) and 'text' in item:
                    timestamps.append({
                        'char': item.get('text', ''),
                        'start_ms': int(item.get('start', 0) * 1000),
                        'end_ms': int(item.get('end', 0) * 1000)
                    })
        
        # 将字级时间戳聚合为词/句级时间戳（便于前端显示）
        segments = _aggregate_timestamps(timestamps, text)
        
        return segments
        
    except Exception as e:
        print(f"⚠️ 时间戳生成错误: {str(e)}")
        traceback.print_exc()
        return []


def _aggregate_timestamps(char_timestamps, original_text):
    """将字级时间戳聚合为句级时间戳
    
    根据原文中的标点符号进行分句，每句话对应一个时间段
    """
    if not char_timestamps:
        return []
    
    segments = []
    current_segment = {
        'text': '',
        'start_ms': char_timestamps[0]['start_ms'] if char_timestamps else 0,
        'end_ms': 0,
        'chars': []  # 保留字级时间戳供精确定位
    }
    
    char_idx = 0
    for char in original_text:
        # 检查是否是标点符号（用于分句）
        is_punctuation = char in '，。！？；：、,!?;:'
        is_sentence_end = char in '。！？!?'
        
        if re.match(r'[\u4e00-\u9fa5a-zA-Z0-9]', char):
            # 是文字字符，添加到当前片段
            current_segment['text'] += char
            if char_idx < len(char_timestamps):
                current_segment['chars'].append(char_timestamps[char_idx])
                current_segment['end_ms'] = char_timestamps[char_idx]['end_ms']
                char_idx += 1
        elif is_punctuation:
            # 是标点符号，添加到文本但不影响时间戳
            current_segment['text'] += char
            
            # 如果是句末标点，结束当前片段
            if is_sentence_end and current_segment['text'].strip():
                segments.append(current_segment)
                # 开始新片段
                next_start = current_segment['end_ms']
                if char_idx < len(char_timestamps):
                    next_start = char_timestamps[char_idx]['start_ms']
                current_segment = {
                    'text': '',
                    'start_ms': next_start,
                    'end_ms': next_start,
                    'chars': []
                }
    
    # 添加最后一个片段
    if current_segment['text'].strip():
        segments.append(current_segment)
    
    return segments


def _call_llm_merge(paraformer_text, sensevoice_text):
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
    - 不要添加不存在的内容"""

    # 从全局缓存读取热词并添加到提示词中
    if hotwords_cache and len(hotwords_cache) > 0:
        hotword_list = "、".join(hotwords_cache)
        system_prompt += f"\n4. **自定义词匹配替换**（优先使用以下自定义词替换识别结果中的可能错误的词）：\n{hotword_list}"
    
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
            "temperature": 0.3
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
            self.vad_buffer = self.vad_buffer[self.vad_chunk_stride:]
            
            # VAD 检测
            is_final = False
            vad_result = vad_model.generate(
                input=vad_chunk,
                cache=self.vad_cache,
                is_final=is_final,
                chunk_size=self.vad_chunk_size
            )
            
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
            print(f"⚠️ VAD 检测错误: {str(e)}")
            return None
    
    def _apply_realtime_punc(self, text):
        """使用实时标点模型添加标点
        
        实时标点模型支持流式处理，会根据上下文智能添加标点
        """
        if not text or not punc_realtime_model:
            return text
        
        try:
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
            self.audio_buffer = self.audio_buffer[self.asr_chunk_stride:]
            
            # 记录当前 chunk 的时间范围
            chunk_start_ms = self.asr_processed_ms
            chunk_end_ms = chunk_start_ms + 600  # 每个 chunk 600ms
            self.asr_processed_ms = chunk_end_ms
            
            # 流式 ASR 识别
            asr_result = asr_model.generate(
                input=speech_chunk,
                cache=self.asr_cache,
                is_final=False,
                chunk_size=self.chunk_size,
                encoder_chunk_look_back=4,
                decoder_chunk_look_back=1,
            )
            
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
            print(f"❌ 流式识别错误: {str(e)}")
            return None
    
    def finalize(self):
        """完成识别，生成最终结果"""
        try:
            # 处理最后剩余的音频
            if len(self.audio_buffer) >= 4800:  # 至少 300ms
                speech_chunk = np.array(self.audio_buffer, dtype=np.float32)
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
            
            # 对剩余待处理文本使用离线标点模型（更准确）
            if self.pending_text and punc_model:
                try:
                    punc_result = punc_model.generate(input=self.pending_text)
                    if punc_result and len(punc_result) > 0:
                        self.text_with_punc += punc_result[0].get("text", self.pending_text)
                except Exception as e:
                    print(f"⚠️ 最终标点恢复失败: {str(e)}")
                    self.text_with_punc += self.pending_text
            else:
                self.text_with_punc += self.pending_text
            
            paraformer_text = self.text_with_punc
            print(f"✅ Paraformer完整文本: {paraformer_text} ({len(paraformer_text)}字)")
            
            # 使用 SenseVoice 对完整音频进行识别
            sensevoice_text = ""
            if len(self.full_audio) > 0:
                print(f"🔁 开始SenseVoice完整识别...")
                try:
                    audio_array = np.array(self.full_audio, dtype=np.float32)
                    sensevoice_text = _run_sensevoice_array(audio_array, self.sample_rate)
                    print(f"✅ SenseVoice完整文本: {sensevoice_text} ({len(sensevoice_text)}字)")
                except Exception as e:
                    print(f"❌ SenseVoice完整识别失败: {str(e)}")
            
            # 调用 LLM 合并纠错
            llm_merged_text = ""
            if paraformer_text or sensevoice_text:
                llm_merged_text = _call_llm_merge(paraformer_text, sensevoice_text)
                print(f"✅ LLM合并文本: {llm_merged_text} ({len(llm_merged_text)}字)")
            
            # 使用 fa-zh 模型为 LLM 纠错后的文本生成精确字级时间戳
            timestamps = []
            final_text = llm_merged_text or sensevoice_text or paraformer_text
            if final_text and len(self.full_audio) > 0 and timestamp_model:
                print(f"🕐 开始生成精确时间戳...")
                try:
                    timestamps = _generate_timestamps(
                        np.array(self.full_audio, dtype=np.float32),
                        self.sample_rate,
                        final_text
                    )
                    print(f"✅ 时间戳生成完成: {len(timestamps)} 个片段")
                except Exception as e:
                    print(f"⚠️ 时间戳生成失败: {str(e)}")
                    # 如果精确时间戳失败，使用实时时间戳作为备选
                    timestamps = self.segments
            
            return {
                'paraformer': paraformer_text,
                'sensevoice': sensevoice_text,
                'llm_merged': llm_merged_text,
                'paraformer_length': len(paraformer_text),
                'sensevoice_length': len(sensevoice_text),
                'llm_merged_length': len(llm_merged_text),
                'timestamps': timestamps,  # 精确字级时间戳
                'realtime_segments': self.segments,  # 实时粗略时间戳（备用）
            }
            
        except Exception as e:
            print(f"❌ 最终识别错误: {str(e)}")
            return {
                'paraformer': self.text_with_punc + self.pending_text,
                'sensevoice': '',
                'llm_merged': '',
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
    if session_id in active_sessions:
        del active_sessions[session_id]
    print(f"❌ 客户端断开: {session_id}")


@socketio.on('start_recording')
def handle_start_recording():
    """开始录音"""
    session_id = request.sid
    active_sessions[session_id] = RealtimeASR(session_id)
    print(f"🎙️ 开始录音: {session_id}")
    emit('recording_started', {'status': 'ok'})


@socketio.on('audio_data')
def handle_audio_data(data):
    """接收音频数据"""
    session_id = request.sid
    
    if session_id not in active_sessions:
        emit('error', {'message': '会话不存在'})
        return
    
    try:
        asr = active_sessions[session_id]
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
    
    if session_id not in active_sessions:
        emit('error', {'message': '会话不存在'})
        return
    
    print(f"🛑 停止录音: {session_id}")
    asr = active_sessions[session_id]
    
    # 通知前端录音已停止，开始LLM处理
    emit('recording_stopped', {'message': '录音已停止，开始LLM纠错'})
    
    try:
        # 生成最终结果（可能耗时较长，包含SenseVoice和LLM处理）
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
        if session_id in active_sessions:
            del active_sessions[session_id]


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
    上传音频文件，仅使用SenseVoice进行识别（高准确度）
    不使用Paraformer和LLM，直接返回SenseVoice结果
    """
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({
                "success": False,
                "error": "未找到上传的文件，请使用 'file' 字段上传音频文件"
            }), 400
        
        file = request.files['file']
        
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
            
            # 删除上传的临时文件
            os.remove(temp_upload_path)
            
            # 仅使用SenseVoice识别（文件上传模式）
            print("✨ SenseVoice识别中...")
            sensevoice_text = _run_sensevoice(temp_path)
            print(f"✅ SenseVoice完成: {len(sensevoice_text)}字")
            
            # 返回结果（仅SenseVoice结果）
            return jsonify({
                "success": True,
                "data": {
                    "text": sensevoice_text,
                    "length": len(sensevoice_text),
                    "model": "SenseVoice"
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


@app.route('/api/asr/hotwords', methods=['GET'])
def get_hotwords():
    """
    获取当前加载的热词列表
    """
    return jsonify({
        "success": True,
        "data": {
            "hotwords": hotwords_cache,
            "count": len(hotwords_cache),
            "file_path": HOTWORDS_FILE
        }
    }), 200


@app.route('/api/asr/hotwords/reload', methods=['POST'])
def reload_hotwords_api():
    """
    重新加载热词配置（无需重启服务器）
    """
    try:
        hotwords = reload_hotwords()
        return jsonify({
            "success": True,
            "message": "热词重新加载成功",
            "data": {
                "hotwords": hotwords,
                "count": len(hotwords)
            }
        }), 200
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    print("=" * 60)
    print("📣 语音识别API服务器")
    print("=" * 60)
    print("📝 支持模式:")
    print("  1. 实时录音模式（WebSocket）:")
    print("     - Paraformer 实时流式识别")
    print("     - SenseVoice 完整音频识别")
    print("     - LLM 智能合并纠错")
    print("  2. 文件上传模式（REST API）:")
    print("     - 仅 SenseVoice 识别（高准确度）")
    print("=" * 60)
    print("🔧 REST API接口:")
    print("  - GET  /api/health              健康检查")
    print("  - POST /api/asr/transcribe      文件转录（仅SenseVoice）")
    print("  - GET  /api/asr/models          模型信息")
    print("  - GET  /api/asr/formats         支持格式")
    print("  - GET  /api/asr/hotwords        获取热词列表")
    print("  - POST /api/asr/hotwords/reload 重新加载热词")
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
    
    # 加载热词
    load_hotwords()
    
    # 启动服务（使用socketio.run支持WebSocket）
    socketio.run(app, host='0.0.0.0', port=5006, debug=False, allow_unsafe_werkzeug=True)
