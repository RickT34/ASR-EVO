-- 对应本机 Hyprland Lua 配置。合并到 conf.d/keybinds.lua；不要整份覆盖。
local asr_control = "/home/rickt/Data/Works/ASR-EVO/.venv/bin/asr-evo-control"
hl.bind("CTRL + ALT + SPACE", hl.dsp.exec_cmd(asr_control .. " toggle --port 8765"))
-- 传统 hyprland.conf 对应写法：
-- bind = CTRL ALT, SPACE, exec, /absolute/path/.venv/bin/asr-evo-control toggle --port 8765
-- 按住说话（替换上述 toggle 绑定）：
-- bind = CTRL ALT, SPACE, exec, /absolute/path/.venv/bin/asr-evo-control start --port 8765
-- bindr = CTRL ALT, SPACE, exec, /absolute/path/.venv/bin/asr-evo-control stop --port 8765
