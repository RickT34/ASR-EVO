# 百炼 Message ASR

`qwen-audio-3.1-asr-flash-message` 使用 WebSocket `run-task` / 二进制音频 / `finish-task` 协议，不支持 Filetrans 的 HTTP 异步任务接口。普通听写、历史重转写和文件转写可使用独立后端：

```toml
[asr]
backend = "dashscope_message"
model = "qwen-audio-3.1-asr-flash-message"
base_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
api_key_env = "DASHSCOPE_API_KEY"
timeout_seconds = 600
```

安装 WebSocket 和音频重采样依赖：

```bash
uv pip install --python .venv/bin/python -e '.[realtime]'
```

停止录音后，程序读取本地音频，转换为 16 kHz 单声道 PCM16，通过 WebSocket 连续发送，等待服务端最终结果再进入原有确认和插入流程。不需要临时 OSS 上传或 HTTP 任务轮询。输入文件必须能由本机 SoundFile 解码；应用自身录制的 WAV 支持此流程。模型自动识别语种，不发送原有 `asr.language` 字段。

此后端只在显式设置 `backend = "dashscope_message"` 时使用，不改变 `openai` 或 `dashscope_filetrans` 的行为。`base_url` 也接受同地域的 `https://.../api/v1` 并规范化为 WebSocket 地址；域名和业务空间保持不变，必须与密钥地域一致。

模型内置的 `disfluency_removal_enabled` 固定为 `false`，避免 ASR 隐式启用额外润色。项目的 LLM 润色继续由统一的 `[llm] auto_polish` 开关控制。

如果要在录音过程中实时显示该模型的中间结果，可另外将 `[realtime_asr]` 的 `backend` 设置为 `dashscope`、`model` 设置为 `qwen-audio-3.1-asr-flash-message`，`url` 设置为同一 WebSocket 地址；适配器会启用 `intermediate_result_enabled`。两种模式的 ASR 配置独立。

首次更新代码后重启 ASR-EVO；以后仅修改配置时可使用菜单「重新加载配置」。

官方参考：[Message WebSocket 接口](https://www.alibabacloud.com/help/en/model-studio/qwen-asr-message-websocket-api)、[客户端事件](https://help.aliyun.com/zh/model-studio/qwen-asr-message-client-events)。
