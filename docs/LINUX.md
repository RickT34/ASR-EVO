# Linux 与本地模型

Linux 复用现有听写、提示词、确认窗口、上下文和 SQLite 历史流程。优先支持 Hyprland；X11 使用 xdotool，其他 Wayland 桌面需要支持 `wtype` 使用的虚拟键盘协议。

## 安装与启动

从项目根目录运行。建议 Python 3.12；桌面 Python 与模型 Python 可以分开。

Arch Linux 系统依赖（按需要安装）：

```bash
# 录音、文本确认、剪贴板、打开文件
sudo pacman -S portaudio tk wl-clipboard xdg-utils
# 普通托盘与 Waybar 右键菜单共用的菜单依赖
sudo pacman -S gtk3 gtk-layer-shell libappindicator-gtk3 gobject-introspection
# 非 Hyprland 的 wlroots Wayland 桌面
sudo pacman -S wtype
# X11 桌面
sudo pacman -S xdotool xclip
```

Debian/Ubuntu 对应依赖为 `libportaudio2 python3-tk wl-clipboard xdg-utils`；普通托盘需要 `gir1.2-ayatanaappindicator3-0.1 gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 libgirepository-2.0-dev libcairo2-dev pkg-config python3-dev`。发行版较旧时请使用与其 GLib 匹配的 PyGObject 版本。

```bash
# 本机已有 uv；它可以下载 Python 3.12，避免依赖 Arch 当前的系统 Python 版本
uv venv --python 3.12 .venv
# 基础包
uv pip install --python .venv/bin/python -e '.[dev]'
# 普通托盘和 Waybar 右键菜单额外安装
uv pip install --python .venv/bin/python -e '.[linux]'
```

首次配置可复制 `config.example.toml`，使用云端时设置对应 API Key。已有 `config.toml` 请合并所需字段。始终在项目目录启动，提示词、`.env`、配置和历史使用该工作目录：

```bash
.venv/bin/asr-evo
```

## 两种图标模式

```toml
[linux]
tray = "standard" # 或 waybar；切换需重启
paste_shortcut = "ctrl+v"
```

- `standard`：AppIndicator 托盘，保留风格、录音设备、确认开关、历史、统计、重新加载配置和退出菜单，额外提供“开始 / 停止听写”。桌面需支持 StatusNotifierItem；Waybar 的 `tray` 可以显示它。GNOME 需要托盘扩展，而且自动粘贴还需单独解决其虚拟键盘限制。
- `waybar`：后台运行，不创建普通托盘图标。自定义模块轮询本机控制端口；左键开始/停止，右键打开菜单，中键停止；悬停显示状态或错误，进程退出显示 offline。右键通过 `asr-evo-control menu --port 8765` 打开鼠标附近的独立 GTK 弹出菜单，共用普通托盘的风格、设备、确认开关、历史、统计、配置与退出操作。菜单需要 `[linux]` 可选依赖、GTK 3，以及 Wayland 下的 `gtk-layer-shell`。Wayland 菜单直接使用合成器的鼠标事件与逻辑坐标，在当前指针所在屏幕显示，靠边时自动向屏幕内调整；不依赖 Tk / XWayland。中文文字使用 GTK/Pango 字体渲染，菜单采用明确的前景和背景颜色。点击箭头项打开子菜单，选择、Esc 或点击菜单外部关闭。

本机现有 `~/.config/waybar/config.jsonc` 中，左侧已有 `tray`，右侧已有 `custom/voice_input`；CSS 使用 `DroidSansM Nerd Font`、半透明背景、虚线圆角边框。示例沿用这些习惯，未自动修改本机文件：

1. 合并 [waybar.jsonc](../examples/linux/waybar.jsonc) 的 `custom/asr-evo` 定义。
2. 将 `modules-right` 中的 `custom/voice_input` 替换为 `custom/asr-evo`，或另行添加。
3. 合并 [waybar.css](../examples/linux/waybar.css)，然后按你现有方式重载 Waybar。
4. 已使用旧版示例时，将 `on-click-right` 的 `stop` 改为 `menu`，重启 ASR-EVO 并重载 Waybar。
5. 示例使用本机绝对项目路径与端口 8765；其他机器需替换路径，修改控制端口时同步修改所有调用。

图标由 Waybar 的 `format-icons` 决定，可自由改成其他 Nerd Font 字符或普通文字；颜色按 idle/recording/transcribing/polishing/reviewing/inserting/error/offline 类设置。

## 快捷键、窗口与剪贴板

Linux 不注册 `[hotkey]` 内置监听，由桌面快捷键运行以下命令。切换模式用 `toggle`，按住说话在按下/释放时分别调用 `start`/`stop`：

```bash
/absolute/path/ASR-EVO/.venv/bin/asr-evo-control toggle --port 8765
```

[hyprland.lua](../examples/linux/hyprland.lua) 按本机 `hl.bind(..., hl.dsp.exec_cmd(...))` 写法提供 Ctrl+Alt+Space 示例，也附传统 Hyprland 配置写法。

Hyprland 通过 `hyprctl activewindow -j` 识别应用，应用绑定的 key 是窗口 class（例如 `kitty`），并在开始听写时记住窗口地址。确认文本后切回该窗口，再发送粘贴快捷键。兼容旧式 dispatcher 和 Lua 模式的 `hl.dsp.focus` / `hl.dsp.send_shortcut`；仅在收到明确的 Lua 语法拒绝时切换接口，不会因普通失败重复发送粘贴。命令错误同时保留 stdout、stderr 和退出码。X11 使用 xdotool 做对应操作。其他 Wayland 桌面无法通用查询/恢复前台窗口，按应用自动风格不可用，用户应保持目标输入框聚焦。`wtype` 不适用于不支持虚拟键盘协议的桌面，例如默认 GNOME Wayland。

