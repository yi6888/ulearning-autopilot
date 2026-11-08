# ulearning-autopilot

Playwright driver for [Ulearning (优学院)](https://www.ulearning.cn) that **logs in once, then watches
the courseware for you** — chapter by chapter, section by section.

Built against the real site structure, so it handles the things that actually break naive scripts:
the first-play modal, session cookies that die with the browser, the popup learn page, HLS playback,
stalls and in-video quizzes.

```bash
python -m ulearning login                     # scan a QR code once
python -m ulearning run -c "形势与政策（三）"   # watch everything
```

## Features

| | |
|---|---|
| Login once | Rewrites session cookies (`AUTHORIZATION`, `token`) to a 30-day expiry |
| Leaves your browser alone | Clones the profile into `profile-auto/`, original data is read-only |
| Dismisses blockers | Clicks `跳过所有提示` / `我知道了` — otherwise the video never starts |
| Walks sections | `1-1`, `1-2`, `…`, `4.` in the left tree; auto-advance on completion |
| Walks chapters | Closes the learn page, returns to the courseware table, opens the next one |
| Strict 100% | After the video ends it waits for the green check / "已看完" label; no auto-skip if unverified |
| Self-heals | Progress stalled → replay; still stalled → reload and restore position |
| Quiz guard | In-page kernel detects quiz overlays, pauses, records the question, screenshots |
| Event log | `logs/events-YYYYMMDD.jsonl`, one JSON per line |

## Install

```bash
pip install -r requirements.txt   # or: pip install .
```

Only `playwright` is required. It drives the Edge/Chrome already installed on the machine
(`channel=msedge` / `channel=chrome`); `playwright install chromium` is only needed for CI/Linux.

## Usage

```bash
python -m ulearning login                                # one-time
python -m ulearning list  -c 形势与政策                    # list courses only
python -m ulearning run   -c 形势与政策（三） --speed 1.5
python -m ulearning run   --course-idx 2 --max-chapters 2
python -m ulearning run   -c 形势与政策 -b chrome --headless
```

| Flag | Default | |
|---|---|---|
| `-c, --course-name` | — | fuzzy match on course title |
| `--course-idx` | 0 | fallback index in the course list |
| `-b, --browser` | msedge | `msedge` / `chrome` / `chromium` |
| `--speed` | 1.0 | playback rate — keep 1.0, the site counts real watch time |
| `--max-chapters` | 0 | stop after N chapters (0 = all) |
| `--headless` | off | requires a saved login |
| `--cookie-days` | 30 | login lifetime |

## How it works

```
courseList ──click by title──▶ course page ──courseId──▶ #/course/textbook?courseId=N
                                                          table.directory-table
                                                          one row per chapter + "开始学习"
                                                                  │
                                             ua.ulearning.cn/learnCourse/…  (popup)
                                                                  │
                                          left tree 1-1 / 1-2 / …
                                          right side <video src="*.m3u8">
                                                                  ▼
                                        dismiss tips → play → t ≥ dur-1.5 → next section
```

- `ulearning/inject.js` runs inside the page and reports `STUCK` / `PAUSE` / `QUIZ` / `NEAR_END` / `NEXT`
  back to Python via `window.__report`.
- Python handles everything that crosses pages and windows.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the state machine and
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) when the site changes.

## Tests

```bash
python tests/test_detector.py                            # uses local Chrome
ULEARN_CHANNEL=chromium python tests/test_detector.py    # uses bundled chromium
```

Runs against `tests/fake-course.html` — a fake course page with a shimmed `<video>`, a popup quiz and
a fake "next chapter" button. Covers kernel injection, playback, stall detection, quiz detection,
auto-advance and resume-after-pause. No real account needed.

## Site changed?

```bash
python tools/probe.py --course <courseId>
```

Dumps `logs/chapters.json`, `logs/learn-items.json`, `logs/learn-info.json` so you can re-align the
selectors in `course.py` / `player.py` / `inject.js`.

## Notes

- Login state, logs and screenshots stay on your machine. `profile-*/`, `logs/`, `shots/`, `*.jsonl`
  are git-ignored — never commit them, they contain your session cookies.
- Use it on your own account in your own learning environment; whether the platform accepts
  automation and playback-rate changes is your call.

MIT License.

