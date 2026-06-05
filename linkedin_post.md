# LinkedIn Post — GLrc

---

🎵 I built a real-time lyrics overlay for Windows 11 — and it works with any media player.

No Spotify Premium. No API keys. No setup.

Just floating, synced lyrics on your desktop.

Here's what GLrc 2.0 brings to the table:
→ A beautiful new GUI Settings Dashboard for real-time customization
→ Multi-app targeting (instantly switch lyrics from Spotify to YouTube to VLC)
→ Reads the currently playing song directly from Windows Media via WinRT
→ Fetches time-synced lyrics from LrcLib via a high-speed connection pool
→ Displays them as a transparent, borderless, always-on-top overlay
→ Multi-line dynamic crossfading and proportional scaling

The fun engineering challenges I solved:
🔧 Built a PyQt6 Settings Dashboard that syncs bi-directionally with global hotkeys
🔧 Used Win32 DwmSetWindowAttribute via ctypes to strip the border Windows 11 forces on frameless windows
🔧 Custom QPainterPath rendering for crisp white text with a black stroke outline — CSS can't do this
🔧 Global hotkeys via the keyboard module with pyqtSignal bridging to keep PyQt6 thread-safe
🔧 O(log N) lyric lookup using Python's bisect on pre-computed timestamp keys

Tech stack: Python · PyQt6 · WinRT · LrcLib API

The best part? It works with Spotify, YouTube, VLC — anything that talks to Windows Media Transport Controls.

Open source → https://github.com/george-g-girgis/GLrc

#Python #PyQt6 #DesktopApp #OpenSource #WindowsDevelopment #SideProject #SoftwareEngineering

---

> **Instructions:** Replace `YOUR_USERNAME` with your actual GitHub username before posting. Feel free to attach a screenshot or short screen recording of the overlay in action — it'll massively boost engagement.
