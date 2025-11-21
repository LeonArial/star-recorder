import { GoogleGenAI } from "@google/genai";

// Helper to convert file to Base64
export const fileToGenerativePart = async (file: File): Promise<{ inlineData: { data: string; mimeType: string } }> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const base64String = (reader.result as string).split(',')[1];
      resolve({
        inlineData: {
          data: base64String,
          mimeType: file.type,
        },
      });
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

export const transcribeAudioFile = async (file: File): Promise<string> => {
  if (!process.env.API_KEY) {
    throw new Error("API Key is missing");
  }

  const ai = new GoogleGenAI({ apiKey: process.env.API_KEY });
  const audioPart = await fileToGenerativePart(file);

  const model = 'gemini-2.5-flash'; 
  
  const response = await ai.models.generateContent({
    model: model,
    contents: {
      parts: [
        audioPart,
        {
          text: "请提供此音频文件的精确逐字转录。不要添加任何评论、介绍性短语或时间戳。只需提供原始内容。",
        },
      ],
    },
  });

  return response.text || "未生成转写内容。";
};