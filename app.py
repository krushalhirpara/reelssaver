from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from flask import send_from_directory
import yt_dlp
import os
import re
import uuid
import shutil
import threading
import time
import requests as req_lib

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
#  COOKIES SETUP
#  Rate-limit bypass karvano sabse reliable tarika.
#
#  HOW TO GET cookies.txt (5 minutes):
#  1. Chrome ma Instagram login karo
#  2. Chrome Extension install karo:
#     "Get cookies.txt LOCALLY"
#     https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc
#  3. instagram.com par jao
#  4. Extension icon click karo → "Export" button → cookies.txt download thase
#  5. aa cookies.txt file project root ma muko (app.py ni sathe j)
#  6. Git commit karo: git add cookies.txt && git commit -m "add cookies"
#  7. Render/Railway deploy — done!
# ══════════════════════════════════════════════════════════════
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.txt")


def get_cookies_opt():
    """Return cookiefile opt if cookies.txt exists."""
    if os.path.exists(COOKIES_FILE):
        return {'cookiefile': COOKIES_FILE}
    return {}


# ── Auto cleanup: delete files older than 10 minutes ──
def cleanup_old_files():
    while True:
        time.sleep(300)
        now = time.time()
        for fname in os.listdir(DOWNLOAD_DIR):
            fpath = os.path.join(DOWNLOAD_DIR, fname)
            try:
                if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > 600:
                    os.remove(fpath)
                elif os.path.isdir(fpath) and (now - os.path.getmtime(fpath)) > 600:
                    shutil.rmtree(fpath)
            except:
                pass

threading.Thread(target=cleanup_old_files, daemon=True).start()


# ════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════

def is_instagram_url(url):
    pattern = r'(https?://)?(www\.)?instagram\.com/(p|reel|tv|reels)/[\w\-]+'
    return bool(re.match(pattern, url))


def clean_url(url):
    """Strip utm_source/igsh/img_index params — prevents extra 401s."""
    return url.split('?')[0].split('#')[0].rstrip('/')


BROWSER_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.instagram.com/',
    'Origin': 'https://www.instagram.com',
}


