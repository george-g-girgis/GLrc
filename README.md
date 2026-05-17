# 🎵 SpotLrc

A minimalist, transparent lyrics overlay for Windows 11. SpotLrc reads your currently playing song directly from Windows Media and syncs real-time lyrics from [LrcLib](https://lrclib.net) — no Spotify Premium required.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D6?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

- **Transparent & Frameless** — Pure floating text with no window chrome, borders, or background
- **Always on Top** — Lyrics stay visible over any app, game, or desktop
- **Click-Through Lock Mode** — Lock the overlay so mouse clicks pass straight through
- **Real-Time Sync** — Reads playback position directly from Windows Media Transport Controls (works with Spotify Free, YouTube, and any media player)
- **LrcLib Integration** — Fetches time-synced `.lrc` lyrics automatically
- **Fade-Up Animations** — Smooth transitions between lyric lines
- **Resizable & Draggable** — Reposition and resize from any edge or corner in Edit Mode
- **Font Scaling** — Adjust font size with keyboard shortcuts while focused

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_USERNAME/SpotLrc.git
cd SpotLrc
python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

### 2. Run

```bash
.\venv\Scripts\python.exe main.py
```

That's it — no API keys, no authentication, no configuration needed.

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Shift+L` | **Lock Mode** — Click-through, undraggable, unresizable |
| `Ctrl+Shift+U` | **Edit Mode** — Draggable, resizable, font shortcuts enabled |
| `Ctrl+Shift+Up` | Increase font size *(only when overlay is focused)* |
| `Ctrl+Shift+Down` | Decrease font size *(only when overlay is focused)* |

> **Note:** Lock/Unlock shortcuts are **global** (work from any app). Font shortcuts are **local** (only when you click the overlay first) so they won't conflict with Excel.

## 🏗️ Architecture

```
SpotLrc/
├── main.py          # PyQt6 overlay window, animations, hotkeys
├── engine.py        # Windows Media integration + LrcLib lyrics fetcher
├── auth_test.py     # Optional Spotify API connection test
├── requirements.txt # Python dependencies
├── .env.example     # Template for Spotify API keys (optional)
└── .gitignore
```

### How It Works

1. **`engine.py`** uses `winrt-Windows.Media.Control` to read the currently playing track and position directly from the Windows OS — no Spotify API needed
2. It queries the [LrcLib API](https://lrclib.net) with the track name and artist to fetch synced `.lrc` lyrics
3. Lyrics are parsed into `(milliseconds, text)` tuples and searched with `bisect` for O(log N) lookups
4. **`main.py`** runs a 100ms `QTimer` that reads the OS position each tick, interpolates when the OS returns stale values, and displays the matching lyric line
5. Text is rendered with a custom `QPainterPath` for a crisp white-on-black-outline aesthetic
6. The Windows 11 DWM border is stripped using `DwmSetWindowAttribute` via `ctypes`

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `PyQt6` | GUI framework (transparent frameless window) |
| `keyboard` | Global hotkey capture |
| `requests` | HTTP requests to LrcLib API |
| `winrt-Windows.Media.Control` | Read currently playing media from Windows |
| `winrt-Windows.Foundation` | Required WinRT foundation types |
| `python-dotenv` | Environment variable loading |

## 📝 Notes

- Works with **any media player** that reports to Windows Media Transport Controls (Spotify, YouTube in browser, VLC, etc.)
- No Spotify Premium required — the app reads from the OS, not the Spotify API
- The `.cache` and `.env` files are gitignored for security

## 📄 License

MIT
