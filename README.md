# 🎵 GLrc

A minimalist, transparent lyrics overlay for Windows 11. GLrc reads your currently playing song directly from Windows Media and syncs real-time lyrics from [LrcLib](https://lrclib.net) — no Spotify Premium required.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-6.x-green?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D6?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

- **Transparent & Frameless** — Pure floating text with no window chrome, borders, or background
- **Always on Top** — Lyrics stay visible over any app, game, or desktop
- **Click-Through Lock Mode** — Lock the overlay so mouse clicks pass straight through
- **Real-Time Sync** — Reads playback position directly from Windows Media Transport Controls (works with Spotify Free, YouTube, and any media player)
- **Settings Dashboard (v2.0)** — A beautiful GUI dashboard to control colors, fonts, sync offsets, and lock states in real-time.
- **Multi-App Targeting (v2.0)** — Instantly switch which media player the lyrics sync to (e.g., switch from Spotify to Chrome).
- **LrcLib Integration** — Fetches time-synced `.lrc` lyrics automatically using prioritized connection pools for speed.
- **Fade-Up Animations** — Smooth crossfade transitions between lyric lines
- **Multi-Line Karaoke Mode** — Show current, previous, and next lines simultaneously (dimmed and dynamically scaled surrounding lines)
- **Color Customizer** — Choose custom fill and outline text colors directly from live-updating color pickers
- **State Persistence** — Window position, size, mode, colors, and font settings are saved in `config.json` and restored on startup

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/george-g-girgis/GLrc.git
cd GLrc
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

> **Note:** Lock/Unlock shortcuts are **global** (work from any app). Font shortcuts are **local** (only when you click the overlay first) so they won't conflict with other app shortcuts.

## 🏗️ Architecture

```
GLrc/
├── main.py          # PyQt6 overlay window, tray menu, hotkey filter
├── engine.py        # WinRT Media integration + background lyrics fetcher
├── config.py        # Reads/writes configuration state
├── requirements.txt # Python dependencies
└── .gitignore
```

### How It Works

1. **`engine.py`** uses `winrt-Windows.Media.Control` to read the currently playing track and position directly from the Windows OS — no Spotify API or Premium required.
2. It queries the [LrcLib API](https://lrclib.net) with the track name, artist, and duration. If exact match fails, it uses search fallback and matches by closest duration.
3. Lyrics are fetched asynchronously in a background `QThread` (`LyricsFetchWorker`) so the main UI thread never blocks or freezes during network requests.
4. **`main.py`** runs a 100ms `QTimer` that reads the OS position, interpolates during playback, and displays the matching lyric lines.
5. Text is rendered using a custom `QPainterPath` for a crisp fill-on-outline aesthetic.
6. The Windows 11 DWM border is stripped using `DwmSetWindowAttribute` via `ctypes`.
7. Global hotkeys are captured via an application-level native event filter (`QAbstractNativeEventFilter`) to avoid crashes on Python 3.11+.

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `PyQt6` | GUI framework (transparent window, tray menu, colors) |
| `requests` | HTTP requests to LrcLib API |
| `winrt-Windows.Media.Control` | Read currently playing media from Windows |
| `winrt-Windows.Foundation` | Required WinRT foundation types |

## 📝 Notes

- Works with **any media player** that reports to Windows Media Transport Controls (Spotify, YouTube in browser, VLC, etc.)
- No Spotify Premium required — the app reads from the OS, not the Spotify API
- The `config.json` file is auto-created on first run to store your preferences.

## 📄 License

MIT
