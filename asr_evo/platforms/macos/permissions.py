from __future__ import annotations


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
