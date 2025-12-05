import React, { useState } from 'react';
import { Mic, Upload, Activity, Sparkles } from 'lucide-react';
import RealTimeTranscriber from './components/RealTimeTranscriber';
import FileTranscriber from './components/FileTranscriber';
import { TranscriptionMode } from './types';

const App: React.FC = () => {
  const [mode, setMode] = useState<TranscriptionMode>(TranscriptionMode.REALTIME);

  return (
    <div className="min-h-screen bg-[#F5F7FA] text-slate-900 selection:bg-blue-100 selection:text-blue-900">
      
      {/* Header */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-md border-b border-slate-200/60">
        <div className="max-w-7xl mx-auto px-4 md:px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-gradient-to-br from-blue-600 to-blue-700 rounded-xl shadow-sm flex items-center justify-center">
              <Activity className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-slate-900">星声记</h1>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
             <div className="hidden md:flex items-center gap-2 text-xs font-medium text-slate-500 bg-slate-100/50 px-3 py-1.5 rounded-full border border-slate-200/50">
              <span>Paraformer + SenseVoice + Qwen3</span>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-8 md:px-6 md:py-10">
        
        {/* Toggle Switch */}
        <div className="flex justify-center mb-8">
          <div className="bg-white p-1.5 rounded-2xl border border-slate-200 shadow-sm inline-flex w-full md:w-auto">
            <button
              onClick={() => setMode(TranscriptionMode.REALTIME)}
              className={`flex-1 md:flex-none flex items-center justify-center gap-2 px-8 py-3 rounded-xl text-sm font-semibold transition-all duration-300 ${
                mode === TranscriptionMode.REALTIME
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <Mic className="w-4 h-4" />
              实时录音
            </button>
            <button
              onClick={() => setMode(TranscriptionMode.UPLOAD)}
              className={`flex-1 md:flex-none flex items-center justify-center gap-2 px-8 py-3 rounded-xl text-sm font-semibold transition-all duration-300 ${
                mode === TranscriptionMode.UPLOAD
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              <Upload className="w-4 h-4" />
              导入音频
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
          {mode === TranscriptionMode.REALTIME ? (
            <RealTimeTranscriber />
          ) : (
            <FileTranscriber />
          )}
        </div>

      </main>
    </div>
  );
};

export default App;