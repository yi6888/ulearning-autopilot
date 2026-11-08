---
name: ulearning-autopilot
description: 优学院(ulearning.cn)网课自动播放技能。当你需要批量看完优学院课件、处理首播"知道了/跳过所有提示"弹窗、卡住自动恢复、弹题拦截、自动切换小节与专题时使用。含 Playwright 驱动器、页面内检测内核、本地自测页与结构探测工具。
---

# 优学院网课自动驾驶

把「登录 → 选课 → 进课件 → 逐个视频看完 → 换下一节/下一个专题」这条链子固化下来。
针对优学院 2026-11 的真实结构写死选择器，改版后用 `tools/probe.py` 重新对齐。

## 什么时候用

- 用户说「帮我刷优学院网课 / 看完这门课的课件 / 自动播完形势与政策」
- 需要检测网课页面状态：卡住、暂停、弹题、切后台、章节结束
- 需要把这类「SPA + 视频 + 弹窗」网站的自动播放做成一键工具

## 前置条件

- 本机装有 Edge 或 Chrome
- `pip install -r requirements.txt`（只有 playwright）
- 首次需要用户扫码或输账号密码一次

## 标准流程

```bash
# 1) 一次性登录（会话 cookie 会被改写成 30 天有效）
python -m ulearning login

# 2) 列出课程确认目标
python -m ulearning list -c 形势与政策

# 3) 自动刷
python -m ulearning run -c "形势与政策（三）" --speed 1.5
```

长任务用后台跑，日志看 `logs/events-YYYYMMDD.jsonl`。

## 平台规则（踩过的坑，必须遵守）

1. **会话 cookie 是临时的**：登录后要 `persist_auth_cookies()` 改写有效期，否则每次重启都要重新扫码。
2. **播放器结束后会自动从头循环**：必须用 `ended` 事件钩子（`player.END_HOOK_JS`）在结束瞬间 `pause()`，轮询永远抓不到 `t≈duration`。
3. **长时间没交互会弹「计时学习已暂停 / 走神太久」**：视频照放但学时不再累计，必须点「继续学习」才恢复。内核每 20 秒发一次合成 mousemove/keydown 预防，同时 `guardIdle()` 一旦看到该弹窗立刻点掉。：看完只会在左下角显示「已看完」，左侧目录的红勾要等你点了下一个才变。所以流程必须是：播完 → 停住 → 等「已看完」→ 点下一个 → 回读上一节红勾。**不要**在播完后关窗重开，那会把上报时机错过。

## 关键实现（改代码前务必先读）

| 位置 | 作用 | 改版时最容易坏的地方 |
|---|---|---|
| `ulearning/browser.py:persist_auth_cookies` | 会话 cookie 转 30 天 | 鉴权 cookie 名变了就不生效 |
| `ulearning/course.py:LIST_CHAPTERS_JS` | 课件目录表 `table.directory-table tr[id^=chapterTr]` | 表格类名 |
| `ulearning/course.py:open_chapter` | 接住 `window.open` 的学习页 | 不是新窗口而是同页跳转时失效 |
| `ulearning/player.py:LEARN_UNITS_JS` | 左侧小节 `1-1.xxx` 编号规则 | 编号格式（`一、` 之类） |
| `ulearning/dom.py:dismiss_tips` | 关「知道了/跳过所有提示」 | 按钮文案 |
| `ulearning/inject.js` | 弹题识别、`STUCK`、`NEXT` 文案 | 下一节按钮文字 |

## 排障顺序

1. `python -m ulearning list -c <课程>` 还列不出课程 → 登录态问题，重跑 `login`
2. 能列课程但进不去课件 → `python tools/probe.py --course <id>` 看 `logs/chapters.json` 是否为空
3. 打开了学习页但视频不动 → 先看是不是提示框没关（`dismiss_tips` 是否命中），再看 `videos` 是否为空
4. 视频播完不切下一个 → 检查 `player.LEARN_UNITS_JS` 是否漏了当前小节的编号格式

详细对照表见 `docs/TROUBLESHOOTING.md`，架构说明见 `docs/ARCHITECTURE.md`。

## 交付物约定

- 不改用户的浏览器配置：只复制到 `profile-*/`
- 不提交 `profile-*/`、`logs/`、`shots/`、`*.jsonl`
- 事件一律写 JSONL，方便接看板或事后核查


