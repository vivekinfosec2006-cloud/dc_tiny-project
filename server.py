"""
================================================================================
DISTRIBUTED FILE SHARING SYSTEM — SERVER & FRONTEND WEB DASHBOARD
================================================================================
MCA 1st Semester Project — Vivek
Dual-Core Architecture:
1. Low-Level TCP Socket Server (Port 8888) -> For client.py CLI socket networking
2. Modern Glassmorphic Web Dashboard (Port 5000) -> For browser access from PC & Mobile
Pure Python Standard Library (socket, http.server, threading, json, struct, hashlib, os)
Zero external dependencies required.
================================================================================
"""
import os
import sys
import json
import time
import struct
import socket
import hashlib
import threading
import urllib.parse
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configuration
SOCKET_PORT = 8888
WEB_PORT = 5000
HOST = "0.0.0.0"
BUFFER_SIZE = 65536  # 64 KB chunks
STORAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage")

os.makedirs(STORAGE_DIR, exist_ok=True)
START_TIME = time.time()


def get_local_ip() -> str:
    """Detects local LAN IP for cross-device sharing on Wi-Fi or Ethernet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def calculate_sha256(filepath: str) -> str:
    """Computes SHA-256 checksum for bit-for-bit file integrity."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_bytes(size: int) -> str:
    """Formats raw bytes into human-readable B, KB, MB, GB."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_file_list() -> list:
    """Scans storage directory and returns list of file metadata objects."""
    files = []
    try:
        for fname in sorted(os.listdir(STORAGE_DIR)):
            fpath = os.path.join(STORAGE_DIR, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                ext = os.path.splitext(fname)[1].lower().replace(".", "") or "file"
                files.append({
                    "name": fname,
                    "size": stat.st_size,
                    "size_formatted": format_bytes(stat.st_size),
                    "ext": ext,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y, %H:%M"),
                    "sha256": calculate_sha256(fpath)
                })
    except Exception as e:
        print(f"[-] Error reading storage files: {e}")
    return files


# ==============================================================================
# 1. TCP SOCKET SERVER (Handles client.py requests)
# ==============================================================================
def send_exact(sock: socket.socket, data: bytes):
    sock.sendall(data)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), BUFFER_SIZE))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_json(sock: socket.socket, header: dict):
    payload = json.dumps(header).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_json(sock: socket.socket) -> dict:
    raw_len = recv_exact(sock, 4)
    if not raw_len:
        return None
    (header_len,) = struct.unpack("!I", raw_len)
    raw_header = recv_exact(sock, header_len)
    if not raw_header:
        return None
    return json.loads(raw_header.decode("utf-8"))


def handle_socket_client(sock: socket.socket, addr: tuple):
    client_ip, client_port = addr
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [+] Socket connection from {client_ip}:{client_port}")

    try:
        while True:
            req = recv_json(sock)
            if not req:
                break

            action = req.get("action", "").upper()

            if action == "PING":
                files = os.listdir(STORAGE_DIR)
                send_json(sock, {
                    "status": "OK",
                    "message": "Distributed File Server is online and active",
                    "file_count": len(files)
                })

            elif action == "LIST":
                files_list = []
                for fname in sorted(os.listdir(STORAGE_DIR)):
                    fpath = os.path.join(STORAGE_DIR, fname)
                    if os.path.isfile(fpath):
                        size = os.path.getsize(fpath)
                        files_list.append({
                            "name": fname,
                            "size": size,
                            "size_kb": round(size / 1024, 2)
                        })
                send_json(sock, {"status": "OK", "files": files_list})

            elif action == "UPLOAD":
                fname = os.path.basename(req.get("filename", "unknown"))
                fsize = req.get("file_size", 0)
                expected_sha = req.get("checksum", "")

                send_json(sock, {"status": "READY"})

                dest_path = os.path.join(STORAGE_DIR, fname)
                hasher = hashlib.sha256()
                bytes_recd = 0

                with open(dest_path, "wb") as f:
                    while bytes_recd < fsize:
                        chunk_to_read = min(fsize - bytes_recd, BUFFER_SIZE)
                        chunk = sock.recv(chunk_to_read)
                        if not chunk:
                            break
                        f.write(chunk)
                        hasher.update(chunk)
                        bytes_recd += len(chunk)

                computed_sha = hasher.hexdigest()
                if computed_sha == expected_sha or not expected_sha:
                    print(f"    -> [SOCKET UPLOAD] '{fname}' ({bytes_recd} bytes) SHA-256: {computed_sha[:10]}...")
                    send_json(sock, {"status": "OK", "message": "Uploaded and verified", "checksum": computed_sha})
                else:
                    print(f"    -> [SOCKET UPLOAD ERROR] Checksum mismatch for '{fname}'!")
                    send_json(sock, {"status": "ERROR", "message": "Checksum verification failed!"})

            elif action == "DOWNLOAD":
                fname = os.path.basename(req.get("filename", ""))
                fpath = os.path.join(STORAGE_DIR, fname)

                if not os.path.isfile(fpath):
                    send_json(sock, {"status": "ERROR", "message": f"File '{fname}' not found."})
                    continue

                fsize = os.path.getsize(fpath)
                sha = calculate_sha256(fpath)

                send_json(sock, {
                    "status": "OK",
                    "filename": fname,
                    "file_size": fsize,
                    "checksum": sha
                })

                client_ack = recv_json(sock)
                if not client_ack or client_ack.get("status") != "READY":
                    continue

                bytes_sent = 0
                with open(fpath, "rb") as f:
                    while chunk := f.read(BUFFER_SIZE):
                        send_exact(sock, chunk)
                        bytes_sent += len(chunk)
                print(f"    -> [SOCKET DOWNLOAD] Sent '{fname}' ({bytes_sent} bytes) to {client_ip}")

            elif action == "DELETE":
                fname = os.path.basename(req.get("filename", ""))
                fpath = os.path.join(STORAGE_DIR, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    print(f"    -> [SOCKET DELETE] Removed '{fname}'")
                    send_json(sock, {"status": "OK", "message": f"File '{fname}' deleted."})
                else:
                    send_json(sock, {"status": "ERROR", "message": "File not found."})
            else:
                send_json(sock, {"status": "ERROR", "message": f"Unknown action '{action}'"})

    except Exception as e:
        print(f"[-] Socket client error: {e}")
    finally:
        sock.close()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [-] Connection closed from {client_ip}:{client_port}")


def run_socket_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, SOCKET_PORT))
    server.listen(25)

    while True:
        try:
            client_sock, addr = server.accept()
            t = threading.Thread(target=handle_socket_client, args=(client_sock, addr), daemon=True)
            t.start()
        except Exception:
            break


# ==============================================================================
# 2. EMBEDDED FRONTEND DASHBOARD HTML, CSS & JAVASCRIPT
# ==============================================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Distributed File Sharing — Web Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-canvas: #060913;
      --bg-surface: #0c1322;
      --bg-card: rgba(15, 23, 42, 0.7);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-glow: rgba(56, 189, 248, 0.35);

      --accent-cyan: #38bdf8;
      --accent-cyan-glow: rgba(56, 189, 248, 0.25);
      --accent-indigo: #818cf8;
      --accent-emerald: #10b981;
      --accent-rose: #f43f5e;
      --accent-amber: #f59e0b;

      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;

      --radius-sm: 8px;
      --radius-md: 14px;
      --radius-lg: 20px;
      --radius-full: 9999px;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      font-family: 'Plus Jakarta Sans', sans-serif;
      background-color: var(--bg-canvas);
      background-image: 
        radial-gradient(circle at 10% 20%, rgba(56, 189, 248, 0.08) 0%, transparent 45%),
        radial-gradient(circle at 90% 80%, rgba(129, 140, 248, 0.08) 0%, transparent 45%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      line-height: 1.5;
    }

    /* Top Navigation Header */
    header {
      position: sticky;
      top: 0;
      z-index: 50;
      background: rgba(6, 9, 19, 0.85);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 0.9rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-icon {
      width: 40px;
      height: 40px;
      border-radius: var(--radius-md);
      background: linear-gradient(135deg, #0284c7, #6366f1);
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 20px;
      box-shadow: 0 0 20px rgba(56, 189, 248, 0.35);
    }

    .brand-text h1 {
      font-size: 1.15rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 40%, #94a3b8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .brand-text p {
      font-size: 0.72rem;
      color: var(--text-dim);
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .status-badge {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 14px;
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: var(--radius-full);
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--accent-emerald);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-emerald);
      box-shadow: 0 0 10px var(--accent-emerald);
      animation: pulse 2s infinite;
    }

    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.8; }
      50% { transform: scale(1.3); opacity: 1; }
      100% { transform: scale(0.95); opacity: 0.8; }
    }

    .btn-copy {
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid var(--border-glow);
      color: var(--accent-cyan);
      padding: 6px 14px;
      border-radius: var(--radius-full);
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    }

    .btn-copy:hover {
      background: rgba(56, 189, 248, 0.22);
      transform: translateY(-1px);
    }

    /* Main Container */
    main {
      max-width: 1200px;
      width: 100%;
      margin: 0 auto;
      padding: 2rem 1.5rem;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 1.8rem;
    }

    /* Metrics Row */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1rem;
    }

    .metric-card {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 1.2rem;
      display: flex;
      align-items: center;
      gap: 14px;
      transition: border-color 0.2s, transform 0.2s;
    }

    .metric-card:hover {
      border-color: var(--border-glow);
      transform: translateY(-2px);
    }

    .metric-icon {
      width: 48px;
      height: 48px;
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
    }

    .icon-files { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); }
    .icon-storage { background: rgba(129, 140, 248, 0.15); color: var(--accent-indigo); }
    .icon-socket { background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); }
    .icon-lan { background: rgba(245, 158, 11, 0.15); color: var(--accent-amber); }

    .metric-info h3 {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
      font-weight: 700;
    }

    .metric-info p {
      font-size: 1.45rem;
      font-weight: 800;
      color: var(--text-main);
      margin-top: 2px;
      letter-spacing: -0.02em;
    }

    /* Drag & Drop Upload Zone */
    .upload-zone {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 2px dashed rgba(56, 189, 248, 0.35);
      border-radius: var(--radius-lg);
      padding: 2.2rem 1.5rem;
      text-align: center;
      cursor: pointer;
      position: relative;
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .upload-zone:hover, .upload-zone.dragover {
      border-color: var(--accent-cyan);
      background: rgba(56, 189, 248, 0.06);
      transform: scale(1.005);
    }

    .upload-icon {
      font-size: 42px;
      margin-bottom: 8px;
      display: inline-block;
      animation: float 3s ease-in-out infinite;
    }

    @keyframes float {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-5px); }
    }

    .upload-zone h2 {
      font-size: 1.15rem;
      font-weight: 700;
      margin-bottom: 4px;
    }

    .upload-zone p {
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    .btn-browse {
      display: inline-block;
      margin-top: 14px;
      background: linear-gradient(135deg, #0284c7, #6366f1);
      color: white;
      font-size: 0.85rem;
      font-weight: 700;
      padding: 8px 22px;
      border-radius: var(--radius-full);
      box-shadow: 0 4px 14px rgba(2, 132, 199, 0.35);
      transition: all 0.2s;
    }

    .btn-browse:hover {
      box-shadow: 0 6px 20px rgba(2, 132, 199, 0.5);
      transform: translateY(-1px);
    }

    /* Upload Progress Overlay */
    .progress-box {
      margin-top: 16px;
      display: none;
      background: rgba(6, 9, 19, 0.9);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 12px 18px;
      text-align: left;
    }

    .progress-header {
      display: flex;
      justify-content: space-between;
      font-size: 0.8rem;
      font-weight: 600;
      margin-bottom: 6px;
    }

    .progress-bar-bg {
      height: 8px;
      background: rgba(255, 255, 255, 0.1);
      border-radius: var(--radius-full);
      overflow: hidden;
    }

    .progress-bar-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #38bdf8, #10b981);
      border-radius: var(--radius-full);
      transition: width 0.15s ease;
    }

    /* Explorer Section */
    .explorer-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
      flex-wrap: wrap;
      gap: 12px;
    }

    .explorer-title {
      font-size: 1.15rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .search-input {
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-full);
      padding: 8px 18px;
      color: var(--text-main);
      font-size: 0.85rem;
      width: 260px;
      outline: none;
      transition: all 0.2s;
    }

    .search-input:focus {
      border-color: var(--accent-cyan);
      box-shadow: 0 0 14px var(--accent-cyan-glow);
    }

    /* Files Table */
    .table-card {
      background: var(--bg-card);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      overflow: hidden;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }

    thead th {
      background: rgba(6, 9, 19, 0.6);
      padding: 12px 18px;
      font-size: 0.72rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-dim);
      border-bottom: 1px solid var(--border-subtle);
    }

    tbody tr {
      border-bottom: 1px solid var(--border-subtle);
      transition: background 0.15s;
    }

    tbody tr:hover {
      background: rgba(56, 189, 248, 0.04);
    }

    tbody td {
      padding: 14px 18px;
      font-size: 0.85rem;
      vertical-align: middle;
    }

    .file-name-cell {
      display: flex;
      align-items: center;
      gap: 12px;
      font-weight: 600;
    }

    .file-badge {
      padding: 4px 8px;
      border-radius: var(--radius-sm);
      font-size: 0.65rem;
      font-weight: 800;
      text-transform: uppercase;
      font-family: 'JetBrains Mono', monospace;
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent-cyan);
    }

    .hash-badge {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.72rem;
      color: var(--text-muted);
      background: rgba(255, 255, 255, 0.04);
      padding: 3px 8px;
      border-radius: 6px;
      cursor: pointer;
      display: inline-block;
      transition: color 0.2s;
    }

    .hash-badge:hover {
      color: var(--accent-cyan);
    }

    .actions-cell {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .btn-action {
      padding: 6px 12px;
      border-radius: var(--radius-sm);
      font-size: 0.75rem;
      font-weight: 700;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 4px;
      text-decoration: none;
      transition: all 0.2s;
    }

    .btn-dl {
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .btn-dl:hover {
      background: var(--accent-emerald);
      color: #060913;
    }

    .btn-del {
      background: rgba(244, 63, 94, 0.12);
      color: var(--accent-rose);
      border: 1px solid rgba(244, 63, 94, 0.25);
    }

    .btn-del:hover {
      background: var(--accent-rose);
      color: white;
    }

    .empty-state {
      padding: 4rem 1rem;
      text-align: center;
      color: var(--text-muted);
    }

    .empty-state p {
      font-size: 0.95rem;
      margin-top: 6px;
    }

    /* Terminal Helper Card */
    .cli-card {
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 1.2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 14px;
    }

    .cli-text h4 {
      font-size: 0.85rem;
      font-weight: 700;
      color: var(--text-main);
    }

    .cli-text p {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 2px;
    }

    .cli-code {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.8rem;
      background: rgba(0, 0, 0, 0.5);
      border: 1px solid var(--border-subtle);
      padding: 6px 14px;
      border-radius: var(--radius-sm);
      color: var(--accent-cyan);
    }

    /* Toast Notification */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: rgba(15, 23, 42, 0.95);
      border: 1px solid var(--border-glow);
      backdrop-filter: blur(16px);
      color: var(--text-main);
      padding: 12px 20px;
      border-radius: var(--radius-md);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
      font-size: 0.85rem;
      font-weight: 600;
      display: none;
      align-items: center;
      gap: 10px;
      z-index: 1000;
      animation: slideIn 0.3s ease;
    }

    @keyframes slideIn {
      from { transform: translateY(20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-icon">⚡</div>
      <div class="brand-text">
        <h1>Distributed File Sharing</h1>
        <p>MCA 1st Semester Project — Vivek</p>
      </div>
    </div>
    <div class="header-actions">
      <div class="status-badge">
        <span class="status-dot"></span>
        Socket Server Online (:8888)
      </div>
      <button class="btn-copy" onclick="copyLanUrl()">
        📋 Copy LAN URL
      </button>
    </div>
  </header>

  <main>
    <!-- Metrics Grid -->
    <div class="metrics-grid">
      <div class="metric-card">
        <div class="metric-icon icon-files">📁</div>
        <div class="metric-info">
          <h3>Total Files</h3>
          <p id="metricFileCount">0</p>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-icon icon-storage">💾</div>
        <div class="metric-info">
          <h3>Storage Used</h3>
          <p id="metricTotalSize">0 B</p>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-icon icon-socket">🔌</div>
        <div class="metric-info">
          <h3>Socket Core Port</h3>
          <p id="metricSocketPort">8888</p>
        </div>
      </div>
      <div class="metric-card">
        <div class="metric-icon icon-lan">🌐</div>
        <div class="metric-info">
          <h3>Host LAN IP</h3>
          <p id="metricLanIp">127.0.0.1</p>
        </div>
      </div>
    </div>

    <!-- Drag & Drop Upload Zone -->
    <div class="upload-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
      <input type="file" id="fileInput" multiple style="display: none;" onchange="handleFileSelect(event)">
      <div class="upload-icon">☁️</div>
      <h2>Drag & Drop Files Here to Share</h2>
      <p>Click to browse from your device or drag files directly onto this card</p>
      <span class="btn-browse">Select Files</span>

      <div class="progress-box" id="progressBox" onclick="event.stopPropagation()">
        <div class="progress-header">
          <span id="progressFilename">Uploading file...</span>
          <span id="progressPercent">0%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" id="progressBar"></div>
        </div>
      </div>
    </div>

    <!-- File Explorer Section -->
    <section>
      <div class="explorer-header">
        <div class="explorer-title">
          <span>📦</span> Shared Files Repository
        </div>
        <input type="text" class="search-input" id="searchInput" placeholder="🔍 Search files..." onkeyup="filterFiles()">
      </div>

      <div class="table-card">
        <table>
          <thead>
            <tr>
              <th>File Name</th>
              <th>Size</th>
              <th>SHA-256 Checksum</th>
              <th>Modified Date</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="filesTableBody">
            <tr>
              <td colspan="5" class="empty-state">
                <div>📂</div>
                <p>Loading files from server...</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Terminal CLI Quick Reference -->
    <div class="cli-card">
      <div class="cli-text">
        <h4>Terminal Socket Client (client.py)</h4>
        <p>You can also access this server from the terminal or another computer over Wi-Fi:</p>
      </div>
      <div class="cli-code" id="cliCommand" onclick="copyCliCommand()" style="cursor: pointer;" title="Click to copy">
        python client.py 127.0.0.1
      </div>
    </div>
  </main>

  <div id="toast">✅ Message</div>

  <script>
    let filesData = [];
    let hostIp = "127.0.0.1";

    function showToast(msg) {
      const toast = document.getElementById('toast');
      toast.textContent = msg;
      toast.style.display = 'flex';
      setTimeout(() => { toast.style.display = 'none'; }, 3000);
    }

    function copyLanUrl() {
      const url = `http://${hostIp}:5000`;
      navigator.clipboard.writeText(url).then(() => {
        showToast(`📋 Copied LAN URL: ${url} (Open on any phone or PC on Wi-Fi)`);
      });
    }

    function copyCliCommand() {
      const cmd = `python client.py ${hostIp}`;
      navigator.clipboard.writeText(cmd).then(() => {
        showToast(`📋 Copied Terminal Command: ${cmd}`);
      });
    }

    function copyHash(hash) {
      navigator.clipboard.writeText(hash).then(() => {
        showToast(`📋 Copied SHA-256 Checksum: ${hash.substring(0, 12)}...`);
      });
    }

    // Fetch Stats & Files
    async function loadStats() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        hostIp = data.server_ip || '127.0.0.1';
        document.getElementById('metricFileCount').textContent = data.file_count;
        document.getElementById('metricTotalSize').textContent = data.total_size_formatted;
        document.getElementById('metricSocketPort').textContent = data.socket_port;
        document.getElementById('metricLanIp').textContent = hostIp;
        document.getElementById('cliCommand').textContent = `python client.py ${hostIp}`;
      } catch (err) {
        console.error('Stats error:', err);
      }
    }

    async function loadFiles() {
      try {
        const res = await fetch('/api/files');
        filesData = await res.json();
        renderFiles(filesData);
        loadStats();
      } catch (err) {
        console.error('Files error:', err);
      }
    }

    function renderFiles(files) {
      const tbody = document.getElementById('filesTableBody');
      if (!files || files.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="5" class="empty-state">
              <div style="font-size: 32px; margin-bottom: 8px;">📂</div>
              <strong>No files shared yet</strong>
              <p>Upload a file using drag & drop above, or via terminal socket client.</p>
            </td>
          </tr>`;
        return;
      }

      tbody.innerHTML = files.map(f => `
        <tr>
          <td>
            <div class="file-name-cell">
              <span class="file-badge">${f.ext}</span>
              <span>${f.name}</span>
            </div>
          </td>
          <td><strong>${f.size_formatted}</strong></td>
          <td>
            <span class="hash-badge" onclick="copyHash('${f.sha256}')" title="Click to copy full SHA-256">
              ${f.sha256.substring(0, 12)}... 📋
            </span>
          </td>
          <td style="color: var(--text-dim);">${f.modified}</td>
          <td>
            <div class="actions-cell">
              <a href="/download/${encodeURIComponent(f.name)}" class="btn-action btn-dl" download>
                ⬇ Download
              </a>
              <button class="btn-action btn-del" onclick="deleteFile('${encodeURIComponent(f.name)}')">
                ✕ Delete
              </button>
            </div>
          </td>
        </tr>
      `).join('');
    }

    function filterFiles() {
      const q = document.getElementById('searchInput').value.toLowerCase();
      const filtered = filesData.filter(f => f.name.toLowerCase().includes(q));
      renderFiles(filtered);
    }

    async function deleteFile(fname) {
      const decoded = decodeURIComponent(fname);
      if (!confirm(`Are you sure you want to delete '${decoded}'?`)) return;

      try {
        const res = await fetch(`/api/delete?file=${encodeURIComponent(decoded)}`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'OK') {
          showToast(`🗑️ File '${decoded}' deleted.`);
          loadFiles();
        } else {
          alert('Delete failed: ' + data.message);
        }
      } catch (err) {
        alert('Delete error: ' + err);
      }
    }

    // Drag and Drop Handling
    const dropZone = document.getElementById('dropZone');

    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('dragover');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length > 0) uploadFiles(files);
    });

    function handleFileSelect(e) {
      const files = e.target.files;
      if (files.length > 0) uploadFiles(files);
    }

    async function uploadFiles(files) {
      const pBox = document.getElementById('progressBox');
      const pName = document.getElementById('progressFilename');
      const pPercent = document.getElementById('progressPercent');
      const pBar = document.getElementById('progressBar');

      pBox.style.display = 'block';

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        pName.textContent = `Uploading: ${file.name} (${i + 1}/${files.length})`;
        pPercent.textContent = '0%';
        pBar.style.width = '0%';

        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('POST', '/api/upload');
          xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));

          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
              const percent = Math.round((e.loaded / e.total) * 100);
              pPercent.textContent = percent + '%';
              pBar.style.width = percent + '%';
            }
          };

          xhr.onload = () => {
            if (xhr.status === 200) {
              resolve();
            } else {
              reject(xhr.responseText);
            }
          };

          xhr.onerror = () => reject('Network error');
          xhr.send(file);
        });
      }

      showToast(`✅ Successfully uploaded ${files.length} file(s)!`);
      setTimeout(() => { pBox.style.display = 'none'; }, 1500);
      loadFiles();
    }

    // Initialize and Auto-refresh every 4 seconds
    loadFiles();
    setInterval(loadFiles, 4000);
  </script>
</body>
</html>
"""


