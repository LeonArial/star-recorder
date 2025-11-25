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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 全局模型实例
asr_model = None
punc_model = None
sensevoice_model = None

# LLM配置
LLM_API_URL = "http://10.8.75.207:9997/v1/chat/completions"
LLM_API_KEY = "sk-dmowsenrtifmlnpmlhaatxgkxnhbmusjfzgnofvlhtblslwa"
LLM_MODEL = "qwen3:8b"

# 支持的音频格式
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'wma'}

# 热词配置文件路径
HOTWORDS_FILE = os.path.join(os.path.dirname(__file__), 'hotwords.json')

# 热词缓存
hotwords_cache = []

# 存储实时录音会话
active_sessions = {}


def init_models():
    """初始化 ASR、标点与复检模型"""
    global asr_model, punc_model, sensevoice_model
    
    if asr_model is None:
        print("🔄 正在加载模型...")
        
        # 检测设备（GPU优先，无GPU则使用CPU）
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda:0"
                print(f"✅ 检测到GPU: {torch.cuda.get_device_name(0)}")
            else:
                device = "cpu"
                print("⚠️ 未检测到GPU，使用CPU模式（性能较低）")
        except:
            device = "cpu"
            print("⚠️ 使用CPU模式")
        
        # 加载中文流式 ASR 模型
        print(f"  - 加载 ASR 模型: paraformer-zh-streaming (设备: {device})")
        asr_model = AutoModel(
            model="paraformer-zh-streaming",
            device=device,
            disable_update=True,
        )
        
        # 加载标点恢复模型
        print(f"  - 加载标点模型: ct-punc (设备: {device})")
        punc_model = AutoModel(
            model="ct-punc",
            device=device,
            disable_update=True,
        )
        
        # SenseVoice 复检模型（配置VAD）
        print(f"  - 加载复检模型: SenseVoiceSmall (设备: {device})")
        sensevoice_model = AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="fsmn-vad",
            vad_kwargs={"max_single_segment_time": 30000},
            device=device,
            disable_update=True,
            use_itn=True,
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
            batch_size_s=60,
            merge_vad=True,
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
            batch_size_s=60,
            merge_vad=True,
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
   - 不要添加不存在的内容
"""

    # 从全局缓存读取热词并添加到提示词中
    if hotwords_cache and len(hotwords_cache) > 0:
        hotword_list = "、".join(hotwords_cache)
        system_prompt += f"\n\n4. **自定义词匹配替换**（优先使用以下自定义词替换识别结果中的可能错误的词）：\n{hotword_list}"
    
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
            "temperature": 0.3,
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


# ==================== 实时录音处理类 ====================

class RealtimeASR:
    """实时语音识别处理器"""
    
    def __init__(self, session_id):
        self.session_id = session_id
        self.audio_buffer = []
        self.sample_rate = 16000
        self.cache = {}  # 流式识别缓存
        self.chunk_size = [0, 10, 5]  # [0, 10, 5] 表示600ms实时出字
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
                audio_data = audio_data[:-1]
            
            if len(audio_data) == 0:
                return
            
            # 将字节数据转换为 float32 numpy 数组
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            self.audio_buffer.extend(audio_np)
            self.full_audio.extend(audio_np)  # 保存完整音频用于SenseVoice
        except Exception as e:
            print(f"❌ 音频数据处理错误: {str(e)}")
        
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
                        punc_result = punc_model.generate(input=self.pending_text)
                        if punc_result and len(punc_result) > 0:
                            punc_text = punc_result[0]["text"]
                            self.text_with_punc += punc_text
                            self.pending_text = ""
                    except Exception as e:
                        print(f"⚠️ 标点恢复失败: {str(e)}")
                        punc_text = self.pending_text
                        self.text_with_punc += punc_text
                        self.pending_text = ""
                
                return {
                    "text": text,
                    "punc_text": punc_text,
                    "full_text": self.text_with_punc + self.pending_text,
                    "is_final": False
                }
            
            return None
            
        except Exception as e:
            print(f"❌ 流式识别错误: {str(e)}")
            return None
    
    def finalize(self):
        """完成识别，生成最终结果"""
        try:
            # 处理最后剩余的音频
            if len(self.audio_buffer) >= 4800:  # 至少300ms
                speech_chunk = np.array(self.audio_buffer, dtype=np.float32)
                asr_result = asr_model.generate(
                    input=speech_chunk,
                    cache=self.cache,
                    is_final=True,
                    chunk_size=self.chunk_size,
                )
                
                if asr_result and len(asr_result) > 0:
                    text = asr_result[0]["text"]
                    self.all_text += text
                    self.pending_text += text
            
            # 对剩余待处理文本进行最终标点恢复
            if self.pending_text and punc_model:
                try:
                    punc_result = punc_model.generate(input=self.pending_text)
                    if punc_result and len(punc_result) > 0:
                        self.text_with_punc += punc_result[0]["text"]
                except Exception as e:
                    print(f"⚠️ 最终标点恢复失败: {str(e)}")
                    self.text_with_punc += self.pending_text
            else:
                self.text_with_punc += self.pending_text
            
            paraformer_text = self.text_with_punc
            print(f"✅ Paraformer完整文本: {paraformer_text} ({len(paraformer_text)}字)")
            
            # 使用SenseVoice对完整音频进行识别
            sensevoice_text = ""
            if len(self.full_audio) > 0:
                print(f"🔁 开始SenseVoice完整识别...")
                try:
                    audio_array = np.array(self.full_audio, dtype=np.float32)
                    sensevoice_text = _run_sensevoice_array(audio_array, self.sample_rate)
                    print(f"✅ SenseVoice完整文本: {sensevoice_text} ({len(sensevoice_text)}字)")
                except Exception as e:
                    print(f"❌ SenseVoice完整识别失败: {str(e)}")
            
            # 调用LLM合并纠错（如果两个结果都有内容）
            llm_merged_text = ""
            if paraformer_text or sensevoice_text:
                llm_merged_text = _call_llm_merge(paraformer_text, sensevoice_text)
                print(f"✅ LLM合并文本: {llm_merged_text} ({len(llm_merged_text)}字)")
            
            return {
                'paraformer': paraformer_text,
                'sensevoice': sensevoice_text,
                'llm_merged': llm_merged_text,
                'paraformer_length': len(paraformer_text),
                'sensevoice_length': len(sensevoice_text),
                'llm_merged_length': len(llm_merged_text),
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
    
    asr = active_sessions[session_id]
    asr.add_audio(data)
    
    # 处理音频并返回实时结果
    result = asr.process_audio()
    if result:
        emit('transcription', result)


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
    
    # 生成最终结果
    final_result = asr.finalize()
    emit('final_result', final_result)
    
    # 清理会话
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
