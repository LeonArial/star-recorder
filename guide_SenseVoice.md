# SenseVoice
# 用法 🛠️

## 推理

### 使用 funasr 推理

支持任意格式音频输入，支持任意时长输入

```python
from funasr import AutoModel
from funasr.utils.postprocess_utils import rich_transcription_postprocess

model_dir = "iic/SenseVoiceSmall"


model = AutoModel(
    model=model_dir,
    trust_remote_code=True,
    remote_code="./model.py",  
    vad_model="fsmn-vad",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cuda:0",
)

res = model.generate(
    input=f"{model.model_path}/example/en.mp3",
    cache={},
    language="auto",  # "zh", "en", "yue", "ja", "ko", "nospeech"
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=15,
)
text = rich_transcription_postprocess(res[0]["text"])
print(text)
```

<details><summary> 参数说明（点击展开）</summary>

- `model_dir`：模型名称，或本地磁盘中的模型路径。
- `trust_remote_code`：
  - `True` 表示 model 代码实现从 `remote_code` 处加载，`remote_code` 指定 `model` 具体代码的位置（例如，当前目录下的 `model.py`），支持绝对路径与相对路径，以及网络 url。
  - `False` 表示，model 代码实现为 [FunASR](https://github.com/modelscope/FunASR) 内部集成版本，此时修改当前目录下的 `model.py` 不会生效，因为加载的是 funasr 内部版本，模型代码 [点击查看](https://github.com/modelscope/FunASR/tree/main/funasr/models/sense_voice)。
- `vad_model`：表示开启 VAD，VAD 的作用是将长音频切割成短音频，此时推理耗时包括了 VAD 与 SenseVoice 总耗时，为链路耗时，如果需要单独测试 SenseVoice 模型耗时，可以关闭 VAD 模型。
- `vad_kwargs`：表示 VAD 模型配置，`max_single_segment_time`: 表示 `vad_model` 最大切割音频时长，单位是毫秒 ms。
- `use_itn`：输出结果中是否包含标点与逆文本正则化。
- `batch_size_s` 表示采用动态 batch，batch 中总音频时长，单位为秒 s。
- `merge_vad`：是否将 vad 模型切割的短音频碎片合成，合并后长度为 `merge_length_s`，单位为秒 s。
- `ban_emo_unk`：禁用 emo_unk 标签，禁用后所有的句子都会被赋与情感标签。默认 `False`

</details>

如果输入均为短音频（小于 30s），并且需要批量化推理，为了加快推理效率，可以移除 vad 模型，并设置 `batch_size`

```python
model = AutoModel(model=model_dir, trust_remote_code=True, device="cuda:0")

res = model.generate(
    input=f"{model.model_path}/example/en.mp3",
    cache={},
    language="auto", # "zh", "en", "yue", "ja", "ko", "nospeech"
    use_itn=True,
    batch_size=64, 
)
```

更多详细用法，请参考 [文档](https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md)

### 直接推理

支持任意格式音频输入，输入音频时长限制在 30s 以下

```python
from model import SenseVoiceSmall
from funasr.utils.postprocess_utils import rich_transcription_postprocess

model_dir = "iic/SenseVoiceSmall"
m, kwargs = SenseVoiceSmall.from_pretrained(model=model_dir, device="cuda:0")
m.eval()

res = m.inference(
    data_in=f"{kwargs ['model_path']}/example/en.mp3",
    language="auto", # "zh", "en", "yue", "ja", "ko", "nospeech"
    use_itn=False,
    ban_emo_unk=False,
    **kwargs,
)

text = rich_transcription_postprocess(res [0][0]["text"])
print(text)
```