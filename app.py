import flask
from flask import Flask, request, send_file, render_template_string, jsonify, url_for, Response
import yt_dlp
import os
import re
import time
import threading
import shutil
import tempfile
import logging
from urllib.parse import urlparse, unquote
from functools import wraps
import atexit
import io
import mimetypes
from werkzeug.utils import secure_filename
import traceback

# --- Importaciones opcionales ---
try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, TIT2, TPE1
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    print("Mutagen no disponible - metadatos MP3 deshabilitados")

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False
    print("QRCode no disponible - códigos QR deshabilitados")

try:
    import requests as req
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Requests no disponible - descargas de miniaturas deshabilitadas")

# --- Configuración de la Aplicación ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
BASE_URL = os.environ.get('BASE_URL', None)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Gestión de Archivos y Limpieza ---
DOWNLOAD_FOLDER = os.path.abspath('downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def cleanup_old_files():
    """Limpia archivos antiguos cada 30 minutos"""
    try:
        current_time = time.time()
        for filename in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, filename)
            if os.path.exists(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > 3600:  # 1 hora
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        logger.info(f"Archivo antiguo eliminado: {filename}")
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
    except Exception as e:
        logger.error(f"Error en limpieza: {e}")

def start_cleanup_scheduler():
    def cleanup_loop():
        while True:
            time.sleep(1800)  # 30 minutos
            cleanup_old_files()
    
    threading.Thread(target=cleanup_loop, daemon=True).start()
    logger.info("Scheduler de limpieza iniciado")

# --- Utilidades ---
def rate_limit(max_requests=10, window=60):
    def decorator(f):
        requests_data = {}
        @wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            current_time = time.time()
            
            if client_ip not in requests_data:
                requests_data[client_ip] = []
            
            requests_data[client_ip] = [
                t for t in requests_data[client_ip] 
                if current_time - t < window
            ]
            
            if len(requests_data[client_ip]) >= max_requests:
                return jsonify({'error': 'Demasiadas peticiones. Intenta más tarde.'}), 429
            
            requests_data[client_ip].append(current_time)
            return f(*args, **kwargs)
        return wrapper
    return decorator

def sanitize_filename(filename, max_length=100):
    """Sanitiza nombres de archivo para evitar problemas"""
    if not filename:
        return f"download_{int(time.time())}"
    
    filename = unquote(filename)
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', '_', filename)
    filename = filename.strip('._')
    
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length-len(ext)] + ext
    
    return filename or f"download_{int(time.time())}"

def embed_mp3_metadata(mp3_path, title, artist, thumbnail_url=None):
    """Incrusta metadatos en archivos MP3"""
    if not MUTAGEN_AVAILABLE:
        return
    
    try:
        audio = MP3(mp3_path, ID3=ID3)
        
        if title:
            audio.tags.add(TIT2(encoding=3, text=title))
        if artist:
            audio.tags.add(TPE1(encoding=3, text=artist))
        
        if thumbnail_url and REQUESTS_AVAILABLE:
            try:
                response = req.get(thumbnail_url, timeout=10)
                if response.status_code == 200:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=response.content
                    ))
            except Exception as e:
                logger.warning(f"No se pudo descargar miniatura: {e}")
        
        audio.save()
        logger.info(f"Metadatos agregados a {os.path.basename(mp3_path)}")
        
    except Exception as e:
        logger.error(f"Error agregando metadatos: {e}")

