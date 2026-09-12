# DeepSeek Harness 一键启动（桌面快捷方式）

双击桌面上的 **DeepSeek Harness** 图标就能启动 dsh web 并自动打开浏览器，
不用再去终端敲 `dsh web`。图标用的是 **DeepSeek 官方鲸鱼标志**（白底 + 品牌蓝 `#4D6BFE` 鲸鱼）。

```
双击快捷方式
      |
      v
DeepSeekHarness.exe（PyInstaller 打包的 dsh_launcher.py）
      |
      +-- 3080 已有 DSH 在跑？ --> 直接开浏览器，不重复启动
      +-- 3080 被别的程序占用？ --> 明确报错，提示换端口
      +-- 端口空闲
             |
             +-- 决定工作区：last（默认，接着上次的工作区）
             |               ask / home / cwd / 固定目录
             |
             +-- 在该工作区目录启动 dsh web
                 （启动时所在目录 = 本次会话的 workspace 根目录）
             |
             +-- 等就绪后自动开浏览器，窗口里滚动日志
                 关窗口 / Ctrl+C 即停止服务
```

## 一、安装后你会得到什么

运行 `python build_and_install.py` 之后：

| 位置 | 内容 |
|---|---|
| `dist\DeepSeekHarness.exe` | 启动器（独立 exe，约 9.5 MB，不用装 Python） |
| 桌面 `DeepSeek Harness.lnk` | 桌面快捷方式（图标 = 官方鲸鱼） |
| 开始菜单 `DeepSeek Harness.lnk` | 按 Win 键搜 "DeepSeek" 也能找到 |
| `%USERPROFILE%\.dsh\launcher.log` | 每次启动的日志，出问题先看这里 |

> 快捷方式指向 `dist\DeepSeekHarness.exe`，**移动 exe 后快捷方式会失效**，
> 重跑一次 `python build_and_install.py` 即可重建。

### 从零开始（clone 本仓库后）

前置条件：Python 3.9+（打包需要，PyInstaller 会自动装）、已装 Node.js 和
`npm i -g @deepseek-ai/dsh`；图标生成还需要 Pillow（`pip install pillow`，可选）。

```bash
git clone https://github.com/HaiYu-22/dsh-launcher.git
cd dsh-launcher
python build_and_install.py        # 打包 exe + 建桌面/开始菜单快捷方式
```

只想直接用、不想装 Python：到本仓库的 **Releases** 页面下载 `DeepSeekHarness.exe`。

## 二、工作区（workspace）怎么定 —— 不用固定在一个地方

DSH 的规则是：**启动时所在目录 = 这次会话的工作目录**。所以启动器只要选好"在哪个目录启动"，
就等于选好了工作区。`--workspace` 支持：

| 模式 | 含义 |
|---|---|
| `last` | **默认**。接着 DSH 上次用的工作区打开（读 `<DSH_HOME>\storages\workspace.json`，取最近更新的那条） |
| `ask` | 每次启动弹系统原生文件夹选择框，框一打开就停在上次的工作区 |
| `home` | 用户主目录（`%USERPROFILE%`），中立起点，不绑定任何项目 |
| `cwd` | 快捷方式"起始位置"那个目录（适合一个文件夹放一个图标） |
| `<路径>` | 固定目录，例如 `--workspace "D:\我的项目"` |

例：

```powershell
DeepSeekHarness.exe                          # 接着上次的工作区（默认）
DeepSeekHarness.exe --workspace ask           # 每次自己选
DeepSeekHarness.exe --workspace home          # 主目录，当通用助手用
DeepSeekHarness.exe --workspace "D:\proj\a"   # 固定到某个项目
DeepSeekHarness.exe --list-workspaces         # 看 DSH 记录过哪些工作区
```

**关于"能不能不处在任何工作区"**（实测结论，不是猜的）：

- **完全没有工作目录的会话不存在。** DSH 的沙箱/文件策略在启动时就解析出
  `workspaceRoot`（`dsh-sandbox-policy` 里是 `config.workspaceRoot ?? process.cwd()`），
  每个会话都带一个 cwd，没有"空工作区"这个状态。
- 但**"不属于任何已注册工作区"是存在的**：这种会话在侧栏显示为 **Ungrouped**。
  想要这个效果就用 `--workspace home`（或任意非项目目录）启动。
- 另外 DSH 界面里本身就能切换/新增工作区（侧栏 + 原生目录选择器），
  换过的目录都会被记进 `workspace.json` —— 这正是 `last` 模式"接着上次打开"的依据。

## 三、文件说明

| 文件 | 作用 |
|---|---|
| `dsh_launcher.py` | 启动器本体，跨平台，也可直接 `python dsh_launcher.py` 运行 |
| `build_and_install.py` | 打包 exe + 创建快捷方式（默认复用现成图标，不重画） |
| `make_logo_icon.py` | 用 DeepSeek 官方标志生成图标（`--ascii` 可在终端字符画预览） |
| `assets\deepseek-logo.svg` | 官方鲸鱼 SVG（取自 DSH 前端自带的 `favicon.svg`），填充色 = 品牌蓝 `#4D6BFE` |
| `dsh-harness.ico` / `.png` | **当前图标 = 蓝鲸鱼 + 白底**（exe 内嵌图标与快捷方式都用这个名字） |
| `dsh-harness-blue-on-white.ico` / `.png` | 同一配色的命名副本，方便单独取用 |
| `.icon-style` | 记录当前是哪套配色；换配色后重新打包会据此重画，避免 exe 与快捷方式图标对不上 |
| `dist\DeepSeekHarness.exe` | 打包产物 |
| `dsh_launcher.json`（可选） | 放 exe 同目录即可改默认行为，不用重新打包 |

## 四、常用参数