# ==============================================================================
# 3. HTTP WEB DASHBOARD SERVER
# ==============================================================================
class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP polling logs in server console
        pass

    def send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/files":
            files = get_file_list()
            self.send_json_response(files)

        elif path == "/api/stats":
            files = get_file_list()
            total_size = sum(f["size"] for f in files)
            stats = {
                "server_ip": get_local_ip(),
                "socket_port": SOCKET_PORT,
                "web_port": WEB_PORT,
                "file_count": len(files),
                "total_size": total_size,
                "total_size_formatted": format_bytes(total_size),
                "uptime_seconds": int(time.time() - START_TIME)
            }
            self.send_json_response(stats)

        elif path.startswith("/download/"):
            raw_fname = path[len("/download/"):]
            fname = os.path.basename(urllib.parse.unquote(raw_fname))
            fpath = os.path.join(STORAGE_DIR, fname)

            if os.path.isfile(fpath):
                fsize = os.path.getsize(fpath)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(fsize))
                self.end_headers()

                with open(fpath, "rb") as f:
                    while chunk := f.read(BUFFER_SIZE):
                        self.wfile.write(chunk)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB DOWNLOAD] '{fname}' ({fsize} bytes) downloaded via browser.")
            else:
                self.send_error(404, "File Not Found")
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            raw_fname = self.headers.get("X-Filename", "uploaded_file")
            fname = os.path.basename(urllib.parse.unquote(raw_fname))
            content_len = int(self.headers.get("Content-Length", 0))

            dest_path = os.path.join(STORAGE_DIR, fname)
            hasher = hashlib.sha256()
            bytes_recd = 0

            with open(dest_path, "wb") as f:
                while bytes_recd < content_len:
                    to_read = min(content_len - bytes_recd, BUFFER_SIZE)
                    chunk = self.rfile.read(to_read)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    bytes_recd += len(chunk)

            sha = hasher.hexdigest()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB UPLOAD] '{fname}' ({bytes_recd} bytes) uploaded via browser. SHA-256: {sha[:10]}...")
            self.send_json_response({"status": "OK", "filename": fname, "checksum": sha})

        elif path == "/api/delete":
            qs = urllib.parse.parse_qs(parsed.query)
            fname_list = qs.get("file", [])
            if not fname_list:
                self.send_json_response({"status": "ERROR", "message": "Missing file parameter"}, 400)
                return

            fname = os.path.basename(urllib.parse.unquote(fname_list[0]))
            fpath = os.path.join(STORAGE_DIR, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB DELETE] '{fname}' removed via browser.")
                self.send_json_response({"status": "OK", "message": f"File '{fname}' deleted"})
            else:
                self.send_json_response({"status": "ERROR", "message": "File not found"}, 404)
        else:
            self.send_error(404, "Not Found")


def run_http_server():
    httpd = HTTPServer((HOST, WEB_PORT), DashboardHandler)
    httpd.serve_forever()


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main():
    local_ip = get_local_ip()

    print("=" * 70)
    print("      DISTRIBUTED FILE SHARING SYSTEM — DUAL-MODE SERVER")
    print("      MCA 1st Semester Project — Vivek")
    print("=" * 70)
    print(f" [1] TCP Socket Server    : {local_ip}:{SOCKET_PORT} (for client.py)")
    print(f" [2] Local Web Dashboard  : http://127.0.0.1:{WEB_PORT}")
    print(f" [3] Shareable LAN Link   : http://{local_ip}:{WEB_PORT}")
    print(f" [4] Storage Directory    : {STORAGE_DIR}")
    print("=" * 70)
    print(" [*] Socket Server and Frontend Web Dashboard are now LIVE!")
    print(" [*] Open the Web Dashboard in your browser or connect with client.py")
    print("=" * 70 + "\n")

    # Start HTTP Web Dashboard in background daemon thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Run TCP Socket Server on main thread
    try:
        run_socket_server()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown requested. Exiting gracefully...")
        sys.exit(0)


if __name__ == "__main__":
    main()