# --- HTML Template Moderno y Mejorado ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VideoTube Downloader</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
            min-height: 100vh;
            color: #ffffff;
            overflow-x: hidden;
        }

        .background-animation {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            z-index: -1;
            opacity: 0.1;
        }

        .floating-shapes {
            position: absolute;
            width: 100%;
            height: 100%;
        }

        .shape {
            position: absolute;
            background: linear-gradient(45deg, #ff6b6b, #4ecdc4);
            border-radius: 50%;
            animation: float 6s ease-in-out infinite;
        }

        .shape:nth-child(1) {
            width: 80px;
            height: 80px;
            top: 20%;
            left: 10%;
            animation-delay: 0s;
        }

        .shape:nth-child(2) {
            width: 120px;
            height: 120px;
            top: 60%;
            right: 10%;
            animation-delay: 2s;
        }

        .shape:nth-child(3) {
            width: 60px;
            height: 60px;
            bottom: 20%;
            left: 20%;
            animation-delay: 4s;
        }

        @keyframes float {
            0%, 100% { transform: translateY(0px) rotate(0deg); }
            50% { transform: translateY(-20px) rotate(10deg); }
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 1;
        }

        .header {
            text-align: center;
            margin-bottom: 40px;
            padding: 40px 0;
        }

        .header h1 {
            font-size: 3.5rem;
            font-weight: 800;
            background: linear-gradient(135deg, #ff6b6b, #4ecdc4, #45b7d1);
            background-size: 200% 200%;
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            animation: gradient 3s ease infinite;
            margin-bottom: 15px;
        }

        .header p {
            font-size: 1.2rem;
            color: #a0a0a0;
            font-weight: 300;
        }

        @keyframes gradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        .card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(20px) saturate(180%);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 24px;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            transition: all 0.3s ease;
        }

        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
            border-color: rgba(255, 255, 255, 0.2);
        }

        .input-group {
            margin-bottom: 25px;
        }

        .input-group label {
            display: block;
            margin-bottom: 12px;
            font-weight: 600;
            color: #ffffff;
            font-size: 1.1rem;
        }

        input[type="url"], select {
            width: 100%;
            padding: 18px 24px;
            background: rgba(255, 255, 255, 0.08);
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            color: #ffffff;
            font-size: 16px;
            transition: all 0.3s ease;
            backdrop-filter: blur(10px);
        }

        input[type="url"]:focus, select:focus {
            outline: none;
            border-color: #4ecdc4;
            background: rgba(255, 255, 255, 0.12);
            box-shadow: 0 0 0 4px rgba(78, 205, 196, 0.1);
        }

        input[type="url"]::placeholder {
            color: #a0a0a0;
        }

        button {
            width: 100%;
            padding: 18px 24px;
            background: linear-gradient(135deg, #ff6b6b, #4ecdc4);
            color: white;
            border: none;
            border-radius: 16px;
            cursor: pointer;
            font-weight: 700;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }

        button::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s;
        }

        button:hover:not(:disabled)::before {
            left: 100%;
        }

        button:hover:not(:disabled) {
            transform: translateY(-3px);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.3);
        }

        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }

        .progress-container {
            margin: 30px 0;
            display: none;
        }

        .progress-bar {
            width: 100%;
            height: 12px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 15px;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #ff6b6b, #4ecdc4);
            width: 0%;
            transition: width 0.3s ease;
            border-radius: 8px;
        }

        .progress-text {
            text-align: center;
            color: #a0a0a0;
            font-weight: 500;
        }

        .video-info {
            display: none;
            margin-top: 30px;
            animation: fadeInUp 0.5s ease;
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .video-details {
            display: flex;
            align-items: flex-start;
            margin-bottom: 25px;
            gap: 25px;
        }

        .thumbnail {
            width: 200px;
            height: 150px;
            object-fit: cover;
            border-radius: 16px;
            flex-shrink: 0;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }

        .info {
            flex: 1;
        }

        .info h3 {
            margin-bottom: 15px;
            color: #ffffff;
            line-height: 1.4;
            font-size: 1.3rem;
            font-weight: 700;
        }

        .info p {
            margin-bottom: 8px;
            color: #a0a0a0;
            font-size: 0.95rem;
        }

        .info p strong {
            color: #ffffff;
        }

        .format-section {
            margin: 25px 0;
        }

        .format-section h4 {
            margin-bottom: 15px;
            color: #ffffff;
            font-size: 1.1rem;
            font-weight: 600;
        }

        .checkbox-group {
            margin: 20px 0;
        }

        .checkbox-group label {
            display: flex;
            align-items: center;
            font-weight: normal;
            cursor: pointer;
            color: #ffffff;
            transition: color 0.3s ease;
        }

        .checkbox-group label:hover {
            color: #4ecdc4;
        }

        .checkbox-group input[type="checkbox"] {
            width: 20px;
            height: 20px;
            margin-right: 12px;
            accent-color: #4ecdc4;
        }

        .result {
            margin-top: 25px;
            padding: 25px;
            border-radius: 16px;
            display: none;
            animation: fadeInUp 0.5s ease;
        }

        .result.success {
            background: rgba(76, 175, 80, 0.1);
            color: #4caf50;
            border: 1px solid rgba(76, 175, 80, 0.3);
        }

        .result.error {
            background: rgba(244, 67, 54, 0.1);
            color: #f44336;
            border: 1px solid rgba(244, 67, 54, 0.3);
        }

        .result.info {
            background: rgba(33, 150, 243, 0.1);
            color: #2196f3;
            border: 1px solid rgba(33, 150, 243, 0.3);
        }

        .download-buttons {
            margin-top: 20px;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }

        .download-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 14px 24px;
            background: linear-gradient(135deg, #4caf50, #45a049);
            color: white;
            text-decoration: none;
            border-radius: 12px;
            font-weight: 600;
            transition: all 0.3s ease;
            font-size: 14px;
        }

        .download-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
        }

        .qr-btn {
            background: linear-gradient(135deg, #2196f3, #1976d2);
        }

        .qr-container {
            text-align: center;
            margin-top: 25px;
            padding: 25px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 16px;
        }

        .qr-container img {
            max-width: 200px;
            border: 2px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            margin-top: 15px;
        }

        .history {
            max-height: 400px;
            overflow-y: auto;
        }

        .history::-webkit-scrollbar {
            width: 8px;
        }

        .history::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.05);
            border-radius: 4px;
        }

        .history::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.2);
            border-radius: 4px;
        }

        .history-item {
            padding: 20px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.3s ease;
        }

        .history-item:hover {
            background: rgba(255, 255, 255, 0.02);
        }

        .history-item:last-child {
            border-bottom: none;
        }

        .loading {
            display: inline-block;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .emoji {
            font-size: 1.2em;
            margin-right: 8px;
        }

        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }

            .card {
                padding: 25px;
            }

            .header h1 {
                font-size: 2.5rem;
            }

            .video-details {
                flex-direction: column;
            }

            .thumbnail {
                width: 100%;
                height: 200px;
            }

            .download-buttons {
                flex-direction: column;
            }

            .download-btn {
                justify-content: center;
            }

            .history-item {
                flex-direction: column;
                align-items: flex-start;
                gap: 15px;
            }
        }

        .supported-sites {
            margin-top: 30px;
            text-align: center;
        }

        .supported-sites h4 {
            color: #ffffff;
            margin-bottom: 15px;
            font-size: 1.1rem;
        }

        .sites-list {
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 15px;
        }

        .site-badge {
            padding: 8px 16px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            color: #a0a0a0;
            font-size: 0.9rem;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
    </style>
</head>
<body>
    <div class="background-animation">
        <div class="floating-shapes">
            <div class="shape"></div>
            <div class="shape"></div>
            <div class="shape"></div>
        </div>
    </div>

    <div class="container">
        <div class="header">
            <h1><span class="emoji">🎬</span>VideoTube Downloader</h1>
            <p>Descarga videos y audio en alta calidad de YouTube y más plataformas</p>
        </div>

        <div class="card">
            <form id="urlForm">
                <div class="input-group">
                    <label for="urlInput"><span class="emoji">🔗</span>URL del Video:</label>
                    <input type="url" id="urlInput" placeholder="https://www.youtube.com/watch?v=..." required>
                </div>
                <button type="submit" id="searchBtn">
                    <span id="searchIcon" class="emoji">🔍</span> Analizar Video
                </button>
            </form>

            <div class="progress-container" id="progressContainer">
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                <p class="progress-text" id="progressText">Procesando...</p>
            </div>

            <div class="video-info" id="videoInfo">
                <div class="video-details" id="videoDetails"></div>
                
                <div class="format-section">
                    <h4><span class="emoji">⚙️</span>Formato de descarga:</h4>
                    <select id="formatSelect">
                        <option value="best_video"><span class="emoji">📹</span> Mejor Calidad Video (MP4)</option>
                        <option value="best_audio"><span class="emoji">🎵</span> Solo Audio (MP3)</option>
                    </select>
                </div>

                <div class="checkbox-group">
                    <label>
                        <input type="checkbox" id="downloadSubs">
                        <span class="emoji">📝</span> Descargar subtítulos (si están disponibles)
                    </label>
                </div>

                <button type="button" id="downloadBtn">
                    <span id="downloadIcon" class="emoji">📥</span> Descargar Ahora
                </button>
            </div>

            <div class="result" id="result"></div>
        </div>

        <div class="card">
            <h3><span class="emoji">📚</span>Historial de Descargas</h3>
            <div class="history" id="history">
                <div class="history-item">
                    <div style="text-align: center; color: #a0a0a0; padding: 40px;">
                        <span class="emoji" style="font-size: 2rem;">📭</span>
                        <p>No hay descargas recientes</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="card supported-sites">
            <h4><span class="emoji">🌐</span>Plataformas Soportadas</h4>
            <div class="sites-list">
                <div class="site-badge">YouTube</div>
                <div class="site-badge">Vimeo</div>
                <div class="site-badge">Facebook</div>
                <div class="site-badge">Instagram</div>
                <div class="site-badge">TikTok</div>
                <div class="site-badge">Twitter</div>
                <div class="site-badge">Twitch</div>
                <div class="site-badge">+1000 más</div>
            </div>
        </div>
    </div>

    <script>
        let currentVideoInfo = null;

        // Elementos del DOM
        const urlForm = document.getElementById('urlForm');
        const urlInput = document.getElementById('urlInput');
        const searchBtn = document.getElementById('searchBtn');
        const searchIcon = document.getElementById('searchIcon');
        const progressContainer = document.getElementById('progressContainer');
        const progressFill = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const videoInfo = document.getElementById('videoInfo');
        const videoDetails = document.getElementById('videoDetails');
        const formatSelect = document.getElementById('formatSelect');
        const downloadSubs = document.getElementById('downloadSubs');
        const downloadBtn = document.getElementById('downloadBtn');
        const downloadIcon = document.getElementById('downloadIcon');
        const result = document.getElementById('result');
        const history = document.getElementById('history');

        // Event listeners
        urlForm.addEventListener('submit', handleSearch);
        downloadBtn.addEventListener('click', handleDownload);

        function showProgress(show = true, text = 'Procesando...') {
            progressContainer.style.display = show ? 'block' : 'none';
            progressText.textContent = text;
            if (!show) {
                progressFill.style.width = '0%';
            }
        }

        function updateProgress(percent) {
            progressFill.style.width = Math.min(percent, 100) + '%';
        }

        function showResult(message, type = 'info', data = null) {
            result.className = `result ${type}`;
            result.style.display = 'block';
            
            let html = `<p>${message}</p>`;
            
            if (data && data.download_url) {
                html += `
                    <div class="download-buttons">
                        <a href="${data.download_url}" class="download-btn" download>
                            <span class="emoji">📥</span> Descargar Archivo
                        </a>`;
                
                if (data.qr_url) {
                    html += `
                        <a href="${data.qr_url}" class="download-btn qr-btn" target="_blank">
                            <span class="emoji">📱</span> Código QR
                        </a>`;
                }
                
                html += `</div>`;
                
                if (data.qr_url) {
                    html += `
                        <div class="qr-container">
                            <p><strong>Escanea para descargar en móvil:</strong></p>
                            <img src="${data.qr_url}" alt="Código QR" loading="lazy">
                        </div>`;
                }
                
                addToHistory(data);
            }
            
            result.innerHTML = html;
        }

        function addToHistory(data) {
            const emptyMessage = history.querySelector('.history-item div[style*="text-align: center"]');
            if (emptyMessage) {
                history.innerHTML = '';
            }
            
            const historyItem = document.createElement('div');
            historyItem.className = 'history-item';
            historyItem.innerHTML = `
                <div>
                    <strong style="color: #ffffff;">${new Date().toLocaleString()}</strong><br>
                    <small style="color: #a0a0a0;">${data.filename || 'Archivo descargado'}</small>
                </div>
                <a href="${data.download_url}" class="download-btn" download>
                    <span class="emoji">📥</span> Descargar
                </a>
            `;
            
            history.insertBefore(historyItem, history.firstChild);
            
            // Limitar historial a 10 elementos
            while (history.children.length > 10) {
                history.removeChild(history.lastChild);
            }
        }

        async function handleSearch(e) {
            e.preventDefault();
            
            const url = urlInput.value.trim();
            if (!url) {
                showResult('❌ Por favor, ingresa una URL válida.', 'error');
                return;
            }

            // Reset UI
            videoInfo.style.display = 'none';
            result.style.display = 'none';
            
            // Disable form
            searchBtn.disabled = true;
            searchIcon.innerHTML = '<span class="loading">⏳</span>';
            
            showProgress(true, 'Obteniendo información del video...');
            updateProgress(25);

            try {
                const response = await fetch('/info', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });

                updateProgress(75);
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Error desconocido');
                }

                currentVideoInfo = data;
                displayVideoInfo(data);
                updateProgress(100);
                
                setTimeout(() => showProgress(false), 500);

            } catch (error) {
                console.error('Error:', error);
                showResult(`❌ ${error.message}`, 'error');
                showProgress(false);
            } finally {
                searchBtn.disabled = false;
                searchIcon.innerHTML = '🔍';
            }
        }

        function displayVideoInfo(info) {
            if (info.is_playlist) {
                videoDetails.innerHTML = `
                    <div class="info">
                        <h3><span class="emoji">📂</span> Lista de Reproducción Detectada</h3>
                        <p><strong>Título:</strong> ${info.title || 'Sin título'}</p>
                        <p><strong>Videos:</strong> ${info.video_count || 'Desconocido'}</p>
                        <p><em>Se descargará el primer video de la lista.</em></p>
                    </div>
                `;
            } else {
                let detailsHtml = '';
                
                if (info.thumbnail) {
                    detailsHtml += `<img src="${info.thumbnail}" alt="Miniatura" class="thumbnail">`;
                }
                
                detailsHtml += `
                    <div class="info">
                        <h3>${info.title || 'Sin título'}</h3>
                        <p><strong>Canal:</strong> ${info.uploader || 'Desconocido'}</p>
                        <p><strong>Duración:</strong> ${formatDuration(info.duration)}</p>
                        <p><strong>Vistas:</strong> ${info.view_count ? info.view_count.toLocaleString() : 'N/A'}</p>
                `;
                
                if (info.upload_date) {
                    const date = new Date(info.upload_date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'));
                    detailsHtml += `<p><strong>Subido:</strong> ${date.toLocaleDateString()}</p>`;
                }
                
                detailsHtml += '</div>';
                videoDetails.innerHTML = detailsHtml;
                
                // Actualizar opciones de formato
                updateFormatOptions(info.formats);
            }
            
            videoInfo.style.display = 'block';
        }

        function updateFormatOptions(formats) {
            // Limpiar opciones existentes excepto las básicas
            formatSelect.innerHTML = `
                <option value="best_video">📹 Mejor Calidad Video (MP4)</option>
                <option value="best_audio">🎵 Solo Audio (MP3)</option>
            `;
            
            if (formats && formats.video) {
                formats.video.forEach(format => {
                    const option = document.createElement('option');
                    option.value = format.id;
                    option.textContent = `📹 ${format.label} (${format.vcodec || 'video'})`;
                    formatSelect.appendChild(option);
                });
            }
        }

        function formatDuration(seconds) {
            if (!seconds) return 'N/A';
            
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            
            if (hours > 0) {
                return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
            }
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }

        async function handleDownload() {
            if (!currentVideoInfo) {
                showResult('❌ Primero debes buscar un video.', 'error');
                return;
            }

            const url = urlInput.value.trim();
            const format = formatSelect.value;
            const includeSubs = downloadSubs.checked;

            // Disable download button
            downloadBtn.disabled = true;
            downloadIcon.innerHTML = '<span class="loading">⏳</span>';
            
            showProgress(true, 'Iniciando descarga...');
            updateProgress(10);
            showResult('⏳ Descargando archivo, por favor espera...', 'info');

            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        url: url,
                        format_id: format,
                        download_subs: includeSubs
                    })
                });

                updateProgress(90);
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Error en la descarga');
                }

                updateProgress(100);
                showResult(`✅ ${data.message}`, 'success', data);

            } catch (error) {
                console.error('Download error:', error);
                showResult(`❌ Error en la descarga: ${error.message}`, 'error');
            } finally {
                downloadBtn.disabled = false;
                downloadIcon.innerHTML = '📥';
                setTimeout(() => showProgress(false), 1000);
            }
        }

        // Auto-focus en el campo URL
        urlInput.focus();

        // Detectar URLs pegadas automáticamente
        urlInput.addEventListener('paste', (e) => {
            setTimeout(() => {
                const url = urlInput.value.trim();
                if (url && (url.includes('youtube.com') || url.includes('youtu.be') || url.includes('vimeo.com'))) {
                    searchBtn.click();
                }
            }, 100);
        });
    </script>