def ydl_base_opts():
    """Base yt-dlp opts — browser headers + cookies if available."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'http_headers': BROWSER_HEADERS,
    }
    opts.update(get_cookies_opt())
    return opts


def oembed_fetch(url_clean):
    """Instagram oEmbed — no login, works from any IP, rate-limit safe."""
    endpoint = (
        f"https://www.instagram.com/api/v1/oembed/"
        f"?url={url_clean}&maxwidth=640&hidecaption=0"
    )
    r = req_lib.get(endpoint, headers=BROWSER_HEADERS, timeout=15)
    r.raise_for_status()
    d = r.json()
    return {
        'title':       d.get('title', 'Instagram Post'),
        'thumbnail':   d.get('thumbnail_url', ''),
        'uploader':    d.get('author_name', ''),
        'description': d.get('title', '')[:200],
    }


def ydl_extract_nodes(url_clean):
    """Extract all media nodes from post URL via yt-dlp (no instaloader)."""
    opts = ydl_base_opts()
    opts['skip_download'] = True
    opts['extract_flat'] = False

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url_clean, download=False)

    nodes = []
    entries = info.get('entries') or []

    if entries:
        for i, entry in enumerate(entries):
            is_vid = (
                entry.get('ext') in ('mp4', 'webm')
                or entry.get('vcodec') not in (None, 'none', '')
            )
            direct = entry.get('url', '')
            thumb  = entry.get('thumbnail', '')
            if is_vid:
                nodes.append({'index': i, 'type': 'video',
                               'thumb': thumb, 'photo_url': thumb, 'video_url': direct})
            else:
                nodes.append({'index': i, 'type': 'photo',
                               'thumb': direct or thumb, 'photo_url': direct or thumb,
                               'video_url': None})
    else:
        is_vid = (
            info.get('ext') in ('mp4', 'webm')
            or info.get('vcodec') not in (None, 'none', '')
        )
        direct = info.get('url', '')
        thumb  = info.get('thumbnail', '')
        if is_vid:
            nodes.append({'index': 0, 'type': 'video',
                           'thumb': thumb, 'photo_url': thumb, 'video_url': direct})
        else:
            nodes.append({'index': 0, 'type': 'photo',
                           'thumb': direct or thumb, 'photo_url': direct or thumb,
                           'video_url': None})

    return info, nodes


# ════════════════════════════════════════════════════
#  /api/info
# ════════════════════════════════════════════════════
@app.route('/api/info', methods=['GET', 'POST'])
def get_info():
    if request.method == 'GET':
        return jsonify({'status': 'ok'})

    body = request.get_json()
    url  = body.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    url_clean = clean_url(url)
    is_reel   = bool(re.search(r'instagram\.com/(reel|reels|tv)/', url_clean))

    try:
        info, nodes = ydl_extract_nodes(url_clean)
        if is_reel:
            media_type = 'reel'
        elif len(nodes) > 1:
            media_type = 'carousel'
        elif nodes and nodes[0]['type'] == 'video':
            media_type = 'video'
        else:
            media_type = 'photo'

        return jsonify({
            'success':     True,
            'title':       info.get('title', 'Instagram Post'),
            'thumbnail':   info.get('thumbnail', ''),
            'duration':    info.get('duration', 0),
            'uploader':    info.get('uploader', ''),
            'description': (info.get('description') or '')[:200],
            'type':        media_type,
            'url':         url_clean,
            'nodes':       nodes if not is_reel else None,
        })
    except Exception:
        pass

    try:
        oe = oembed_fetch(url_clean)
        return jsonify({
            'success': True, 'title': oe['title'], 'thumbnail': oe['thumbnail'],
            'duration': 0, 'uploader': oe['uploader'], 'description': oe['description'],
            'type': 'photo', 'url': url_clean, 'nodes': None,
        })
    except Exception as e2:
        return jsonify({
            'success': False,
            'error': f'Post info fetch failed. Public chhe? Rate limit hoy to thodi vaar raho. ({e2})'
        }), 500


# ════════════════════════════════════════════════════
#  /api/download/video
# ════════════════════════════════════════════════════
@app.route('/api/download/video', methods=['POST'])
def download_video():
    body    = request.get_json()
    url     = body.get('url', '').strip()
    quality = body.get('quality', 'best')

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    url_clean = clean_url(url)
    uid = str(uuid.uuid4())[:8]
    out_dir = os.path.join(DOWNLOAD_DIR, uid)
    os.makedirs(out_dir, exist_ok=True)

    fmt  = 'bestvideo+bestaudio/best' if quality == 'best' else 'worstvideo+worstaudio/worst'
    opts = ydl_base_opts()
    opts.update({'outtmpl': os.path.join(out_dir, '%(id)s.%(ext)s'),
                 'format': fmt, 'merge_output_format': 'mp4'})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url_clean, download=True)
        files = os.listdir(out_dir)
        if not files:
            return jsonify({'success': False, 'error': 'Download failed'}), 500
        return send_file(os.path.join(out_dir, files[0]), as_attachment=True,
                         download_name=f'reelssaver_video_{uid}.mp4', mimetype='video/mp4')
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════
#  /api/download/thumbnail
# ════════════════════════════════════════════════════
@app.route('/api/download/thumbnail', methods=['POST'])
def download_thumbnail():
    body = request.get_json()
    url  = body.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    url_clean = clean_url(url)
    uid = str(uuid.uuid4())[:8]
    out_dir = os.path.join(DOWNLOAD_DIR, uid)
    os.makedirs(out_dir, exist_ok=True)

    opts = ydl_base_opts()
    opts.update({'outtmpl': os.path.join(out_dir, '%(id)s.%(ext)s'),
                 'skip_download': True, 'writethumbnail': True})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url_clean, download=True)
        img_file = next((f for f in os.listdir(out_dir)
                         if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))), None)
        if not img_file:
            return jsonify({'success': False, 'error': 'No thumbnail file found'}), 500
        ext = img_file.rsplit('.', 1)[-1].lower()
        return send_file(os.path.join(out_dir, img_file), as_attachment=True,
                         download_name=f'reelssaver_thumbnail_{uid}.{ext}',
                         mimetype=f'image/{ext}')
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════
#  /api/download/photo
# ════════════════════════════════════════════════════
@app.route('/api/download/photo', methods=['POST'])
def download_photo():
    body = request.get_json()
    url  = body.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    url_clean = clean_url(url)
    try:
        _, nodes = ydl_extract_nodes(url_clean)
        if not nodes:
            return jsonify({'success': False, 'error': 'No media found'}), 404
        post_type = 'carousel' if len(nodes) > 1 else nodes[0]['type']
        return jsonify({'success': True, 'type': post_type, 'nodes': nodes, 'count': len(nodes)})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Could not fetch post media: {e}'}), 500


# ════════════════════════════════════════════════════
#  /api/download/carousel-video
# ════════════════════════════════════════════════════
@app.route('/api/download/carousel-video', methods=['POST'])
def download_carousel_video():
    body      = request.get_json()
    video_url = body.get('video_url', '').strip()
    idx       = int(body.get('index', 0))

    if not video_url:
        return jsonify({'success': False, 'error': 'No video URL provided'}), 400

    try:
        r = req_lib.get(video_url, headers=BROWSER_HEADERS, timeout=60, stream=True)
        r.raise_for_status()
        uid = str(uuid.uuid4())[:6]
        file_path = os.path.join(DOWNLOAD_DIR, f'cvid_{uid}_{idx}.mp4')
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
        return send_file(file_path, as_attachment=True,
                         download_name=f'reelssaver_video_{idx+1}.mp4', mimetype='video/mp4')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════
#  /api/proxy/image
# ════════════════════════════════════════════════════
@app.route('/api/proxy/image', methods=['POST'])
def proxy_image():
    body    = request.get_json()
    img_url = body.get('url', '').strip()
    idx     = int(body.get('index', 0))

    if not img_url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    try:
        r = req_lib.get(img_url, headers=BROWSER_HEADERS, timeout=30)
        r.raise_for_status()
        uid = str(uuid.uuid4())[:6]
        file_path = os.path.join(DOWNLOAD_DIR, f'proxy_{uid}_{idx}.jpg')
        with open(file_path, 'wb') as f:
            f.write(r.content)
        return send_file(file_path, as_attachment=True,
                         download_name=f'reelssaver_photo_{idx+1}.jpg', mimetype='image/jpeg')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ════════════════════════════════════════════════════
#  /api/prepare-preview + /api/stream/<token>
# ════════════════════════════════════════════════════
_preview_store = {}


@app.route('/api/prepare-preview', methods=['POST'])
def prepare_preview():
    body = request.get_json()
    url  = body.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    url_clean = clean_url(url)
    uid = str(uuid.uuid4())[:10]
    out_dir = os.path.join(DOWNLOAD_DIR, 'preview_' + uid)
    os.makedirs(out_dir, exist_ok=True)

    opts = ydl_base_opts()
    opts.update({'outtmpl': os.path.join(out_dir, 'video.%(ext)s'),
                 'format': 'best[ext=mp4]/best', 'merge_output_format': 'mp4'})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url_clean, download=True)
        files = [f for f in os.listdir(out_dir) if f.endswith(('.mp4', '.webm'))]
        if not files:
            files = os.listdir(out_dir)
        if not files:
            return jsonify({'success': False, 'error': 'Preview download failed'}), 500
        file_path = os.path.join(out_dir, files[0])
        _preview_store[uid] = file_path
        return jsonify({'success': True, 'token': uid})
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stream/<token>', methods=['GET'])
def stream_video(token):
    file_path = _preview_store.get(token)
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Token expired or not found'}), 404

    file_size    = os.path.getsize(file_path)
    range_header = request.headers.get('Range')

    if range_header:
        byte_range = range_header.replace('bytes=', '').split('-')
        start  = int(byte_range[0])
        end    = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1
        with open(file_path, 'rb') as f:
            f.seek(start)
            data = f.read(length)
        rv = Response(data, status=206, mimetype='video/mp4', direct_passthrough=True)
        rv.headers['Content-Range']  = f'bytes {start}-{end}/{file_size}'
        rv.headers['Accept-Ranges']  = 'bytes'
        rv.headers['Content-Length'] = str(length)
        rv.headers['Access-Control-Allow-Origin'] = '*'
        return rv

    def generate():
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                yield chunk

    rv = Response(generate(), mimetype='video/mp4')
    rv.headers['Content-Length'] = str(file_size)
    rv.headers['Accept-Ranges']  = 'bytes'
    rv.headers['Access-Control-Allow-Origin'] = '*'
    return rv


# ════════════════════════════════════════════════════
#  Health + Static + Frontend
# ════════════════════════════════════════════════════
@app.route('/api/health', methods=['GET'])
def health():
    cookies_ok = os.path.exists(COOKIES_FILE)
    return jsonify({
        'status': 'ok',
        'message': 'ReelsSaver running!',
        'cookies': 'active ✅' if cookies_ok else 'missing ⚠️ — add cookies.txt to fix rate-limit',
    })

@app.route('/ads.txt')
def ads():
    return send_from_directory('.', 'ads.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')

BASE = os.path.dirname(__file__)

@app.route('/')
def index():
    return send_file(os.path.join(BASE, 'index.html'))

@app.route('/privacy-policy')
def privacy_policy():
    return send_file(os.path.join(BASE, 'privacy-policy.html'))

@app.route('/terms-conditions')
def terms_conditions():
    return send_file(os.path.join(BASE, 'terms-conditions.html'))

@app.route('/contact-us')
def contact_us():
    return send_file(os.path.join(BASE, 'contact-us.html'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    cookies_ok = os.path.exists(COOKIES_FILE)
    print(f'🚀 ReelsSaver running on port {port}')
    print(f'🍪 Cookies: {"ACTIVE ✅" if cookies_ok else "NOT FOUND ⚠️  add cookies.txt!"}')
    app.run(debug=False, host='0.0.0.0', port=port)
