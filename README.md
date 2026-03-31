# 📥 InstaGet — Instagram Downloader

Instagram Reels, Photos, Videos & Thumbnails downloader
**No official API · No Login required · Public posts only**

---

## 🛠️ Setup (5 minutes)

### Step 1 — Python install karo (if not installed)
Download from: https://www.python.org/downloads/
(Python 3.8+ joie)

### Step 2 — Dependencies install karo
Terminal/Command Prompt kholo aur project folder ma jao:

```bash
cd instagram-downloader
pip install -r requirements.txt
```

### Step 3 — Server start karo

```bash
python app.py
```

Browser ma khulshe: http://localhost:5000

---

## 📦 Features

| Feature | Tool Used |
|---|---|
| 🎬 Reels Download | yt-dlp |
| 📹 Videos Download | yt-dlp |
| 🖼️ Photos / Carousel | instaloader |
| 🖼️ Thumbnail Download | yt-dlp --write-thumbnail |
| 🔍 Post Info Fetch | yt-dlp + instaloader |

---

## 📁 Project Structure

```
instagram-downloader/
├── app.py          ← Flask backend (Python)
├── index.html      ← Frontend (HTML/CSS/JS)
├── requirements.txt
├── downloads/      ← Temp downloads (auto cleanup)
└── README.md
```

---

## ⚠️ Important Notes

- **Public posts only** — Private accounts are not supported
- **Personal use only** — Get permission from creators
- Downloads folder auto-cleanup after 10 minutes
- Instagram rate limiting? Please wait a few minutes

---

## 🔧 Troubleshooting

**"Cannot connect to server"** → `python app.py` chalelu chhe ke nahi check karo

**"yt-dlp error"** → Update karo: `pip install -U yt-dlp`

**Photo download nai thatu** → `pip install -U instaloader`

**Port 5000 busy** → `app.py` ma `port=5001` karo aur `index.html` ma `API = 'http://localhost:5001'` karo
