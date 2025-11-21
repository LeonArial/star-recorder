import React, { useState, useRef, useCallback, useEffect } from 'react';
import { io, Socket } from 'socket.io-client';
import { Mic, MicOff, Loader2, Copy, Trash2, Download, Sparkles } from 'lucide-react';
import AudioVisualizer from './AudioVisualizer';
import { API_BASE_URL } from '../services/asrService';

interface FinalResult {
  paraformer: string;
  sensevoice: string;
  llm_merged: string;
  paraformer_length: number;
  sensevoice_length: number;
  llm_merged_length: number;
}

const RealTimeTranscriber: React.FC = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState<string>("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [isProcessingLLM, setIsProcessingLLM] = useState(false);

  // Refs
  const socketRef = useRef<Socket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // 清理 Socket 连接
  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
    };
  }, []);

  // 停止录音
  const stopRecording = useCallback(async () => {
    console.log('停止录音...');
    
    // 通知服务器停止录音（如果socket还连接着）
    if (socketRef.current && socketRef.current.connected) {
      socketRef.current.emit('stop_recording');
    }
    
    // Stop MediaRecorder
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }

    // 停止音频流
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
    }

    // 清理音频处理节点
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    if (audioContextRef.current) {
      await audioContextRef.current.close();
      audioContextRef.current = null;
    }

    setIsRecording(false);
  }, [stream]);

  const startRecording = async () => {
    setError(null);
    setIsConnecting(true);
    setAudioUrl(null);
    setTranscript("");
    setIsProcessingLLM(false);
    audioChunksRef.current = [];
    
    try {
      // 1. 连接 Socket.IO
      const socket = io(API_BASE_URL, {
        transports: ['websocket'],
      });

      socketRef.current = socket;

      // Socket 事件监听
      socket.on('connected', (data) => {
        console.log('✅ 已连接到服务器:', data.session_id);
        setIsConnecting(false);
        setIsRecording(true);
      });

      socket.on('recording_started', (data) => {
        console.log('🎙️ 录音已开始:', data);
      });

      socket.on('transcription', (data) => {
        console.log('📝 实时识别:', data);
        // 显示实时文本
        if (data.full_text) {
          setTranscript(data.full_text);
        }
      });

      socket.on('final_result', (data: FinalResult) => {
        console.log('✅ 最终结果:', data);
        // 自动用LLM合并的结果替换transcript
        if (data.llm_merged) {
          setTranscript(data.llm_merged);
        }
        setIsProcessingLLM(false);
        
        // 接收完最终结果后断开socket连接
        console.log('🔌 断开Socket连接');
        socket.disconnect();
        socketRef.current = null;
      });

      // 监听录音停止事件，显示LLM处理中
      socket.on('recording_stopped', () => {
        console.log('🛑 录音已停止，开始LLM纠错...');
        setIsProcessingLLM(true);
      });

      socket.on('error', (data) => {
        console.error('❌ 错误:', data);
        setError(data.message || '发生错误');
        setIsProcessingLLM(false);
        stopRecording();
        // 错误时断开socket连接
        socket.disconnect();
        socketRef.current = null;
      });

      socket.on('disconnect', () => {
        console.log('⚠️ 断开连接');
        socketRef.current = null;
      });

      // 2. 获取麦克风
      const mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        } 
      });
      setStream(mediaStream);

      // 3. 初始化 MediaRecorder（用于下载录音）
      const recorder = new MediaRecorder(mediaStream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const url = URL.createObjectURL(blob);
        setAudioUrl(url);
      };
      recorder.start();
      mediaRecorderRef.current = recorder;

      // 4. 设置音频处理
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(mediaStream);
      sourceRef.current = source;

      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        
        // 转换为 Int16Array
        const int16Data = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        // 发送音频数据到服务器
        if (socket && socket.connected) {
          socket.emit('audio_data', int16Data.buffer);
        }
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

      // 5. 通知服务器开始录音
      socket.emit('start_recording');

    } catch (err: any) {
      console.error("启动录音失败:", err);
      setError(err.message || "无法访问麦克风或连接到服务器");
      setIsConnecting(false);
      setIsProcessingLLM(false);
      stopRecording();
      // 启动失败时断开socket
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const handleClear = () => {
    setTranscript("");
    setIsProcessingLLM(false);
  };

  return (
    <div className="flex flex-col w-full max-w-3xl mx-auto">
      {/* Visualizer Area */}
      <div className="relative w-full mb-6">
        <AudioVisualizer stream={stream} isRecording={isRecording} />
        
        {/* Status Overlay */}
        {!isRecording && !isConnecting && (
          <div className="absolute inset-0 flex items-center justify-center text-slate-400 text-xs md:text-sm font-medium pointer-events-none">
            准备就绪
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center space-x-4 md:space-x-6 mb-6 md:mb-8">
        {!isRecording ? (
          <button
            onClick={startRecording}
            disabled={isConnecting}
            className={`group relative flex items-center justify-center w-14 h-14 md:w-16 md:h-16 rounded-full transition-all duration-300 ${
              isConnecting 
              ? 'bg-slate-200 cursor-not-allowed' 
              : 'bg-slate-900 hover:bg-indigo-600 shadow-lg hover:shadow-indigo-500/30 hover:scale-105'
            }`}
          >
            {isConnecting ? (
              <Loader2 className="w-5 h-5 md:w-6 md:h-6 text-slate-500 animate-spin" />
            ) : (
              <Mic className="w-5 h-5 md:w-6 md:h-6 text-white group-hover:text-white" />
            )}
          </button>
        ) : (
          <button
            onClick={stopRecording}
            className="group flex items-center justify-center w-14 h-14 md:w-16 md:h-16 rounded-full bg-red-500 hover:bg-red-600 shadow-lg hover:shadow-red-500/30 transition-all duration-300 hover:scale-105"
          >
            <MicOff className="w-5 h-5 md:w-6 md:h-6 text-white" />
          </button>
        )}
        
      </div>

      {/* Audio Download Option */}
      {!isRecording && audioUrl && (
        <div className="flex justify-center mb-6">
           <a
            href={audioUrl}
            download={`recording-${new Date().toISOString()}.webm`}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 rounded-full text-xs md:text-sm font-medium text-slate-600 hover:text-indigo-600 hover:border-indigo-200 hover:bg-indigo-50 transition-all shadow-sm active:scale-95"
          >
            <Download className="w-3.5 h-3.5 md:w-4 md:h-4" />
            下载录音文件
          </a>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="mb-4 p-3 md:p-4 bg-red-50 border border-red-100 text-red-600 rounded-lg text-xs md:text-sm text-center">
          {error}
        </div>
      )}

      {/* LLM处理中提示 */}
      {isProcessingLLM && (
        <div className="mb-4 flex items-center justify-center gap-3 p-3 bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl animate-in fade-in slide-in-from-top-2 duration-300">
          <Sparkles className="w-5 h-5 text-indigo-600 animate-pulse" />
          <span className="text-sm font-medium text-indigo-700">调用 Qwen3 纠错中...</span>
          <Loader2 className="w-4 h-4 text-indigo-600 animate-spin" />
        </div>
      )}

      {/* Transcript Display */}
      <div className="relative group">
        <div className="absolute top-3 right-3 md:top-4 md:right-4 flex space-x-2 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity duration-200 z-10">
          <button 
            onClick={() => handleCopy(transcript)}
            className="p-1.5 md:p-2 rounded-lg bg-white/90 hover:bg-white shadow-sm border border-slate-200 text-slate-500 hover:text-indigo-600 transition-colors"
            title="复制"
          >
            <Copy className="w-3.5 h-3.5 md:w-4 md:h-4" />
          </button>
          <button 
            onClick={handleClear}
            className="p-1.5 md:p-2 rounded-lg bg-white/90 hover:bg-white shadow-sm border border-slate-200 text-slate-500 hover:text-red-500 transition-colors"
            title="清空"
          >
            <Trash2 className="w-3.5 h-3.5 md:w-4 md:h-4" />
          </button>
        </div>
        
        <textarea
          readOnly
          value={transcript}
          placeholder="开始录音后，此处将显示实时转写内容..."
          className={`w-full h-72 md:h-96 p-4 md:p-6 rounded-xl md:rounded-2xl bg-white border shadow-sm resize-none focus:outline-none focus:ring-2 text-slate-700 text-base md:text-lg leading-relaxed transition-all duration-300 ${
            isProcessingLLM 
              ? 'border-indigo-300 focus:ring-indigo-500/20 opacity-75' 
              : 'border-slate-100 focus:ring-indigo-500/10'
          }`}
        />
      </div>
    </div>
  );
};

export default RealTimeTranscriber;