Linux 将结果复制到剪贴板并保留，便于手动重贴，不承诺恢复任意 MIME 类型的旧剪贴板。终端通常需要 `paste_shortcut = "ctrl+shift+v"`；图形文本框通常用 `ctrl+v`。未识别目标窗口或窗口已关闭时，检查错误提示和历史中的文本。

确认窗口需要 Tk；若没有 Tk，安装相应系统依赖或设置 `[review] enabled = false`。

Linux 确认窗口优先使用 `/usr/bin/python3` 的系统 Tk（若可导入 tkinter），主程序和模型仍使用虚拟环境。部分 uv/standalone Python 自带的 Tk 使用旧式 X11 字体后端，无法识别系统的 Noto CJK 等中文字体；系统 Tk 通常提供 Xft/fontconfig 支持。确认子进程只依赖标准库，无需向系统 Python 安装项目依赖。修改此启动逻辑后需重启 ASR-EVO 主进程。

## 本地 ASR：Qwen3-ASR-0.6B

安装可选依赖后，将下面配置合并到 `config.toml`。PyTorch/CUDA 版本需适合自己的显卡；无需安装 vLLM 或 FlashAttention。

```bash
uv pip install --python .venv/bin/python -e '.[local-asr]'
```

```toml
[asr]
backend = "qwen_local"
model = "Qwen/Qwen3-ASR-0.6B"
device = "auto"
dtype = "auto"
language = ""
python_executable = ""
timeout_seconds = 600
```

- `model` 支持 Hugging Face 模型 ID 或本地模型目录。首次使用模型 ID 时下载权重；之后使用磁盘缓存。离线使用可预先下载并填写目录，或设置 `HF_HUB_OFFLINE=1`。
- `device = "auto"`：CUDA 可用则 `cuda:0`，否则 CPU；可显式设为 `cpu` / `cuda:0`。本实现没有自动选择 MPS。
- `dtype = "auto"`：CUDA 使用 bfloat16，CPU 使用 float32；不支持 bfloat16 的显卡请用 float16。
- `language = ""` 自动检测；强制中文使用 `Chinese`。
- `python_executable` 可指定独立环境的 Python，该环境只需安装 `qwen-asr` 及适合硬件的 PyTorch；无需再安装 ASR-EVO。适合让桌面环境和模型依赖独立。

应用启动时不导入 torch、不下载模型、不占用模型显存。每次转写才创建一个独立进程，加载模型并处理音频；成功、报错、超时或取消后均回收进程，退出时释放该进程的内存/显存，包括 CUDA 上下文。权重缓存文件保留在磁盘。代价是每次转写都有冷启动延迟；默认不跨请求常驻，不使用后台 ASR HTTP 服务。

## 本地 LLM：Ollama

先安装并启动 Ollama，再自行准备模型，例如：

```bash
ollama serve # 已由系统服务运行时无需重复启动
ollama pull qwen3:4b
```

```toml
[llm]
default_profile = "balanced"

[llm.profiles.balanced]
backend = "ollama"
base_url = "http://127.0.0.1:11434"
model = "qwen3:4b"
enable_thinking = false
keep_alive_seconds = 0
timeout_seconds = 300
```

使用 Ollama 原生 `/api/chat`，所以 `base_url` 不应附加 `/v1`。本地 profile 不需要 API Key；ASR 和每个 LLM profile 可分别选择本地/云端。内置提示词使用 `deep`（未指定时用默认 `balanced`） 别名，全部本地运行请使用 [config.local.toml](../examples/linux/config.local.toml) 中的完整 profile 配置，或修改模板引用。

模型在请求时由 Ollama 加载；`keep_alive_seconds = 0` 要求生成结束即卸载，设为 60 则空闲约一分钟后卸载。应用关闭或替换已使用的 provider 时也发送卸载请求；未使用的 profile 不会触发模型加载。Ollama 服务本身继续运行，模型磁盘文件不会删除。如果其他应用同时使用同一个 Ollama 模型，它们也会影响模型驻留，不能将该服务视为 ASR-EVO 独占资源。

测试已有音频的完整 ASR/LLM 流程：

```bash
.venv/bin/asr-evo-transcribe /path/to/audio.wav --config examples/linux/config.local.toml
```

全部使用本地后端时，推理音频与文本不会由 ASR-EVO 发送给云端 API；首次模型下载仍需联网，历史录音仍按项目原有策略保存在本地。

## 可选自启动

[asr-evo.service](../examples/linux/asr-evo.service) 是用户服务示例，安装前修改 `WorkingDirectory` 与 `ExecStart` 路径。图形会话应向 systemd user manager 导入 `WAYLAND_DISPLAY DISPLAY HYPRLAND_INSTANCE_SIGNATURE` 等环境；在 Hyprland 会话内可执行：

```bash
systemctl --user import-environment WAYLAND_DISPLAY DISPLAY HYPRLAND_INSTANCE_SIGNATURE
```

再将服务文件安装到 `~/.config/systemd/user/`，执行 `systemctl --user daemon-reload` 与 `systemctl --user enable --now asr-evo.service`。也可以直接在合成器的启动命令中以项目目录为工作目录启动，无需 systemd。

协议参考：[Qwen3-ASR 官方实现](https://github.com/QwenLM/Qwen3-ASR)、[Ollama Chat API](https://docs.ollama.com/api/chat)、[Waybar custom 模块](https://github.com/Alexays/Waybar/wiki/Module:-Custom)、[pystray 后端](https://pystray.readthedocs.io/en/latest/usage.html#selecting-a-backend)。
