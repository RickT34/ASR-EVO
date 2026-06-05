from __future__ import annotations

from dataclasses import dataclass


class PermissionDeniedError(RuntimeError):
    def __init__(self, detail: str, *, suggestion: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.suggestion = suggestion


@dataclass(frozen=True)
class ErrorFeedback:
    title: str
    detail: str
    suggestion: str
    technical_detail: str = ""
    raw_text_saved: bool = False

    @property
    def tooltip(self) -> str:
        return f"{self.title}：{self.detail}。{self.suggestion}"

    def copy_text(self) -> str:
        parts = [
            f"错误：{self.title}",
            f"原因：{self.detail}",
            f"建议：{self.suggestion}",
        ]
        if self.raw_text_saved:
            parts.append("补充：原始转写已保存到历史记录，可从托盘历史记录复制。")
        if self.technical_detail:
            parts.append(f"技术细节：{self.technical_detail}")
        return "\n".join(parts)


def feedback_from_exception(exc: Exception, *, raw_text_saved: bool = False) -> ErrorFeedback:
    message = str(exc).strip() or exc.__class__.__name__
    lower_message = message.lower()
    title = "听写失败"
    detail = _compact_message(message)
    suggestion = "请稍后重试；如果连续失败，复制错误详情检查配置、网络和权限。"

    if isinstance(exc, PermissionDeniedError):
        title = "缺少系统权限"
        detail = exc.detail
        suggestion = exc.suggestion or "请按当前平台要求授予必要权限后重启应用。"
    elif "missing api key" in lower_message or "dashscope_api_key" in lower_message:
        title = "缺少 API Key"
        detail = ".env 中没有读取到 DASHSCOPE_API_KEY。"
        suggestion = "请在 .env 添加 DASHSCOPE_API_KEY=... 后重启应用，或重新加载配置。"
    elif "network error" in lower_message or "timed out" in lower_message or "timeout" in lower_message:
        title = "网络连接失败"
        detail = "连接 ASR/LLM 服务时失败或超时。"
        suggestion = "请检查网络、代理和 base_url；恢复后重新听写即可。"
    elif _has_status_code(lower_message, 401, 403):
        title = "服务鉴权失败"
        detail = "ASR/LLM 服务拒绝了当前请求。"
        suggestion = "请检查 DASHSCOPE_API_KEY 是否正确、是否有模型权限或额度。"
    elif _has_status_code(lower_message, 429):
        title = "请求过于频繁"
        detail = "服务端触发了限流。"
        suggestion = "请稍等一会儿再试；如果经常出现，降低连续听写频率或检查服务限额。"
    elif _has_status_code(lower_message, 400, 404):
        title = "服务配置有误"
        detail = "服务端无法识别当前请求、模型或地址。"
        suggestion = "请检查 config.toml 中的 model 和 base_url，然后重新加载配置。"
    elif _has_status_code(lower_message, 500, 502, 503, 504):
        title = "服务暂时不可用"
        detail = "ASR/LLM 服务端返回了临时错误。"
        suggestion = "请稍后重试；如果持续出现，检查服务状态或切换可用模型。"
    elif "accessibility permission" in lower_message or "grant accessibility" in lower_message:
        title = "缺少辅助功能权限"
        detail = "当前进程没有控制键盘或插入文本所需的系统权限。"
        suggestion = "请按当前平台要求授予辅助功能或输入控制权限后重启。"
    elif "microphone" in lower_message or "inputstream" in lower_message or "portaudio" in lower_message:
        title = "录音设备不可用"
        detail = "无法从麦克风开始录音。"
        suggestion = "请检查麦克风权限、默认输入设备，确认没有被其他软件独占。"
    elif "pyobjc appkit/quartz" in lower_message or "pasteboard insertion" in lower_message:
        title = "文本插入失败"
        detail = "无法通过剪贴板方式把结果插入当前应用。"
        suggestion = "请确认光标在可输入区域，并检查辅助功能权限；必要时用 asr-evo-insert-test 单独测试插入层。"
    elif "unicode event insertion" in lower_message:
        title = "文本插入失败"
        detail = "无法通过键盘事件方式输入文本。"
        suggestion = "请检查辅助功能权限，或切回默认 pasteboard_restore 插入方式。"
    elif "style not found" in lower_message or "prompt files" in lower_message:
        title = "提示词风格不可用"
        detail = "当前选择或绑定的提示词风格不存在。"
        suggestion = "请打开提示词文件夹检查文件是否存在，或重新选择一个风格。"

    if raw_text_saved:
        suggestion = f"{suggestion} 原始转写已保存到历史记录，可从托盘历史记录复制。"

    return ErrorFeedback(
        title=title,
        detail=detail,
        suggestion=suggestion,
        technical_detail=message,
        raw_text_saved=raw_text_saved,
    )


def _compact_message(message: str, *, limit: int = 120) -> str:
    text = " ".join(message.split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _has_status_code(message: str, *codes: int) -> bool:
    return any(
        f"provider http {code}" in message
        or f"error code: {code}" in message
        or f"status code: {code}" in message
        for code in codes
    )
