# Mise Park 场地占用记录

每天抓一次 San Jose PRNS 预订系统，把当天能看到的占用情况存下来，
补上网站因为「至少提前 4 天」规则而不再显示的那部分，并发布成一个谁都能打开的网页。

## 装（跑一次就好）

```bash
bash ~/Documents/MiseParkCalendar/install.command      # 每天 07:30 自动抓取
bash ~/Documents/MiseParkCalendar/setup_github.command # 建仓库 + 开 Pages（想分享才需要）
```

装完之后每天 07:30 自动：抓取 → 生成页面 → push 到 GitHub Pages。
只想自己看就别跑第二个，`publish.sh` 检测不到 git 会自己跳过，不影响采集。

## 文件
| 文件 | 说明 |
|---|---|
| `data/snapshot-YYYY-MM-DD.json` | 每天一份原始快照，只增不改 |
| `history.csv` | 所有快照的平表，可直接用 Excel 打开 |
| `index.html` | 网页，每次抓取后重新生成；GitHub Pages 就服务这个 |
| `template.html` | 页面模板，改样式改这里 |
| `fetch_mise.py` | 抓取 + 生成页面 |
| `run_daily.sh` | launchd 调的入口：抓取 + 发布 |
| `publish.sh` | git commit + push |
| `run.log` | 定时任务输出，出问题看这个 |

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
