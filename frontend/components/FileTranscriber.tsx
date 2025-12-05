import React, { useState } from 'react';
import { UploadCloud, FileAudio, Loader2, CheckCircle2, AlertCircle, Copy, Trash2, X } from 'lucide-react';
import { transcribeAudioFile } from '../services/asrService';
import AudioPlayer from './AudioPlayer';

const FileTranscriber: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcription, setTranscription] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      setFileUrl(URL.createObjectURL(selectedFile));
      setTranscription(null);
      setError(null);
    }
  };

  const handleClearFile = () => {
    setFile(null);
    setFileUrl(null);
    setTranscription(null);
    setError(null);
  };

  const handleTranscribe = async () => {
    if (!file) return;

    setIsTranscribing(true);
    setError(null);
    try {
      const result = await transcribeAudioFile(file);
      setTranscription(result);
    } catch (err: any) {
      console.error(err);
      setError("转写失败，请确保文件格式正确并重试。");
    } finally {
      setIsTranscribing(false);
    }
  };

  const handleCopy = () => {
    if (transcription) {
      navigator.clipboard.writeText(transcription);
    }
  };

  return (
    <div className="w-full max-w-4xl mx-auto flex flex-col gap-6">
      
      {/* Upload Area or File Player Area */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm transition-all">
        {!file ? (
            <div className="relative border-2 border-dashed border-slate-200 rounded-xl p-12 text-center hover:border-blue-300 hover:bg-blue-50/30 transition-all group cursor-pointer">
                <input
                type="file"
                accept="audio/*"
                onChange={handleFileChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                />
                <div className="flex flex-col items-center pointer-events-none">
                    <div className="w-16 h-16 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mb-4 group-hover:scale-110 group-hover:bg-blue-100 group-hover:text-blue-500 transition-all duration-300">
                        <UploadCloud className="w-8 h-8" />
                    </div>
                    <p className="text-lg font-semibold text-slate-900 mb-1">点击上传或拖拽文件</p>
                    <p className="text-sm text-slate-500">支持 MP3, WAV, AAC, OGG (最大 20MB)</p>
                </div>
            </div>
        ) : (
            <div className="flex flex-col gap-6 animate-in fade-in slide-in-from-bottom-2">
                {/* File Info Header */}
                <div className="flex items-center justify-between">
                     <div className="flex items-center gap-4">
                        <div className="w-12 h-12 bg-blue-100 text-blue-600 rounded-xl flex items-center justify-center">
                            <FileAudio className="w-6 h-6" />
                        </div>
                        <div>
                            <p className="font-semibold text-slate-900 truncate max-w-[200px] md:max-w-md">{file.name}</p>
                            <p className="text-xs text-slate-500 font-medium">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                        </div>
                     </div>
                     <button 
                        onClick={handleClearFile}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-full transition-colors"
                        title="移除文件"
                     >
                         <X className="w-5 h-5" />
                     </button>
                </div>

                {/* Player */}
                {fileUrl && <AudioPlayer audioUrl={fileUrl} />}

                {/* Action Button */}
                <div className="flex justify-center pt-2">
                    <button
                    onClick={handleTranscribe}
                    disabled={isTranscribing}
                    className={`flex items-center px-8 py-3 rounded-full font-semibold text-white shadow-lg transition-all active:scale-95 ${
                        isTranscribing
                        ? 'bg-slate-300 cursor-not-allowed'
                        : 'bg-blue-600 hover:bg-blue-700 hover:shadow-blue-500/30'
                    }`}
                    >
                    {isTranscribing ? (
                        <>
                        <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                        正在转写...
                        </>
                    ) : (
                        <>
                        开始转写
                        </>
                    )}
                    </button>
                </div>
                
                 {/* Error State */}
                {error && (
                    <div className="p-3 bg-red-50 border border-red-100 rounded-lg flex items-start gap-3">
                        <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
                        <p className="text-sm text-red-700">{error}</p>
                    </div>
                )}
            </div>
        )}
      </div>

      {/* Result Display */}
      <div className={`bg-white border border-slate-200 rounded-2xl shadow-sm flex flex-col overflow-hidden transition-all duration-500 ${transcription ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'}`}>
          {/* Toolbar */}
        <div className="border-b border-slate-100 px-4 py-3 flex items-center justify-between bg-slate-50/50">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700">转写结果</span>
                {transcription && (
                    <div className="flex items-center gap-1.5 text-green-600 text-xs font-medium">
                         <CheckCircle2 className="w-3.5 h-3.5" />
                         <span>完成</span>
                    </div>
                )}
            </div>
            <div className="flex items-center gap-1">
                <button 
                    onClick={handleCopy}
                    disabled={!transcription}
                    className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors disabled:opacity-0"
                    title="复制全部"
                >
                    <Copy className="w-4 h-4" />
                </button>
            </div>
        </div>

        <div className="p-6 min-h-[300px]">
             {transcription ? (
                 <p className="whitespace-pre-wrap text-slate-700 leading-relaxed text-lg">{transcription}</p>
             ) : (
                 <div className="h-full flex items-center justify-center text-slate-300 text-sm">
                     转写内容将显示在这里
                 </div>
             )}
        </div>
      </div>
    </div>
  );
};

export default FileTranscriber;