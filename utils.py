import yt_dlp
import urllib.request
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor  # Added for parallel speedup

def format_size(bytes_size):
    """Converts raw bytes data into clean, readable strings like 884.44 MB."""
    if not bytes_size:
        return "Unknown Size"
    for unit in ['Bytes', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"

def get_remote_file_size(url):
    """Hits the image URL header to fetch its exact size without downloading the file."""
    try:
        req = urllib.request.Request(
            url, 
            method='HEAD', 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            content_length = resp.headers.get('Content-Length')
            if content_length:
                return int(content_length)
    except Exception:
        pass
    return None

def extract_height_fallback(f):
    """
    Attempts to pull a numeric height value from other format fields 
    if f.get('height') is None or missing.
    """
    # 1. Check if height is already a valid integer
    height = f.get('height')
    if height and isinstance(height, (int, float)):
        return int(height)
        
    # 2. Try parsing from 'resolution' (e.g., '1920x1080')
    resolution = f.get('resolution')
    if resolution and isinstance(resolution, str):
        match = re.search(r'x(\d+)', resolution)
        if match:
            return int(match.group(1))
            
    # 3. Try parsing from 'format_note' or 'format_id' (e.g., '1080p', '720p60')
    for field_key in ['format_note', 'format_id']:
        field_val = f.get(field_key)
        if field_val and isinstance(field_val, str):
            match = re.search(r'(\d+)p', field_val)
            if match:
                return int(match.group(1))
                
    return None

def get_resolution_label(height):
    """Generates an aesthetic quality tag based on numeric height."""
    if height >= 2160:
        return f"{height}p (4K)"
    elif height >= 1440:
        return f"{height}p (2K)"
    elif height >= 720:
        return f"{height}p (HD)"
    else:
        return f"{height}p (SD)"

# ==============================================================================
# NEW HELPER FUNCTIONS FOR VIDEO INFORMATION METADATA EXTRACTION
# ==============================================================================

def format_duration(seconds):
    """Converts raw seconds into an intuitive countdown string (e.g., 4:17 or 1:05:22)."""
    if not seconds:
        return "Unknown Duration"
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"

def format_upload_date(date_str):
    """Converts standard YYYYMMDD string format into a clean display layout (e.g., Jul 17, 2026)."""
    if not date_str:
        return "Unknown Date"
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return date_str

# ==============================================================================

def extract_media_info(url):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        formats = info.get('formats', [])
        
        # ----------------------------------------------------------------------
        # COMPILING VIDEO CONTENT INFORMATION CARRIER BLOCK
        # ----------------------------------------------------------------------
        video_metadata = {
            'title': info.get('title', 'Unknown Title'),
            'duration': format_duration(info.get('duration')),
            'upload_date': format_upload_date(info.get('upload_date'))
        }
        # ----------------------------------------------------------------------
        
        # Dictionaries keyed by resolution height to automatically filter duplicates
        best_table1_tracks = {}  # height -> format_dict
        best_table2_tracks = {}  # height -> format_dict
        table3 = []              # Audio Only
        table4 = []              # Thumbnails

        # 1. Find the single best audio track to use for high-res stitching
        best_audio = None
        best_audio_size = 0
        for f in formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                size = f.get('filesize') or f.get('filesize_approx') or 0
                if size > best_audio_size:
                    best_audio_size = size
                    best_audio = f

        if not best_audio and formats:
            best_audio = formats[0]

        # 2. Populate Table 1 (Video with Audio)
        for f in formats:
            if f.get('vcodec') == 'none' or f.get('acodec') == 'none':
                # Skip muted or audio-only formats for native Table 1 processing
                continue
                
            height = extract_height_fallback(f)
            if not height:
                continue

            raw_size = f.get('filesize') or f.get('filesize_approx') or 0
            resolution_name = get_resolution_label(height)

            # Keep the largest file size stream for each resolution
            if height not in best_table1_tracks or raw_size > best_table1_tracks[height]['raw_size']:
                best_table1_tracks[height] = {
                    'quality': resolution_name,
                    'size': format_size(raw_size),
                    'url': f.get('url'),
                    'needs_client_merge': False,
                    'raw_size': raw_size
                }

        # Check if stitching a muted high-quality video with our best audio yields a better quality format
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                height = extract_height_fallback(f)
                if not height:
                    continue

                raw_size = f.get('filesize') or f.get('filesize_approx') or 0
                combined_bytes = raw_size + best_audio_size
                
                resolution_name = get_resolution_label(height)

                # If no native video exists, or the merged hybrid stream has a larger total file size
                if height not in best_table1_tracks or combined_bytes > best_table1_tracks[height]['raw_size']:
                    best_table1_tracks[height] = {
                        'quality': resolution_name,
                        'size': format_size(combined_bytes),
                        'url': f.get('url'),
                        'audio_url': best_audio.get('url') if best_audio else None,
                        'needs_client_merge': True,
                        'raw_size': combined_bytes
                    }

        # 3. Populate Table 2 (Video Without Audio / Muted)
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('acodec') == 'none':
                height = extract_height_fallback(f)
                if not height:
                    continue

                raw_size = f.get('filesize') or f.get('filesize_approx') or 0
                resolution_name = get_resolution_label(height)

                # Deduplicate: Keep only the stream with the largest file size for this height
                if height not in best_table2_tracks or raw_size > best_table2_tracks[height]['raw_size']:
                    best_table2_tracks[height] = {
                        'quality': f"{resolution_name} (Muted)",
                        'size': format_size(raw_size),
                        'url': f.get('url'),
                        'needs_client_merge': False,
                        'raw_size': raw_size
                    }

        # 4. Populate Table 3 (Audio Only)
        for f in formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                raw_size = f.get('filesize') or f.get('filesize_approx') or 0
                size_str = format_size(raw_size)
                
                ext = f.get('ext', 'mp3').upper()
                abr = f.get('abr')
                bitrate_str = f"{int(abr)}kbps" if abr else "High Quality"
                
                table3.append({
                    'quality': f"{ext} ({bitrate_str})",
                    'size': size_str,
                    'url': f.get('url'),
                    'needs_client_merge': False
                })

        # 5. Populate Table 4 (Visual Assets / Thumbnails) - SPED UP VIA PARALLEL THREADS
        thumbnails = info.get('thumbnails', [])
        valid_thumbs = [t for t in thumbnails if t.get('url') and t.get('width') and t.get('height')]

        # Fetch sizes in parallel instead of one-by-one
        with ThreadPoolExecutor(max_workers=10) as executor:
            sizes = list(executor.map(lambda t: get_remote_file_size(t.get('url')), valid_thumbs))

        for thumb, img_bytes in zip(valid_thumbs, sizes):
            res_str = f"Thumbnail ({thumb.get('width')}x{thumb.get('height')})"
            img_size_str = format_size(img_bytes) if img_bytes else "Unknown Size"
            
            table4.append({
                'quality': res_str,
                'size': img_size_str,
                'url': thumb.get('url'),
                'needs_client_merge': False,
                'is_thumbnail': True
            })

        # Remove duplicate resolutions in Table 4
        unique_table4 = []
        seen_resolutions = set()
        for item in table4:
            if item['quality'] not in seen_resolutions:
                seen_resolutions.add(item['quality'])
                unique_table4.append(item)

        # Convert dictionaries back to lists
        table1 = list(best_table1_tracks.values())
        table2 = list(best_table2_tracks.values())

        # Sort the datasets cleanly
        table1.sort(key=lambda x: int(''.join(filter(str.isdigit, x['quality'])) or 0), reverse=True)
        table2.sort(key=lambda x: int(''.join(filter(str.isdigit, x['quality'])) or 0), reverse=True)
        unique_table4.sort(key=lambda x: int(''.join(filter(str.isdigit, x['quality'].split('x')[0])) or 0), reverse=True)

        # Clean up temporary helper keys
        for item in table1: item.pop('raw_size', None)
        for item in table2: item.pop('raw_size', None)

        # Return payload with video metadata mapped explicitly
        return {
            'metadata': video_metadata,
            'table1': table1,
            'table2': table2,
            'table3': table3,
            'table4': unique_table4
        }

    except Exception as e:
        print(f"Extraction processing error: {str(e)}")
        return None