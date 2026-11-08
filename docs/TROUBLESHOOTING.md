# 排障

按"在哪一步停住"往下找。

## 1. `login` 一直没反应 / 登录后仍提示过期

先确认鉴权 cookie 到底有没有出现：

```python
# 调试片段
from playwright.sync_api import sync_playwright
from ulearning import browser as B
with sync_playwright() as p:
    ctx = B.launch(p, __import__("pathlib").Path("profile-auto"), "msedge")
    print([c["name"] for c in ctx.cookies() if "ulearning" in c["domain"]])
```

- 只有 `_abfpc / cna / belong / lang` 这类 → 还是未登录态，`token`、`AUTHORIZATION`、`USERINFO` 一个都没出现
- 有 `token` 但页面仍 timeout → 访问 `courseweb.ulearning.cn` 与 `umooc.ulearning.cn` 属于不同子域，
  确认 cookie 的 `domain` 是 `.ulearning.cn`（带前导点），否则只能在 umooc 生效

**根本原因**：优学院的会话 cookie 不带 `expires`，关浏览器即失效。
本项目的 `persist_auth_cookies()` 就是干这个的；如果它没跑到，检查 `runner.ensure_login` 的判定分支。

## 2. 能列出课程，点进去却进不了课件

```bash
python tools/probe.py --course <courseId>
```

看 `logs/chapters.json`：

| 现象 | 原因 | 改哪 |
|---|---|---|
| 文件是 `[]` | `table.directory-table` 没渲染 | 多半是 hash 直接跳过去，SPA 没初始化；必须「先点课程卡片，再改 hash」 |
| 有行但 `name` 为空 | `.tabchapter-name` 变了 | `course.LIST_CHAPTERS_JS` |
| 有行但 `btn` 为空 | 按钮不是 `<button>` | `course.OPEN_CHAPTER_JS` 里换成 `a` / `div[role=button]` |

`#/course/units?courseId=` 是"单元"视图，不是课件目录，内容为空，别用。

## 3. 学习页打开了，视频不动

按顺序检查：

1. **提示框没关**。首播会弹「视频观看时长≥视频时长才能算完成，进度条不能拖拽哦～」+ 左上「退出学习」气泡。
   不点掉，`video.currentTime` 停在 0。→ `dom.dismiss_tips()` 是否命中，按钮文案改没改
2. **`video` 元素不存在**。`tools/probe.py` 的 `learn-info.json` 里 `videos` 为空 → 播放器换了实现
   （iframe / canvas / 第三方 SDK），需要把 `dom.VSTAT_JS` 改成对应取法
3. **倍速被重置**。优学院播放器自己维护 `playbackRate`，改完会被 UI 覆盖。`dom.force_play()`
   每次调用都比对一次，不一致就重设
4. **被判定不在场**。切后台/最小化时部分课程会暂停 → `inject.js` 的 `autoResume` 会拉回来

## 4. 视频播完不切下一个小节

`player.LEARN_UNITS_JS` 的编号正则：

```js
/^(\d+[-.．]\d+|\d+)[.．]/
```

覆盖 `1-1.`、`1-2.`、`4.` 三种。如果课程改成 `第一部分`、`（一）`、`Chapter 1`，正则要跟着改。
排查方法：`python tools/probe.py --course <id>` 打出来的 `learn-items.json` 就是匹配结果，
数量对不上就是正则的问题。

## 5. 反复重载 / 疯狂重试

- `STUCK` 阈值默认 20s（kernel `stuckSec`），大文件起播慢可以调到 40
- `player.watch()` 里 `max_retry` 默认 3，重载 2 次还不动就放弃本节
- 如果日志里 `STUCK` 每 20 秒一条且 `at` 值不变，说明是真卡：检查网络或该视频的 m3u8 是否 403

## 6. 窗口疯狂弹出

- 学习页是站点 `window.open` 出来的**新窗口**，属于正常
- 如果连主窗口都在跳，检查是不是登录判定误命中（本项目早期版本用「URL 里没有 login」判断，
  `about:blank` 会误判，导致 10 秒一跳）。现在只认「新出现的鉴权 cookie」

## 7. 浏览器顶部报 `--no-sandbox` 不受支持

Playwright 默认会加 `--no-sandbox`。`browser.IGNORE_DEFAULT_ARGS` 已经排除它，
如果还出现，说明你直接用了 `p.chromium.launch()` 而不是 `browser.launch()`。

## 8. CI / Linux 上跑不起来

`channel="msedge"` / `"chrome"` 在 Linux runner 上没有。用：

```bash
ULEARN_CHANNEL=chromium python tests/test_detector.py
```

或 `python -m ulearning run -b chromium`（需 `playwright install chromium`）。
注意：优学院登录在无头环境下通常需要扫码，CI 只适合跑单测。
