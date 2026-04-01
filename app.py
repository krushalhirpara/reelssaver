
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
import yt_dlp
import instaloader
import os
import re
import uuid
import shutil
import tempfile
import threading
import time

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Auto cleanup: delete files older than 10 minutes
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


def is_instagram_url(url):
    pattern = r'(https?://)?(www\.)?instagram\.com/(p|reel|tv|reels)/[\w\-]+'
    return bool(re.match(pattern, url))


def extract_shortcode(url):
    """Reliably extract shortcode from any Instagram URL format including ?img_index=1"""
    # Remove query string and fragments
    url_clean = url.split('?')[0].split('#')[0].rstrip('/')
    # Last path segment is the shortcode
    return url_clean.split('/')[-1]


# ──────────────────────────────────────────
#  ROUTE: Get media info (before download)
# ──────────────────────────────────────────
@app.route('/api/info', methods=['GET', 'POST'])
def get_info():
    if request.method == 'GET':
        return {"status": "ok"}

    data = request.get_json()
    url = data.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        media_type = 'reel' if ('/reel/' in url or '/reels/' in url) else 'video' if info.get('ext') in ['mp4','webm'] else 'photo'

        return jsonify({
            'success': True,
            'title': info.get('title', 'Instagram Post'),
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration', 0),
            'uploader': info.get('uploader', ''),
            'description': info.get('description', '')[:200] if info.get('description') else '',
            'type': media_type,
            'url': url
        })
    except Exception as e:
        # yt-dlp failed — might be a photo post, try instaloader
        try:
            L = instaloader.Instaloader()
            shortcode = extract_shortcode(url)
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            return jsonify({
                'success': True,
                'title': post.owner_username + "'s post",
                'thumbnail': post.url if not post.is_video else post.video_url,
                'duration': 0,
                'uploader': post.owner_username,
                'description': (post.caption or '')[:200],
                'type': 'video' if post.is_video else 'photo',
                'url': url
            })
        except Exception as e2:
            return jsonify({'success': False, 'error': f'Could not fetch info: {str(e2)}'}), 500


# ──────────────────────────────────────────
#  ROUTE: Download Reel / Video
# ──────────────────────────────────────────

from flask import send_from_directory 

@app.route('/ads.txt')
def ads():
    return send_from_directory('.', 'ads.txt')

@app.route('/sitemap.xml')
def sitemap():
    return send_from_directory('.', 'sitemap.xml')
    
