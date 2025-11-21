import React, { useState, useRef, useCallback } from 'react';
import { GoogleGenAI, LiveServerMessage, Modality, Blob as GenAIBlob } from '@google/genai';
import { Mic, MicOff, Loader2, Copy, Trash2, Download } from 'lucide-react';
import AudioVisualizer from './AudioVisualizer';

const RealTimeTranscriber: React.FC = () => {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState<string>("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  // Refs for audio processing and session management
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const sessionRef = useRef<Promise<any> | null>(null);
  const currentTranscriptRef = useRef<string>("");
  
  // Recording refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  // Cleanup function to stop all tracks and nodes
  const stopRecording = useCallback(async () => {
    setIsRecording(false);
    
    // Stop MediaRecorder if active
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }

    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
    }

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

    sessionRef.current = null;
  }, [stream]);

  // Convert Float32Array to PCM16
  const createPcmBlob = (data: Float32Array): GenAIBlob => {
    const l = data.length;
    const int16 = new Int16Array(l);
    for (let i = 0; i < l; i++) {
      // Clamp values
      const s = Math.max(-1, Math.min(1, data[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    
    // Manually encode to base64 (btoa) for the API
    let binary = '';
    const bytes = new Uint8Array(int16.buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    const base64Data = btoa(binary);

    return {
      data: base64Data,
      mimeType: 'audio/pcm;rate=16000',
    };
  };

  const startRecording = async () => {
    setError(null);
    setIsConnecting(true);
    setAudioUrl(null);
    audioChunksRef.current = [];
    
    try {
      // 1. Get Media Stream
      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      setStream(mediaStream);

      // Initialize MediaRecorder for downloading
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

      // 2. Initialize Gemini Client
      if (!process.env.API_KEY) throw new Error("API Key not found");
      const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });

      // 3. Connect to Live API
      const sessionPromise = ai.live.connect({
        model: 'gemini-2.5-flash-native-audio-preview-09-2025',
        config: {
          responseModalities: [Modality.AUDIO], // Required by API
          inputAudioTranscription: {}, // Enable transcription of user input
          systemInstruction: {
            parts: [{ text: "你是一个静默的听写员。不要说话，只负责听写。" }]
          }
        },
        callbacks: {
          onopen: () => {
            console.log("Gemini Live Connection Opened");
            setIsConnecting(false);
            setIsRecording(true);
          },
          onmessage: (message: LiveServerMessage) => {
            const inputTranscription = message.serverContent?.inputTranscription;
            if (inputTranscription) {
               const text = inputTranscription.text;
               if (text) {
                 currentTranscriptRef.current += text;
                 setTranscript(currentTranscriptRef.current);
               }
            }
            
            if (message.serverContent?.turnComplete) {
               currentTranscriptRef.current += " "; 
               setTranscript(currentTranscriptRef.current);
            }
          },
          onclose: () => {
            console.log("Gemini Live Connection Closed");
            stopRecording();
          },
          onerror: (err) => {
            console.error("Gemini Live Error", err);
            setError("连接错误，请重试。");
            stopRecording();
          }
        }
      });
      
      sessionRef.current = sessionPromise;

      // 4. Set up Audio Context & Processing
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(mediaStream);
      sourceRef.current = source;

      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0);
        const pcmBlob = createPcmBlob(inputData);
        
        sessionPromise.then(session => {
          session.sendRealtimeInput({ media: pcmBlob });
        });
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

    } catch (err: any) {
      console.error("Failed to start recording:", err);
      setError(err.message || "无法访问麦克风或连接到 API。");
      setIsConnecting(false);
      stopRecording();
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(transcript);
  };

  const handleClear = () => {
    setTranscript("");
    currentTranscriptRef.current = "";
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

      {/* Transcript Display */}
      <div className="relative group">
        <div className="absolute top-3 right-3 md:top-4 md:right-4 flex space-x-2 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity duration-200 z-10">
           <button 
            onClick={handleCopy}
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
          className="w-full h-72 md:h-96 p-4 md:p-6 rounded-xl md:rounded-2xl bg-white border border-slate-100 shadow-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500/10 text-slate-700 text-base md:text-lg leading-relaxed"
        />
      </div>
    </div>
  );
};

export default RealTimeTranscriber;