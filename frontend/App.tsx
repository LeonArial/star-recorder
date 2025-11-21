import React, { useState } from 'react';
import { Mic, Upload, Activity } from 'lucide-react';
import RealTimeTranscriber from './components/RealTimeTranscriber';
import FileTranscriber from './components/FileTranscriber';
import { TranscriptionMode } from './types';

const App: React.FC = () => {
  const [mode, setMode] = useState<TranscriptionMode>(TranscriptionMode.REALTIME);

  return (
    <div className="min-h-screen bg-[#FAFAFA] text-slate-900 selection:bg-indigo-100 selection:text-indigo-900">
      
      {/* Header */}
      <header className="sticky top-0 z-50 backdrop-blur-md bg-white/70 border-b border-slate-100">
        <div className="max-w-5xl mx-auto px-4 md:px-6 h-14 md:h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 md:w-8 md:h-8 bg-slate-900 rounded-lg flex items-center justify-center">
              <Activity className="w-4 h-4 md:w-5 md:h-5 text-white" />
            </div>
            <h1 className="text-base md:text-lg font-semibold tracking-tight">星声记</h1>
          </div>
          
          <div className="text-[10px] md:text-xs font-medium text-slate-400 bg-slate-50 px-2 md:px-3 py-1 rounded-full border border-slate-100">
            Paraformer + SenseVoice + Qwen3
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 md:px-6 md:py-12">
        
        {/* Hero Text */}
        <div className="text-center mb-8 md:mb-12">
          <h2 className="text-3xl md:text-5xl font-bold mb-3 md:mb-4 text-slate-900 tracking-tight leading-tight">
            语音转录  <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-500 to-violet-500">即刻生成</span>
          </h2>
        </div>

        {/* Toggle Switch */}
        <div className="flex justify-center mb-8 md:mb-12">
          <div className="bg-white p-1 md:p-1.5 rounded-xl md:rounded-2xl border border-slate-200 shadow-sm inline-flex w-full md:w-auto max-w-xs md:max-w-none">
            <button
              onClick={() => setMode(TranscriptionMode.REALTIME)}
              className={`flex-1 md:flex-none flex items-center justify-center gap-1.5 md:gap-2 px-4 py-2 md:px-6 md:py-3 rounded-lg md:rounded-xl text-xs md:text-sm font-medium transition-all duration-200 whitespace-nowrap ${
                mode === TranscriptionMode.REALTIME
                  ? 'bg-slate-900 text-white shadow-md'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <Mic className="w-3.5 h-3.5 md:w-4 md:h-4" />
              实时录音
            </button>
            <button
              onClick={() => setMode(TranscriptionMode.UPLOAD)}
              className={`flex-1 md:flex-none flex items-center justify-center gap-1.5 md:gap-2 px-4 py-2 md:px-6 md:py-3 rounded-lg md:rounded-xl text-xs md:text-sm font-medium transition-all duration-200 whitespace-nowrap ${
                mode === TranscriptionMode.UPLOAD
                  ? 'bg-slate-900 text-white shadow-md'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <Upload className="w-3.5 h-3.5 md:w-4 md:h-4" />
              上传文件
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="animate-in fade-in slide-in-from-bottom-8 duration-700">
          {mode === TranscriptionMode.REALTIME ? (
            <RealTimeTranscriber />
          ) : (
            <FileTranscriber />
          )}
        </div>

      </main>

      {/* Footer */}
      <footer className="py-6 md:py-8 text-center text-slate-400 text-xs md:text-sm px-4">
        <p>&copy; {new Date().getFullYear()} 星声记. 基于 React & FunASR 构建。</p>
      </footer>

    </div>
  );
};

export default App;