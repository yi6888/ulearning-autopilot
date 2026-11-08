# 架构

## 分层

```
cli.py        参数解析，装配 RunOptions
  └ runner.py     Session：登录编排、课程编排、专题/小节循环
      ├ browser.py  启动、配置克隆、cookie 续期
      ├ course.py   课程列表、课件目录、打开学习页
      ├ player.py   小节列表、点开、看完判定
      ├ dom.py      通用 DOM 原语、提示关闭、视频状态
      └ inject.js   注入到每个页面的检测内核
```

`inject.js` 与 Python 侧职责分开：

- **inject.js** 跑在页面里，负责高频、低延迟的判断：`STUCK`（进度不动）、`PAUSE`、`QUIZ`、
  `NEAR_END`、`NEXT`。它把事件通过 `window.__report` 回传给 Python。
- **Python** 负责跨页面、跨窗口的编排：什么时候进下一个专题、什么时候重载、什么时候放弃。

这样页面内不需要知道"下一步该干嘛"，Python 也不需要每秒 poll 一次 DOM。

## 关键路径

### 登录

```
goto #/index/courseList
  └ 未登录 → 跳 timeout.html → goto umooc 登录页
      └ 轮询 ctx.cookies()：出现新的鉴权 cookie（AUTHORIZATION/token/...）即视为成功
          └ persist_auth_cookies()：add_cookies 重写 expires = now + 30d
              └ goto #/index/courseList 验证
```

为什么不复用已有浏览器：浏览器运行中 `Cookies` 是独占锁（`ERROR_SHARING_VIOLATION`，即便
`FILE_FLAG_BACKUP_SEMANTICS` 也打不开），只能关掉浏览器再复制，或者重新登录一次。

### 课件目录

```
#/course/textbook?courseId=N
  table.directory-table tbody tr[id^="chapterTr"]
     ├ .tabchapter-name      专题名
     ├ td[1]                 进度 xx%
     └ button                开始学习 / 继续学习  → click: learnChapter
```

点这个按钮，站点 `window.open()` 弹出学习页：

```
ua.ulearning.cn/learnCourse/learnCourse.html?courseId=&chapterId=&classId=
```

### 学习页

```
左栏：span 列表，文本形如 1-1.何为长征 / 4.长征精神的时代价值 / 单元小测
右栏：<video src="https://obscloud.ulearning.cn/resources/...m3u8?token=...">
```

完成判定用 `currentTime >= duration - 1.5`。站点自己的规则是"观看时长≥视频时长"，
所以不要 Seek——本项目从不改 `currentTime`（唯一例外是卡住重载后回跳，见 `player.watch`）。

## 状态机

```
             ┌────────────── 每周目 ──────────────┐
textbook ──▶ open_chapter ──▶ learnPage ──▶ play_unit ──▶ watch
   ▲                                                    │
   │◀───────────── 小节播完 / 失败 ───────────────────────┘
   │
   └── 下一个专题
```

`watch()` 返回四种结局，决定上层动作：

| 结局 | 触发 | 上层动作 |
|---|---|---|
| `done` | `t ≥ dur - 1.5` | 下一个小节 |
| `stuck` | 在播但进度不动，重载 2 次仍不动 | 放弃本节，进下一节 |
| `stuck_paused` | 反复暂停，连续 3 次唤醒失败 | 放弃本节 |
| `closed` | 学习页被关 | 终止整轮 |

## 为什么这样设计

- **不写死 courseId**：从 URL 里 `re.search(r"courseId=(\d+)")` 取，课程名只用于定位卡片。
- **不猜路由**：`#/course/textbook` 是实测出来的课件页，`#/course/units` 是"单元"另一个视图，
  内容为空。改版时以 `tools/probe.py` 抓到的为准。
- **指数退避**：内核里 `STUCK` 的阈值随次数放大（`stuckSec × min(n+1, 4)`），避免卡住时刷屏。
