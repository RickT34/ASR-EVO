# 百炼非实时文件转写

`qwen-audio-3.0-asr-flash-filetrans` 等 Filetrans 模型使用原生异步 HTTP 接口，不支持 OpenAI 兼容的 `/chat/completions`。请选择独立的 `dashscope_filetrans` 后端；`openai` 后端的行为保持不变，不会按模型名自动换协议。

```toml
[asr]
backend = "dashscope_filetrans"
model = "qwen-audio-3.0-asr-flash-filetrans"
base_url = "https://dashscope.aliyuncs.com/api/v1"
api_key_env = "DASHSCOPE_API_KEY"
language = "" # 自动识别；指定中文可填 zh
# 从上传开始到下载结果的整体超时，包含服务端排队与处理
timeout_seconds = 600
```

修改配置后使用菜单「重新加载配置」。首次安装该适配器代码后需要重启主程序。此配置用于普通听写、历史重转写与文件转写，实时模式继续使用独立的 `[realtime_asr]`。

处理流程：

1. 从百炼获取临时上传凭证，将本地音频上传到官方 OSS 临时存储。
2. 使用 `oss://` 临时地址调用 `/api/v1/services/audio/asr/transcription`，提交所选模型的异步任务。
3. 轮询 `/api/v1/tasks/{task_id}`，成功后下载文本结果并进入原有润色、确认流程。

无需自行部署文件服务器或配置 OSS 密钥。文件会上传到百炼临时存储，官方说明临时 URL 有效期为 48 小时；适合个人桌面用途，不适合作为生产环境的高并发上传方案。退出或超时会停止本地等待，已经提交的云端任务可能继续处理。录音仍按原有历史记录规则保存在本地。

`base_url` 的域名决定地域和业务空间，必须与密钥匹配；也支持官方业务空间专属域名，例如 `https://实际WorkspaceId.cn-beijing.maas.aliyuncs.com/api/v1`。原有 `/compatible-mode/v1` 地址在此后端中会规范化为同域名的 `/api/v1`，该转换仅适用于 `dashscope_filetrans`。

参考：[Filetrans 原生 HTTP API](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api)、[官方临时上传流程](https://help.aliyun.com/zh/model-studio/get-temporary-file-url/)。

`qwen-audio-3.1-asr-flash-message` 不属于 Filetrans 模型，请改用独立的 [dashscope_message 后端](MESSAGE.md)，不能只修改模型名继续提交 Filetrans 任务。
