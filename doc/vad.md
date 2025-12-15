# FSMN-Monophone VAD 模型介绍

## Highlight

* 16k中文通用VAD模型：可用于检测长语音片段中有效语音的起止时间点。
  * 基于[Paraformer-large长音频模型](https://www.modelscope.cn/models/damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch/summary)场景的使用
  * 基于[FunASR框架](https://github.com/alibaba-damo-academy/FunASR)，可进行ASR，VAD，[中文标点](https://www.modelscope.cn/models/damo/punc_ct-transformer_zh-cn-common-vocab272727-pytorch/summary)的自由组合
  * 基于音频数据的有效语音片段起止时间点检测

## **[FunASR开源项目介绍](https://github.com/alibaba-damo-academy/FunASR)**

**[FunASR](https://github.com/alibaba-damo-academy/FunASR)**希望在语音识别的学术研究和工业应用之间架起一座桥梁。通过发布工业级语音识别模型的训练和微调，研究人员和开发人员可以更方便地进行语音识别模型的研究和生产，并推动语音识别生态的发展。让语音识别更有趣！

[**github仓库**](https://github.com/alibaba-damo-academy/FunASR) | [**最新动态**](https://github.com/alibaba-damo-academy/FunASR#whats-new) | [**环境安装**](https://github.com/alibaba-damo-academy/FunASR#installation) | [**服务部署**](https://www.funasr.com/) | [**模型库**](https://github.com/alibaba-damo-academy/FunASR/tree/main/model_zoo) | [**联系我们**](https://github.com/alibaba-damo-academy/FunASR#contact)

## 模型原理介绍

FSMN-Monophone VAD是达摩院语音团队提出的高效语音端点检测模型，用于检测输入音频中有效语音的起止时间点信息，并将检测出来的有效音频片段输入识别引擎进行识别，减少无效语音带来的识别错误。

![VAD模型结构](https://www.modelscope.cn/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch/resolve/master/fig/struct.png)

FSMN-Monophone VAD模型结构如上图所示：模型结构层面，FSMN模型结构建模时可考虑上下文信息，训练和推理速度快，且时延可控；同时根据VAD模型size以及低时延的要求，对FSMN的网络结构、右看帧数进行了适配。在建模单元层面，speech信息比较丰富，仅用单类来表征学习能力有限，我们将单一speech类升级为Monophone。建模单元细分，可以避免参数平均，抽象学习能力增强，区分性更好。

## 基于ModelScope进行推理

* 推理支持音频格式如下：
  * wav文件路径，例如：data/test/audios/vad_example.wav
  * wav文件url，例如：[https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.wav](https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.wav)
  * wav二进制数据，格式bytes，例如：用户直接从文件里读出bytes数据或者是麦克风录出bytes数据。
  * 已解析的audio音频，例如：audio, rate = soundfile.read("vad_example_zh.wav")，类型为numpy.ndarray或者torch.Tensor。
  * wav.scp文件，需符合如下要求：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-sh"><span><span>cat wav.scp
</span></span><span>vad_example1  data/test/audios/vad_example1.wav
</span><span>vad_example2  data/test/audios/vad_example2.wav
</span><span>...
</span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="0edb1100649548" autolog-exp-reported="1"></div></div></div></pre>

* 若输入格式wav文件url，api调用方式可参考如下范例：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-python"><span><span>from</span><span> modelscope.pipelines </span><span>import</span><span> pipeline
</span></span><span><span></span><span>from</span><span> modelscope.utils.constant </span><span>import</span><span> Tasks
</span></span><span>
</span><span>inference_pipeline = pipeline(
</span><span>    task=Tasks.voice_activity_detection,
</span><span><span>    model=</span><span>'iic/speech_fsmn_vad_zh-cn-16k-common-pytorch'</span><span>,
</span></span><span><span>    model_revision=</span><span>"v2.0.4"</span><span>,
</span></span><span>)
</span><span>
</span><span><span>segments_result = inference_pipeline(</span><span>input</span><span>=</span><span>'https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.wav'</span><span>)
</span></span><span><span></span><span>print</span><span>(segments_result)
</span></span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="08fb523ac56f46" autolog-exp-reported="1"></div></div></div></pre>

* 输入音频为pcm格式，调用api时需要传入音频采样率参数fs，例如：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-python"><span><span>segments_result = inference_pipeline(</span><span>input</span><span>=</span><span>'https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/vad_example.pcm'</span><span>, fs=</span><span>16000</span><span>)
</span></span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="53950c0278b94e" autolog-exp-reported="1"></div></div></div></pre>

* 若输入格式为文件wav.scp(注：文件名需要以.scp结尾)，可添加 output_dir 参数将识别结果写入文件中，参考示例如下：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-python"><span><span>inference_pipeline(</span><span>input</span><span>=</span><span>"wav.scp"</span><span>, output_dir=</span><span>'./output_dir'</span><span>)
</span></span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="82ba9bf079464a" autolog-exp-reported="1"></div></div></div></pre>

识别结果输出路径结构如下：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-sh"><span><span>tree output_dir/
</span></span><span>output_dir/
</span><span>└── 1best_recog
</span><span>    └── text
</span><span>
</span><span>1 directory, 1 files
</span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="03a69d527a0047" autolog-exp-reported="1"></div></div></div></pre>

text：VAD检测语音起止时间点结果文件（单位：ms）

* 若输入音频为已解析的audio音频，api调用方式可参考如下范例：

<pre><div class="acss-q09o5g"><div node="[object Object]"><code class="language-python"><span><span>import</span><span> soundfile
</span></span><span>
</span><span><span>waveform, sample_rate = soundfile.read(</span><span>"vad_example_zh.wav"</span><span>)
</span></span><span><span>segments_result = inference_pipeline(</span><span>input</span><span>=waveform)
</span></span><span><span></span><span>print</span><span>(segments_result)
</span></span><span></span></code></div><div class="acss-1wlnmrj"><span role="img" tabindex="-1" class="anticon acss-1sra2vo acss-yiit70"><svg width="1em" height="1em" fill="currentColor" aria-hidden="true" focusable="false" class=""><use xlink:href="#icon-maasfuzhi-copy-line"></use></svg></span><div data-autolog="clk=true&exp=true&c3=notebook&c4=openNotebookDrawerFree&c5=%7B%22source%22%3A%22codeBlock%22%2C%22inNotebook%22%3Afalse%7D" autolog-exp-hash="5704af9bd4fd47" autolog-exp-reported="1"></div></div></div></pre>

* VAD常用参数调整说明（参考：vad.yaml文件）：
  * max_end_silence_time：尾部连续检测到多长时间静音进行尾点判停，参数范围500ms～6000ms，默认值800ms(该值过低容易出现语音提前截断的情况)。
  * speech_noise_thres：speech的得分减去noise的得分大于此值则判断为speech，参数范围：（-1,1）
    * 取值越趋于-1，噪音被误判定为语音的概率越大，FA越高
    * 取值越趋于+1，语音被误判定为噪音的概率越大，Pmiss越高
    * 通常情况下，该值会根据当前模型在长语音测试集上的效果取balance
