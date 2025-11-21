/**
 * ASR 服务 - 连接到后端 API
 * 支持实时录音（WebSocket）和文件上传（REST API）两种模式
 */

// 后端 API 地址配置
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5006';

/**
 * 文件上传转录接口
 * 使用 SenseVoice 模型进行高准确度识别
 */
export const transcribeAudioFile = async (file: File): Promise<string> => {
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch(`${API_BASE_URL}/api/asr/transcribe`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`转录失败: ${response.statusText}`);
    }

    const result = await response.json();

    if (result.success) {
      return result.data.text;
    } else {
      throw new Error(result.error || '转录失败');
    }
  } catch (error: any) {
    console.error('文件转录错误:', error);
    throw new Error(error.message || '转录失败，请稍后重试');
  }
};

/**
 * 获取 API 健康状态
 */
export const checkHealth = async (): Promise<boolean> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    const data = await response.json();
    return data.status === 'ok';
  } catch {
    return false;
  }
};

/**
 * 获取支持的音频格式
 */
export const getSupportedFormats = async (): Promise<string[]> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/asr/formats`);
    const data = await response.json();
    return data.data.formats || [];
  } catch {
    return ['wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'wma'];
  }
};

export { API_BASE_URL };
