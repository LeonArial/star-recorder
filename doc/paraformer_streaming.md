## 快速使用

python代码调用（推荐）

```python
from funasr import AutoModel

model = AutoModel(model="paraformer-zh")

res = model.generate(input="https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.wav")
print(res)
```

### 接口说明

#### AutoModel 定义

```python
model = AutoModel(model=[str], device=[str], ncpu=[int], output_dir=[str], batch_size=[int], hub=[str], **kwargs)
```

- `model`(str): [模型仓库](https://github.com/alibaba-damo-academy/FunASR/tree/main/model_zoo) 中的模型名称，或本地磁盘中的模型路径
- `device`(str): `cuda:0`（默认gpu0），使用 GPU 进行推理，指定。如果为 `cpu`，则使用 CPU 进行推理
- `ncpu`(int): `4` （默认），设置用于 CPU 内部操作并行性的线程数
- `output_dir`(str): `None` （默认），如果设置，输出结果的输出路径
- `batch_size`(int): `1` （默认），解码时的批处理，样本个数
- `hub`(str)：`ms`（默认），从modelscope下载模型。如果为 `hf`，从huggingface下载模型。
- `**kwargs`(dict): 所有在 `config.yaml`中参数，均可以直接在此处指定，例如，vad模型中最大切割长度 `max_single_segment_time=6000` （毫秒）。

#### AutoModel 推理

```python
res = model.generate(input=[str], output_dir=[str])
```

- `input`: 要解码的输入，可以是：

  - wav文件路径, 例如: asr_example.wav
  - pcm文件路径, 例如: asr_example.pcm，此时需要指定音频采样率fs（默认为16000）
  - 音频字节数流，例如：麦克风的字节数数据
  - wav.scp，kaldi 样式的 wav 列表 (`wav_id \t wav_path`), 例如:

  ```text
  asr_example1  ./audios/asr_example1.wav
  asr_example2  ./audios/asr_example2.wav
  ```

  在这种输入 `wav.scp` 的情况下，必须设置 `output_dir` 以保存输出结果- 音频采样点，例如：`audio, rate = soundfile.read("asr_example_zh.wav")`, 数据类型为 numpy.ndarray。支持batch输入，类型为list：
  ``[audio_sample1, audio_sample2, ..., audio_sampleN]``

  - fbank输入，支持组batch。shape为[batch, frames, dim]，类型为torch.Tensor，例如
- `output_dir`: None （默认），如果设置，输出结果的输出路径
- `**kwargs`(dict): 与模型相关的推理参数，例如，`beam_size=10`，`decoding_ctc_weight=0.1`。

#### 实时语音识别

```python
from funasr import AutoModel

chunk_size = [0, 10, 5] #[0, 10, 5] 600ms, [0, 8, 4] 480ms
encoder_chunk_look_back = 4 #number of chunks to lookback for encoder self-attention
decoder_chunk_look_back = 1 #number of encoder chunks to lookback for decoder cross-attention

model = AutoModel(model="paraformer-zh-streaming")

import soundfile
import os

wav_file = os.path.join(model.model_path, "example/asr_example.wav")
speech, sample_rate = soundfile.read(wav_file)
chunk_stride = chunk_size[1] * 960 # 600ms

cache = {}
total_chunk_num = int(len((speech)-1)/chunk_stride+1)
for i in range(total_chunk_num):
    speech_chunk = speech[i*chunk_stride:(i+1)*chunk_stride]
    is_final = i == total_chunk_num - 1
    res = model.generate(input=speech_chunk, cache=cache, is_final=is_final, chunk_size=chunk_size, encoder_chunk_look_back=encoder_chunk_look_back, decoder_chunk_look_back=decoder_chunk_look_back)
    print(res)
```

注：`chunk_size`为流式延时配置，`[0,10,5]`表示上屏实时出字粒度为 `10*60=600ms`，未来信息为 `5*60=300ms`。每次推理输入为 `600ms`（采样点数为 `16000*0.6=960`），输出为对应文字，最后一个语音片段输入需要设置 `is_final=True`来强制输出最后一个字。

#### 语音端点检测（实时）

```python
from funasr import AutoModel

chunk_size = 200 # ms
model = AutoModel(model="fsmn-vad")

import soundfile

wav_file = f"{model.model_path}/example/vad_example.wav"
speech, sample_rate = soundfile.read(wav_file)
chunk_stride = int(chunk_size * sample_rate / 1000)

cache = {}
total_chunk_num = int(len((speech)-1)/chunk_stride+1)
for i in range(total_chunk_num):
    speech_chunk = speech[i*chunk_stride:(i+1)*chunk_stride]
    is_final = i == total_chunk_num - 1
    res = model.generate(input=speech_chunk, cache=cache, is_final=is_final, chunk_size=chunk_size)
    if len(res[0]["value"]):
        print(res)
```

注：流式VAD模型输出格式为4种情况：

- `[[beg1, end1], [beg2, end2], .., [begN, endN]]`：同上离线VAD输出结果。
- `[[beg, -1]]`：表示只检测到起始点。
- `[[-1, end]]`：表示只检测到结束点。
- `[]`：表示既没有检测到起始点，也没有检测到结束点
  输出结果单位为毫秒，从起始点开始的绝对时间。

#### 标点恢复

```python
from funasr import AutoModel

model = AutoModel(model="ct-punc")

res = model.generate(input="那今天的会就到这里吧 happy new year 明年见")
print(res)
```

#### 标点恢复实时

```python
from funasr import AutoModel

model = AutoModel(model="iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727")

inputs = "跨境河流是养育沿岸|人民的生命之源长期以来为帮助下游地区防灾减灾中方技术人员|在上游地区极为恶劣的自然条件下克服巨大困难甚至冒着生命危险|向印方提供汛期水文资料处理紧急事件中方重视印方在跨境河流问题上的关切|愿意进一步完善双方联合工作机制|凡是|中方能做的我们|都会去做而且会做得更好我请印度朋友们放心中国在上游的|任何开发利用都会经过科学|规划和论证兼顾上下游的利益"
vads = inputs.split("|")
rec_result_all = "outputs: "
cache = {}
for vad in vads:
    rec_result = model.generate(input=vad, cache=cache)
    rec_result_all += rec_result[0]["text"]

print(rec_result_all)
```


#### 时间戳预测

```python
from funasr import AutoModel

model = AutoModel(model="fa-zh")

wav_file = f"{model.model_path}/example/asr_example.wav"
text_file = f"{model.model_path}/example/text.txt"
res = model.generate(input=(wav_file, text_file), data_type=("sound", "text"))
print(res)
```

更多（[示例](https://github.com/alibaba-damo-academy/FunASR/tree/main/examples/industrial_data_pretraining)）

`<a name="核心功能"></a>`

### 详细参数介绍

```shell
funasr/bin/train.py \
++model="${model_name_or_model_dir}" \
++train_data_set_list="${train_data}" \
++valid_data_set_list="${val_data}" \
++dataset_conf.batch_size=20000 \
++dataset_conf.batch_type="token" \
++dataset_conf.num_workers=4 \
++train_conf.max_epoch=50 \
++train_conf.log_interval=1 \
++train_conf.resume=false \
++train_conf.validate_interval=2000 \
++train_conf.save_checkpoint_interval=2000 \
++train_conf.keep_nbest_models=20 \
++train_conf.avg_nbest_model=10 \
++optim_conf.lr=0.0002 \
++output_dir="${output_dir}" &> ${log_file}
```

- `model`（str）：模型名字（模型仓库中的ID），此时脚本会自动下载模型到本读；或者本地已经下载好的模型路径。
- `train_data_set_list`（str）：训练数据路径，默认为jsonl格式，具体参考（[例子](https://github.com/alibaba-damo-academy/FunASR/blob/main/data/list)）。
- `valid_data_set_list`（str）：验证数据路径，默认为jsonl格式，具体参考（[例子](https://github.com/alibaba-damo-academy/FunASR/blob/main/data/list)）。
- `dataset_conf.batch_type`（str）：`example`（默认），batch的类型。`example`表示按照固定数目batch_size个样本组batch；`length` or `token` 表示动态组batch，batch总长度或者token数为batch_size。
- `dataset_conf.batch_size`（int）：与 `batch_type` 搭配使用，当 `batch_type=example` 时，表示样本个数；当 `batch_type=length` 时，表示样本中长度，单位为fbank帧数（1帧10ms）或者文字token个数。
- `train_conf.max_epoch`（int）：`100`（默认），训练总epoch数。
- `train_conf.log_interval`（int）：`50`（默认），打印日志间隔step数。
- `train_conf.resume`（int）：`True`（默认），是否开启断点重训。
- `train_conf.validate_interval`（int）：`5000`（默认），训练中做验证测试的间隔step数。
- `train_conf.save_checkpoint_interval`（int）：`5000`（默认），训练中模型保存间隔step数。
- `train_conf.avg_keep_nbest_models_type`（str）：`acc`（默认），保留nbest的标准为acc（越大越好）。`loss`表示，保留nbest的标准为loss（越小越好）。
- `train_conf.keep_nbest_models`（int）：`500`（默认），保留最大多少个模型参数，配合 `avg_keep_nbest_models_type` 按照验证集 acc/loss 保留最佳的n个模型，其他删除，节约存储空间。
- `train_conf.avg_nbest_model`（int）：`10`（默认），保留最大多少个模型参数，配合 `avg_keep_nbest_models_type` 按照验证集 acc/loss 对最佳的n个模型平均。
- `train_conf.accum_grad`（int）：`1`（默认），梯度累积功能。
- `train_conf.grad_clip`（float）：`10.0`（默认），梯度截断功能。
- `train_conf.use_fp16`（bool）：`False`（默认），开启fp16训练，加快训练速度。
- `optim_conf.lr`（float）：学习率。
- `output_dir`（str）：模型保存路径。
- `**kwargs`(dict): 所有在 `config.yaml`中参数，均可以直接在此处指定，例如，过滤20s以上长音频：`dataset_conf.max_token_length=2000`，单位为音频fbank帧数（1帧10ms）或者文字token个数。
