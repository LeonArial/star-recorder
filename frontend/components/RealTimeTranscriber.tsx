import React, { useState, useRef, useCallback, useEffect } from 'react';
import { io, Socket } from 'socket.io-client';
import { Mic, MicOff, Loader2, Copy, Trash2, Download, Sparkles } from 'lucide-react';
import AudioVisualizer from './AudioVisualizer';
import AudioPlayer from './AudioPlayer';
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
      // 1. 连接 Socket.IO（配置超时参数以支持长时间录音）
      const socket = io(API_BASE_URL, {
        transports: ['websocket'],
        // 与后端配置匹配，增加超时时间
        timeout: 120000,  // 连接超时 120 秒
        reconnection: true,  // 启用自动重连
        reconnectionAttempts: 3,  // 最多重连 3 次
        reconnectionDelay: 1000,  // 重连延迟 1 秒
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

      socket.on('disconnect', (reason) => {
        console.log('⚠️ 断开连接，原因:', reason);
        socketRef.current = null;
        // 如果是服务器主动断开或传输错误，显示提示
        if (reason === 'transport error' || reason === 'transport close') {
          setError('连接中断，请检查网络后重试');
          setIsProcessingLLM(false);
        }
      });

      // 重连事件
      socket.on('reconnect_attempt', (attempt) => {
        console.log(`🔄 正在尝试重连 (${attempt}/3)...`);
      });

      socket.on('reconnect', () => {
        console.log('✅ 重连成功');
      });

      socket.on('reconnect_failed', () => {
        console.log('❌ 重连失败');
        setError('连接断开且重连失败，请刷新页面重试');
        setIsProcessingLLM(false);
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
    <div className="flex flex-col w-full max-w-4xl mx-auto gap-6">
      {/* Top Section: Visualizer / Player & Controls */}
      <div className="rounded-2xl p-6">
        <div className="flex flex-col items-center gap-6">
          
          {/* Audio Visualization or Player */}
          <div className="w-full">
             {!isRecording && audioUrl ? (
                <AudioPlayer audioUrl={audioUrl} />
             ) : (
                <div className="relative w-full h-32 rounded-xl overflow-hidden flex items-center justify-center">
                   <AudioVisualizer stream={stream} isRecording={isRecording} />
                   {!isRecording && !isConnecting && (
                      <div className="absolute inset-0 flex items-center justify-center text-slate-400 text-sm font-medium pointer-events-none">
                        准备就绪，点击下方按钮开始录音
                      </div>
                   )}
                </div>
             )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-4">
            {!isRecording ? (
              <button
                onClick={startRecording}
                disabled={isConnecting}
                className={`flex items-center gap-2 px-8 py-3 rounded-full font-semibold text-white shadow-lg transition-all active:scale-95 ${
                    isConnecting
                    ? 'bg-slate-300 cursor-not-allowed'
                    : 'bg-blue-600 hover:bg-blue-700 shadow-blue-500/30 hover:shadow-blue-500/40'
                }`}
              >
                {isConnecting ? <Loader2 className="w-5 h-5 animate-spin" /> : <Mic className="w-5 h-5" />}
                {isConnecting ? '连接中...' : (audioUrl ? '重新录音' : '开始录音')}
              </button>
            ) : (
              <button
                onClick={stopRecording}
                className="flex items-center gap-2 px-8 py-3 rounded-full font-semibold text-white bg-red-500 hover:bg-red-600 shadow-lg shadow-red-500/30 hover:shadow-red-500/40 transition-all active:scale-95"
              >
                <MicOff className="w-5 h-5" />
                停止录音
              </button>
            )}
            
             {/* Download Button (Small) */}
             {!isRecording && audioUrl && (
               <a
                href={audioUrl}
                download={`recording-${new Date().toISOString()}.webm`}
                className="p-3 rounded-full border border-slate-200 text-slate-600 hover:text-blue-600 hover:bg-blue-50 transition-all"
                title="下载录音"
               >
                 <Download className="w-5 h-5" />
               </a>
             )}
          </div>

          {/* Error Message */}
          {error && (
            <div className="text-sm text-red-600 bg-red-50 px-4 py-2 rounded-lg border border-red-100">
              {error}
            </div>
          )}
        </div>
      </div>

      {/* Bottom Section: Transcript */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm flex flex-col overflow-hidden min-h-[400px]">
        {/* Toolbar */}
        <div className="border-b border-slate-100 px-4 py-3 flex items-center justify-between bg-slate-50/50">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700">转写结果</span>
                {isProcessingLLM && (
                    <div className="flex items-center gap-1.5 px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-xs font-medium border border-blue-100">
                        <Sparkles className="w-3 h-3 animate-pulse" />
                        AI 优化中...
                    </div>
                )}
            </div>
            <div className="flex items-center gap-1">
                <button 
                    onClick={() => handleCopy(transcript)}
                    disabled={!transcript}
                    className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors disabled:opacity-50"
                    title="复制全部"
                >
                    <Copy className="w-4 h-4" />
                </button>
                <button 
                    onClick={handleClear}
                    disabled={!transcript}
                    className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
                    title="清空"
                >
                    <Trash2 className="w-4 h-4" />
                </button>
            </div>
        </div>

        {/* Text Area */}
        <div className="flex-1 relative">
             <textarea
                readOnly
                value={transcript}
                placeholder="等待录音..."
                className="w-full h-full p-6 resize-none outline-none text-slate-700 text-sm leading-relaxed bg-transparent font-sans"
            />
        </div>
      </div>
    </div>
  );
};

export default RealTimeTranscriber;