| 参数 | 说明 |
|---|---|
| `--workspace <last\|ask\|home\|cwd\|目录>` | 工作区模式，默认 `last` |
| `--fallback-workspace <目录>` | `last` 解析不出来时用哪个目录（默认主目录） |
| `--port <端口>` | 监听端口，默认 `3080` |
| `--host <地址>` | 监听地址，默认 `127.0.0.1`（仅本机可访问） |
| `--no-browser` | 不自动打开浏览器 |
| `--new` | 即使已有实例在跑也强制新开（端口冲突会报错） |
| `--timeout <秒>` | 等服务就绪的超时，默认 180 秒 |
| `--list-workspaces` | 列出 DSH 记录过的工作区 |
| `--selftest` | 只体检环境（node/dsh/端口/工作区），不启动 |
| `--print-config` | 打印最终生效的配置 |
| `--no-pause` | 出错后不等待回车 |
| `--quiet` | 少打印点 |

**环境变量**：`DSH_LAUNCH_WORKSPACE`、`DSH_LAUNCH_PORT`、`DSH_LAUNCH_HOST`、
`DSH_LAUNCH_OPEN_BROWSER=0`、`DSH_LAUNCH_REUSE=0`、`DSH_LAUNCH_LOG`、`DSH_LAUNCH_TIMEOUT`。

**配置优先级**：默认值 < `dsh_launcher.json` < 环境变量 < 命令行参数。

`dsh_launcher.json`（放在 exe 旁边）示例：

```json
{
  "workspace": "last",
  "fallback_workspace": "D:\\我的项目",
  "port": 3080
}
```

## 五、重新打包 / 重建快捷方式

```powershell
cd <本仓库目录>

python build_and_install.py                 # 打包 + 桌面&开始菜单快捷方式
python build_and_install.py --skip-build    # 只用现有 exe 重建快捷方式
python build_and_install.py --desktop       # 只建桌面快捷方式
python build_and_install.py --startmenu     # 只建开始菜单快捷方式
python build_and_install.py --windowed      # 打包成不带黑窗口的版本
python build_and_install.py --regen-icon    # 重画图标（配色没变时默认复用现成的）
python build_and_install.py --icon-style white-on-blue   # 换成"白鲸鱼+品牌蓝底"配色
python make_logo_icon.py --ascii            # 终端里字符画预览图标
```

**打包时 DSH 正开着也没关系**：Windows 不允许覆盖正在运行的 exe，脚本会自动把旧 exe
改名成 `DeepSeekHarness-old.exe` 让位（正在运行的窗口完全不受影响），下次启动才换新版本；
那个 `-old.exe` 会在下一次打包时自动清理。

## 六、macOS 上怎么用

exe 是 Windows 专用的，macOS 用同一个 `dsh_launcher.py`：

```bash
python3 build_and_install.py
```

生成 `~/Desktop/DeepSeek Harness.command`（双击运行，可拖到 Dock）和
`~/Applications/DeepSeek Harness.app`（标准应用包）。

> 这部分代码写好了但这台机器是 Windows，**没有实机验证过**。macOS 上图标渲染会优先用
> 本机 Chrome/Edge 无头模式；都没有时退回内置的纯 Python 光栅化器（离线可用）。

## 七、常见问题

**双击后黑窗口一闪就没了？**
看 `%USERPROFILE%\.dsh\launcher.log` 最后几行，或跑 `DeepSeekHarness.exe --selftest`。

**报 `[PYI-xxxx:ERROR] Security validation failure: parent process has different executable!`**
这是 PyInstaller 打包程序的自我保护：如果进程继承到了 PyInstaller 的引导变量
（`_PYI_PARENT_PROCESS_LEVEL` 等），它会误判"父进程不是同一个 exe"而拒绝启动。

- 启动器现在会在拉起 dsh 之前**主动清掉这些变量**，所以正常双击、从桌面/开始菜单启动不会有问题。
- 如果确实遇到了，多半是当前 DSH 会话仍由**旧版本启动器**拉起、环境里残留了这些变量。
  **关掉 DSH 窗口，用桌面快捷方式重新打开一次**即可清除。

**提示 "端口 3080 已被其它程序占用"**
给快捷方式加参数 `--port 3081`（右键快捷方式 → 属性 → 目标后面加）。

**找不到 dsh / node**
确认 `npm i -g @deepseek-ai/dsh` 装过、`node -v` 可用。启动器会自动在
`%APPDATA%\npm\node_modules`、node 安装目录、`npm root -g` 等处找入口，
也可用环境变量 `DSH_ENTRY` 指定 `...\@deepseek-ai\dsh\lib\bin.js`、`DSH_NODE` 指定 node.exe。

**想开机自动启动**
`Win+R` 输入 `shell:startup`，把桌面那个快捷方式复制进去。

**会不会重复开一堆服务？**
不会。默认检测到 3080 上已有 DSH 就只开浏览器、自己直接退出。

**`DSH_HOME` 没设置会不会跑错目录？**
不会。未设置时会自动指向已存在的 `%USERPROFILE%\.dsh`，与在终端里启动的行为一致。

## 八、声明

- 本项目是**社区非官方工具**，与 DeepSeek 无隶属或合作关系。
- 仓库内 `assets/deepseek-logo.svg` 及由其渲染的 `dsh-harness.ico` / `.png` 使用
  DeepSeek 官方鲸鱼标志与品牌色 `#4D6BFE`，仅用于标识所启动的软件。
  **DeepSeek 名称与标志归 DeepSeek 所有，不在本项目的 MIT 许可证授权范围内**，
  详见 [LICENSE](LICENSE) 中的第三方内容与商标声明。
- 本工具启动的 DeepSeek Harness（`@deepseek-ai/dsh`）遵循其自身许可证。
