# 实时转写润色模式

托盘（包括 Waybar 右键菜单）中的「实时转写润色模式」开关会保存到 `config.toml`，默认关闭。请先配置流式 ASR 并重新加载配置，再开启开关。切换仅在没有听写任务时生效。

开启后，开始录音即打开原有确认窗口：

- 左侧显示流式识别的当前完整文本，包括尚未定稿的部分；识别修正会替换旧内容。
- 右侧按 `review.polish_interval_seconds` 定时润色最新全文，默认 5 秒。同一时间只有一个润色请求；没有新文字时不重复请求。
- 尚未润色的新增内容会立即显示在右侧「待润色」区域。若 ASR 修正了已经润色的原文，会显示待处理的新版本，下一次润色后替换。
- 点击「停止录音」或使用原来的停止快捷键，等待 ASR 提交尾句、完成最终润色，再编辑和确认插入。录音中暂不可编辑右侧或切换提示词，以免更新覆盖用户修改。
- 关闭窗口或点击「取消」会停止录音、不插入文字，并保存已收到的转写及完整录音到历史记录。实时模式始终需要确认，不受 `review.enabled` 影响。

这是连续音频帧输入的流式会话，不会定时保存音频快照，也不会反复调用普通文件转写 API。原来的 `[asr]` 仍用于普通模式、历史重转写和文件转写；实时模式独立使用 `[realtime_asr]`，不会自动回退到普通接口。

## 云端：百炼 Qwen-ASR-Realtime

安装应用环境中的流式依赖：

```bash
uv pip install --python .venv/bin/python -e '.[realtime]'
```

在 `config.toml` 添加下面的表（已存在则修改，避免重复表）：

```toml
[realtime_asr]
backend = "dashscope"
url = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
model = "qwen3-asr-flash-realtime"
api_key_env = "ASR_REALTIME_API_KEY"
language = "zh"
timeout_seconds = 600

[review]
enabled = true
realtime_enabled = false
polish_interval_seconds = 5.0
```

在 `.env` 设置 `ASR_REALTIME_API_KEY`。接口地域须与密钥、模型的开通地域相符。可以显式将 `api_key_env` 设置为已有密钥变量名，但不会自动复用普通 ASR 密钥。此适配器支持百炼的 Qwen-ASR-Realtime 会话协议和 Qwen-Audio-ASR-Streaming 任务协议，不是任意 OpenAI 兼容 WebSocket 服务。

采用 16 kHz、单声道 PCM16 连续上传、服务端 VAD 分句；停止时发送 `session.finish` 并等待 `session.finished`，保留最后一句。会话错误会停止录音并保留历史，不会静默丢失音频或重新上传整个会话。

参考：[连接说明](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-model-access)、[客户端事件](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-client-events)、[服务端事件](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-realtime-server-events)。

### Qwen-Audio-3.x-ASR-Flash-Streaming

`qwen-audio-3.0-asr-flash-streaming`、`qwen-audio-3.1-asr-flash-streaming` 使用另一种任务协议：

```toml
[realtime_asr]
backend = "dashscope"
url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
model = "qwen-audio-3.0-asr-flash-streaming"
api_key_env = "ASR_REALTIME_API_KEY"
language = "zh"
```

程序按模型系列选择协议，并将标准路径 `/api-ws/v1/realtime` 或 `/api-ws/v1/inference` 匹配到对应接口，保留配置的地域、域名和业务空间。已有配置即使保留 `/realtime`，这些模型也会使用 `/inference`。模型在 `run-task` 消息中指定；收到 `task-started` 后发送二进制 PCM，停止时发送 `finish-task`，等待 `task-finished` 并收齐尾句。不要把两种协议的模型名和消息格式混用，否则可能收到 1007 / Model not found。

官方推荐业务空间专属域名，按账号实际 Workspace ID 和地域填写；模型权限和可用地域以账号实际开通情况为准。[官方任务协议说明](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-websocket-api)。

## 本地：Qwen3-ASR-0.6B

Qwen 官方 Python 流式接口要求 **vLLM 后端**。普通模式使用的 Transformers 环境不能直接代替；建议为 vLLM 使用独立 Linux Python 环境和可用 GPU，按 Qwen 官方依赖要求安装：

```bash
uv venv .venv-qwen-stream --python 3.12
uv pip install --python .venv-qwen-stream/bin/python 'qwen-asr[vllm]>=0.0.6'
uv pip install --python .venv/bin/python -e '.[realtime]'
```

然后配置：

```toml
[realtime_asr]
backend = "qwen_local"
model = "Qwen/Qwen3-ASR-0.6B" # 也可以填写已下载的本地模型目录
python_executable = "/绝对路径/ASR-EVO/.venv-qwen-stream/bin/python"
language = "Chinese" # 空字符串表示自动识别；云端使用 zh 等语言代码
chunk_size_seconds = 2.0
# vLLM 预留显存比例，需要为本地 LLM 留出空间
# 显存不足时应调整模型部署/设备，不能只凭模型参数量判断能否同时运行。
gpu_memory_utilization = 0.5
timeout_seconds = 600
```

每次录音启动一个模型子进程，并在整个流式会话中复用 `init_streaming_state` 创建的状态，连续调用 `streaming_transcribe`，停止时调用 `finish_streaming_transcribe`。录音结束、取消或失败后终止整个模型进程组，释放本地 ASR 显存。冷启动时加载模型会延迟首字；音频会先缓冲，积压超过约两分钟时停止并保留录音，避免无限积压。

应用不自行制作全量音频快照；Qwen 官方流式实现内部的音频累积、前缀回退由其推理库负责。参考：[官方流式示例](https://github.com/QwenLM/Qwen3-ASR/blob/main/examples/example_qwen3_asr_vllm_streaming.py)。

## 润色模型

继续使用所选提示词的现有 LLM profile，支持云端或本地 Ollama。`keep_alive_seconds = 0` 会在每次请求后卸载 Ollama 模型，可能增加实时润色延迟；可按自己的内存条件设置短暂保留时间。ASR 和 LLM 可同时使用 GPU，需为两者预留空间。实际更新频率取决于识别速度、生成速度和配置间隔。

## 统一自动润色开关

托盘和 Waybar 右键菜单的「LLM 自动润色」统一控制实时与非实时听写，默认开启，保存为 `[llm] auto_polish = true/false`。在没有进行中任务时切换，下次听写生效。

关闭后，非实时听写直接使用转写原文；实时窗口左右两侧同步显示原文，录音中和结束时均不自动调用 LLM。确认窗口可点击「润色一次」或按 Ctrl+R（macOS 为 Command+R）手动处理当前原文；实时模式须先停止录音、等待转写完成。手动润色不改变全局开关，关闭开关时编辑提示词、切换风格也不会自动发起请求。

「插入前确认文本」是独立开关：非实时模式同时关闭两项时直接输入原文。历史「重新转写」和文件转写命令也遵循自动润色开关；明确选择历史「重新润色」仍会调用 LLM。
