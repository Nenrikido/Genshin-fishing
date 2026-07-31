![](logo.png)

**原神钓鱼自动人偶**  
**Genshin Impact Fishing Automata**

## Video 视频
- Bilibili (Zh): https://www.bilibili.com/video/BV1pq4y1f7V2/
- Youtube (En): https://www.youtube.com/watch?v=3lvCEh7quxE

## Communities 社群
- 开黑啦(中国大陆): https://kaihei.co/IWXRLp
- Discord(Global): https://discord.gg/5PCebykNaC

## Related Repo 相关项目
- DoMiSo-Genshin(原神自动弹琴人偶): https://github.com/Nigh/DoMiSo-genshin
- LyreMaster-Genshin(原神手搓弹琴大师): https://github.com/Nigh/LyreMaster-Genshin

## Download(下载)

- [GitHub Download - GitHub下载](https://github.com/Nigh/Genshin-fishing/releases/latest/download/GenshinFishing.zip)
- [Mirror Download - 镜像下载](https://mirror.ghproxy.com/https://github.com/Nigh/Genshin-fishing/releases/latest/download/GenshinFishing.zip)

## Usage 用法用量
解压到文件夹，直接运行exe即可。  
Unzip it into a folder and run the exe directly.

软件更新需要先关闭软件。如果没有自动关闭，右键任务栏小图标即可关闭。  
Software update needs to close the software first. If it does not close automatically, right-click the small icon in the taskbar to close.

以下图像设置已经测试可以正常工作：  
The following image settings have been tested to work properly:

| 分辨率 Resolution | 支持 Support |
| ----------------- | ------------ |
| 3840 x 2160       | ✔            |
| 3440 x 1440       | ✔            |
| 1920 x 1200       | ✔            |
| 1920 x 1080       | ✔            |
| 2560 x 1600       | ✔            |
| 2560 x 1440       | ✔            |
| 2560 x 1080       | ✔            |
| 1600 x 900        | ✔            |
| 1440 x 900        | ✔            |
| 1280 x 720        | ✔            |

如果需要更多的分辨率支持，请提交issue。  
If you need more resolutions support, please submit an issue.

因个人精力有限，非常规尺寸的分辨率将不予支持。  
Due to limited spare time, resolutions of unconventional sizes will not be supported. 

### Setting.ini

Tooltip messages are turned off by default, specify `debug=1` in `setting.ini` to turn on

提示信息默认关闭，在`setting.ini`中指定`debug=1`开启

specify `log=1` or `log=2` in `setting.ini` to start logs with different levels of detail and save them in the genshinfishing.log file

在`setting.ini`中指定`log=1`或`log=2`启动不同详细程度的log，保存在genshinfishing.log文件中

You can turn off automatic updates by specifying `autoupdate=0` in `setting.ini`

在`setting.ini`中可以指定`autoupdate=0`来关闭自动更新

Auto bait selection (1920x1080 only, enabled by default):

- Set `enabled=0` in section `[bait]` to turn it off.
- Set `target=<fish_name>` in section `[bait]` to choose your fish target (default `medaka`).
- Fish target matching normalizes spaces/hyphens/case (for example `Tea-Colored Shirakodai` == `tea colored shirakodai`).
- You can also set `target` directly to a bait name (for example `target=fakefly`).
- Optional fish->bait override in section `[bait_target]` (key=`fish_name`, value=`bait_name`).
- Optional tuning in section `[bait]`: `button_x`, `button_y`, `menu_open_delay_ms`, `click_delay_ms`, `detect_variation`, `retry_ms`.

How it works: when the rod is ready, the script first confirms it is really
in fishing mode by locating the rod (cast/LMB) and bait (RMB) HUD buttons at
the bottom right, then opens the "Select Bait" dialog with a right click (the
in-game command), verifies the dialog is open by locating the Confirm button,
image-searches the bait grid for the target bait (the dialog only shows baits
usable in the current water body), clicks it and confirms. If the bait is not
found it clicks Cancel and keeps fishing with the current bait.

Pond scan (`target=auto`, source checkout with Python + OpenCV + Pillow
required): instead of a fixed target, `tools/fish_scan.py` grabs a few frames
of the screen, finds moving color blobs in the water and classifies them into
coarse color families (gold = maintenance meks, pale = medaka, red = betta
family, blue = heartfeather bass family, purple = angelfish family, orange =
koi family). The ranked bait suggestions are then tried in the bait menu in
order. This is a heuristic — true species recognition would need a trained
model (see IrisRainbowNeko/genshin_auto_fish for the YOLOX approach).

Auto cast (experimental, off by default): with `enabled=1` in `[autocast]`,
after the bait is ensured the script holds LMB and casts at a scanned fish.
With Python available, aiming is closed loop: `tools/aim_cast.py` detects the
white elliptical landing reticle on the water (detector validated against
frames of the project's demo video) and steers it to land `fish_offset` px
short of the fish, measuring the mouse-to-reticle gain automatically — no
calibration needed. Without Python (compiled build), an open-loop fallback
uses `aim_origin_x/y` and `aim_gain_x/y`, which need per-setup calibration;
watch `genshinfishing.log` with `log=1` while tuning.

Templates live in `assets/19201080/` (`bait_<baitname>.png` plus `_b`/`_c`
scale variants and a `_sel` variant for the already-selected zoomed card,
`menu_confirm.png`/`menu_cancel.png` for the dialog buttons, and
`btn_rod.png`/`btn_bait.png` for the fishing-mode HUD buttons). They are
generated from `assets/references/bait/` by
`tools/generate_local_bait_templates.py`, which also validates them against
`screenshots/bait_menu_opened.png` and `screenshots/fishing_ui.png`.

Calibration hotkeys (only needed if the defaults miss, in game while the
Genshin window is active):

- `Ctrl+Alt+F7`: save bait button position (`button_x`, `button_y`) — only used as right-click fallback when the HUD button templates are missing.
- `Ctrl+Alt+F8`: save Confirm button position (`confirm_x`, `confirm_y`) — used as fallback when the button template is not found.
- `Ctrl+Alt+F9`: save Cancel button position (`cancel_x`, `cancel_y`).

Example:

```ini
[bait]
enabled=1
target=auto            ; a fish name, a bait name, or auto (pond scan)
menu_open_delay_ms=500
click_delay_ms=150
detect_variation=48
retry_ms=8000

[bait_target]
medaka=fruitpaste
stickleback=redrot
koi=fakefly
ray=sourbait

[autocast]
enabled=0              ; experimental, needs calibration
aim_origin_x=960
aim_origin_y=620
aim_gain_x=1.0
aim_gain_y=1.0
fish_offset=110
max_move=500
settle_ms=700
cooldown_ms=6000
```

Fish/bait defaults are based on in-game fish listings and cross-checked against public guide sources such as GameWith.

Developer note: running source directly works without a generated
`fileinstalls.ahk`; the script copies `assets/` to the temp directory itself.
`dist.ahk` regenerates `fileinstalls.ahk` with `FileInstall` directives for
release builds.

### 性能 Performance

- CPU: AMD R5 3600
- GPU: GTX1060
- Res: `1920`x`1080`

在以上配置下，目前单帧画面的检测用时为 `25ms`  
Under the above hardware configuration, the current detection time for a single frame is `25ms`.

### Donate(捐助)

| Platform |                          Donate                          |
| :------: | :------------------------------------------------------- |
|  Ko-fi   | https://ko-fi.com/xianii                                 |
|  Paypal  | https://paypal.me/xianii                                 |
|  爱发电  | https://afdian.net/a/xianii                              |
|   微信   | <img src="assets/wechat.jpg" alt="wechat" height="256"/> |
|  支付宝  | <img src="assets/alipay.jpg" alt="alipay" height="256"/> |

## Stargazers over time

[![Stargazers over time](https://starchart.cc/Nigh/Genshin-fishing.svg)](https://starchart.cc/Nigh/Genshin-fishing)



## For developers

Since this script is designed to run after being compiled into a binary. So you can not simply run the `GenshinFishing.ahk`. 

You should run `dist.ahk` at fisrt, which will automatically generate a fileinstalls file and compile it into binary. Running the compiled binary is necessary to correctly release the assets files into the temporary directory.
