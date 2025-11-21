import React, { useState } from 'react';
import { UploadCloud, FileAudio, Loader2, CheckCircle2, AlertCircle, Copy } from 'lucide-react';
import { transcribeAudioFile } from '../services/geminiService';

const FileTranscriber: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcription, setTranscription] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setTranscription(null);
      setError(null);
    }
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
    <div className="w-full max-w-3xl mx-auto">
      
      {/* Upload Area */}
      <div className={`relative border-2 border-dashed rounded-2xl p-6 md:p-12 text-center transition-all duration-300 ${
        file ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'
      }`}>
        <input
          type="file"
          accept="audio/*"
          onChange={handleFileChange}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
        
        <div className="flex flex-col items-center pointer-events-none">
          {file ? (
            <>
              <div className="w-12 h-12 md:w-16 md:h-16 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center mb-3 md:mb-4">
                <FileAudio className="w-6 h-6 md:w-8 md:h-8" />
              </div>
              <p className="text-base md:text-lg font-medium text-slate-900 mb-1 truncate max-w-full px-4">{file.name}</p>
              <p className="text-xs md:text-sm text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
            </>
          ) : (
            <>
              <div className="w-12 h-12 md:w-16 md:h-16 bg-slate-100 text-slate-400 rounded-full flex items-center justify-center mb-3 md:mb-4">
                <UploadCloud className="w-6 h-6 md:w-8 md:h-8" />
              </div>
              <p className="text-base md:text-lg font-medium text-slate-900 mb-1">点击上传或拖拽文件至此</p>
              <p className="text-xs md:text-sm text-slate-500">支持 MP3, WAV, AAC, OGG (最大 20MB)</p>
            </>
          )}
        </div>
      </div>

      {/* Action Button */}
      <div className="mt-6 flex justify-center">
        <button
          onClick={handleTranscribe}
          disabled={!file || isTranscribing}
          className={`flex items-center px-6 py-2.5 md:px-8 md:py-3 rounded-full font-medium text-white shadow-lg transition-all duration-300 text-sm md:text-base ${
            !file || isTranscribing
              ? 'bg-slate-300 cursor-not-allowed'
              : 'bg-slate-900 hover:bg-indigo-600 hover:shadow-indigo-500/30 hover:-translate-y-0.5'
          }`}
        >
          {isTranscribing ? (
            <>
              <Loader2 className="w-4 h-4 md:w-5 md:h-5 mr-2 animate-spin" />
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
        <div className="mt-6 p-3 md:p-4 bg-red-50 border border-red-100 rounded-xl flex items-start gap-2 md:gap-3">
          <AlertCircle className="w-4 h-4 md:w-5 md:h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-xs md:text-sm text-red-700">{error}</p>
        </div>
      )}

      {/* Result Display */}
      {transcription && (
        <div className="mt-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <div className="flex items-center justify-between mb-3 px-2">
            <div className="flex items-center gap-2 text-green-600">
              <CheckCircle2 className="w-4 h-4 md:w-5 md:h-5" />
              <span className="font-medium text-sm">转写完成</span>
            </div>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-indigo-600 transition-colors px-3 py-1.5 rounded-lg hover:bg-slate-100"
            >
              <Copy className="w-3.5 h-3.5" />
              复制文本
            </button>
          </div>
          
          <div className="bg-white border border-slate-100 rounded-2xl p-4 md:p-8 shadow-sm">
            <p className="whitespace-pre-wrap text-slate-700 leading-relaxed text-base md:text-lg">
              {transcription}
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

export default FileTranscriber;