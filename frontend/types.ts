export enum TranscriptionMode {
  REALTIME = 'REALTIME',
  UPLOAD = 'UPLOAD'
}

export interface AudioVisualizerProps {
  stream: MediaStream | null;
  isRecording: boolean;
}

export interface TranscriptionSegment {
  id: string;
  text: string;
  isFinal: boolean;
  timestamp: number;
}