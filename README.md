# Mise Park 场地占用记录

每天两次（11:00 / 23:00）抓取 San Jose PRNS 预订系统，把当下能看到的占用情况存下来，
补上网站因为「至少提前 4 天」规则而不再显示的那部分，并发布成一个谁都能打开的网页。

## 部署到 Railway（推荐，不依赖本机）

一个常驻服务：内置调度器每天 11:00 和 23:00 各抓一次，同时把页面提供出去。
**必须挂 Volume** —— 容器文件系统是临时的，不挂的话每次重新部署快照全没。

首次：

```bash
brew install railway          # 或 npm i -g @railway/cli
railway login
cd ~/Documents/MiseParkCalendar
railway init                  # 建项目
railway up                    # 首次部署
railway link                  # 把服务绑到当前目录（后面几条要用）
railway volume add --mount-path /data          # 持久化快照
railway variables --set MISE_DATA=/data
railway domain                # 拿公网地址
```

之后改代码**不用再 `railway up`** —— 把仓库接上 GitHub 自动部署：

```bash
bash setup_github.command     # 建 GitHub 仓库并推送
```

然后 Railway → 服务 → **Settings → Source → Connect Repo**，选这个仓库和 `main` 分支。
接上之后每次：

```bash
git add -A && git commit -m "..." && git push   # 推完自动构建部署
```

改完变量会自动重新部署。地址出来后：

- `/` 页面
- `/status` 运行状态（抓了几份、上次成功/失败原因）—— 出问题先看这个
- `/history.csv`、`/data/*.json` 原始数据

也可以在 https://railway.com/new 用网页操作：Deploy from GitHub repo →
服务 Settings 里加 Volume（挂载路径 `/data`）→ Variables 加 `MISE_DATA=/data`
→ Networking 里 Generate Domain。

### 环境变量
| 变量 | 作用 |
|---|---|
| `MISE_DATA` | 数据落盘目录。Railway 上设成 Volume 的挂载路径 `/data` |
| `MISE_TZ` | 时区，默认 `America/Los_Angeles`。一般不用设 |
| `MISE_RUN_HOURS` | 每天抓取的整点，默认 `11,23`。想加一次就写 `8,14,20` |
| `PORT` | Railway 自动注入，不用管 |

### 时区那个坑（踩过一次）
**不要**用 `TZ` 环境变量 + `time.tzset()` 来定时区。Railway 的运行镜像里没有系统
tzdata，`tzset()` 会**静默回落到 UTC** —— 而 `/status` 里的 `tz` 字段只是回显环境变量，
看起来一切正常，实际上"今天"和 11:00/23:00 全部按 UTC 算，差 7 小时。

现在改成显式 `zoneinfo.ZoneInfo`，并在 `requirements.txt` 里装 `tzdata` 包自带数据库，
跟基础镜像无关。夏令时（2026-11-01 PDT→PST）也会自动跟上，11:00 永远是当地 11:00。

`/status` 现在同时报 `now`、`now_utc` 和 `utc_offset`，一眼就能看出有没有再犯：
`utc_offset` 该是 `-0700`（夏令时）或 `-0800`（冬令时），**不该是 `+0000`**。

抓取是**幂等**的：快照文件按「时段」命名（`snapshot-2026-09-12-1100.json`），
当前时段已有文件就跳过。所以重新部署、重启都不会重复记账；
而停机期间错过的时段，一上线就会立刻补抓最近的那个。

### 仓库里放什么
`data/`、`history.csv`、`index.html` 都在 `.gitignore` 里 —— 线上这些住在 Railway 的
Volume（`/data`），不是仓库内容。仓库只放代码。

## 备选：在本机跑（不用 Railway 的话）

`install.command` / `run_daily.sh` / `publish.sh` 是本机 launchd 方案的残留，
现在用不到，留着当退路（万一 Railway 访问不了那个网站）。

```bash
bash ~/Documents/MiseParkCalendar/install.command      # 每天 07:30 自动抓取
bash ~/Documents/MiseParkCalendar/setup_github.command # 建仓库 + 开 Pages（想分享才需要）
```

装完之后每天 07:30 自动：抓取 → 生成页面 → push 到 GitHub Pages。
只想自己看就别跑第二个，`publish.sh` 检测不到 git 会自己跳过，不影响采集。