@app.route('/api/download/video', methods=['POST'])
def download_video():
    data = request.get_json()
    url = data.get('url', '').strip()
    quality = data.get('quality', 'best')  # best / worst

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    uid = str(uuid.uuid4())[:8]
    out_dir = os.path.join(DOWNLOAD_DIR, uid)
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, '%(id)s.%(ext)s')

    fmt = 'bestvideo+bestaudio/best' if quality == 'best' else 'worstvideo+worstaudio/worst'

    ydl_opts = {
        'outtmpl': out_template,
        'format': fmt,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Find the downloaded file
        files = os.listdir(out_dir)
        if not files:
            return jsonify({'success': False, 'error': 'Download failed'}), 500

        file_path = os.path.join(out_dir, files[0])
        fname = f"instaGet_reel_{uid}.mp4"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=fname,
            mimetype='video/mp4'
        )
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────
#  ROUTE: Download Thumbnail
# ──────────────────────────────────────────
@app.route('/api/download/thumbnail', methods=['POST'])
def download_thumbnail():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    uid = str(uuid.uuid4())[:8]
    out_dir = os.path.join(DOWNLOAD_DIR, uid)
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, '%(id)s.%(ext)s')

    ydl_opts = {
        'outtmpl': out_template,
        'skip_download': True,
        'writethumbnail': True,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        files = os.listdir(out_dir)
        if not files:
            return jsonify({'success': False, 'error': 'Thumbnail not found'}), 500

        # find image file
        img_file = None
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                img_file = f
                break

        if not img_file:
            return jsonify({'success': False, 'error': 'No thumbnail file found'}), 500

        file_path = os.path.join(out_dir, img_file)
        ext = img_file.rsplit('.', 1)[-1]
        fname = f"instaGet_thumbnail_{uid}.{ext}"

        return send_file(
            file_path,
            as_attachment=True,
            download_name=fname,
            mimetype=f'image/{ext}'
        )
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────
#  ROUTE: Download Photo(s) — yt-dlp based (no instaloader needed)
#  Returns nodes list so frontend shows grid preview + download buttons
# ──────────────────────────────────────────
@app.route('/api/download/photo', methods=['POST'])
def download_photo():
    import requests as req_lib
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    # Strip query params
    url_clean = url.split('?')[0].rstrip('/')

    try:
        # Use yt-dlp to extract all media info (works for photo posts too)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url_clean, download=False)

        nodes = []

        # Carousel / sidecar — multiple entries
        entries = info.get('entries') or []
        if entries:
            for i, entry in enumerate(entries):
                ext = entry.get('ext', '')
                is_vid = ext in ['mp4', 'webm'] or (entry.get('vcodec') not in [None, 'none', ''])
                # Get best image/video URL
                direct_url = entry.get('url', '')
                thumb = entry.get('thumbnail', '')
                if is_vid:
                    nodes.append({
                        'index': i,
                        'type': 'video',
                        'thumb': thumb,
                        'photo_url': thumb,
                        'video_url': direct_url,
                    })
                else:
                    # For photos, direct url IS the image
                    nodes.append({
                        'index': i,
                        'type': 'photo',
                        'thumb': direct_url or thumb,
                        'photo_url': direct_url or thumb,
                        'video_url': None,
                    })
        else:
            # Single item
            ext = info.get('ext', '')
            is_vid = ext in ['mp4', 'webm'] or (info.get('vcodec') not in [None, 'none', ''])
            direct_url = info.get('url', '')
            thumb = info.get('thumbnail', '')
            if is_vid:
                nodes.append({
                    'index': 0,
                    'type': 'video',
                    'thumb': thumb,
                    'photo_url': thumb,
                    'video_url': direct_url,
                })
            else:
                nodes.append({
                    'index': 0,
                    'type': 'photo',
                    'thumb': direct_url or thumb,
                    'photo_url': direct_url or thumb,
                    'video_url': None,
                })

        if not nodes:
            return jsonify({'success': False, 'error': 'No media found in this post'}), 404

        return jsonify({
            'success': True,
            'type': 'carousel' if len(nodes) > 1 else nodes[0]['type'],
            'nodes': nodes,
            'count': len(nodes),
        })

    except Exception as e:
        # yt-dlp failed — fallback to instaloader
        try:
            import requests as req_lib
            shortcode = extract_shortcode(url_clean)
            L = instaloader.Instaloader(
                quiet=True, download_pictures=False, download_videos=False,
                download_video_thumbnails=False, download_geotags=False,
                download_comments=False, save_metadata=False,
            )
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            nodes = []
            if post.typename == 'GraphSidecar':
                for i, node in enumerate(post.get_sidecar_nodes()):
                    if node.is_video:
                        nodes.append({'index': i, 'type': 'video', 'thumb': node.display_url,
                                      'photo_url': node.display_url, 'video_url': node.video_url})
                    else:
                        nodes.append({'index': i, 'type': 'photo', 'thumb': node.display_url,
                                      'photo_url': node.display_url, 'video_url': None})
            else:
                nodes.append({'index': 0, 'type': 'photo', 'thumb': post.url,
                              'photo_url': post.url, 'video_url': None})
            return jsonify({
                'success': True,
                'type': 'carousel' if len(nodes) > 1 else nodes[0]['type'],
                'nodes': nodes,
                'count': len(nodes),
            })
        except Exception as e2:
            return jsonify({'success': False, 'error': f'Photo fetch failed: {str(e2)}'}), 500


# ──────────────────────────────────────────
#  ROUTE: Download a single carousel video by its CDN URL
# ──────────────────────────────────────────
@app.route('/api/download/carousel-video', methods=['POST'])
def download_carousel_video():
    import requests as req_lib
    data = request.get_json()
    video_url = data.get('video_url', '').strip()
    idx = int(data.get('index', 0))

    if not video_url:
        return jsonify({'success': False, 'error': 'No video URL provided'}), 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.instagram.com/',
            'Accept': '*/*',
        }
        r = req_lib.get(video_url, headers=headers, timeout=60, stream=True)
        r.raise_for_status()

        uid = str(uuid.uuid4())[:6]
        file_path = os.path.join(DOWNLOAD_DIR, f'cvid_{uid}_{idx}.mp4')
        with open(file_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f'reelssaver_video_{idx+1}.mp4',
            mimetype='video/mp4'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────
#  ROUTE: Proxy-download a CDN image
#  (Instagram CDN blocks direct browser downloads)
# ──────────────────────────────────────────
@app.route('/api/proxy/image', methods=['POST'])
def proxy_image():
    import requests as req_lib
    data = request.get_json()
    img_url = data.get('url', '').strip()
    idx = int(data.get('index', 0))

    if not img_url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.instagram.com/'
        }
        r = req_lib.get(img_url, headers=headers, timeout=30)
        r.raise_for_status()

        uid = str(uuid.uuid4())[:6]
        file_path = os.path.join(DOWNLOAD_DIR, f'photo_{uid}_{idx}.jpg')
        with open(file_path, 'wb') as f:
            f.write(r.content)

        return send_file(
            file_path,
            as_attachment=True,
            download_name=f'instaGet_photo_{idx+1}.jpg',
            mimetype='image/jpeg'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ──────────────────────────────────────────
#  ROUTE: Prepare video for preview
#  Downloads video to server, returns a token to stream it
# ──────────────────────────────────────────

# In-memory store: token -> file_path
_preview_store = {}

@app.route('/api/prepare-preview', methods=['POST'])
def prepare_preview():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url or not is_instagram_url(url):
        return jsonify({'success': False, 'error': 'Invalid Instagram URL'}), 400

    uid = str(uuid.uuid4())[:10]
    out_dir = os.path.join(DOWNLOAD_DIR, 'preview_' + uid)
    os.makedirs(out_dir, exist_ok=True)
    out_template = os.path.join(out_dir, 'video.%(ext)s')

    ydl_opts = {
        'outtmpl': out_template,
        'format': 'best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        files = [f for f in os.listdir(out_dir) if f.endswith('.mp4') or f.endswith('.webm')]
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
    """Stream a previously prepared preview video with range support."""
    from flask import Response
    import mimetypes

    file_path = _preview_store.get(token)
    if not file_path or not os.path.exists(file_path):
        return jsonify({'error': 'Token expired or not found'}), 404

    file_size = os.path.getsize(file_path)
    mime = 'video/mp4'

    range_header = request.headers.get('Range', None)

    if range_header:
        # Parse Range: bytes=start-end
        byte_range = range_header.replace('bytes=', '').split('-')
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1

        with open(file_path, 'rb') as f:
            f.seek(start)
            data = f.read(length)

        rv = Response(
            data,
            status=206,
            mimetype=mime,
            direct_passthrough=True
        )
        rv.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
        rv.headers['Accept-Ranges'] = 'bytes'
        rv.headers['Content-Length'] = str(length)
        rv.headers['Access-Control-Allow-Origin'] = '*'
        return rv
    else:
        def generate():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk

        rv = Response(generate(), mimetype=mime)
        rv.headers['Content-Length'] = str(file_size)
        rv.headers['Accept-Ranges'] = 'bytes'
        rv.headers['Access-Control-Allow-Origin'] = '*'
        return rv


# ──────────────────────────────────────────
#  ROUTE: Health check
# ──────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'message': 'InstaGet server is running!'})


# ──────────────────────────────────────────
#  Serve frontend
# ──────────────────────────────────────────
@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))


@app.route('/privacy-policy')
def privacy_policy():
    return send_file(os.path.join(os.path.dirname(__file__), 'privacy-policy.html'))


@app.route('/terms-conditions')
def terms_conditions():
    return send_file(os.path.join(os.path.dirname(__file__), 'terms-conditions.html'))


@app.route('/contact-us')
def contact_us():
    return send_file(os.path.join(os.path.dirname(__file__), 'contact-us.html'))


import os

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 InstaGet Server running on port {port}")
    app.run(debug=False, host='0.0.0.0', port=port)
