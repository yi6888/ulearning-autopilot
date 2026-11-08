# ulearning-autopilot

优学院（ulearning.cn）网课自动驾驶：**登录一次，之后按专题自动看完课件**。

针对优学院真实的页面结构写成，不是通用爬虫壳子——处理了首播提示框、会话 cookie 续期、
新窗口学习页、m3u8 播放器、卡住与弹题这些实际会卡住的地方。

```
$ python -m ulearning login                  # 扫一次码，登录态存 30 天
$ python -m ulearning run -c 形势与政策（三）  # 自动刷完课件
```

---

## 特性

| 能力 | 实现 |
|---|---|
| 免重复登录 | 登录后把 `AUTHORIZATION` / `token` 等会话 cookie 改写成 30 天有效 |
| 不碰你的浏览器 | 克隆配置到 `profile-auto/` 再启动，原浏览器数据只读 |
| 自动关提示 | 「跳过所有提示 / 我知道了」逐层点掉，否则视频不播 |
| 逐小节推进 | 学习页左侧目录 `1-1 / 1-2 / … / 4.`，播完自动下一个 |
| 逐专题推进 | 专题播完关掉学习页，回课件目录点下一个专题 |
| 严格 100% | 播到结尾立刻暂停 → 等左下角「已看完」→ 点下一个（平台在这一步才上报上一节）→ 回读红勾 |
| 防走神暂停 | 合成鼠标/键盘事件预防；出现「计时学习已暂停」立即点「继续学习」 |
| 卡住自愈 | 进度不动 → 重播；重播无效 → 重载并回到原进度 |
| 弹题拦截 | 页面内内核识别弹层 → 暂停 + 记录题干 + 截图 |
| 事件留痕 | `logs/events-YYYYMMDD.jsonl` 一行一条，可接看板 |

---

## 安装

```bash
pip install -r requirements.txt
```

只有 `playwright` 一个依赖。浏览器用系统已装的 Edge / Chrome（`channel=msedge` / `channel=chrome`），
不需要 `playwright install chromium`；CI 或 Linux 环境可回落到自带 chromium。

---

## 用法

### 1. 登录（一次）

```bash
python -m ulearning login
```

弹出受控浏览器 → 扫码或账号密码 → 检测到鉴权 cookie 后自动把登录态写进 `profile-auto/`。
窗口会自己关，下次不用再登。

### 2. 刷课

```bash
# 按课程名
python -m ulearning run -c "形势与政策（三）"

# 按序号（课程列表第 1 门是 0）
python -m ulearning run --course-idx 2

# 只刷前 2 个专题，倍速 2.0，无头
python -m ulearning run -c 形势与政策 --max-chapters 2 --headless

# 换 Chrome
python -m ulearning run -c 形势与政策 -b chrome
```

### 3. 只看不刷

```bash
python -m ulearning list -c 形势与政策
```

列出课程 + 专题进度，不打开学习页。

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `-c, --course-name` | 空 | 课程名关键词，模糊匹配 |
| `--course-idx` | 0 | 没给名字时按序号选 |
| `-b, --browser` | msedge | `msedge` / `chrome` / `chromium` |
| `--speed` | 1.0 | 播放倍速。**必须 1.0 才能刷满 100%**（平台按实际时长记账，倍速会少记） |
| `--max-chapters` | 0 | 只刷前 N 个专题，0 = 全部 |
| `--headless` | 关 | 无头运行（登录态需已保存） |
| `--profile` | profile-auto | 配置目录 |
| `--cookie-days` | 30 | 登录态保留天数 |

---

## 目录结构

```
ulearning-autopilot/
├─ ulearning/
│  ├─ cli.py         命令行
│  ├─ runner.py      编排：登录 → 选课 → 专题 → 小节
│  ├─ browser.py     启动 / 配置克隆 / cookie 续期
│  ├─ course.py      课程列表 / 课件目录 / 打开学习页
│  ├─ player.py      学习页小节、播放、看完判定
│  ├─ dom.py         通用 DOM 操作、提示框关闭、视频状态
│  ├─ log.py         彩色日志 + JSONL
│  └─ inject.js      页面内检测内核（注入到每一页）
├─ tools/
│  ├─ hook_server.py webhook 接收 + 实时看板
│  └─ probe.py       结构探测，改版后用它抓真实 DOM
├─ tests/
│  ├─ fake-course.html   模拟课程页（假播放器 / 假弹题 / 假下一节）
│  └─ test_detector.py   内核自测
└─ docs/
   ├─ ARCHITECTURE.md
   └─ TROUBLESHOOTING.md
```