## 文件
| 文件 | 说明 |
|---|---|
| `data/snapshot-YYYY-MM-DD-HHMM.json` | 每个时段一份原始快照，只增不改 |
| `history.csv` | 所有快照的平表，每次抓完从 `data/` 全量重建，可直接用 Excel 打开 |
| `changes.csv` | 变更日志，**只追加**。列：noticed_at, from_slot, to_slot, resource_id, resource_name, target_date, kind(booked/freed), start, end |
| `changes_state.json` | 变更日志算到哪一份快照了 |
| `index.html` | 网页，每次抓取后重新生成；GitHub Pages 就服务这个 |
| `template.html` | 页面模板，改样式改这里 |
| `fetch_mise.py` | 抓取 + 生成页面 |
| `run_daily.sh` | launchd 调的入口：抓取 + 发布 |
| `publish.sh` | git commit + push |
| `server.py` | Railway 上的常驻服务：调度器 + HTTP server |
| `railway.json` | Railway 部署配置 |
| `run.log` | 本机定时任务输出，出问题看这个 |

## 页面怎么看

**红色 = 已被占用**，浅色 = 还空着。画幅默认是场地开放时间 8:00–22:00，
个别日期空档超出这个范围时会自动撑开（比如 10/31 空到 23:00）。

注意接口给的是**空闲**时段，红色的占用是用「开放时间减去空闲」算出来的。
所以「占用」严格说是「不可预订」—— 可能是别人订走了，也可能是场地维护或封场。

**虚线框**的日期表示网站已经不显示了（进入 4 天封锁期，或已经过去），
框里是它**最后一次可见时**的快照，角标注明取自哪天。这是整个项目存在的理由：
网站规定至少提前 4 天才能订，4 天内的日期服务器直接返回空数据，事后无法补查，
只能靠每天存快照把它留住。

**最后更新**显示的是**实际抓取时刻**，不是场次标签。两者可能差很远 ——
容器重启后会补抓错过的场次，「23:00 那一场」可能实际是次日 00:07 跑的。

**最近变化**是一份持续累积的日志，不只是最近一次的对比。每次抓取都会跟上一份快照
做 diff，有变化就追加进 `changes.csv`，页面按「第几次抓取发现的」倒序展示，
红色是被订走、绿色是被退掉。页面只渲染最近 60 次事件（最多 800 条），
完整记录点页面上的链接下载，或直接访问 `/changes.csv`。

这是唯一能回答「**谁在什么时候订走了这个时段**」的数据 —— 快照只记录状态，
变化必须在发生的当下捕捉，事后从快照重算虽然可以，但代价随历史增长。
所以日志是**增量追加**的：每次只 diff 新出现的那一对，用 `changes_state.json` 记进度。

## 监控的场地
| id | 名称 |
|---|---|
| 257 | Mise Soccer Field North (Half) |
| 648 | Mise Soccer Field South (Half) |
| 258 | Mise Softball Field (Full Field) |

三块互相重叠：整场(258)被订走时两个半场也不可用。

## 常用操作
```bash
python3 ~/Documents/MiseParkCalendar/fetch_mise.py   # 手动抓一次
launchctl list | grep mise                            # 看定时任务
tail -20 ~/Documents/MiseParkCalendar/run.log         # 看上次跑得怎么样

# 卸载
launchctl unload ~/Library/LaunchAgents/com.yi.mise-calendar.plist
rm ~/Library/LaunchAgents/com.yi.mise-calendar.plist
```

改场地或天数：`fetch_mise.py` 顶部的 `RESOURCES` / `DAYS_AHEAD`。
改抓取时间：`~/Library/LaunchAgents/com.yi.mise-calendar.plist` 里的
`StartCalendarInterval`，改完 `launchctl unload` 再 `load`。

## 接口
```
GET /sanjoseparksandrec/rest/reservation/resource/availability/daily/{id}
    ?start_date=&end_date=&customer_id=0&company_id=0&locale=en-US
```
无需登录。`daily_details[].status`：`0` 可订 · `5` 已过期 · `7` 未满 4 天（封锁）· `8` 超过 365 天。
`times[]` 里是**空闲**时段，页面上的红色占用是用开放时间(8:00–22:00)减出来的。

两个坑：单次最多返回 **44 天**（超了报 `1043`，所以分 40 天一段抓）；
**不支持 CORS**，所以网页不能自己去调，必须由本机抓好再发布。
