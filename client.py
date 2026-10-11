"""
================================================================================
DISTRIBUTED FILE SHARING SYSTEM (TINY PROJECT) - CLIENT
================================================================================
MCA 1st Semester — Vivek
Pure Python Standard Library (socket, json, struct, hashlib, os, sys)
Zero external dependencies required.
================================================================================
"""
import os
import sys
import json
import struct
import socket
import hashlib

DEFAULT_PORT = 8888
BUFFER_SIZE = 65536
DOWNLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def calculate_sha256(filepath: str) -> str:
    """Computes SHA-256 checksum to guarantee bit-for-bit file integrity."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(BUFFER_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()


# ------------------------------------------------------------------------------
# Protocol Framing
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# Client Operations
# ------------------------------------------------------------------------------
class TinyClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"[!] Connection failed to {self.host}:{self.port} -> {e}")
            return False

    def close(self):
        if self.sock:
            self.sock.close()

    def ping(self):
        send_json(self.sock, {"action": "PING"})
        res = recv_json(self.sock)
        if res and res.get("status") == "OK":
            print(f"[*] Server Response: {res.get('message')}")
            print(f"[*] Total files stored on server: {res.get('file_count')}")
        else:
            print(f"[!] Ping failed or invalid response: {res}")

    def list_files(self):
        send_json(self.sock, {"action": "LIST"})
        res = recv_json(self.sock)
        if not res or res.get("status") != "OK":
            print("[!] Could not retrieve file list.")
            return

        files = res.get("files", [])
        if not files:
            print("[*] No files currently stored on server.")
            return

        print("\n" + "=" * 65)
        print(f"{'#':<4} {'Filename':<35} {'Size (Bytes)':<14} {'Size (KB)':<10}")
        print("-" * 65)
        for idx, f in enumerate(files, start=1):
            print(f"{idx:<4} {f['name'][:33]:<35} {f['size']:<14} {f['size_kb']:<10}")
        print("=" * 65 + "\n")

    def upload_file(self, filepath: str):
        if not os.path.isfile(filepath):
            print(f"[!] Local file not found: {filepath}")
            return

        fname = os.path.basename(filepath)
        fsize = os.path.getsize(filepath)
        sha = calculate_sha256(filepath)

        print(f"[*] Preparing upload: '{fname}' ({fsize} bytes)")
        print(f"[*] Pre-computed SHA-256: {sha}")

        # Send UPLOAD request
        send_json(self.sock, {
            "action": "UPLOAD",
            "filename": fname,
            "file_size": fsize,
            "checksum": sha
        })

        ack = recv_json(self.sock)
        if not ack or ack.get("status") != "READY":
            print(f"[!] Server not ready: {ack}")
            return

        # Stream file
        bytes_sent = 0
        with open(filepath, "rb") as f:
            while chunk := f.read(BUFFER_SIZE):
                send_exact(self.sock, chunk)
                bytes_sent += len(chunk)

        result = recv_json(self.sock)
        if result and result.get("status") == "OK":
            print(f"[+] UPLOAD SUCCESSFUL! {result.get('message')}")
            print(f"[+] Server confirmed SHA-256: {result.get('checksum')}")
        else:
            print(f"[!] Upload failed on server: {result}")

    def download_file(self, filename: str):
        send_json(self.sock, {"action": "DOWNLOAD", "filename": filename})
        res = recv_json(self.sock)

        if not res or res.get("status") != "OK":
            print(f"[!] Server error: {res.get('message') if res else 'No response'}")
            return

        fsize = res.get("file_size", 0)
        expected_sha = res.get("checksum", "")
        dest_path = os.path.join(DOWNLOADS_DIR, filename)

        print(f"[*] Starting download: '{filename}' ({fsize} bytes)...")
        send_json(self.sock, {"status": "READY"})

        hasher = hashlib.sha256()
        bytes_recd = 0
        with open(dest_path, "wb") as f:
            while bytes_recd < fsize:
                to_read = min(fsize - bytes_recd, BUFFER_SIZE)
                chunk = self.sock.recv(to_read)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                bytes_recd += len(chunk)

        computed_sha = hasher.hexdigest()
        if computed_sha == expected_sha:
            print(f"[+] DOWNLOAD SUCCESSFUL!")
            print(f"[+] Saved to: {dest_path}")
            print(f"[+] Bit-for-bit SHA-256 Verified: {computed_sha}")
        else:
            print(f"[!] CHECKSUM CORRUPTION DETECTED!")
            print(f"    Expected: {expected_sha}")
            print(f"    Computed: {computed_sha}")

    def delete_file(self, filename: str):
        send_json(self.sock, {"action": "DELETE", "filename": filename})
        res = recv_json(self.sock)
        if res and res.get("status") == "OK":
            print(f"[+] {res.get('message')}")
        else:
            print(f"[!] Delete failed: {res.get('message') if res else 'Unknown error'}")


def interactive_menu(server_ip: str, port: int):
    client = TinyClient(server_ip, port)
    if not client.connect():
        return

    print("=" * 65)
    print("      DISTRIBUTED FILE SHARING SYSTEM (TINY CLIENT)")
    print(f"      Connected to: {server_ip}:{port}")
    print("=" * 65)

    try:
        while True:
            print("\n---------------- MENU ----------------")
            print(" [1] List Files on Server")
            print(" [2] Upload File to Server")
            print(" [3] Download File from Server")
            print(" [4] Delete File from Server")
            print(" [5] Check Server Status (Ping)")
            print(" [6] Exit")
            print("--------------------------------------")
            try:
                choice = input("Enter choice (1-6): ").strip()
            except KeyboardInterrupt:
                print("\n[*] Exiting client. Goodbye!")
                break

            if choice == "1":
                client.list_files()
            elif choice == "2":
                path = input("Enter file path or filename to upload (e.g. README.md): ").strip()
                path = path.strip('"').strip("'")
                if not path:
                    continue
                client.upload_file(path)
            elif choice == "3":
                fname = input("Enter filename on server to download: ").strip()
                if fname:
                    client.download_file(fname)
            elif choice == "4":
                fname = input("Enter filename on server to delete: ").strip()
                if fname:
                    client.delete_file(fname)
            elif choice == "5":
                client.ping()
            elif choice == "6":
                print("[*] Disconnecting from server. Goodbye!")
                break
            else:
                print("[!] Invalid option. Please enter 1 to 6.")
    finally:
        client.close()


if __name__ == "__main__":
    target_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    target_port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
    interactive_menu(target_ip, target_port)