---

## 工作原理

```
courseList ──按名字点──▶ 课程页 ──取 courseId──▶ #/course/textbook?courseId=N
                                                   │  table.directory-table
                                                   │  每行一个专题 + “开始学习”
                                                   ▼
                                   ua.ulearning.cn/learnCourse/...（新窗口）
                                                   │  左侧目录 1-1 / 1-2 / …
                                                   │  右侧 <video src="*.m3u8">
                                                   ▼
                              关提示 → 播放 → t ≥ dur-1.5s → 下一个小节
```

几个关键点：

**会话 cookie 是临时的。** 优学院的 `token` / `AUTHORIZATION` 不带 `expires`，关浏览器即失效。
`browser.persist_auth_cookies()` 用 `ctx.add_cookies()` 把它们重写成 30 天有效，写回配置库。

**提示框会挡住播放。** 首播弹「视频观看时长≥视频时长才能算完成」，不点掉视频停在 00:00。
`dom.dismiss_tips()` 按 `跳过所有提示 → 我知道了 → 知道了 → 确定` 顺序点，进入学习页、点开小节、
以及播放中途暂停时都会调一次。

**学习页是新窗口。** `course.open_chapter()` 用 `ctx.expect_page()` 接住站点 `window.open` 出来的页面，
一个专题处理完主动关掉，避免窗口堆积。

**倍速会被播放器重置。** `dom.force_play()` 每次都检查 `playbackRate`，不一致就重设。

---

## 自测

本地模拟页覆盖全部检测分支，不用碰真站：

```bash
python tests/test_detector.py                    # 用本机 Chrome
ULEARN_CHANNEL=chromium python tests/test_detector.py   # 用自带 chromium
```

```
[1] READY / VIDEO_BOUND        PASS
[2] PLAY / muted               PASS
[3] STUCK 卡死识别              PASS
[4] QUIZ + 题干 + 自动暂停      PASS
[5] NEAR_END → NEXT → 第 2 节   PASS
[6] 暂停自动恢复                PASS
```

---

## 看板（可选）

```bash
python tools/hook_server.py --port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

`run` 时加 `--webhook http://127.0.0.1:8765/hook` 可把事件实时推到面板。当前版本 webhook 由
`inject.js` 的 `CFG.webhook` 控制，可通过 `window.__ULEARN_CFG` 注入。

---

## 适配站点改版

选择器集中在三个文件，改版后按 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) 逐个对：

```
ulearning/course.py   课程卡片、课件目录表、开始学习按钮
ulearning/player.py   左侧小节列表的编号规则
ulearning/inject.js   弹题识别、下一节按钮文案
```

先用 `python tools/probe.py --course <courseId>` 把真实 DOM 抓下来对着改。

---

## 说明

- 登录态、事件日志、截图全部留在本机；`profile-*/`、`logs/`、`shots/` 已在 `.gitignore` 里。
- 上传仓库前别把 `profile-auto/` 或 `logs/*.jsonl` 一起提交——里面有你的账号 cookie。
- 仅用于自己账号的学习环境；倍速与自动化行为是否被平台接受，由使用者自行判断。

MIT License.@

---

## ⚠️ 免责声明

**本项目仅供个人技术学习与研究，非盈利，禁止任何商业用途（含付费代刷）。**

- 全部登录态、日志、截图只存在使用者本机，作者不收集任何数据
- 自动化行为可能与优学院用户协议或你所在学校的规定冲突，使用前请自行判断
- 因使用本项目产生的**任何直接或间接后果**（学习记录异常、成绩无效、账号受限、校纪处理、经济损失等）**均由使用者自行承担，与作者无关**
- 本项目按「现状」提供，不作任何可用性或正确性担保

完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。如果你所在课程明确禁止自动化工具，请不要使用。

