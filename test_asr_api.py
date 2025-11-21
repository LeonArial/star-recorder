"""
ASR API 测试脚本
用于测试语音识别API的各个接口
"""
import requests
import json
import os

# API配置
BASE_URL = "http://localhost:5006"
# BASE_URL = "http://10.8.75.207:5006"  # 使用内网服务器

def test_health():
    """测试健康检查接口"""
    print("=" * 60)
    print("测试 1: 健康检查")
    print("=" * 60)
    
    url = f"{BASE_URL}/api/health"
    response = requests.get(url)
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()


def test_models_info():
    """测试获取模型信息接口"""
    print("=" * 60)
    print("测试 2: 获取模型信息")
    print("=" * 60)
    
    url = f"{BASE_URL}/api/asr/models"
    response = requests.get(url)
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()


def test_formats():
    """测试获取支持格式接口"""
    print("=" * 60)
    print("测试 3: 获取支持的音频格式")
    print("=" * 60)
    
    url = f"{BASE_URL}/api/asr/formats"
    response = requests.get(url)
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()


def test_transcribe(audio_file_path):
    """测试音频转录接口（文件上传模式，仅SenseVoice）"""
    print("=" * 60)
    print("测试 4: 音频文件转录（仅SenseVoice）")
    print("=" * 60)
    
    if not os.path.exists(audio_file_path):
        print(f"❌ 音频文件不存在: {audio_file_path}")
        print("请提供有效的音频文件路径")
        return
    
    url = f"{BASE_URL}/api/asr/transcribe"
    
    # 准备请求
    files = {"file": open(audio_file_path, "rb")}
    
    print(f"上传文件: {audio_file_path}")
    print("正在处理，请稍候...")
    
    try:
        response = requests.post(url, files=files, timeout=60)
        
        print(f"\n状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            if result["success"]:
                print("\n✅ 转录成功！")
                print("-" * 60)
                
                # SenseVoice结果（文件上传模式只返回SenseVoice）
                data = result["data"]
                print(f"\n✨ SenseVoice 识别结果 ({data['length']}字):")
                print(f"   {data['text']}")
                
                print("-" * 60)
                print(f"\n文件名: {result.get('filename', 'N/A')}")
                print(f"模式: {result.get('mode', 'N/A')}")
                print(f"模型: {data.get('model', 'N/A')}")
            else:
                print(f"\n❌ 转录失败: {result.get('error', '未知错误')}")
        else:
            print(f"\n❌ 请求失败: {response.text}")
    
    except requests.exceptions.Timeout:
        print("\n❌ 请求超时，音频文件可能太大")
    except Exception as e:
        print(f"\n❌ 错误: {str(e)}")
    finally:
        files["file"].close()
    
    print()


def test_error_cases():
    """测试错误情况"""
    print("=" * 60)
    print("测试 5: 错误处理")
    print("=" * 60)
    
    # 测试1: 不上传文件
    print("\n测试 5.1: 未上传文件")
    url = f"{BASE_URL}/api/asr/transcribe"
    response = requests.post(url)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    
    # 测试2: 不支持的文件格式（如果有测试文件）
    print("\n测试 5.2: 不支持的文件格式")
    # 这里可以创建一个临时的txt文件测试
    test_file = "test_invalid.txt"
    with open(test_file, "w") as f:
        f.write("This is not an audio file")
    
    files = {"file": open(test_file, "rb")}
    response = requests.post(url, files=files)
    files["file"].close()
    os.remove(test_file)
    
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()


def main():
    """主测试函数"""
    print("\n")
    print("🎙️  ASR API 测试工具")
    print("=" * 60)
    print(f"测试服务器: {BASE_URL}")
    print("=" * 60)
    print("\n")
    
    # 测试基础接口
    test_health()
    test_models_info()
    test_formats()
    
    # 测试音频转录
    # 请修改为您的实际音频文件路径
    audio_file = "test.mp3"  # 修改为实际的音频文件路径
    
    if os.path.exists(audio_file):
        # 测试文件转录（仅SenseVoice）
        test_transcribe(audio_file)
    else:
        print("=" * 60)
        print("⚠️  跳过音频转录测试")
        print("=" * 60)
        print(f"音频文件不存在: {audio_file}")
        print("请将测试音频文件放在当前目录，或修改 audio_file 变量的路径")
        print()
    
    # 测试错误情况
    test_error_cases()
    
    print("=" * 60)
    print("✅ 所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