</body>
</html>
'''

# --- Rutas principales con mejoras ---
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/info', methods=['POST'])
@rate_limit(max_requests=15, window=120)
def get_video_info():
    try:
        data = request.get_json()
        if not data or not data.get('url'):
            return jsonify({'error': 'URL no proporcionada'}), 400

        url = data['url'].strip()
        logger.info(f"Obteniendo info para: {url}")

        # Configuración mejorada de yt-dlp
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 3,
            'ignoreerrors': False
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                logger.error(f"Error extrayendo info: {e}")
                if "Video unavailable" in str(e):
                    return jsonify({'error': 'Video no disponible o privado'}), 400
                elif "Unsupported URL" in str(e):
                    return jsonify({'error': 'URL no soportada. Verifica que sea una URL válida de video.'}), 400
                else:
                    return jsonify({'error': f'Error obteniendo información: {str(e)}'}), 500

        if not info:
            return jsonify({'error': 'No se pudo obtener información del video'}), 400

        # Verificar si es playlist
        if info.get('_type') == 'playlist':
            return jsonify({
                'is_playlist': True,
                'title': info.get('title', 'Playlist sin título'),
                'video_count': info.get('playlist_count', len(info.get('entries', []))),
                'webpage_url': info.get('webpage_url', url)
            })

        # Procesar formatos de video
        video_formats = []
        if info.get('formats'):
            seen_heights = set()
            for fmt in info['formats']:
                if (fmt.get('vcodec') != 'none' and 
                    fmt.get('height') and 
                    fmt.get('height') not in seen_heights and
                    fmt.get('height') >= 144):
                    
                    video_formats.append({
                        'id': fmt['format_id'],
                        'label': f"{fmt['height']}p",
                        'height': fmt['height'],
                        'vcodec': fmt.get('vcodec', 'unknown'),
                        'filesize': fmt.get('filesize') or fmt.get('filesize_approx')
                    })
                    seen_heights.add(fmt['height'])
            
            # Ordenar por calidad (mayor a menor)
            video_formats.sort(key=lambda x: x['height'], reverse=True)

        response_data = {
            'is_playlist': False,
            'title': info.get('title', 'Video sin título'),
            'uploader': info.get('uploader', 'Canal desconocido'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'view_count': info.get('view_count'),
            'upload_date': info.get('upload_date'),
            'webpage_url': info.get('webpage_url', url),
            'formats': {'video': video_formats},
            'subtitles': list(info.get('subtitles', {}).keys()) if info.get('subtitles') else []
        }

        return jsonify(response_data)

    except Exception as e:
        logger.exception(f"Error obteniendo info de video: {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

def progress_hook(d):
    """Hook mejorado para monitorear progreso de yt-dlp"""
    if d['status'] == 'downloading':
        if d.get('_percent_str'):
            logger.info(f"Descarga: {d['_percent_str']} - {d.get('_speed_str', 'N/A')}")
    elif d['status'] == 'finished':
        logger.info(f"Descarga completada: {d.get('filename', 'archivo')}")
    elif d['status'] == 'error':
        logger.error("Error en descarga de yt-dlp")

@app.route('/download', methods=['POST'])
@rate_limit(max_requests=3, window=300)
def download_video():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Datos no proporcionados'}), 400

        url = data.get('url', '').strip()
        format_id = data.get('format_id', 'best_video')
        download_subs = data.get('download_subs', False)

        if not url:
            return jsonify({'error': 'URL no proporcionada'}), 400

        logger.info(f"Iniciando descarga: {url} - Formato: {format_id}")

        # Crear directorio único para esta descarga
        unique_id = f"{int(time.time())}_{os.urandom(3).hex()}"
        temp_dir = os.path.join(DOWNLOAD_FOLDER, f"temp_{unique_id}")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            # Obtener información básica del video
            logger.info("Obteniendo información del video...")
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'error': 'No se pudo obtener información del video'}), 400

            # Sanitizar nombre del archivo
            title = sanitize_filename(info.get('title', 'video'))
            logger.info(f"Título sanitizado: {title}")
            
            # Configuración mejorada de descarga
            ydl_opts = {
                'outtmpl': os.path.join(temp_dir, f'{title}.%(ext)s'),
                'quiet': False,
                'no_warnings': False,
                'progress_hooks': [progress_hook],
                'noplaylist': True,
                'extract_flat': False,
                'ignoreerrors': False,
                'retries': 3,
                'fragment_retries': 3,
                'skip_unavailable_fragments': True,
                'keepvideo': False,
                'embed_info_json': False,
                'writeinfojson': False,
                'socket_timeout': 30,
            }

            # Configurar formato según selección con fallbacks mejorados
            if format_id == 'best_video':
                ydl_opts['format'] = 'best[height<=1080][ext=mp4]/best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'
            elif format_id == 'best_audio':
                ydl_opts.update({
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                        'nopostoverwrites': False
                    }]
                })
            else:
                ydl_opts['format'] = f"{format_id}+bestaudio/best"

            # Configurar subtítulos si se solicitan
            if download_subs:
                ydl_opts.update({
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'subtitleslangs': ['es', 'en', 'es-419', 'en-US'],
                    'subtitlesformat': 'srt/vtt/best'
                })

            logger.info("Iniciando descarga...")

            # Realizar descarga con manejo de errores mejorado
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    ydl.download([url])
                    logger.info("Descarga de yt-dlp completada")
                except Exception as download_error:
                    logger.error(f"Error en descarga de yt-dlp: {download_error}")
                    error_msg = str(download_error)
                    if "Video unavailable" in error_msg:
                        raise Exception("Video no disponible o privado")
                    elif "format not available" in error_msg:
                        raise Exception("Formato de video no disponible")
                    elif "HTTP Error 403" in error_msg:
                        raise Exception("Acceso denegado al video")
                    else:
                        raise Exception(f"Error en descarga: {error_msg}")

            # Esperar un momento para que se complete la escritura
            time.sleep(1)
            
            # Verificar archivos descargados
            logger.info(f"Verificando archivos en: {temp_dir}")
            if not os.path.exists(temp_dir):
                raise Exception("El directorio de descarga no existe")
                
            all_files = os.listdir(temp_dir)
            logger.info(f"Archivos encontrados: {all_files}")
            
            downloaded_files = []
            for file in all_files:
                if not file.endswith(('.part', '.tmp', '.ytdl')) and not file.startswith('.'):
                    file_path = os.path.join(temp_dir, file)
                    if os.path.isfile(file_path):
                        file_size = os.path.getsize(file_path)
                        logger.info(f"Archivo: {file} ({file_size:,} bytes)")
                        if file_size > 0:
                            downloaded_files.append(file)

            if not downloaded_files:
                raise Exception("La descarga no produjo archivos válidos")

            logger.info(f"Archivos válidos: {downloaded_files}")

            # Encontrar archivo principal
            main_file = None
            priority_extensions = ['.mp4', '.mp3', '.webm', '.mkv', '.m4a', '.avi']
            
            for ext in priority_extensions:
                for file in downloaded_files:
                    if file.endswith(ext):
                        main_file = file
                        break
                if main_file:
                    break

            if not main_file:
                main_file = max(downloaded_files, key=lambda f: os.path.getsize(os.path.join(temp_dir, f)))
                
            logger.info(f"Archivo principal: {main_file}")

            # Mover archivos al directorio de descargas
            final_files = []
            for file in downloaded_files:
                src_path = os.path.join(temp_dir, file)
                base_name, ext = os.path.splitext(file)
                base_name = re.sub(r'[^\w\-_\.\s]', '', base_name)
                unique_name = f"{base_name}_{unique_id}{ext}"
                dst_path = os.path.join(DOWNLOAD_FOLDER, unique_name)
                
                src_size = os.path.getsize(src_path)
                if src_size == 0:
                    continue
                
                try:
                    shutil.move(src_path, dst_path)
                    dst_size = os.path.getsize(dst_path)
                    
                    if dst_size == src_size:
                        final_files.append(unique_name)
                        logger.info(f"Transferido: {file} -> {unique_name}")
                    else:
                        os.remove(dst_path)
                        logger.error(f"Error en transferencia: {file}")
                        
                except Exception as move_error:
                    logger.error(f"Error moviendo {file}: {move_error}")

            # Limpiar directorio temporal
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass

            if not final_files:
                raise Exception("No se pudieron transferir archivos válidos")

            # Actualizar nombre del archivo principal
            main_file_final = None
            original_main = main_file
            
            for file in final_files:
                if original_main in file or file.endswith(os.path.splitext(original_main)[1]):
                    main_file_final = file
                    break
            
            if not main_file_final:
                main_file_final = final_files[0]

            # Agregar metadatos a MP3
            if main_file_final.endswith('.mp3'):
                mp3_path = os.path.join(DOWNLOAD_FOLDER, main_file_final)
                embed_mp3_metadata(
                    mp3_path, 
                    info.get('title'), 
                    info.get('uploader'), 
                    info.get('thumbnail')
                )

            # Preparar respuesta
            final_filename = main_file_final
            message = f"Descarga completada: {final_filename}"
            
            # Si hay múltiples archivos, crear ZIP
            if len(final_files) > 1:
                zip_name = f"{title}_{unique_id}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_name)
                
                try:
                    import zipfile
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for file in final_files:
                            file_path = os.path.join(DOWNLOAD_FOLDER, file)
                            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                                original_name = file.replace(f"_{unique_id}", "")
                                zipf.write(file_path, original_name)
                    
                    if os.path.exists(zip_path) and os.path.getsize(zip_path) > 0:
                        for file in final_files:
                            try:
                                os.remove(os.path.join(DOWNLOAD_FOLDER, file))
                            except:
                                pass
                        
                        final_filename = zip_name
                        message = f"Paquete creado: {zip_name}"
                        
                except Exception as e:
                    logger.error(f"Error creando ZIP: {e}")

            # Generar URLs
            base_url = BASE_URL or request.host_url.rstrip('/')
            download_url = f"{base_url}/serve/{final_filename}"
            qr_url = f"{base_url}/qr/{final_filename}" if QR_AVAILABLE else None

            # Verificar archivo final
            final_path = os.path.join(DOWNLOAD_FOLDER, final_filename)
            if not os.path.exists(final_path) or os.path.getsize(final_path) == 0:
                raise Exception("El archivo final no es válido")
            
            final_size = os.path.getsize(final_path)
            logger.info(f"Descarga exitosa: {final_filename} ({final_size:,} bytes)")

            return jsonify({
                'message': message,
                'download_url': download_url,
                'qr_url': qr_url,
                'filename': final_filename,
                'filesize': final_size
            })

        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise e

    except Exception as e:
        logger.exception(f"Error en descarga: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/serve/<path:filename>')
def serve_file(filename):
    """Servir archivos para descarga con manejo robusto"""
    try:
        safe_filename = secure_filename(filename)
        if not safe_filename:
            return "Nombre de archivo inválido", 400
            
        file_path = os.path.join(DOWNLOAD_FOLDER, safe_filename)
        
        if not os.path.exists(file_path):
            return "Archivo no encontrado", 404
        
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            return "Archivo vacío", 500
        
        logger.info(f"Sirviendo: {safe_filename} ({file_size:,} bytes)")
        
        # Detectar tipo MIME
        if safe_filename.endswith('.mp4'):
            mimetype = 'video/mp4'
        elif safe_filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif safe_filename.endswith('.zip'):
            mimetype = 'application/zip'
        elif safe_filename.endswith('.webm'):
            mimetype = 'video/webm'
        else:
            mimetype = 'application/octet-stream'
        
        return send_file(
            file_path,
            mimetype=mimetype,
            as_attachment=True,
            download_name=safe_filename
        )
        
    except Exception as e:
        logger.exception(f"Error sirviendo archivo {filename}: {e}")
        return f"Error del servidor: {str(e)}", 500

@app.route('/qr/<path:filename>')
def generate_qr(filename):
    """Generar código QR para descarga móvil"""
    if not QR_AVAILABLE:
        return jsonify({'error': 'Códigos QR no disponibles'}), 503
    
    try:
        safe_filename = secure_filename(filename)
        
        if not os.path.exists(os.path.join(DOWNLOAD_FOLDER, safe_filename)):
            return jsonify({'error': 'Archivo no encontrado'}), 404
        
        base_url = BASE_URL or request.host_url.rstrip('/')
        download_url = f"{base_url}/serve/{safe_filename}"
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(download_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='image/png',
            as_attachment=False,
            download_name=f'qr_{safe_filename}.png'
        )
        
    except Exception as e:
        logger.exception(f"Error generando QR para {filename}")
        return jsonify({'error': 'Error generando código QR'}), 500

@app.errorhandler(500)
def internal_error(error):
    logger.exception("Error interno del servidor")
    return jsonify({'error': 'Error interno del servidor'}), 500

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({'error': 'Archivo demasiado grande'}), 413

# --- Punto de entrada ---
if __name__ == '__main__':
    logger.info("Iniciando VideoTube Downloader...")
    
    # Verificar dependencias
    logger.info(f"Mutagen: {MUTAGEN_AVAILABLE}")
    logger.info(f"QRCode: {QR_AVAILABLE}")
    logger.info(f"Requests: {REQUESTS_AVAILABLE}")
    
    os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
    start_cleanup_scheduler()
    cleanup_old_files()
    
    logger.info("Servidor iniciado en http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)