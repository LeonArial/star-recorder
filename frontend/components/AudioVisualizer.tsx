import React, { useEffect, useRef } from 'react';
import { AudioVisualizerProps } from '../types';

const AudioVisualizer: React.FC<AudioVisualizerProps> = ({ stream, isRecording }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);

  useEffect(() => {
    if (!stream || !isRecording || !canvasRef.current) {
      // Cleanup if stopped
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      if (contextRef.current && contextRef.current.state !== 'closed') {
        contextRef.current.close();
        contextRef.current = null;
      }
      // Clear canvas
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const initAudio = () => {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
      contextRef.current = audioCtx;
      
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;

      const source = audioCtx.createMediaStreamSource(stream);
      source.connect(analyser);
      sourceRef.current = source;

      draw();
    };

    const draw = () => {
      if (!canvasRef.current || !analyserRef.current) return;

      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const bufferLength = analyserRef.current.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      
      analyserRef.current.getByteFrequencyData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const width = canvas.width;
      const height = canvas.height;
      const barWidth = (width / bufferLength) * 2.5;
      let barHeight;
      let x = 0;

      // Soft gradient
      const gradient = ctx.createLinearGradient(0, height, 0, 0);
      gradient.addColorStop(0, 'rgba(99, 102, 241, 0.2)'); // Indigo-500 low opacity
      gradient.addColorStop(1, 'rgba(99, 102, 241, 0.8)'); // Indigo-500 high opacity

      ctx.fillStyle = gradient;

      for (let i = 0; i < bufferLength; i++) {
        barHeight = (dataArray[i] / 255) * height;
        
        // Rounded bars
        ctx.beginPath();
        if (typeof ctx.roundRect === 'function') {
            ctx.roundRect(x, height - barHeight, barWidth, barHeight, 4);
        } else {
            ctx.rect(x, height - barHeight, barWidth, barHeight);
        }
        ctx.fill();

        x += barWidth + 2;
      }

      animationRef.current = requestAnimationFrame(draw);
    };

    initAudio();

    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      if (contextRef.current) contextRef.current.close();
    };
  }, [stream, isRecording]);

  return (
    <canvas 
      ref={canvasRef} 
      width={600} 
      height={100} 
      className="w-full h-24 rounded-xl bg-slate-50 border border-slate-100"
    />
  );
};

export default AudioVisualizer;