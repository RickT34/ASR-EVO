from __future__ import annotations

from asr_evo.core.errors import PermissionDeniedError


MACOS_ACCESSIBILITY_SUGGESTION = (
    "请到系统设置 -> 隐私与安全性 -> 辅助功能，为终端或 Python 解释器开启权限后重启。"
)


class MacOSPermissions:
    def accessibility_trusted(self, *, prompt: bool = False) -> bool:
        try:
            import ApplicationServices as AS
        except ImportError:
            return False

        options = None
        if prompt:
            options = {AS.kAXTrustedCheckOptionPrompt: True}
        return bool(AS.AXIsProcessTrustedWithOptions(options))

    def microphone_status(self) -> str:
        try:
            from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        except ImportError:
            return "unknown"
        return str(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))

    def accessibility_error(self) -> PermissionDeniedError:
        return PermissionDeniedError(
            "当前进程没有控制键盘或插入文本所需的 macOS 辅助功能权限。",
            suggestion=MACOS_ACCESSIBILITY_SUGGESTION,
        )
