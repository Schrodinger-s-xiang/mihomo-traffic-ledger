# Mihomo 流量账本

中文 | [English](#english)

在本机持续记录经过 Mihomo 的连接流量，按网站、域名、程序和出口方式汇总，支持历史查询和分钟范围筛选。

采用 Python 标准库、SQLite 与原生 HTML/CSS/JavaScript，无需安装第三方 Python 依赖。提供 Windows 启动和登录自启脚本；Python 服务也可在其他支持的平台手动运行。

## 功能

- 按网站/服务、域名/IP、程序、直连/代理出口查看上传和下载流量。
- 今天、昨天、近七天、近三十天、本月查询，以及自定义到分钟的起止时间。
- 近十五分钟、近一小时、近六小时快捷筛选；自定义结束时间可跟随当前。
- 按流量或最近活动时间排序，默认显示前五项，可展开全部。
- 同一网站的不同出口分别显示标签，悬停查看对应流量。
- CSV 导出、深浅色主题、本地 SQLite 历史记录。
- Windows 登录后静默自启，不打开浏览器。

## 环境要求

- Python 3.10 或更高版本。
- 正在运行的 Mihomo 内核，例如 Clash Verge Rev 使用的 Mihomo。
- 本机 HTTP 外部控制接口，如 `http://127.0.0.1:9090`，以及对应的 Secret。

统计器不会修改 Clash 的规则、代理模式或节点配置。它不包含代理服务。

## 快速开始

1. 下载并解压本仓库源码，放入固定目录。
2. 安装 Python。Windows 安装时勾选 **Add Python to PATH**。
3. 在 Clash 的设置或运行配置中查看 `external-controller` 和 `secret`。代理混合端口不是控制端口。
4. Windows 双击 `start.bat`；其他平台运行 `python3 app.py`。
5. 浏览器打开 `http://127.0.0.1:8765`，展开“连接设置与状态”，填写控制地址和 Secret，保存。
6. 右上角显示“正在记录”后，通过 Clash 访问网站，等待几秒查看累计流量。

控制接口配置示例：

```yaml
external-controller: 127.0.0.1:9090
secret: "replace-with-your-own-secret"
```

如当前没有启用 HTTP 外部控制接口，请通过 Clash 客户端支持的持久设置或覆写配置启用。无需为了统计强制开启 TUN，只要连接经过 Mihomo 即可。

## 启动与停止

| 文件或命令 | 用途 |
| --- | --- |
| `start.bat` | 前台启动，自动打开网页 |
| `start-background.vbs` | Windows 隐藏启动窗口，仍会打开网页 |
| `stop.bat` | 按本目录 app.py 的完整路径匹配并停止 Python 进程 |
| `restart.bat` | 停止本目录的进程并重新启动 |
| `enable-autostart.bat` | 设置当前 Windows 用户登录自启，并尝试启动后台 |
| `disable-autostart.bat` | 取消登录自启，不停止当前进程 |
| `python app.py --no-browser` | 不自动打开网页 |
| `python app.py --port 8766` | 使用其他网页端口 |

登录自启使用检测到的 `pythonw.exe`，不显示终端，不打开网页，也不需要管理员权限。设置成功后保持程序目录和 Python 安装位置不变；移动后请重新设置。Clash 也需要运行，统计器会在无法连接时重试。

关闭网页不会停止记录，停止后台会停止记录。开机尚未登录、休眠或关机期间不会持续采集。Windows 脚本尚未在项目维护环境中进行实机测试，使用后请在网页检查连接状态。

## 时间范围与统计口径

### 每日汇总与分钟明细

“今天”“昨天”“近七天”等预设查询每日汇总，保留旧版历史。自定义日期和时间、近几分钟/小时查询分钟明细；结束分钟包含整分钟。例如 10:01 至 10:01 表示该分钟内采集的增量。

分钟明细从支持该功能的版本启动后开始保存。旧版每日总量无法反推出分钟分布，不会被填进分钟查询；界面会提示分钟采集开始时间。两类数据分别查询，不相加，避免重复累计。

“最近活动”是所选范围内最后一次采集到新增流量的时间，不是连接建立时间或逐条浏览历史。旧数据没有具体时间时显示“未记录”。按时间排序时，无时间记录放在末尾。

### 精度限制

- 从 `/connections` WebSocket 快照读取连接 ID、累计字节和元数据，计算相邻快照的增量。
- 首次连接和断线重连的首个快照只建立基线，不补记离线期间流量。
- 快照间已结束的短连接和连接消失前的尾部流量可能漏记。
- 时间按采集时的本机日期和分钟归属，跨分钟边界的增量可能分配到下一分钟。
- 字节数是内核连接载荷，与代理服务商的计费开销、倍率和其他设备用量可能不同。
- 只能看到经过 Mihomo 的连接，无法统计绕过内核的流量。

## 网站、程序与出口识别

服务分类使用域名和进程名启发式归类，可编辑 `app.py` 中的 `SERVICES`。一个服务可能包含多个关联域名。

Codex 优先按进程名识别，缺少进程信息时，共享 OpenAI 域名不强制归入 Codex。iOS 代理客户端的日志并不直接兼容本项目。

出口依据 Mihomo 的 `chains` 最终出站名称分类。DIRECT/COMPATIBLE 归直连，REJECT/REJECT-DROP 归拦截，缺失链路归未知，其他归代理。自定义特殊出站可能需要调整分类。

## 数据与隐私

所有运行数据放在程序目录下的 `data/`：

- `config.json`：控制地址和 Secret。
- `traffic.sqlite3`：流量汇总、分钟明细和采集元数据。
- `background.log`：无窗口启动时的本地输出与错误。

本服务只监听 `127.0.0.1`，不提供公共网站托管或远程多用户功能。页面不返回保存的 Secret，配置写入需要运行时生成的本机令牌。

**不要公开 data 文件夹、控制密钥、订阅链接或包含个人浏览记录的截图。** `.gitignore` 已排除运行数据、日志、数据库和环境文件。备份时先停止程序，再备份整个 data 目录；数据库运行时可能同时存在 WAL 文件。

## 升级

停止后台，覆盖源码文件，保留原 data 文件夹，然后重新启动、刷新网页。数据库会自动补充需要的字段和分钟表，不清空原有汇总。

当前后端版本为 1.4.0，界面版本为 1.4.1。两者单独标识。网页更新后如仍运行旧后台，部分新字段和查询模式不会生效。

## 常见问题

- **无法连接**：检查内核运行状态、HTTP 控制地址和 Secret；不要填写代理混合端口。
- **没有流量**：首个快照只作基线；确认出口筛选与时间范围正确，并产生经过 Mihomo 的新流量。
- **时间未记录**：旧历史缺少时间；若显示“后台未提供”，更新 app.py 并重启后台。
- **同时显示代理和直连**：同一汇总对象在所选时段存在不同出口的连接，不表示同一连接同时走两路。
- **端口已占用**：可能已有实例；打开现有网页或改用其他网页端口，避免重复启动。
- **取消自启后还在记录**：取消只影响下次登录；停止当前实例请运行 stop.bat。

## 测试

```bash
python -m unittest -v test_app.py
```

测试使用临时数据库和本地模拟控制接口，无需真实 Clash。覆盖增量去重、断线基线、历史迁移、时间排序、分钟边界、时区、出口筛选、WebSocket 握手及 HTTP 接口。

## 许可证与相关项目

本项目采用 [MIT License](LICENSE)。本仓库包含统计器源码，不包含或分发 Mihomo 内核。

- [Mihomo](https://github.com/MetaCubeX/mihomo)
- [Mihomo 配置文档](https://wiki.metacubex.one/)

---

# English

## Mihomo Traffic Ledger

Continuously record connection traffic passing through Mihomo on your computer. Aggregate usage by website, domain, process, and outbound route, with historical queries and minute-level time filters.

Built with the Python standard library, SQLite, and plain HTML/CSS/JavaScript. No third-party Python packages are required. Windows launch and sign-in startup scripts are included; the Python service can also be started manually on other supported platforms.

## Features

- View upload and download usage by website/service, domain/IP, process, and direct/proxy outbound route.
- Query today, yesterday, the last seven or thirty days, the current month, or a custom start and end time specified to the minute.
- Quickly select the last fifteen minutes, one hour, or six hours; custom end times can follow the current time.
- Sort by traffic volume or latest activity. Show the first five entries by default and expand to view all entries.
- Display separate outbound labels when a website uses multiple routes. Hover over each label to see its traffic usage.
- Export CSV files, switch between light and dark themes, and retain local SQLite history.
- Start silently after Windows sign-in without opening a browser.

## Requirements

- Python 3.10 or newer.
- A running Mihomo core, such as the core used by Clash Verge Rev.
- A local HTTP external controller, for example `http://127.0.0.1:9090`, and its corresponding Secret.

The recorder does not modify Clash rules, routing modes, or node configurations. It does not include a proxy service.

## Quick Start

1. Download and extract this repository's source code to a permanent directory.
2. Install Python. On Windows, enable **Add Python to PATH** during installation.
3. Find `external-controller` and `secret` in your Clash settings or active configuration. The mixed proxy port is not the controller port.
4. On Windows, double-click `start.bat`. On other platforms, run `python3 app.py`.
5. Open `http://127.0.0.1:8765` in your browser. Expand “连接设置与状态” (Connection settings and status), enter the controller address and Secret, and save.
6. Once the upper-right indicator says “正在记录” (Recording), visit websites through Clash and wait a few seconds to see accumulated usage.

Example controller configuration:

```yaml
external-controller: 127.0.0.1:9090
secret: "replace-with-your-own-secret"
```

If the HTTP external controller is not enabled, enable it through your Clash client's persistent settings or configuration overrides. TUN is not required solely for recording; the connections simply need to pass through Mihomo.

## Starting and Stopping

| File or command | Purpose |
| --- | --- |
| `start.bat` | Start in the foreground and open the dashboard |
| `start-background.vbs` | Hide the Windows console window, while still opening the dashboard |
| `stop.bat` | Stop Python processes whose command line matches the full path of app.py in this directory |
| `restart.bat` | Stop this directory's processes and restart the recorder |
| `enable-autostart.bat` | Enable startup for the current Windows user at sign-in and attempt to start the background recorder |
| `disable-autostart.bat` | Disable sign-in startup without stopping an already-running process |
| `python app.py --no-browser` | Start without opening the dashboard automatically |
| `python app.py --port 8766` | Use a different dashboard port |

Automatic startup uses the detected `pythonw.exe`. It does not show a console, open a browser, or require administrator rights. Keep the program directory and Python installation in the same locations after setup; rerun setup if they move. Clash must also be running. The recorder retries when it cannot connect.

Closing the dashboard does not stop recording; stopping the background service does. Recording does not continue before Windows sign-in, during sleep, or while the computer is shut down. The Windows scripts have not been tested on a real Windows machine in the project's maintenance environment, so check the dashboard connection status after using them.

## Time Ranges and Measurement

### Daily Summaries and Minute Details

Presets such as Today, Yesterday, and Last Seven Days query daily summaries, preserving history from older versions. Custom date/time ranges and recent-minute/hour presets query minute details. The entire ending minute is included: for example, 10:01 to 10:01 selects the increments collected during that minute.

Minute details are saved only after a version supporting them has started. Daily totals from older versions cannot be reconstructed into minute-by-minute usage and are not included in minute queries. The dashboard shows when minute recording began. The two datasets are queried separately, rather than added together, to avoid double counting.

“最近活动” (Latest activity) is the last time new traffic was collected within the selected range. It is not the connection creation time or a per-visit browsing history. Older records without timestamps show “未记录” (Not recorded). Records without timestamps appear last when sorting by time.

### Accuracy Limitations

- Read connection IDs, cumulative byte counters, and metadata from `/connections` WebSocket snapshots, then calculate differences between snapshots.
- The first snapshot on initial connection or reconnection only establishes a baseline. Traffic from offline periods is not backfilled.
- Short connections that end between snapshots and the final bytes before a connection disappears may be missed.
- Traffic is assigned to the computer's local date and minute at collection time. Increments spanning a minute boundary may be assigned to the next minute.
- Byte counts represent connection payload measured by the core. Provider billing overhead, multipliers, and traffic from other devices may differ.
- Only connections passing through Mihomo are visible. Traffic bypassing the core cannot be counted.

## Website, Process, and Outbound Identification

Services are grouped heuristically using domain and process names. Edit `SERVICES` in `app.py` to customize them. One service may include multiple related domains.

Codex is identified by process name when available. Without process information, shared OpenAI domains are not automatically attributed to Codex. Logs from iOS proxy clients are not directly compatible with this project.

Outbound classification uses the final outbound name in Mihomo's `chains`: DIRECT/COMPATIBLE is classified as direct, REJECT/REJECT-DROP as blocked, a missing chain as unknown, and other names as proxy. Custom special outbounds may require classification adjustments.

## Data and Privacy

Runtime data is stored in `data/` under the program directory:

- `config.json`: Controller address and Secret.
- `traffic.sqlite3`: Traffic summaries, minute details, and recording metadata.
- `background.log`: Local output and errors when started without a console.

The service listens only on `127.0.0.1`. It does not provide public website hosting or remote multi-user access. The dashboard does not return the saved Secret, and configuration writes require a runtime-generated local token.

**Do not publish the data directory, controller secrets, subscription URLs, or screenshots containing personal browsing history.** `.gitignore` excludes runtime data, logs, databases, and environment files. Stop the recorder before backing up the entire data directory; an active database may also have WAL files.

## Upgrading

Stop the background process, replace the source files, retain the existing data directory, and restart the recorder and refresh the dashboard. The database automatically adds required fields and minute tables without clearing existing summaries.

The current backend version is 1.4.0 and the dashboard version is 1.4.1. They are labeled separately. If the dashboard is updated while an older backend remains running, some new fields and query modes will not work.

## Troubleshooting

- **Cannot connect:** Check that the core is running and verify the HTTP controller address and Secret. Do not use the mixed proxy port.
- **No traffic:** The first snapshot only establishes a baseline. Check the outbound filter and time range, then generate new traffic through Mihomo.
- **Activity time is not recorded:** Older history has no timestamps. If the dashboard says “后台未提供” (Not provided by backend), update app.py and restart the backend.
- **Both proxy and direct labels appear:** Different connections in the selected period used different outbounds. This does not mean one connection used both paths simultaneously.
- **Port already in use:** An instance may already be running. Open its dashboard or use a different dashboard port instead of starting duplicate instances.
- **Recording continues after disabling autostart:** Disabling autostart only affects future sign-ins. Run stop.bat to stop the current instance.

## Tests

```bash
python -m unittest -v test_app.py
```

Tests use temporary databases and local simulated controller endpoints; a real Clash instance is not required. They cover incremental counting, reconnection baselines, history migration, time sorting, minute boundaries, time zones, outbound filters, WebSocket handshakes, and HTTP endpoints.

## License and Related Projects

This project is released under the [MIT License](LICENSE). This repository contains the recorder source code; it does not include or distribute the Mihomo core.

- [Mihomo](https://github.com/MetaCubeX/mihomo)
- [Mihomo documentation](https://wiki.metacubex.one/)

---

本项目全部由 ChatGPT（Codex，基于 GPT-6）上传至 GitHub。

This project was uploaded to GitHub entirely by ChatGPT (Codex, based on GPT-6).
