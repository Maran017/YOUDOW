from flask import Flask, render_template, request, jsonify, Response
from utils import extract_media_info
import requests
import os

app = Flask(__name__)

@app.route('/')
def home():
    """Renders the main production dashboard webpage."""
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract():
    """
    API Endpoint: Receives the URL payload from the front-end,
    passes it to the extraction engine, and returns the sorted tables.
    """
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'No URL provided'}), 400
            
        target_url = data['url'].strip()
        
        # Trigger our extraction logic engine from utils.py
        result_tables = extract_media_info(target_url)
        
        if not result_tables:
            return jsonify({'error': 'Failed to extract media from this URL. Please check the link and try again.'}), 500
            
        # Send the clean 4-table data back to the JavaScript front-end
        return jsonify(result_tables)
        
    except Exception as e:
        print(f"Server Route Error: {str(e)}")
        return jsonify({'error': 'An internal server error occurred.'}), 500

@app.route('/proxy-stream')
def proxy_stream():
    """
    Acts as a lightweight pass-through proxy to eliminate browser CORS limits.
    Streams raw data blocks directly in real-time without writing to host disk storage.
    """
    target_url = request.args.get('url')
    if not target_url:
        return "Missing target stream URL query parameter value", 400

    try:
        # Request stream chunks from the external content hosting node
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        req = requests.get(target_url, stream=True, headers=headers, timeout=15)

        def generate_chunks():
            # Pipe byte blocks directly down the socket pipe in 64KB increments
            for block in req.iter_content(chunk_size=65536):
                if block:
                    yield block

        # Construct streaming wrapper with unrestricted wildcard headers
        stream_response = Response(generate_chunks(), content_type=req.headers.get('Content-Type'))
        stream_response.headers['Access-Control-Allow-Origin'] = '*'
        return stream_response

    except Exception as e:
        print(f"Streaming Proxy Tunnel Error: {str(e)}")
        return f"Failed to pipe asset blocks: {str(e)}", 500

@app.route('/healthz')
def health_check():
    """Simple health check endpoint for cloud platforms to verify server readiness."""
    return jsonify({'status': 'healthy'}), 200

@app.after_request
def add_security_headers(response):
    """
    Injects high-security cross-origin headers required by the browser 
    to spin up the local client-side FFmpeg Web Worker engine sandbox safely.
    """
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
    return response

if __name__ == '__main__':
    # Binds dynamically to the cloud environment's routing port or falls back to 5000 locally
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)