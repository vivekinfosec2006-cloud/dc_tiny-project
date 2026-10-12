"""
================================================================================
DISTRIBUTED FILE SHARING SYSTEM — OPTIMIZED SERVER
================================================================================
MCA 1st Semester Project — Vivek
Dual Architecture in Pure Python Standard Library:
1. Multi-Threaded TCP Socket Server (Port 8888) -> For client.py CLI socket networking
2. Lightweight HTTP Web Server (Port 5000)       -> Serves index.html & REST API
Zero external pip dependencies required.
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

# Network & Storage Configuration
SOCKET_PORT = 8888
WEB_PORT = 5000
HOST = "0.0.0.0"
BUFFER_SIZE = 65536  # 64 KB streaming chunks
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
INDEX_HTML_PATH = os.path.join(BASE_DIR, "index.html")

os.makedirs(STORAGE_DIR, exist_ok=True)
START_TIME = time.time()


def get_local_ip() -> str:
    """Finds local LAN IP for sharing files across devices on Wi-Fi or Ethernet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def calculate_sha256(filepath: str) -> str:
    """Computes SHA-256 checksum to guarantee bit-for-bit file integrity."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


def format_bytes(size: int) -> str:
    """Converts raw byte count into human-readable B, KB, MB, GB."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_file_list() -> list:
    """Scans the storage directory and returns list of file metadata objects."""
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
                    "ext": ext.upper(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y, %H:%M"),
                    "sha256": calculate_sha256(fpath)
                })
    except Exception as e:
        print(f"[-] Error reading storage folder: {e}")
    return files


# ==============================================================================
# 1. LOW-LEVEL TCP SOCKET SERVER (Handles client.py)
# ==============================================================================
def send_exact(sock: socket.socket, data: bytes):
    """Ensures all bytes in buffer are flushed across the TCP socket."""
    sock.sendall(data)


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Reads exactly n bytes or returns None if connection is broken."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(min(n - len(buf), BUFFER_SIZE))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_json(sock: socket.socket, header: dict):
    """Packs header as [4-byte Big-Endian Length Prefix] + [JSON bytes]."""
    payload = json.dumps(header).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_json(sock: socket.socket) -> dict:
    """Unpacks length prefix then decodes JSON header."""
    raw_len = recv_exact(sock, 4)
    if not raw_len:
        return None
    (header_len,) = struct.unpack("!I", raw_len)
    raw_header = recv_exact(sock, header_len)
    if not raw_header:
        return None
    return json.loads(raw_header.decode("utf-8"))


def handle_socket_client(sock: socket.socket, addr: tuple):
    """Worker thread per connected TCP socket client."""
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
                    print(f"    -> [SOCKET UPLOAD] '{fname}' ({bytes_recd} bytes) SHA-256 match: {computed_sha[:10]}...")
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
# 2. HTTP SERVER (Serves index.html and REST API on Port 5000)
# ==============================================================================
class WebDashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress noisy HTTP polling in console
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

        if path in ["/", "/index.html"]:
            if os.path.isfile(INDEX_HTML_PATH):
                with open(INDEX_HTML_PATH, "rb") as f:
                    body = f.read()
            else:
                body = b"<h1>Distributed File Sharing Dashboard</h1><p>index.html not found.</p>"

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
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB DOWNLOAD] '{fname}' ({fsize} bytes) downloaded.")
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
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB UPLOAD] '{fname}' ({bytes_recd} bytes). SHA-256: {sha[:10]}...")
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
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [WEB DELETE] Removed '{fname}'")
                self.send_json_response({"status": "OK", "message": f"File '{fname}' deleted"})
            else:
                self.send_json_response({"status": "ERROR", "message": "File not found"}, 404)
        else:
            self.send_error(404, "Not Found")


def run_http_server():
    httpd = HTTPServer((HOST, WEB_PORT), WebDashboardHandler)
    httpd.serve_forever()


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main():
    local_ip = get_local_ip()

    print("=" * 68)
    print("      DISTRIBUTED FILE SHARING SYSTEM — DUAL-CORE SERVER")
    print("      MCA 1st Semester Project — Vivek")
    print("=" * 68)
    print(f" [*] TCP Socket Core : {local_ip}:{SOCKET_PORT} (for client.py)")
    print(f" [*] Web Dashboard   : http://127.0.0.1:{WEB_PORT}")
    print(f" [*] LAN Wi-Fi Link  : http://{local_ip}:{WEB_PORT}")
    print(f" [*] Storage Folder  : {STORAGE_DIR}")
    print("=" * 68)
    print(" [*] Server is active! Press Ctrl+C to stop.")
    print("=" * 68 + "\n")

    # Start HTTP server in background thread
    threading.Thread(target=run_http_server, daemon=True).start()

    # Run Socket server on main thread
    try:
        run_socket_server()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown gracefully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
