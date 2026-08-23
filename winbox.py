#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WINBOX MANAGER - Web Interface for VM Management
Tông màu: Xanh dương (#2196F3) + Trắng
Chức năng: Tạo VM, quản lý VM, Chợ VPS, cài Tailscale, quản lý User & Số dư (VNĐ) & Cấu hình / OS,
Quản lý Giftcode / Random Keys, Nạp tiền tự động Sepay / VietQR, Quản lý Bảng tin chính,
Thuê VPS theo giờ/ngày/tháng, Khóa/mở logs VM, Thư mục User & VM riêng biệt.
"""

import os
import sys
import json
import time
import uuid
import hashlib
import secrets
import subprocess
import threading
import re
import platform
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# ==================== FLASK IMPORTS ====================
try:
    from flask import Flask, render_template_string, request, jsonify, redirect, session, flash
except ImportError:
    print("[ERROR] Flask chưa được cài đặt. Đang tiến hành cài đặt...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "-q"], check=True)
    from flask import Flask, render_template_string, request, jsonify, redirect, session, flash

try:
    import requests
except ImportError:
    print("[ERROR] requests chưa được cài đặt. Đang tiến hành cài đặt...")
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"], check=True)
    import requests

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ==================== DATA STORAGE ====================
DATA_DIR = Path.home() / ".winbox_manager"
DATA_DIR.mkdir(exist_ok=True)

USERS_DIR = DATA_DIR / "users"
USERS_DIR.mkdir(exist_ok=True)

NODES_FILE = DATA_DIR / "nodes.json"
WORKER_PORT = 5001

CONFIGS_FILE = DATA_DIR / "configs.json"
OS_IMAGES_FILE = DATA_DIR / "os_images.json"
KEYS_FILE = DATA_DIR / "keys.json"
ANNOUNCEMENT_FILE = DATA_DIR / "announcement.json"
MARKETPLACE_FILE = DATA_DIR / "marketplace_vms.json"
DEPOSITS_FILE = DATA_DIR / "deposits.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

# ==================== HELPERS ====================
def load_json(filepath, default=None):
    if default is None:
        default = {}
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_dir(user_id):
    d = USERS_DIR / str(user_id)
    d.mkdir(exist_ok=True)
    return d

def get_user_vm_dir(user_id, vm_id):
    d = get_user_dir(user_id) / "vms" / str(vm_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_user_profile(user_id):
    f = get_user_dir(user_id) / "profile.json"
    return load_json(f)

def save_user_profile(user_id, data):
    f = get_user_dir(user_id) / "profile.json"
    save_json(f, data)

def get_user_deposits(user_id):
    f = get_user_dir(user_id) / "deposits.json"
    return load_json(f, [])

def save_user_deposits(user_id, data):
    f = get_user_dir(user_id) / "deposits.json"
    save_json(f, data)

def get_user_vms(user_id):
    vm_dir = get_user_dir(user_id) / "vms"
    vms = {}
    if vm_dir.exists():
        for vm_subdir in vm_dir.iterdir():
            if vm_subdir.is_dir():
                vm_json = vm_subdir / "vm.json"
                if vm_json.exists():
                    try:
                        vms[vm_subdir.name] = load_json(vm_json)
                    except Exception:
                        pass
    return vms

def get_vm_data(user_id, vm_id):
    f = get_user_vm_dir(user_id, vm_id) / "vm.json"
    return load_json(f)

def save_vm_data(user_id, vm_id, data):
    f = get_user_vm_dir(user_id, vm_id) / "vm.json"
    save_json(f, data)

def get_vm_log_path(user_id, vm_id):
    return get_user_vm_dir(user_id, vm_id) / "logs.txt"

# ==================== NODE / WORKER HELPERS ====================
def get_worker_token():
    token_file = DATA_DIR / "worker_token.json"
    if token_file.exists():
        return load_json(token_file).get("token", "")
    token = secrets.token_hex(32)
    save_json(token_file, {"token": token})
    return token

def get_nodes():
    defaults = {
        "local": {
            "name": "🖥️ Server Local (Master)",
            "tunnel_url": "",
            "host": "127.0.0.1",
            "port": WORKER_PORT,
            "type": "local",
            "enabled": True,
            "token": ""
        }
    }
    nodes = load_json(NODES_FILE)
    for k, v in defaults.items():
        if k not in nodes:
            nodes[k] = v
    return nodes

def save_nodes(data):
    save_json(NODES_FILE, data)

def _get_node_url(node):
    """Lấy URL để gọi worker — ưu tiên tunnel_url, fallback host:port"""
    tunnel = node.get("tunnel_url", "").strip()
    if tunnel:
        return tunnel.rstrip("/")
    host = node.get("host", "127.0.0.1")
    port = node.get("port", WORKER_PORT)
    return f"http://{host}:{port}"

def worker_request(node, endpoint, method="POST", data=None, timeout=30):
    base_url = _get_node_url(node)
    url = f"{base_url}{endpoint}"
    headers = {"X-Worker-Token": node.get("token", "")}
    try:
        if method == "POST":
            r = requests.post(url, data=data, headers=headers, timeout=timeout)
        else:
            r = requests.get(url, headers=headers, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"success": False, "error": f"Không kết nối được worker: {e}"}

def get_node_status(node):
    base_url = _get_node_url(node)
    try:
        r = requests.get(
            f"{base_url}/worker/status",
            headers={"X-Worker-Token": node.get("token", "")},
            timeout=5
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"success": False, "online": False}

def append_vm_log(user_id, vm_id, text):
    log_path = get_vm_log_path(user_id, vm_id)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")

def get_vm_logs(user_id, vm_id):
    log_path = get_vm_log_path(user_id, vm_id)
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            return f.read()
    return "Chưa có log."

# ==================== SYSTEM SETTINGS ====================
def get_settings():
    defaults = {
        "site_name": "WinBox VPS",
        "primary_color": "#2196F3",
        "allow_registration": True,
        "default_logs_locked": True,
        "maintenance_mode": False,
        "marketplace_cleanup_minutes": 2
    }
    s = load_json(SETTINGS_FILE)
    for k, v in defaults.items():
        if k not in s:
            s[k] = v
    return s

def save_settings(data):
    save_json(SETTINGS_FILE, data)

# ==================== CONFIGS & OS DATA ====================
DEFAULT_VM_CONFIGS = {
    "basic": {"name": "Basic", "cpu": 1, "ram": 1, "disk": 15, "price_minutely": 200, "price_hourly": 5000, "price_daily": 35000, "price_weekly": 200000, "price_monthly": 100000},
    "standard": {"name": "Standard", "cpu": 2, "ram": 4, "disk": 60, "price_minutely": 500, "price_hourly": 15000, "price_daily": 100000, "price_weekly": 600000, "price_monthly": 300000},
    "pro": {"name": "Pro", "cpu": 4, "ram": 8, "disk": 120, "price_minutely": 1000, "price_hourly": 30000, "price_daily": 200000, "price_weekly": 1200000, "price_monthly": 600000},
    "enterprise": {"name": "Enterprise", "cpu": 8, "ram": 16, "disk": 250, "price_minutely": 2000, "price_hourly": 60000, "price_daily": 400000, "price_weekly": 2400000, "price_monthly": 1200000},
    "ultra": {"name": "Ultra", "cpu": 16, "ram": 32, "disk": 500, "price_minutely": 4000, "price_hourly": 120000, "price_daily": 800000, "price_weekly": 4800000, "price_monthly": 2400000},
    "super": {"name": "Super", "cpu": 32, "ram": 64, "disk": 1000, "price_minutely": 8000, "price_hourly": 240000, "price_daily": 1600000, "price_weekly": 9600000, "price_monthly": 4800000},
    "mega": {"name": "Mega", "cpu": 64, "ram": 128, "disk": 2000, "price_minutely": 16000, "price_hourly": 480000, "price_daily": 3200000, "price_weekly": 19200000, "price_monthly": 9600000},
}

DEFAULT_WINDOWS_IMAGES = {
    "win2012": {"name": "Windows Server 2012 R2", "url": "https://archive.org/download/tamnguyen-2012r2/2012.img", "user": "administrator", "pass": "Tamnguyenyt@123"},
    "win2022": {"name": "Windows Server 2022", "url": "https://archive.org/download/tamnguyen-2022/2022.img", "user": "administrator", "pass": "Tamnguyenyt@123"},
    "win11": {"name": "Windows 11 LTSB", "url": "https://archive.org/download/win_20260203/win.img", "user": "Admin", "pass": "Tam255Z"},
    "win10ltsb": {"name": "Windows 10 LTSB 2015", "url": "https://archive.org/download/win_20260208/win.img", "user": "Admin", "pass": "Tam255Z"},
    "win10ltsc": {"name": "Windows 10 LTSC 2023", "url": "https://archive.org/download/win_20260215/win.img", "user": "Admin", "pass": "Tam255Z"},
    "win10ltsb2022": {"name": "Windows 10 LTSB 2022", "url": "https://archive.org/download/win_20260717/win.img", "user": "Admin", "pass": "Tam255Z"},
}

DEFAULT_ANNOUNCEMENT = {
    "title": "Chào mừng đến với Hệ thống WinBox Cloud VPS",
    "content": "Hệ thống cung cấp dịch vụ máy ảo Windows QEMU/KVM tốc độ cao, hỗ trợ kết nối RDP qua Tailscale VPN an toàn. Vui lòng nạp tiền hoặc sử dụng Giftcode để trải nghiệm dịch vụ!",
    "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M")
}

def get_vm_configs():
    configs = load_json(CONFIGS_FILE)
    if not configs:
        configs = DEFAULT_VM_CONFIGS
        save_json(CONFIGS_FILE, configs)
    # backward compat: đảm bảo mỗi config có đủ 5 giá
    for k, cfg in configs.items():
        for price_key in ("price_minutely", "price_hourly", "price_daily", "price_weekly", "price_monthly"):
            if price_key not in cfg:
                cfg[price_key] = 0
    return configs

def get_windows_images():
    images = load_json(OS_IMAGES_FILE)
    if not images:
        images = DEFAULT_WINDOWS_IMAGES
        save_json(OS_IMAGES_FILE, images)
    return images

def get_announcement():
    anc = load_json(ANNOUNCEMENT_FILE)
    if not anc:
        anc = DEFAULT_ANNOUNCEMENT
        save_json(ANNOUNCEMENT_FILE, anc)
    return anc

# ==================== USER MANAGEMENT ====================
def load_all_users():
    users = {}
    if USERS_DIR.exists():
        for user_dir in USERS_DIR.iterdir():
            if user_dir.is_dir():
                profile = get_user_profile(user_dir.name)
                if profile and profile.get("id"):
                    users[profile["id"]] = profile
    return users

def save_user(user_id, data):
    save_user_profile(user_id, data)

def find_user_by_username(username):
    users = load_all_users()
    for uid, u in users.items():
        if u.get("username", "").lower() == username.lower():
            return u
    return None

def init_default_admin():
    users = load_all_users()
    admin_exists = False
    for uid, user in users.items():
        if user.get("username") == "admin":
            user["password"] = hash_password("Tam255Z")
            user["role"] = "admin"
            if "balance" not in user or user["balance"] < 100000:
                user["balance"] = 99999999.0
            if "created_at" not in user or not user["created_at"]:
                user["created_at"] = datetime.now().isoformat()
            save_user(uid, user)
            admin_exists = True
            break
    if not admin_exists:
        uid = str(uuid.uuid4())
        user_data = {
            "id": uid,
            "username": "admin",
            "email": "admin@winbox.local",
            "password": hash_password("Tam255Z"),
            "role": "admin",
            "balance": 99999999.0,
            "created_at": datetime.now().isoformat(),
        }
        save_user(uid, user_data)

# ==================== AUTH HELPERS ====================
def is_logged_in():
    return session.get("user_id") is not None

def get_current_user():
    uid = session.get("user_id")
    if uid:
        user = get_user_profile(uid)
        if user:
            if "balance" not in user:
                user["balance"] = 0.0
            if "role" not in user:
                user["role"] = "user"
            return user
    return None

def is_admin():
    user = get_current_user()
    return user is not None and user.get("role") == "admin"

# ==================== TAILSCALE INSTALLER ====================
TAILSCALE_SCRIPT = """#!/bin/bash
set -e
TAILSCALE_KEY="$1"
if [ -z "$TAILSCALE_KEY" ]; then
    echo "Lỗi: Chưa nhập Auth Key Tailscale."
    exit 1
fi
echo "Đang tiến hành cài đặt Tailscale..."
pkill -f tailscaled 2>/dev/null || true
rm -f "$HOME/tailscaled.sock"
sleep 1
cd "$HOME" || exit 1
if [ ! -f "tailscale.tgz" ]; then
    echo "Đang tải xuống Tailscale Binary..."
    curl -L https://pkgs.tailscale.com/stable/tailscale_1.64.0_amd64.tgz -o tailscale.tgz
fi
tar xzf tailscale.tgz
cd tailscale_* || exit 1
RANDOM_PORT=$(shuf -i 2000-65000 -n 1)
echo "Khởi chạy Tailscale Daemon..."
nohup ./tailscaled --tun=userspace-networking --socks5-server=localhost:$RANDOM_PORT --socket="$HOME/tailscaled.sock" > /dev/null 2>&1 &
sleep 3
echo "Đang kết nối mạng..."
./tailscale --socket="$HOME/tailscaled.sock" up --authkey="$TAILSCALE_KEY" --reset
if [ $? -eq 0 ]; then
    echo "Kết nối mạng Tailscale thành công!"
    IP=$(./tailscale --socket="$HOME/tailscaled.sock" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('TailscaleIPs',[''])[0])" 2>/dev/null || echo "")
    if [ -n "$IP" ]; then
        echo "Địa chỉ Tailscale IP: $IP"
    fi
    ./tailscale --socket="$HOME/tailscaled.sock" status
else
    echo "Thất bại, vui lòng kiểm tra lại Key."
    exit 1
fi
"""

# ==================== QEMU HELPERS ====================
active_vms = {}
vm_lock = threading.Lock()

def find_and_kill_qemu_for_vm(vm_dir):
    vm_dir_str = str(vm_dir)
    patterns = [f"qemu.*{re.escape(vm_dir_str)}", f"qemu.*{re.escape(vm_dir.name)}"]
    killed_any = False
    for pat in patterns:
        try:
            subprocess.run(["pkill", "-9", "-f", pat], capture_output=True, text=True)
            killed_any = True
        except Exception:
            pass
    # Kill generic qemu processes as requested
    try:
        subprocess.run(["pkill", "-9", "qemu"], capture_output=True, text=True)
        killed_any = True
    except Exception:
        pass
    try:
        subprocess.run(["sudo", "pkill", "-9", "qemu"], capture_output=True, text=True)
        killed_any = True
    except Exception:
        pass
    return killed_any

def _check_qemu_running(vm_dir):
    """Kiểm tra xem còn process QEMU nào liên quan đến vm_dir không."""
    vm_dir_str = str(vm_dir)
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"qemu.*{re.escape(vm_dir_str)}"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            return True
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"qemu.*{re.escape(vm_dir.name)}"],
            capture_output=True, text=True
        )
        if result.stdout.strip():
            return True
    except Exception:
        pass
    try:
        result = subprocess.run(["pgrep", "qemu"], capture_output=True, text=True)
        if result.stdout.strip():
            return True
    except Exception:
        pass
    return False

def _stop_vm_logged(user_id, vm_id, vm_dir):
    """Dừng VM với pkill, check, fallback kill -9, log đầy đủ."""
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[STOP] BẮT ĐẦU DỪNG VM")
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[STOP] STEP 1: Gửi lệnh pkill qemu và sudo pkill qemu...")

    try:
        subprocess.run(["pkill", "qemu"], capture_output=True, text=True)
        append_vm_log(user_id, vm_id, "[STOP] Đã gửi: pkill qemu")
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[STOP] Lỗi pkill qemu: {e}")
    try:
        subprocess.run(["sudo", "pkill", "qemu"], capture_output=True, text=True)
        append_vm_log(user_id, vm_id, "[STOP] Đã gửi: sudo pkill qemu")
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[STOP] Lỗi sudo pkill qemu: {e}")

    append_vm_log(user_id, vm_id, "[STOP] Đang chờ 2 giây để QEMU tắt...")
    time.sleep(2)

    if _check_qemu_running(vm_dir):
        append_vm_log(user_id, vm_id, "[STOP] CẢNH BÁO: QEMU vẫn còn chạy! Dùng pkill -9...")
        try:
            subprocess.run(["pkill", "-9", "qemu"], capture_output=True, text=True)
            append_vm_log(user_id, vm_id, "[STOP] Đã gửi: pkill -9 qemu")
        except Exception as e:
            append_vm_log(user_id, vm_id, f"[STOP] Lỗi pkill -9 qemu: {e}")
        try:
            subprocess.run(["sudo", "pkill", "-9", "qemu"], capture_output=True, text=True)
            append_vm_log(user_id, vm_id, "[STOP] Đã gửi: sudo pkill -9 qemu")
        except Exception as e:
            append_vm_log(user_id, vm_id, f"[STOP] Lỗi sudo pkill -9 qemu: {e}")

        append_vm_log(user_id, vm_id, "[STOP] Đang chờ thêm 2 giây...")
        time.sleep(2)

        if _check_qemu_running(vm_dir):
            append_vm_log(user_id, vm_id, "[STOP] CẢNH BÁO: QEMU vẫn còn! Thử kill trực tiếp bằng PID...")
            try:
                result = subprocess.run(["pgrep", "-f", f"qemu.*{re.escape(str(vm_dir))}"],
                                        capture_output=True, text=True)
                for pid in result.stdout.strip().split("\n"):
                    if pid.strip():
                        try:
                            subprocess.run(["kill", "-9", pid.strip()], capture_output=True, text=True)
                            append_vm_log(user_id, vm_id, f"[STOP] Đã kill -9 PID {pid.strip()}")
                        except Exception as ke:
                            append_vm_log(user_id, vm_id, f"[STOP] Lỗi kill -9 PID {pid.strip()}: {ke}")
            except Exception as e:
                append_vm_log(user_id, vm_id, f"[STOP] Lỗi lấy PID: {e}")

            time.sleep(1)
            if _check_qemu_running(vm_dir):
                append_vm_log(user_id, vm_id, "[STOP] KHÔNG THỂ TẮT QEMU! Có thể cần reboot server.")
            else:
                append_vm_log(user_id, vm_id, "[STOP] QEMU đã tắt sau kill -9 trực tiếp.")
        else:
            append_vm_log(user_id, vm_id, "[STOP] QEMU đã tắt sau pkill -9.")
    else:
        append_vm_log(user_id, vm_id, "[STOP] QEMU đã tắt thành công sau pkill.")

    with vm_lock:
        if vm_id in active_vms and active_vms[vm_id].get("process"):
            try:
                active_vms[vm_id]["process"].terminate()
                active_vms[vm_id]["process"].wait(timeout=3)
            except Exception:
                try:
                    active_vms[vm_id]["process"].kill()
                except Exception:
                    pass
        if vm_id in active_vms:
            active_vms[vm_id]["status"] = "stopped"
    append_vm_log(user_id, vm_id, "[STOP] Đã cập nhật trạng thái VM thành STOPPED.")
    append_vm_log(user_id, vm_id, "==========================================================")

def _delete_vm_logged(user_id, vm_id, vm_dir, windows_key="win11"):
    """Xóa VM: chạy script với option 3, sau đó xóa thư mục, log đầy đủ."""
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[DELETE] BẮT ĐẦU XÓA VM")
    append_vm_log(user_id, vm_id, "==========================================================")

    append_vm_log(user_id, vm_id, "[DELETE] STEP 1: TẢI WINBOX SCRIPT ĐỂ XÓA VM")
    script_url = "https://raw.githubusercontent.com/thanhtrung-devVNG/demo_web/refs/heads/main/winbox.sh"
    script_path = vm_dir / "win.sh"
    try:
        download_proc = subprocess.run(
            ["wget", "-O", str(script_path), script_url],
            capture_output=True, text=True, timeout=120
        )
        if download_proc.returncode != 0 and not script_path.exists():
            download_proc = subprocess.run(
                ["curl", "-fsSL", "-o", str(script_path), script_url],
                capture_output=True, text=True, timeout=120
            )
        if script_path.exists() and script_path.stat().st_size > 1000:
            os.chmod(script_path, 0o755)
            append_vm_log(user_id, vm_id, f"[DELETE] Đã tải win.sh ({script_path.stat().st_size} bytes)")
        else:
            append_vm_log(user_id, vm_id, "[DELETE] Không tải được win.sh, bỏ qua bước chạy script xóa.")
            script_path = None
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[DELETE] Lỗi tải script: {e}")
        script_path = None

    if script_path and script_path.exists():
        append_vm_log(user_id, vm_id, "[DELETE] STEP 2: CHẠY SCRIPT VỚI OPTION 3 (XÓA SẠCH VM)")
        try:
            env = os.environ.copy()
            env["HOME"] = str(vm_dir)
            env["USER"] = "winbox"
            env["LOGNAME"] = "winbox"
            proc = subprocess.Popen(
                ["bash", str(script_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(vm_dir),
                env=env
            )
            proc.stdin.write("3\n")
            proc.stdin.flush()
            proc.stdin.close()
            for line in proc.stdout:
                line_str = line.strip()
                append_vm_log(user_id, vm_id, f"[DELETE-SCRIPT] {line_str}")
            proc.wait()
            append_vm_log(user_id, vm_id, "[DELETE] Script xóa VM đã chạy xong.")
        except Exception as e:
            append_vm_log(user_id, vm_id, f"[DELETE] Lỗi chạy script xóa: {e}")

    append_vm_log(user_id, vm_id, "[DELETE] STEP 3: DỪNG QEMU NẾU CÒN CHẠY")
    _stop_vm_logged(user_id, vm_id, vm_dir)

    append_vm_log(user_id, vm_id, "[DELETE] STEP 4: XÓA THƯ MỤC VM")
    try:
        with vm_lock:
            active_vms.pop(vm_id, None)
        if vm_dir.exists():
            shutil.rmtree(vm_dir, ignore_errors=True)
        append_vm_log(user_id, vm_id, "[DELETE] Đã xóa toàn bộ dữ liệu VM.")
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[DELETE] Lỗi xóa thư mục: {e}")

    append_vm_log(user_id, vm_id, "[DELETE] QUÁ TRÌNH XÓA VM HOÀN TẤT.")
    append_vm_log(user_id, vm_id, "==========================================================")

def _tailscale_worker(user_id, vm_id, tailscale_key, vm_dir):
    """Chạy tailscale trong thread riêng, parse IP và cập nhật ngay lập tức."""
    if not tailscale_key:
        append_vm_log(user_id, vm_id, "[TAILSCALE] Không có Auth Key, bỏ qua.")
        return
    ts_script = vm_dir / "install_tailscale.sh"
    with open(ts_script, "w", encoding="utf-8") as f:
        f.write(TAILSCALE_SCRIPT)
    os.chmod(ts_script, 0o755)
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[TAILSCALE] Đang khởi động Tailscale song song với QEMU...")
    append_vm_log(user_id, vm_id, "==========================================================")
    try:
        ts_process = subprocess.Popen(
            ["bash", str(ts_script), tailscale_key],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(vm_dir)
        )
        for line in ts_process.stdout:
            line_str = line.strip()
            append_vm_log(user_id, vm_id, f"[TAILSCALE] {line_str}")
            ip_match = re.search(r'Tailscale IP: ([0-9.]+)', line_str)
            if ip_match:
                ts_ip = ip_match.group(1)
                with vm_lock:
                    if vm_id in active_vms:
                        active_vms[vm_id]["tailscale_ip"] = ts_ip
                vm_data = get_vm_data(user_id, vm_id)
                if vm_data:
                    vm_data["tailscale_ip"] = ts_ip
                    save_vm_data(user_id, vm_id, vm_data)
                    append_vm_log(user_id, vm_id, f"[TAILSCALE] IP đã cập nhật: {ts_ip}")
        ts_process.wait()
        append_vm_log(user_id, vm_id, "[TAILSCALE] Tiến trình Tailscale đã kết thúc.")
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[TAILSCALE] Lỗi cài đặt Tailscale: {e}")


def start_vm_existing(user_id, vm_id, config, vm_dir, vm_name, windows_key, tailscale_key):
    """
    Khởi động lại VM bằng cách tải lại script win.sh và chạy lại.
    Giống như tạo VM mới, nhưng KHÔNG resize disk.
    """
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[START] BẮT ĐẦU KHỞI ĐỘNG LẠI VM")
    append_vm_log(user_id, vm_id, "==========================================================")
    append_vm_log(user_id, vm_id, "[START] STEP 1: TẢI LẠI WINBOX SCRIPT")

    script_url = "https://raw.githubusercontent.com/thanhtrung-devVNG/demo_web/refs/heads/main/winbox.sh"
    script_path = vm_dir / "win.sh"
    try:
        download_proc = subprocess.run(
            ["wget", "-O", str(script_path), script_url],
            capture_output=True, text=True, timeout=120
        )
        if download_proc.returncode != 0 and not script_path.exists():
            download_proc = subprocess.run(
                ["curl", "-fsSL", "-o", str(script_path), script_url],
                capture_output=True, text=True, timeout=120
            )
        if script_path.exists() and script_path.stat().st_size > 1000:
            os.chmod(script_path, 0o755)
            append_vm_log(user_id, vm_id, f"[START] Đã tải lại win.sh ({script_path.stat().st_size} bytes)")
        else:
            append_vm_log(user_id, vm_id, "[START] CẢNH BÁO: Không tải được win.sh, thử dùng script cũ...")
            old_script = vm_dir / "win.sh"
            if not old_script.exists():
                old_script = vm_dir / "win.sh"
            if old_script.exists():
                script_path = old_script
            else:
                return False, "Không tìm thấy script nào để khởi động lại VM."
    except Exception as e:
        append_vm_log(user_id, vm_id, f"[START] Lỗi tải script: {e}")
        return False, f"Lỗi tải script: {e}"

    append_vm_log(user_id, vm_id, "[START] STEP 2: CHUẨN BỊ THAM SỐ TỰ ĐỘNG CHO SCRIPT")
    WIN_FLAG_MAP = {
        "win2012": "--win2012",
        "win2022": "--win2022",
        "win11": "--win11",
        "win10ltsb": "--win10ltsb",
        "win10ltsc": "--win10ltsc",
        "win10ltsb2022": "--win10ltsb2022",
    }
    win_flag = WIN_FLAG_MAP.get(windows_key, "--win11")
    wrapper_script = vm_dir / "run_vm.sh"
    cmd_args = ["bash", str(script_path), "--auto", win_flag, "--vnc"]
    wrapper_lines = [
        "#!/bin/bash",
        f'cd "{vm_dir}"',
        " ".join(cmd_args),
        ""
    ]
    with open(wrapper_script, "w", encoding="utf-8") as f:
        f.write("\n".join(wrapper_lines))
    os.chmod(wrapper_script, 0o755)

    env = os.environ.copy()
    env["WINBOX_VCPUS"] = str(config.get("cpu", 2))
    env["WINBOX_RAM_GB"] = str(config.get("ram", 4))
    env["WINBOX_DISK_GB"] = str(config.get("disk", 15))
    env["WINBOX_VNC"] = "1"
    env["HOME"] = str(vm_dir)
    env["USER"] = "winbox"
    env["LOGNAME"] = "winbox"

    append_vm_log(user_id, vm_id, f"[START] Cấu hình: {config.get('name', 'Custom')} ({config.get('cpu', 2)} vCPU, {config.get('ram', 4)} GB RAM, {config.get('disk', 15)} GB Disk)")
    append_vm_log(user_id, vm_id, f"[START] Hệ điều hành: {windows_key} ({win_flag})")
    append_vm_log(user_id, vm_id, "[START] KHÔNG resize disk - giữ nguyên dung lượng hiện tại")
    append_vm_log(user_id, vm_id, "----------------------------------------------------------")

    try:
        process = subprocess.Popen(
            ["bash", str(wrapper_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(vm_dir),
            env=env
        )
        with vm_lock:
            old_data = active_vms.get(vm_id, {})
            active_vms[vm_id] = {
                "process": process,
                "status": "running",
                "tailscale_ip": old_data.get("tailscale_ip"),
                "tailscale_key": tailscale_key or old_data.get("tailscale_key"),
                "config": config,
                "windows": old_data.get("windows"),
                "name": vm_name,
                "created_at": old_data.get("created_at", datetime.now().isoformat()),
                "vm_dir": str(vm_dir),
            }

        vm_data = get_vm_data(user_id, vm_id)
        if vm_data:
            vm_data["status"] = "running"
            save_vm_data(user_id, vm_id, vm_data)

        # Chạy tailscale song song ngay lập tức
        ts_thread = threading.Thread(
            target=_tailscale_worker,
            args=(user_id, vm_id, tailscale_key or old_data.get("tailscale_key"), vm_dir),
            daemon=True
        )
        ts_thread.start()

        def _log_worker():
            for line in process.stdout:
                line_str = line.strip()
                append_vm_log(user_id, vm_id, line_str)
            process.wait()
            append_vm_log(user_id, vm_id, "[START] Tiến trình QEMU đã kết thúc.")

        t = threading.Thread(target=_log_worker, daemon=True)
        t.start()

        return True, "VM đã được khởi động lại bằng win.sh (KHÔNG resize disk)"
    except Exception as e:
        return False, f"Lỗi khởi động lại VM: {e}"


# ==================== VM RUNNER ====================
def run_winbox_script(user_id, vm_id, config, win_img, tailscale_key, vm_name, windows_key="win11"):
    if isinstance(config, str):
        configs = get_vm_configs()
        config = configs.get(config, list(configs.values())[0])
    if isinstance(win_img, str):
        images = get_windows_images()
        windows_key = win_img
        win_img = images.get(win_img, list(images.values())[0])
    vm_dir = get_user_vm_dir(user_id, vm_id)
    with vm_lock:
        active_vms[vm_id] = {
            "process": None,
            "status": "creating",
            "tailscale_ip": None,
            "tailscale_key": tailscale_key,
            "config": config,
            "windows": win_img,
            "name": vm_name,
            "created_at": datetime.now().isoformat(),
            "vm_dir": str(vm_dir),
        }
    def log_append(text):
        append_vm_log(user_id, vm_id, text)
    log_append("==========================================================")
    log_append("STEP 1: TẢI WINBOXES STABLE SCRIPT")
    log_append("==========================================================")
    script_url = "https://raw.githubusercontent.com/thanhtrung-devVNG/demo_web/refs/heads/main/winbox.sh"
    script_path = vm_dir / "win.sh"
    try:
        download_proc = subprocess.run(
            ["wget", "-O", str(script_path), script_url],
            capture_output=True, text=True, timeout=120
        )
        if download_proc.returncode != 0 and not script_path.exists():
            download_proc = subprocess.run(
                ["curl", "-fsSL", "-o", str(script_path), script_url],
                capture_output=True, text=True, timeout=120
            )
        if script_path.exists() and script_path.stat().st_size > 1000:
            os.chmod(script_path, 0o755)
            log_append(f"Đã tải winboxes-stable-3-2.sh ({script_path.stat().st_size} bytes)")
        else:
            log_append("Không tải được script winboxes-stable-3-2.sh")
            return
    except Exception as e:
        log_append(f"Lỗi tải script: {e}")
        return
    log_append("==========================================================")
    log_append("STEP 2: CHUẨN BỊ THAM SỐ TỰ ĐỘNG CHO SCRIPT")
    log_append("==========================================================")
    WIN_FLAG_MAP = {
        "win2012": "--win2012",
        "win2022": "--win2022",
        "win11": "--win11",
        "win10ltsb": "--win10ltsb",
        "win10ltsc": "--win10ltsc",
        "win10ltsb2022": "--win10ltsb2022",
    }
    win_flag = WIN_FLAG_MAP.get(windows_key, "--win11")
    wrapper_script = vm_dir / "run_vm.sh"
    cmd_args = ["bash", str(script_path), "--auto", win_flag, "--vnc"]
    wrapper_lines = [
        "#!/bin/bash",
        f'cd "{vm_dir}"',
        " ".join(cmd_args),
        ""
    ]
    with open(wrapper_script, "w", encoding="utf-8") as f:
        f.write("\n".join(wrapper_lines))
    os.chmod(wrapper_script, 0o755)
    env = os.environ.copy()
    env["WINBOX_VCPUS"] = str(config["cpu"])
    env["WINBOX_RAM_GB"] = str(config["ram"])
    env["WINBOX_DISK_GB"] = str(config["disk"])
    env["WINBOX_VNC"] = "1"
    env["HOME"] = str(vm_dir)
    env["USER"] = "winbox"
    env["LOGNAME"] = "winbox"
    target_disk_gb = int(config.get("disk", 15))
    log_append(f"Gói VPS được chọn: {config.get('name', 'Custom')} ({config['cpu']} vCPU, {config['ram']} GB RAM, {config['disk']} GB Disk)")
    log_append(f"Hệ điều hành được chọn: {win_img.get('name', 'Custom OS')} ({win_flag})")
    log_append(f"Tham số gửi sang script: {' '.join(cmd_args)}")
    log_append("----------------------------------------------------------")
    def _disk_resize_worker():
        win_img_path = vm_dir / "win.img"
        max_wait = 600
        waited = 0
        resized = False
        while waited < max_wait and not resized:
            if win_img_path.exists():
                try:
                    size = win_img_path.stat().st_size
                    if size > 1_000_000_000:
                        log_append(f"[RESIZE] Phát hiện win.img ({size / 1_073_741_824:.1f} GB), đang resize đến {target_disk_gb}GB...")
                        qemu_img = shutil.which("qemu-img")
                        if not qemu_img:
                            for p in (vm_dir / "qemu-static" / "bin").glob("qemu-img"):
                                if p.exists():
                                    qemu_img = str(p)
                                    break
                        if qemu_img:
                            r = subprocess.run(
                                [qemu_img, "resize", str(win_img_path), f"{target_disk_gb}G"],
                                capture_output=True, text=True, timeout=60
                            )
                            if r.returncode == 0:
                                log_append(f"[RESIZE] Resize disk thành công đến {target_disk_gb}GB")
                            else:
                                log_append(f"[RESIZE] qemu-img resize exit code {r.returncode}: {r.stderr or r.stdout}")
                        else:
                            log_append("[RESIZE] Không tìm thấy qemu-img để resize")
                        resized = True
                        break
                except Exception as e:
                    log_append(f"[RESIZE] Lỗi kiểm tra file: {e}")
            time.sleep(3)
            waited += 3
        if not resized:
            log_append(f"[RESIZE] Hết thờigian chờ ({max_wait}s), không resize được disk")
    resize_thread = threading.Thread(target=_disk_resize_worker, daemon=True)
    resize_thread.start()
    process = subprocess.Popen(
        ["bash", str(wrapper_script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(vm_dir),
        env=env
    )
    with vm_lock:
        if vm_id in active_vms:
            active_vms[vm_id]["process"] = process
            active_vms[vm_id]["status"] = "running"
    vm_data = get_vm_data(user_id, vm_id)
    if vm_data:
        vm_data["status"] = "running"
        save_vm_data(user_id, vm_id, vm_data)
    # Chạy tailscale song song ngay lập tức (không chờ QEMU kết thúc)
    ts_thread = threading.Thread(
        target=_tailscale_worker,
        args=(user_id, vm_id, tailscale_key, vm_dir),
        daemon=True
    )
    ts_thread.start()

    # Thread chính đọc log QEMU
    for line in process.stdout:
        line_str = line.strip()
        log_append(line_str)
    process.wait()
    log_append("==========================================================")
    log_append("[SYSTEM] QEMU process đã kết thúc.")

# ==================== BILLING HELPERS ====================
def get_price_for_cycle(config, cycle):
    mapping = {
        "minutely": "price_minutely",
        "hourly": "price_hourly",
        "daily": "price_daily",
        "weekly": "price_weekly",
        "monthly": "price_monthly"
    }
    return config.get(mapping.get(cycle, "price_monthly"), 0)

def calculate_expiry(cycle, duration=1):
    now = datetime.now()
    dur = max(1, int(duration))
    if cycle == "minutely":
        return now + timedelta(minutes=dur)
    elif cycle == "hourly":
        return now + timedelta(hours=dur)
    elif cycle == "daily":
        return now + timedelta(days=dur)
    elif cycle == "weekly":
        return now + timedelta(weeks=dur)
    else:  # monthly
        return now + timedelta(days=30*dur)

# ==================== MARKETPLACE CLEANUP ====================
def cleanup_marketplace():
    market_data = load_json(MARKETPLACE_FILE)
    keys_data = load_json(KEYS_FILE)
    current_time = time.time()
    updated = False
    # 1. Cleanup VPS items (hết hàng sau 2 phút mặc định)
    to_delete = []
    for item_id, item in market_data.items():
        if item.get("quantity", 0) <= 0:
            sold_out_at = item.get("sold_out_at")
            if sold_out_at and (current_time - sold_out_at > 120):
                to_delete.append(item_id)
                updated = True
    for item_id in to_delete:
        del market_data[item_id]
    # 2. Cleanup Keys đã BÁN HẾT trên Shop → gỡ khỏi shop (dùng shop_grace_minutes)
    keys_to_unshop = []
    for k_code, k in keys_data.items():
        if k.get("on_shop") and k.get("used"):
            sold_out_at = k.get("sold_out_at")
            grace = max(1, k.get("shop_grace_minutes", 2)) * 60
            if sold_out_at and (current_time - sold_out_at > grace):
                keys_to_unshop.append(k_code)
                updated = True
    for k_code in keys_to_unshop:
        keys_data[k_code]["on_shop"] = False
    # 3. Cleanup Keys đã ĐƯỢC NHẬP (redeemed) → XÓA HOÀN TOÀN (dùng key_lifetime_minutes)
    keys_to_delete = []
    for k_code, k in keys_data.items():
        redeemed_at = k.get("redeemed_at")
        if redeemed_at:
            lifetime = max(1, k.get("key_lifetime_minutes", 60)) * 60
            if current_time - redeemed_at > lifetime:
                keys_to_delete.append(k_code)
                updated = True
    for k_code in keys_to_delete:
        del keys_data[k_code]
    # 4. Cleanup Keys đã HẾT HẠN VALIDITY (từ lúc tạo) → XÓA HOÀN TOÀN
    keys_to_delete_validity = []
    for k_code, k in keys_data.items():
        created_at = k.get("created_at")
        validity_days = int(k.get("key_validity_days", 30) or 30)
        if created_at:
            try:
                created_dt = datetime.fromisoformat(created_at)
                if datetime.now() > created_dt + timedelta(days=validity_days):
                    keys_to_delete_validity.append(k_code)
                    updated = True
            except Exception:
                pass
    for k_code in keys_to_delete_validity:
        del keys_data[k_code]
    if updated:
        save_json(MARKETPLACE_FILE, market_data)
        save_json(KEYS_FILE, keys_data)

def marketplace_cleanup_worker():
    while True:
        try:
            cleanup_marketplace()
        except Exception as e:
            print(f"[MARKETPLACE CLEANUP] {e}")
        time.sleep(10)

# ==================== EXPIRED VM AUTO-CLEANUP ====================
GRACE_PERIOD_MINUTES = 10

def cleanup_expired_vms():
    """Tự động xóa VM đã hết hạn quá grace period để giải phóng tài nguyên."""
    now = datetime.now()
    users = load_all_users()
    cleaned_count = 0
    for uid, user in users.items():
        user_vms = get_user_vms(uid)
        for vid, vm in user_vms.items():
            expiry_str = vm.get("expiry_time", "")
            if not expiry_str:
                continue
            try:
                expiry_dt = datetime.fromisoformat(expiry_str)
            except Exception:
                continue
            if now > expiry_dt + timedelta(minutes=GRACE_PERIOD_MINUTES):
                # VM đã hết hạn quá 10 phút → tự động xóa
                vm_dir = get_user_vm_dir(uid, vid)
                find_and_kill_qemu_for_vm(vm_dir)
                with vm_lock:
                    if vid in active_vms and active_vms[vid].get("process"):
                        try:
                            active_vms[vid]["process"].terminate()
                            active_vms[vid]["process"].wait(timeout=5)
                        except Exception:
                            try:
                                active_vms[vid]["process"].kill()
                            except Exception:
                                pass
                    active_vms.pop(vid, None)
                if vm_dir.exists():
                    shutil.rmtree(vm_dir, ignore_errors=True)
                append_vm_log(uid, vid, f"[AUTO-DELETE] VM đã hết hạn quá {GRACE_PERIOD_MINUTES} phút. Hệ thống tự động xóa để giải phóng tài nguyên.")
                cleaned_count += 1
                print(f"[AUTO-CLEANUP] Đã xóa VM {vid} của user {user.get('username', uid)} (hết hạn lúc {expiry_str})")
    if cleaned_count > 0:
        print(f"[AUTO-CLEANUP] Tổng cộng đã xóa {cleaned_count} VM hết hạn.")

def expired_vm_cleanup_worker():
    while True:
        try:
            cleanup_expired_vms()
        except Exception as e:
            print(f"[EXPIRED CLEANUP ERROR] {e}")
        time.sleep(60)

# ==================== TEMPLATE FILTER ====================
@app.template_filter('vnd')
def vnd_filter(value):
    try:
        val = float(value)
        return f"{val:,.0f}".replace(",", ".") + " VNĐ"
    except (ValueError, TypeError):
        return "0 VNĐ"

# ==================== HTML TEMPLATES ====================
LANDING_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ settings.site_name }} - Quản lý máy ảo Cloud Windows</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#ffffff;color:#333;min-height:100vh;}
.navbar{background:#ffffff;padding:15px 50px;display:flex;justify-content:space-between;align-items:center;position:fixed;width:100%;top:0;z-index:1000;border-bottom:1px solid #e0e0e0}
.navbar .logo{font-size:28px;font-weight:800;color:{{ settings.primary_color }};display:flex;align-items:center;gap:10px}
.nav-links{display:flex;gap:20px;align-items:center}
.nav-links a{text-decoration:none;color:#333;font-weight:500}
.btn-primary{background:{{ settings.primary_color }};color:#ffffff !important;padding:10px 20px;border-radius:8px;font-weight:600;text-decoration:none;display:inline-block;transition:all 0.2s ease}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(33,150,243,0.3)}
.hero{padding:140px 20px 80px;text-align:center;color:#ffffff;background:{{ settings.primary_color }};}
.hero h1{font-size:48px;font-weight:800;margin-bottom:20px}
.hero p{font-size:18px;max-width:700px;margin:0 auto 30px;opacity:0.95}
.hero-btns{display:flex;gap:15px;justify-content:center}
.btn-large{padding:14px 32px;font-size:16px;border-radius:8px;text-decoration:none;font-weight:600;transition:all 0.2s ease}
.btn-white{background:#ffffff;color:{{ settings.primary_color }};}
.btn-white:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}
.btn-outline{border:2px solid #ffffff;color:#ffffff;background:transparent}
.btn-outline:hover{background:rgba(255,255,255,0.1)}
.section{padding:60px 50px;background:#ffffff}
.section-title{text-align:center;font-size:32px;font-weight:700;margin-bottom:40px}
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px;max-width:1200px;margin:0 auto}
.pricing-card{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:30px 20px;text-align:center;transition:all 0.3s ease}
.pricing-card:hover{transform:translateY(-5px);box-shadow:0 10px 20px rgba(0,0,0,0.08);border-color:{{ settings.primary_color }};}
.pricing-card h3{font-size:22px;color:#333;margin-bottom:10px}
.pricing-card .price{font-size:28px;font-weight:800;color:{{ settings.primary_color }};margin:15px 0}
.specs{list-style:none;margin:20px 0;text-align:left}
.specs li{padding:8px 0;border-bottom:1px solid #f0f0f0;color:#555;font-size:14px}
.footer{background:#1a1a2e;color:#ffffff;padding:30px;text-align:center;font-size:14px}
</style>
</head>
<body>
<nav class="navbar">
<div class="logo"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<div class="nav-links">
<a href="#vps">VPS là gì?</a>
<a href="#pricing">Bảng giá</a>
<a href="/login" class="btn-primary">Đăng nhập</a>
<a href="/register" class="btn-primary" style="background:#FF5722">Đăng ký</a>
</div>
</nav>
<section class="hero">
<h1>Cloud Windows VM</h1>
<p>Tạo và quản lý máy ảo Windows chỉ trong vài giây. Hỗ trợ kết nối RDP qua Tailscale, cấu hình linh hoạt từ cơ bản đến siêu cao.</p>
<div class="hero-btns">
<a href="/register" class="btn-large btn-white"><i class="fas fa-rocket"></i> Bắt đầu ngay</a>
<a href="#vps" class="btn-large btn-outline"><i class="fas fa-info-circle"></i> Tìm hiểu thêm</a>
</div>
</section>
<section class="section" id="vps">
<h2 class="section-title">Khái niệm về VPS</h2>
<div style="max-width:900px;margin:0 auto;line-height:1.8;color:#555">
<p style="margin-bottom:15px">Máy chủ ảo riêng (VPS - Virtual Private Server) là giải pháp phân chia máy chủ vật lý thành nhiều máy chủ ảo độc lập. Mỗi VPS sở hữu dung lượng RAM, CPU, ổ cứng riêng và hệ điều hành độc lập.</p>
<p>Với hệ thống {{ settings.site_name }}, bạn dễ dàng khởi tạo VPS Windows chạy nền tảng QEMU/KVM với giao diện Desktop đầy đủ, tích hợp kết nối RDP an toàn thông qua mạng Tailscale VPN.</p>
</div>
</section>
<section class="section" id="pricing" style="background:#f9f9f9">
<h2 class="section-title">Bảng giá cấu hình</h2>
<div class="pricing-grid">
{% for key, cfg in vm_configs.items() %}
<div class="pricing-card">
<h3>{{ cfg.name }}</h3>
<div class="price">{{ cfg.price_monthly|vnd }}<span>/tháng</span></div>
<ul class="specs">
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.cpu }} vCPU</li>
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.ram }} GB RAM</li>
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.disk }} GB SSD</li>
</ul>
<div style="font-size:12px;color:#666;margin-top:10px">
  <div>Theo giờ: {{ cfg.price_hourly|vnd }}</div>
  <div>Theo ngày: {{ cfg.price_daily|vnd }}</div>
</div>
</div>
{% endfor %}
</div>
</section>
<footer class="footer">
<p> 2026 {{ settings.site_name }}. Bản quyền thuộc về hệ thống quản lý máy ảo.</p>
</footer>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Đăng nhập - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.login-container{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:40px;width:400px;box-shadow: 0 8px 24px rgba(0,0,0,0.05);}
.login-header{text-align:center;margin-bottom:30px}
.login-header .logo{font-size:28px;font-weight:800;color:{{ settings.primary_color }};margin-bottom:8px}
.login-header p{color:#666;font-size:14px}
.form-group{margin-bottom:20px}
.form-group label{display:block;margin-bottom:6px;color:#333;font-weight:500;font-size:14px}
.form-group input{width:100%;padding:12px;border:1px solid #ccc;border-radius:6px;font-size:14px;outline:none;transition: border-color 0.2s}
.form-group input:focus{border-color:{{ settings.primary_color }};}
.btn-submit{width:100%;padding:12px;background:{{ settings.primary_color }};color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition: background 0.2s}
.btn-submit:hover{opacity:0.9}
.alert{padding:10px 14px;border-radius:6px;margin-bottom:15px;font-size:13px}
.alert-error{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.alert-success{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}
.register-link{text-align:center;margin-top:20px;font-size:14px;color:#666}
.register-link a{color:{{ settings.primary_color }};text-decoration:none;font-weight:600}
</style>
</head>
<body>
<div class="login-container">
<div class="login-header">
<div class="logo"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<p>Đăng nhập vào tài khoản của bạn.</p>
</div>
{% if error %}<div class="alert alert-error"><i class="fas fa-exclamation-circle"></i> {{ error }}</div>{% endif %}
{% if success %}<div class="alert alert-success"><i class="fas fa-check-circle"></i> {{ success }}</div>{% endif %}
<form method="POST" action="/login">
<div class="form-group">
<label><i class="fas fa-user"></i> Tên đăng nhập</label>
<input type="text" name="username" placeholder="Nhập tên đăng nhập" required>
</div>
<div class="form-group">
<label><i class="fas fa-lock"></i> Mật khẩu</label>
<input type="password" name="password" placeholder="Nhập mật khẩu" required>
</div>
<button type="submit" class="btn-submit"><i class="fas fa-sign-in-alt"></i> Đăng nhập</button>
</form>
<div class="register-link">Chưa có tài khoản? <a href="/register">Đăng ký ngay</a></div>
<div style="text-align:center;margin-top:15px"><a href="/" style="color:#888;text-decoration:none;font-size:13px"><i class="fas fa-arrow-left"></i> Quay lại trang chủ</a></div>
</div>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

REGISTER_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Đăng ký - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.login-container{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:40px;width:400px;box-shadow: 0 8px 24px rgba(0,0,0,0.05);}
.login-header{text-align:center;margin-bottom:25px}
.login-header .logo{font-size:28px;font-weight:800;color:{{ settings.primary_color }};margin-bottom:8px}
.login-header p{color:#666;font-size:14px}
.form-group{margin-bottom:15px}
.form-group label{display:block;margin-bottom:6px;color:#333;font-weight:500;font-size:14px}
.form-group input{width:100%;padding:10px 12px;border:1px solid #ccc;border-radius:6px;font-size:14px;outline:none;transition: border-color 0.2s}
.form-group input:focus{border-color:{{ settings.primary_color }};}
.btn-submit{width:100%;padding:12px;background:#FF5722;color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition: background 0.2s}
.btn-submit:hover{background:#E64A19}
.alert{padding:10px 14px;border-radius:6px;margin-bottom:15px;font-size:13px}
.alert-error{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.register-link{text-align:center;margin-top:20px;font-size:14px;color:#666}
.register-link a{color:{{ settings.primary_color }};text-decoration:none;font-weight:600}
</style>
</head>
<body>
<div class="login-container">
<div class="login-header">
<div class="logo"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<p>Tạo tài khoản mới.</p>
</div>
{% if error %}<div class="alert alert-error"><i class="fas fa-exclamation-circle"></i> {{ error }}</div>{% endif %}
<form method="POST" action="/register">
<div class="form-group">
<label><i class="fas fa-user"></i> Tên đăng nhập</label>
<input type="text" name="username" placeholder="Chọn tên đăng nhập" required>
</div>
<div class="form-group">
<label><i class="fas fa-envelope"></i> Địa chỉ Email</label>
<input type="email" name="email" placeholder="Nhập địa chỉ email" required>
</div>
<div class="form-group">
<label><i class="fas fa-lock"></i> Mật khẩu</label>
<input type="password" name="password" placeholder="Ít nhất 6 ký tự" required minlength="6">
</div>
<div class="form-group">
<label><i class="fas fa-lock"></i> Xác nhận mật khẩu</label>
<input type="password" name="password_confirm" placeholder="Nhập lại mật khẩu" required>
</div>
<button type="submit" class="btn-submit"><i class="fas fa-user-plus"></i> Đăng ký</button>
</form>
<div class="register-link">Đã có tài khoản? <a href="/login">Đăng nhập</a></div>
<div style="text-align:center;margin-top:15px"><a href="/" style="color:#888;text-decoration:none;font-size:13px"><i class="fas fa-arrow-left"></i> Quay lại trang chủ</a></div>
</div>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

ANNOUNCEMENT_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bảng tin chính - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e2e8f0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e2e8f0;color:{{ settings.primary_color }};}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#64748b;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:{{ settings.primary_color }};border-left:4px solid {{ settings.primary_color }};}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e2e8f0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:{{ settings.primary_color }};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.btn-create{background:#FF9800;color:#ffffff;padding:10px 20px;border-radius:8px;border:none;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;transition: transform 0.2s, background 0.2s;}
.btn-create:hover{background:#e68a00;transform: translateY(-2px);}
.announcement-card{background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%); border: 1px solid #90caf9; border-radius: 14px; padding: 30px; margin-bottom: 25px; box-shadow: 0 6px 18px rgba(33,150,243,0.08);}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{background:#ffffff;border-radius:12px;padding:30px;width:420px;transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.modal-overlay.active .modal{transform: scale(1);}
.center-notif-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;z-index:3000;opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.form-group{margin-bottom:15px}
.form-group label{display:block;margin-bottom:6px;font-weight:500;font-size:13px}
.form-group input{width:100%;padding:10px;border:1px solid #ccc;border-radius:6px;font-size:14px;outline:none}
.btn-submit{width:100%;padding:12px;background:#FF9800;color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition: background 0.2s;}
.btn-submit:hover{background:#e68a00;}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<div class="sidebar-menu">
<a href="/dashboard" class="active"><i class="fas fa-bullhorn"></i> Bảng tin chính</a>
<a href="/my-vms"><i class="fas fa-server"></i> Máy ảo của tôi</a>
<a href="/marketplace"><i class="fas fa-store"></i> Chợ VPS</a>
<a href="/deposit"><i class="fas fa-wallet"></i> Nạp tiền</a>
{% if role == 'admin' %}
<a href="/admin" style="color:#d97706"><i class="fas fa-user-shield"></i> Trang Quản Trị (Admin)</a>
{% endif %}
<a href="/logout"><i class="fas fa-sign-out-alt"></i> Đăng xuất</a>
</div>
<div class="sidebar-footer">
<div class="user-info">
<div class="user-avatar">{{ username[0]|upper }}</div>
<div>
<div style="font-weight:600;font-size:14px">{{ username }}</div>
<div style="font-size:12px;color:#666">Số dư: {{ balance|vnd }}</div>
</div>
</div>
</div>
</div>
<div class="main-content">
<div class="top-bar">
<h1><i class="fas fa-bullhorn" style="color:{{ settings.primary_color }}"></i> Bảng tin chính hệ thống</h1>
<button class="btn-create" onclick="openRedeemModal()"><i class="fas fa-gift"></i> Hộp Quà / Nhập Key</button>
</div>
<div class="announcement-card">
<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom: 20px; border-bottom:1px solid #e0e0e0; padding-bottom:15px">
<h2 style="color: #1565c0; font-size: 22px; display:flex; align-items:center; gap: 12px; font-weight:700">
<i class="fas fa-bullhorn" style="color: {{ settings.primary_color }};"></i> {{ announcement.title }}
</h2>
<span style="font-size: 13px; color: #64748b; background: rgba(33,150,243,0.1); padding: 6px 14px; border-radius: 20px; font-weight:600;">
<i class="far fa-clock"></i> {{ announcement.updated_at }}
</span>
</div>
<div style="color: #334155; font-size: 15px; line-height: 1.8; white-space: pre-wrap; font-weight:400">{{ announcement.content }}</div>
</div>
</div>
<div class="modal-overlay" id="redeemModal">
<div class="modal" style="text-align:center;">
<div class="modal-header">
<h3 style="font-size:18px"><i class="fas fa-gift" style="color:#FF9800"></i> Hộp Quà / Nhập Code</h3>
<button onclick="closeRedeemModal()" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
</div>
<form id="redeemForm" onsubmit="return redeemKey(event)">
<div class="form-group" style="margin:20px 0">
<label style="font-size:14px;color:#555;margin-bottom:10px">Nhập mã Giftcode / Key của bạn:</label>
<input type="text" id="giftCodeInput" name="code" placeholder="Ví dụ: WINBOX-XXXX-XXXX" style="text-align:center;font-weight:700;font-size:16px;letter-spacing:1px;text-transform:uppercase" required>
</div>
<button type="submit" class="btn-submit"><i class="fas fa-check-circle"></i> Nhận Quà Ngay</button>
</form>
</div>
</div>
<div class="modal-overlay" id="renewModal">
<div class="modal" style="width:520px">
<div class="modal-header">
<h3><i class="fas fa-sync-alt" style="color:{{ settings.primary_color }}"></i> Gia hạn Máy ảo</h3>
<div class="modal-close" onclick="closeRenewModal()">&times;</div>
</div>
<form id="renewForm" onsubmit="return renewVM(event)">
<input type="hidden" name="vm_id" id="renewVmId">
<div class="form-group">
<label><i class="fas fa-clock" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn đơn vị gia hạn:</label>
<div class="cycle-options" style="grid-template-columns:repeat(5,1fr)">
<div class="cycle-option selected" data-cycle="minutely" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-stopwatch"></i> Phút</div>
<div class="cycle-price" id="renewPriceMinutely">--</div>
</div>
<div class="cycle-option" data-cycle="hourly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-hourglass-half"></i> Giờ</div>
<div class="cycle-price" id="renewPriceHourly">--</div>
</div>
<div class="cycle-option" data-cycle="daily" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-sun"></i> Ngày</div>
<div class="cycle-price" id="renewPriceDaily">--</div>
</div>
<div class="cycle-option" data-cycle="weekly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-week"></i> Tuần</div>
<div class="cycle-price" id="renewPriceWeekly">--</div>
</div>
<div class="cycle-option" data-cycle="monthly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-alt"></i> Tháng</div>
<div class="cycle-price" id="renewPriceMonthly">--</div>
</div>
</div>
<div class="form-group" style="margin-top:12px;display:flex;align-items:center;gap:12px">
<label style="margin:0;white-space:nowrap;font-weight:600">Số lượng gia hạn:</label>
<input type="number" id="renewDurationInput" name="duration" value="1" min="1" style="width:100px;padding:10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px" oninput="updateRenewTotal()">
<span style="color:#64748b;font-size:13px" id="renewDurationLabel">phút</span>
</div>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<span style="font-weight:600;color:#1e293b">Tổng tiền gia hạn:</span>
<span id="renewTotalDisplay" style="font-size:18px;font-weight:800;color:#2563eb">0 VNĐ</span>
</div>
<input type="hidden" name="billing_cycle" id="selectedRenewCycle" value="minutely">
</div>
<button type="submit" class="btn-submit" id="renewSubmitBtn"><i class="fas fa-check-circle"></i> Xác nhận Gia hạn</button>
</form>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:{{ settings.primary_color }}"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>
<script>
function openRedeemModal(){ document.getElementById('redeemModal').classList.add('active'); }
function closeRedeemModal(){ document.getElementById('redeemModal').classList.remove('active'); }
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const codeParam = urlParams.get('code');
    if(codeParam){ document.getElementById('giftCodeInput').value = codeParam; openRedeemModal(); }
});
function redeemKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/keys/redeem', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ closeRedeemModal(); showCenterNotice(d.message || 'Nhập Key thành công!', false, 1800, () => location.reload()); }
        else { showCenterNotice(d.error || 'Mã Giftcode không hợp lệ hoặc đã sử dụng!', true); }
    })
    .catch(err=>showCenterNotice('Lỗi kết nối máy chủ!', true));
    return false;
}
function showCenterNotice(msg, isError=false, duration=2200, callback=null){
    const overlay = document.getElementById('centerNotif');
    const icon = document.getElementById('centerNotifIcon');
    const msgEl = document.getElementById('centerNotifMsg');
    if(!overlay) return;
    msgEl.textContent = msg;
    if(isError){ icon.className = 'fas fa-exclamation-circle'; icon.style.color = '#c62828'; }
    else { icon.className = 'fas fa-check-circle'; icon.style.color = '#2e7d32'; }
    overlay.classList.add('active');
    setTimeout(() => { overlay.classList.remove('active'); if(callback) setTimeout(callback, 300); }, duration);
}
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

MY_VMS_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Máy ảo của tôi - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e2e8f0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e2e8f0;color:{{ settings.primary_color }};}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#64748b;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:{{ settings.primary_color }};border-left:4px solid {{ settings.primary_color }};}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e2e8f0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:{{ settings.primary_color }};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.btn-create{background:{{ settings.primary_color }};color:#ffffff;padding:10px 20px;border-radius:8px;border:none;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;transition: transform 0.2s, background 0.2s;}
.btn-create:hover{opacity:0.9;transform: translateY(-2px);}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:25px}
.stat-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;transition: transform 0.2s;box-shadow: 0 2px 6px rgba(0,0,0,0.02);}
.stat-card:hover{transform: translateY(-2px);}
.stat-card h3{font-size:22px;font-weight:700;margin-bottom:5px;color:{{ settings.primary_color }};}
.stat-card p{color:#64748b;font-size:13px}
.vm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
.vm-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;box-shadow: 0 2px 8px rgba(0,0,0,0.03);transition: all 0.25s ease;display:flex;flex-direction:column;justify-content:space-between;}
.vm-card:hover{box-shadow: 0 8px 20px rgba(0,0,0,0.08);border-color:{{ settings.primary_color }};}
.vm-header{display:flex;justify-content:space-between;align-items:center;padding-bottom:12px;margin-bottom:12px;border-bottom:1px solid #f1f5f9}
.vm-header h4{font-size:16px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:8px}
.vm-status{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600}
.vm-status .status-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.vm-status.running{background:#dcfce7;color:#15803d}
.vm-status.running .status-dot{background:#22c55e;animation: pulse 1.8s infinite;}
.vm-status.creating{background:#fef3c7;color:#b45309}
.vm-status.creating .status-dot{background:#f59e0b}
.vm-status.stopped{background:#fee2e2;color:#b91c1c}
.vm-status.stopped .status-dot{background:#ef4444}
.vm-status.expired{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}
.vm-status.expired .status-dot{background:#ef4444;animation: none;}
.btn-renew{background:#dcfce7;color:#15803d;flex:1}
.btn-renew:hover{opacity:0.88;transform:translateY(-1px)}
@keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } 100% { opacity: 1; transform: scale(1); } }
.vm-info{display:flex;flex-direction:column;gap:8px;font-size:13px}
.vm-info-row{display:flex;justify-content:space-between;color:#64748b}
.vm-actions{display:flex;gap:8px;margin-top:16px}
.vm-actions button{flex:1;padding:8px 12px;border-radius:6px;border:none;font-size:12px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:5px;transition: all 0.2s;}
.vm-actions button:hover{opacity:0.88;transform:translateY(-1px)}
.btn-start{background:#dcfce7;color:#15803d}
.btn-stop{background:#fef3c7;color:#b45309}
.btn-delete{background:#fee2e2;color:#dc2626;max-width:42px}
.btn-view{background:#dbeafe;color:#1d4ed8}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15, 23, 42, 0.6);backdrop-filter: blur(4px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{background:#ffffff;border-radius:16px;padding:32px;width:680px;max-height:92vh;overflow-y:auto;box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);transform: scale(0.9) translateY(10px); transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);}
.modal-overlay.active .modal{transform: scale(1) translateY(0);}
.center-notif-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;z-index:3000;opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;border-bottom:1px solid #f1f5f9;padding-bottom:16px}
.modal-header h3{font-size:20px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:10px}
.modal-header h3 i{color:{{ settings.primary_color }};}
.modal-close{background:#f8fafc;border:1px solid #e2e8f0;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;cursor:pointer;color:#64748b;transition:all 0.2s}
.modal-close:hover{background:#fee2e2;color:#dc2626;border-color:#fecaca}
.form-group{margin-bottom:20px}
.form-group label{display:block;margin-bottom:8px;font-weight:600;font-size:13.5px;color:#334155}
.form-group input, .form-group select{width:100%;padding:11px 14px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;outline:none;transition:all 0.2s;background:#fff;color:#0f172a;}
.form-group input:focus, .form-group select:focus{border-color:{{ settings.primary_color }};box-shadow:0 0 0 3px rgba(33,150,243,0.12)}
.config-options{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:5px}
.config-option{padding:14px 16px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;text-align:left;font-size:13.5px;transition: all 0.2s ease;display:flex;flex-direction:column;gap:4px;}
.config-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.config-option.selected{border-color:{{ settings.primary_color }};background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15)}
.config-option .cfg-title{font-weight:700;color:#1e293b;font-size:14px;display:flex;justify-content:space-between;align-items:center}
.config-option .cfg-desc{color:#64748b;font-size:12.5px}
.config-option .cfg-price{color:#2563eb;font-weight:600;font-size:13px;margin-top:2px}
.os-options{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:5px}
.os-option{padding:12px 14px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;text-align:left;font-size:13.5px;transition: all 0.2s ease;display:flex;align-items:center;gap:10px;}
.os-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.os-option.selected{border-color:{{ settings.primary_color }};background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15);font-weight:600;color:#1d4ed8}
.os-option i{font-size:18px;color:{{ settings.primary_color }};}
.btn-submit{width:100%;padding:13px;background:linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);color:#ffffff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition: all 0.2s;box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);display:flex;align-items:center;justify-content:center;gap:8px;margin-top:5px;}
.btn-submit:hover{background:linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);transform:translateY(-1px);box-shadow: 0 6px 16px rgba(37, 99, 235, 0.35)}
.cycle-options{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:5px}
.cycle-option{padding:12px 14px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;text-align:center;font-size:13.5px;transition: all 0.2s ease;}
.cycle-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.cycle-option.selected{border-color:{{ settings.primary_color }};background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15);font-weight:700;color:#1d4ed8}
.cycle-option .cycle-name{font-weight:700;font-size:14px}
.cycle-option .cycle-price{color:#2563eb;font-weight:600;font-size:13px;margin-top:4px}
.expiry-badge{display:inline-block;background:#fff3e0;color:#e65100;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;margin-top:6px}
.logs-locked-badge{display:inline-block;background:#ffebee;color:#c62828;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;margin-top:6px}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<div class="sidebar-menu">
<a href="/dashboard"><i class="fas fa-bullhorn"></i> Bảng tin chính</a>
<a href="/my-vms" class="active"><i class="fas fa-server"></i> Máy ảo của tôi</a>
<a href="/marketplace"><i class="fas fa-store"></i> Chợ VPS</a>
<a href="/deposit"><i class="fas fa-wallet"></i> Nạp tiền</a>
{% if role == 'admin' %}
<a href="/admin" style="color:#d97706"><i class="fas fa-user-shield"></i> Trang Quản Trị (Admin)</a>
{% endif %}
<a href="/logout"><i class="fas fa-sign-out-alt"></i> Đăng xuất</a>
</div>
<div class="sidebar-footer">
<div class="user-info">
<div class="user-avatar">{{ username[0]|upper }}</div>
<div>
<div style="font-weight:600;font-size:14px">{{ username }}</div>
<div style="font-size:12px;color:#666">Số dư: {{ balance|vnd }}</div>
</div>
</div>
</div>
</div>
<div class="main-content">
<div class="top-bar">
<h1><i class="fas fa-server" style="color:{{ settings.primary_color }}"></i> Quản lý Máy ảo của tôi</h1>
<div style="display:flex;gap:10px;">
<button class="btn-create" style="background:#FF9800" onclick="openRedeemModal()"><i class="fas fa-gift"></i> Hộp Quà / Nhập Code</button>
<button class="btn-create" onclick="openModal()"><i class="fas fa-plus"></i> Tạo VM mới</button>
</div>
</div>
<div class="stats-grid">
<div class="stat-card"><h3>{{ balance|vnd }}</h3><p>Số dư tài khoản</p></div>
<div class="stat-card"><h3>{{ vm_count }}</h3><p>Tổng số VM</p></div>
<div class="stat-card"><h3>{{ running_count }}</h3><p>Đang hoạt động</p></div>
<div class="stat-card"><h3>{{ creating_count }}</h3><p>Đang khởi tạo</p></div>
</div>
<div class="vm-grid">
{% if vms %}
{% for vm in vms %}
<div class="vm-card" data-vm-id="{{ vm.id }}" data-expiry="{{ vm.expiry_time }}" data-name="{{ vm.name }}">
<div>
<div class="vm-header">
<h4><i class="fab fa-windows" style="color:{{ settings.primary_color }};font-size:18px"></i> {{ vm.name }}</h4>
{% if vm.is_expired %}
<span class="vm-status expired"><span class="status-dot"></span> Đã hết hạn</span>
{% else %}
<span class="vm-status {{ vm.status }}"><span class="status-dot"></span> {{ vm.status_text }}</span>
{% endif %}
</div>
<div class="vm-info">
<div class="vm-info-row"><span>Cấu hình:</span><strong style="color:#0f172a">{{ vm.cpu }} vCPU / {{ vm.ram }} GB RAM</strong></div>
<div class="vm-info-row"><span>Dung lượng ổ đĩa:</span><strong style="color:#0f172a">{{ vm.disk }} GB SSD</strong></div>
<div class="vm-info-row"><span>Hệ điều hành:</span><strong style="color:#0f172a">{{ vm.os }}</strong></div>
<div class="vm-info-row"><span>Server:</span><strong style="color:#0f172a">{{ vm.node_name }}</strong></div>
<div class="vm-info-row"><span>Tài khoản RDP:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.user }}</strong></div>
<div class="vm-info-row"><span>Mật khẩu:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.password }}</strong></div>
<div class="vm-info-row"><span>Chu kỳ thuê:</span><strong style="color:#0f172a">{{ vm.billing_text }}</strong></div>
<div class="vm-info-row"><span>Hết hạn:</span><strong style="color:{% if vm.is_expired %}#dc2626{% else %}#d97706{% endif %}">{{ vm.expiry_text }}</strong></div>
<div class="vm-info-row" style="background:#f1f5f9;padding:8px 10px;border-radius:6px;margin-top:4px">
<span>Địa chỉ IP (Tailscale):</span>
{% if vm.tailscale_ip %}
<strong style="color:#16a34a;font-family:monospace;font-size:14px">{{ vm.tailscale_ip }}</strong>
{% else %}
<span style="color:#d97706;font-size:12px"><i class="fas fa-spinner fa-spin"></i> Đang lấy IP...</span>
{% endif %}
</div>
<div class="vm-info-row countdown-row" style="background:#e0f2fe;padding:6px 10px;border-radius:6px;margin-top:4px;display:none">
<span><i class="fas fa-clock" style="color:#0284c7"></i> Còn lại:</span>
<strong class="countdown-text" style="color:#0369a1;font-family:monospace">--</strong>
</div>
{% if vm.logs_locked %}
<div class="logs-locked-badge"><i class="fas fa-lock"></i> Logs đang bị khóa bởi Admin</div>
{% endif %}
{% if vm.is_expired %}
<div style="background:#fee2e2;color:#b91c1c;padding:8px 10px;border-radius:6px;margin-top:8px;font-size:12px;font-weight:600;text-align:center;border:1px solid #fecaca">
<i class="fas fa-exclamation-triangle"></i> Máy ảo đã hết hạn. Vui lòng gia hạn hoặc xóa.
</div>
{% endif %}
</div>
</div>
<div class="vm-actions">
{% if vm.is_expired %}
<button class="btn-renew" onclick="openRenewModal('{{ vm.id }}', {{ vm.config.price_minutely|default(0) }}, {{ vm.config.price_hourly|default(0) }}, {{ vm.config.price_daily|default(0) }}, {{ vm.config.price_weekly|default(0) }}, {{ vm.config.price_monthly|default(0) }})"><i class="fas fa-sync-alt"></i> Gia hạn</button>
<button class="btn-delete" onclick="deleteVM('{{ vm.id }}')" title="Xóa máy ảo"><i class="fas fa-trash"></i> Xóa VM</button>
{% else %}
{% if vm.status == 'stopped' %}
<button class="btn-start" onclick="startVM('{{ vm.id }}')"><i class="fas fa-play"></i> Bật</button>
{% else %}
<button class="btn-stop" onclick="stopVM('{{ vm.id }}')"><i class="fas fa-stop"></i> Tắt</button>
{% endif %}
{% if not vm.logs_locked %}
<button class="btn-view" onclick="viewVM('{{ vm.id }}')"><i class="fas fa-terminal"></i> Xem Log</button>
{% else %}
<button class="btn-view" disabled style="opacity:0.5;cursor:not-allowed" title="Logs đang bị khóa"><i class="fas fa-lock"></i> Log khóa</button>
{% endif %}
<button class="btn-delete" onclick="deleteVM('{{ vm.id }}')" title="Xóa máy ảo"><i class="fas fa-trash"></i></button>
{% endif %}
</div>
</div>
{% endfor %}
{% else %}
<div style="grid-column:1/-1;background:#fff;padding:40px;text-align:center;border-radius:12px;border:1px solid #e2e8f0;color:#777">
<i class="fas fa-server" style="font-size:40px;margin-bottom:10px;color:#cbd5e1"></i>
<p>Bạn chưa có máy ảo nào. Bấm nút "Tạo VM mới" hoặc nhập Giftcode để tiến hành khởi tạo.</p>
</div>
{% endif %}
</div>
</div>
<div class="modal-overlay" id="redeemModal">
<div class="modal" style="width:420px;text-align:center;">
<div class="modal-header">
<h3 style="font-size:18px"><i class="fas fa-gift" style="color:#FF9800"></i> Hộp Quà / Nhập Code</h3>
<button class="modal-close" onclick="closeRedeemModal()">&times;</button>
</div>
<form id="redeemForm" onsubmit="return redeemKey(event)">
<div class="form-group" style="margin:20px 0">
<label style="font-size:14px;color:#555;margin-bottom:10px">Nhập mã Giftcode / Key của bạn:</label>
<input type="text" id="giftCodeInput" name="code" placeholder="Ví dụ: WINBOX-XXXX-XXXX" style="text-align:center;font-weight:700;font-size:16px;letter-spacing:1px;text-transform:uppercase" required>
</div>
<button type="submit" class="btn-submit" style="background:#FF9800"><i class="fas fa-check-circle"></i> Nhận Quà Ngay</button>
</form>
</div>
</div>
<div class="modal-overlay" id="createModal">
<div class="modal">
<div class="modal-header">
<h3><i class="fas fa-plus-circle"></i> Khởi tạo Máy ảo mới</h3>
<div class="modal-close" onclick="closeModal()">&times;</div>
</div>
<form id="createForm" onsubmit="return createVM(event)">
<div class="form-group">
<label><i class="fas fa-tag" style="color:{{ settings.primary_color }};margin-right:6px"></i> Tên máy ảo</label>
<input type="text" name="vm_name" placeholder="Ví dụ: VPS-Ketoan-01" required>
</div>
<div class="form-group">
<label><i class="fas fa-microchip" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn cấu hình tài nguyên</label>
<div class="config-options">
{% for key, cfg in vm_configs.items() %}
<div class="config-option" data-config="{{ key }}" onclick="selectConfig(this)">
<div class="cfg-title"><span>{{ cfg.name }}</span> <i class="fas fa-check-circle" style="color:#2563eb;opacity:0;transition:opacity 0.2s"></i></div>
<div class="cfg-desc">{{ cfg.cpu }} vCPU • {{ cfg.ram }} GB RAM • {{ cfg.disk }} GB SSD</div>
<div class="cfg-price" id="price_{{ key }}">{{ cfg.price_minutely|vnd }}/phút</div>
</div>
{% endfor %}
</div>
<input type="hidden" name="config" id="selectedConfig" value="">
</div>
<div class="form-group">
<label><i class="fas fa-clock" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn đơn vị thuê & Số lượng</label>
<div class="cycle-options" style="grid-template-columns:repeat(5,1fr)">
<div class="cycle-option selected" data-cycle="minutely" onclick="selectCycle(this)">
<div class="cycle-name"><i class="fas fa-stopwatch"></i> Phút</div>
<div class="cycle-price" id="cyclePriceMinutely">Chọn cấu hình</div>
</div>
<div class="cycle-option" data-cycle="hourly" onclick="selectCycle(this)">
<div class="cycle-name"><i class="fas fa-hourglass-half"></i> Giờ</div>
<div class="cycle-price" id="cyclePriceHourly">Chọn cấu hình</div>
</div>
<div class="cycle-option" data-cycle="daily" onclick="selectCycle(this)">
<div class="cycle-name"><i class="fas fa-sun"></i> Ngày</div>
<div class="cycle-price" id="cyclePriceDaily">Chọn cấu hình</div>
</div>
<div class="cycle-option" data-cycle="weekly" onclick="selectCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-week"></i> Tuần</div>
<div class="cycle-price" id="cyclePriceWeekly">Chọn cấu hình</div>
</div>
<div class="cycle-option" data-cycle="monthly" onclick="selectCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-alt"></i> Tháng</div>
<div class="cycle-price" id="cyclePriceMonthly">Chọn cấu hình</div>
</div>
</div>
<div class="form-group" style="margin-top:12px;display:flex;align-items:center;gap:12px">
<label style="margin:0;white-space:nowrap;font-weight:600">Số lượng thuê:</label>
<input type="number" id="durationInput" name="duration" value="1" min="1" style="width:100px;padding:10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px" oninput="updateTotalPrice()">
<span style="color:#64748b;font-size:13px" id="durationLabel">phút</span>
</div>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<span style="font-weight:600;color:#1e293b">Tổng tiền:</span>
<span id="totalPriceDisplay" style="font-size:18px;font-weight:800;color:#2563eb">0 VNĐ</span>
</div>
<input type="hidden" name="billing_cycle" id="selectedCycle" value="minutely">
</div>
<div class="form-group">
<label><i class="fab fa-windows" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn hệ điều hành Windows</label>
<div class="os-options">
{% for os_key, os_val in windows_images.items() %}
<div class="os-option" data-os="{{ os_key }}" onclick="selectOS(this)">
<i class="fab fa-windows"></i>
<div style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ os_val.name }}</div>
</div>
{% endfor %}
</div>
<input type="hidden" name="windows" id="selectedOS" value="">
</div>
<div class="form-group">
<label><i class="fas fa-server" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn Server chạy VM</label>
<select name="node_id" id="selectedNode" style="width:100%;padding:11px 14px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;outline:none;background:#fff;color:#0f172a;">
{% for node_id, node in nodes.items() %}
{% if node.enabled %}
<option value="{{ node_id }}">{{ node.name }} {% if node.type == 'local' %}(Local){% else %}({{ node.host }}:{{ node.port }}){% endif %}</option>
{% endif %}
{% endfor %}
</select>
<small style="color:#64748b;font-size:12px;display:block;margin-top:6px"><i class="fas fa-info-circle"></i> Chọn máy chủ để chạy VM. Có thể chọn Local hoặc Worker Node đã kết nối.</small>
</div>
<div class="form-group">
<label><i class="fas fa-key" style="color:{{ settings.primary_color }};margin-right:6px"></i> Tailscale Auth Key (<span style="color:red">* Bắt buộc</span>)</label>
<input type="text" name="tailscale_key" placeholder="tskey-auth-xxxxxxxxxxxx" required>
<small style="color:#64748b;font-size:12px;display:block;margin-top:6px"><i class="fas fa-info-circle"></i> Lấy Auth Key tại bảng điều khiển tailscale.com để kích hoạt mạng RDP từ xa.</small>
</div>
<button type="submit" class="btn-submit" id="submitBtn"><i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay</button>
</form>
</div>
</div>
<div class="modal-overlay" id="renewModal">
<div class="modal" style="width:520px">
<div class="modal-header">
<h3><i class="fas fa-sync-alt" style="color:{{ settings.primary_color }}"></i> Gia hạn Máy ảo</h3>
<div class="modal-close" onclick="closeRenewModal()">&times;</div>
</div>
<form id="renewForm" onsubmit="return renewVM(event)">
<input type="hidden" name="vm_id" id="renewVmId">
<div class="form-group">
<label><i class="fas fa-clock" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn đơn vị gia hạn:</label>
<div class="cycle-options" style="grid-template-columns:repeat(5,1fr)">
<div class="cycle-option selected" data-cycle="minutely" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-stopwatch"></i> Phút</div>
<div class="cycle-price" id="renewPriceMinutely">--</div>
</div>
<div class="cycle-option" data-cycle="hourly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-hourglass-half"></i> Giờ</div>
<div class="cycle-price" id="renewPriceHourly">--</div>
</div>
<div class="cycle-option" data-cycle="daily" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-sun"></i> Ngày</div>
<div class="cycle-price" id="renewPriceDaily">--</div>
</div>
<div class="cycle-option" data-cycle="weekly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-week"></i> Tuần</div>
<div class="cycle-price" id="renewPriceWeekly">--</div>
</div>
<div class="cycle-option" data-cycle="monthly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-alt"></i> Tháng</div>
<div class="cycle-price" id="renewPriceMonthly">--</div>
</div>
</div>
<div class="form-group" style="margin-top:12px;display:flex;align-items:center;gap:12px">
<label style="margin:0;white-space:nowrap;font-weight:600">Số lượng gia hạn:</label>
<input type="number" id="renewDurationInput" name="duration" value="1" min="1" style="width:100px;padding:10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px" oninput="updateRenewTotal()">
<span style="color:#64748b;font-size:13px" id="renewDurationLabel">phút</span>
</div>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<span style="font-weight:600;color:#1e293b">Tổng tiền gia hạn:</span>
<span id="renewTotalDisplay" style="font-size:18px;font-weight:800;color:#2563eb">0 VNĐ</span>
</div>
<input type="hidden" name="billing_cycle" id="selectedRenewCycle" value="minutely">
</div>
<button type="submit" class="btn-submit" id="renewSubmitBtn"><i class="fas fa-check-circle"></i> Xác nhận Gia hạn</button>
</form>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:{{ settings.primary_color }}"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>
<script>
const vmConfigs = {{ vm_configs|tojson }};
function openRedeemModal(){ document.getElementById('redeemModal').classList.add('active'); }
function closeRedeemModal(){ document.getElementById('redeemModal').classList.remove('active'); }
window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const codeParam = urlParams.get('code');
    if(codeParam){ document.getElementById('giftCodeInput').value = codeParam; openRedeemModal(); }
});
function redeemKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/keys/redeem', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ closeRedeemModal(); showCenterNotice(d.message || 'Nhập Key thành công!', false, 1800, () => location.reload()); }
        else { showCenterNotice(d.error || 'Mã Giftcode không hợp lệ hoặc đã sử dụng!', true); }
    })
    .catch(err=>showCenterNotice('Lỗi kết nối máy chủ!', true));
    return false;
}
function openModal(){
    document.querySelectorAll('.config-option').forEach(e=>{
        e.classList.remove('selected');
        const icon = e.querySelector('.fa-check-circle');
        if(icon) icon.style.opacity = '0';
    });
    document.querySelectorAll('.os-option').forEach(e=>e.classList.remove('selected'));
    document.getElementById('selectedConfig').value = '';
    document.getElementById('selectedOS').value = '';
    document.getElementById('createModal').classList.add('active');
}
function closeModal(){ document.getElementById('createModal').classList.remove('active'); }
function showCenterNotice(msg, isError=false, duration=2200, callback=null){
    const overlay = document.getElementById('centerNotif');
    const icon = document.getElementById('centerNotifIcon');
    const msgEl = document.getElementById('centerNotifMsg');
    if(!overlay) return;
    msgEl.textContent = msg;
    if(isError){ icon.className = 'fas fa-exclamation-circle'; icon.style.color = '#c62828'; }
    else { icon.className = 'fas fa-check-circle'; icon.style.color = '#2e7d32'; }
    overlay.classList.add('active');
    setTimeout(() => { overlay.classList.remove('active'); if(callback) setTimeout(callback, 300); }, duration);
}
function selectConfig(el){
    document.querySelectorAll('.config-option').forEach(e=>{
        e.classList.remove('selected');
        const icon = e.querySelector('.fa-check-circle');
        if(icon) icon.style.opacity = '0';
    });
    el.classList.add('selected');
    const icon = el.querySelector('.fa-check-circle');
    if(icon) icon.style.opacity = '1';
    const val = el.dataset.config;
    document.getElementById('selectedConfig').value = val;
    updateCyclePrices(val);
}
function selectCycle(el){
    document.querySelectorAll('.cycle-option').forEach(e=>e.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('selectedCycle').value = el.dataset.cycle;
    updateTotalPrice();
}
function selectOS(el){
    document.querySelectorAll('.os-option').forEach(e=>e.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('selectedOS').value = el.dataset.os;
}
function updateCyclePrices(configKey){
    const cfg = vmConfigs[configKey];
    if(!cfg) return;
    document.getElementById('cyclePriceMinutely').innerText = (cfg.price_minutely||0).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('cyclePriceHourly').innerText = (cfg.price_hourly||0).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('cyclePriceDaily').innerText = (cfg.price_daily||0).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('cyclePriceWeekly').innerText = (cfg.price_weekly||0).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('cyclePriceMonthly').innerText = (cfg.price_monthly||0).toLocaleString('vi-VN') + ' VNĐ';
    updateTotalPrice();
}

function updateTotalPrice(){
    const configKey = document.getElementById('selectedConfig').value;
    const cycle = document.getElementById('selectedCycle').value;
    const dur = parseInt(document.getElementById('durationInput').value) || 1;
    const cfg = vmConfigs[configKey];
    if(!cfg) { document.getElementById('totalPriceDisplay').innerText = '0 VNĐ'; return; }
    const unitPrice = cfg['price_' + cycle] || 0;
    const total = unitPrice * dur;
    document.getElementById('totalPriceDisplay').innerText = total.toLocaleString('vi-VN') + ' VNĐ';
    const labels = {minutely:'phút', hourly:'giờ', daily:'ngày', weekly:'tuần', monthly:'tháng'};
    document.getElementById('durationLabel').innerText = labels[cycle] || '';
    // Cập nhật giá hiển thị trên config card đang chọn
    document.querySelectorAll('.config-option').forEach(el=>{
        if(el.dataset.config === configKey){
            const priceEl = el.querySelector('.cfg-price');
            if(priceEl) priceEl.innerText = unitPrice.toLocaleString('vi-VN') + ' VNĐ/' + (labels[cycle]||'');
        }
    });
}
function createVM(e){
    e.preventDefault();
    const configVal = document.getElementById('selectedConfig').value;
    const osVal = document.getElementById('selectedOS').value;
    if(!configVal){ showCenterNotice('Vui lòng chọn Cấu hình tài nguyên cho máy ảo!', true); return false; }
    if(!osVal){ showCenterNotice('Vui lòng chọn Hệ điều hành Windows!', true); return false; }
    const btn=document.getElementById('submitBtn');
    btn.disabled=true;
    btn.innerHTML='<i class="fas fa-spinner fa-spin"></i> Đang khởi tạo máy ảo...';
    const form=new FormData(e.target);
    fetch('/api/vm/create',{method:'POST',body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ closeModal(); showCenterNotice('Khởi tạo thành công máy ảo mới!', false, 1800, () => location.reload()); }
        else { showCenterNotice(d.error || 'Lỗi khởi tạo!', true); btn.disabled=false; btn.innerHTML='<i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay'; }
    })
    .catch(err=>{ showCenterNotice('Lỗi kết nối máy chủ!', true); btn.disabled=false; btn.innerHTML='<i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay'; });
    return false;
}
function startVM(id){ showCenterNotice('Đang gửi lệnh bật máy ảo...', false, 1200); fetch('/api/vm/'+id+'/start',{method:'POST'}).then(r=>r.json()).then(d=>{ if(d.success){ showCenterNotice('Đã phát lệnh bật VM thành công.', false, 1500, () => location.reload()); } else showCenterNotice(d.error || 'Thất bại!', true); }); }
function stopVM(id){ showCenterNotice('Đang gửi lệnh tắt máy ảo...', false, 1200); fetch('/api/vm/'+id+'/stop',{method:'POST'}).then(r=>r.json()).then(d=>{ if(d.success){ showCenterNotice('Đã phát lệnh tắt VM thành công.', false, 1500, () => location.reload()); } else showCenterNotice(d.error || 'Thất bại!', true); }); }
function deleteVM(id){ if(!confirm('Bạn có chắc chắn muốn xóa máy ảo này? Thao tác không thể hoàn tác.')) return; fetch('/api/vm/'+id+'/delete',{method:'POST'}).then(r=>r.json()).then(d=>{ if(d.success){ showCenterNotice('Đã xóa máy ảo thành công.', false, 1500, () => location.reload()); } else showCenterNotice(d.error || 'Thất bại!', true); }); }
function viewVM(id){ window.open('/vm/'+id+'/logs','_blank','width=900,height=700'); }
let currentRenewPrices = {};
function openRenewModal(vmId, pMinutely, pHourly, pDaily, pWeekly, pMonthly){
    document.getElementById('renewVmId').value = vmId;
    currentRenewPrices = {minutely:pMinutely||0, hourly:pHourly||0, daily:pDaily||0, weekly:pWeekly||0, monthly:pMonthly||0};
    document.getElementById('renewPriceMinutely').innerText = Number(currentRenewPrices.minutely).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('renewPriceHourly').innerText = Number(currentRenewPrices.hourly).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('renewPriceDaily').innerText = Number(currentRenewPrices.daily).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('renewPriceWeekly').innerText = Number(currentRenewPrices.weekly).toLocaleString('vi-VN') + ' VNĐ';
    document.getElementById('renewPriceMonthly').innerText = Number(currentRenewPrices.monthly).toLocaleString('vi-VN') + ' VNĐ';
    document.querySelectorAll('#renewModal .cycle-option').forEach(e=>e.classList.remove('selected'));
    document.querySelector('#renewModal .cycle-option[data-cycle="minutely"]').classList.add('selected');
    document.getElementById('selectedRenewCycle').value = 'minutely';
    document.getElementById('renewDurationInput').value = 1;
    updateRenewTotal();
    document.getElementById('renewModal').classList.add('active');
}
function updateRenewTotal(){
    const cycle = document.getElementById('selectedRenewCycle').value;
    const dur = parseInt(document.getElementById('renewDurationInput').value) || 1;
    const unitPrice = currentRenewPrices[cycle] || 0;
    const total = unitPrice * dur;
    document.getElementById('renewTotalDisplay').innerText = total.toLocaleString('vi-VN') + ' VNĐ';
    const labels = {minutely:'phút', hourly:'giờ', daily:'ngày', weekly:'tuần', monthly:'tháng'};
    document.getElementById('renewDurationLabel').innerText = labels[cycle] || '';
}
function closeRenewModal(){ document.getElementById('renewModal').classList.remove('active'); }
function selectRenewCycle(el){
    document.querySelectorAll('#renewModal .cycle-option').forEach(e=>e.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('selectedRenewCycle').value = el.dataset.cycle;
    updateRenewTotal();
}
function renewVM(e){
    e.preventDefault();
    const btn = document.getElementById('renewSubmitBtn');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang gia hạn...';
    const form = new FormData(e.target);
    const vmId = document.getElementById('renewVmId').value;
    fetch('/api/vm/' + vmId + '/renew', {method:'POST', body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success){ closeRenewModal(); showCenterNotice(d.message || 'Gia hạn thành công!', false, 1800, ()=>location.reload()); }
        else { showCenterNotice(d.error || 'Gia hạn thất bại!', true); btn.disabled=false; btn.innerHTML='<i class="fas fa-check-circle"></i> Xác nhận Gia hạn'; }
    }).catch(err=>{ showCenterNotice('Lỗi kết nối máy chủ!', true); btn.disabled=false; btn.innerHTML='<i class="fas fa-check-circle"></i> Xác nhận Gia hạn'; });
    return false;
}
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>

<!-- MODAL CẢNH BÁO HẾT HẠN -->
<div class="modal-overlay" id="expiryAlertModal" style="z-index:4000;background:rgba(15,23,42,0.85)">
<div class="modal" style="width:520px;text-align:center;border-top:5px solid #dc2626">
<div class="modal-header" style="border-bottom:none;justify-content:center">
<h3 style="color:#dc2626;font-size:20px"><i class="fas fa-exclamation-triangle"></i> CẢNH BÁO: Máy ảo sắp hết hạn</h3>
</div>
<div style="font-size:15px;color:#334155;margin-bottom:20px;line-height:1.6">
Máy ảo <strong id="expiryVmName" style="color:#0f172a"></strong> sẽ hết hạn sau <strong id="expiryTimeLeft" style="color:#dc2626;font-size:18px"></strong>.<br>
Vui lòng chọn hành động ngay bây giờ!
</div>
<div style="background:#fee2e2;border:1px solid #fecaca;color:#991b1b;padding:10px;border-radius:8px;margin-bottom:20px;font-weight:600;font-size:13px">
<i class="fas fa-stopwatch"></i> Tự động dừng & xóa sau: <span id="expiryAutoDelete" style="font-size:18px;font-family:monospace">02:00</span> nếu không chọn
</div>
<div style="display:flex;gap:12px;justify-content:center">
<button class="btn-submit" style="background:#dc2626;flex:1" onclick="expiryChooseNoRenew()"><i class="fas fa-trash"></i> Không gia hạn (Xóa VM)</button>
<button class="btn-submit" style="background:#16a34a;flex:1" onclick="expiryChooseRenew()"><i class="fas fa-sync-alt"></i> Gia hạn ngay</button>
</div>
</div>
</div>

<script>
(function(){
  const WARNING_SECONDS = 600; // 10 phút cảnh báo
  const AUTO_DELETE_SECONDS = 120; // 2 phút tự động xóa
  let expiryModalActive = false;
  let expiryAutoDeleteTimer = null;
  let currentExpiryVmId = null;
  let currentExpiryVmName = "";

  function formatCountdown(ms){
    if(ms <= 0) return "00:00:00";
    const totalSec = Math.floor(ms/1000);
    const h = Math.floor(totalSec/3600);
    const m = Math.floor((totalSec%3600)/60);
    const s = totalSec%60;
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }

  function updateCountdowns(){
    const now = new Date().getTime();
    document.querySelectorAll('.vm-card[data-expiry]').forEach(card=>{
      const expiry = card.dataset.expiry;
      const vmId = card.dataset.vmId;
      const vmName = card.dataset.name;
      const row = card.querySelector('.countdown-row');
      const txt = card.querySelector('.countdown-text');
      if(!expiry || expiry === ""){ if(row) row.style.display='none'; return; }
      const end = new Date(expiry).getTime();
      const diff = end - now;
      if(row) row.style.display = 'flex';
      if(txt) txt.textContent = formatCountdown(diff);
      if(diff <= 0 && txt){ txt.style.color = '#dc2626'; txt.textContent = "ĐÃ HẾT HẠN"; }
      else if(diff <= WARNING_SECONDS*1000 && txt){ txt.style.color = '#dc2626'; }
      else if(txt){ txt.style.color = '#0369a1'; }

      // Cảnh báo modal khi trong khoảng 0 -> 10 phút
      if(diff <= WARNING_SECONDS*1000 && diff > 0 && !expiryModalActive){
        openExpiryAlert(vmId, vmName, diff);
      }
    });
  }

  function openExpiryAlert(vmId, vmName, diffMs){
    expiryModalActive = true;
    currentExpiryVmId = vmId;
    currentExpiryVmName = vmName;
    document.getElementById('expiryVmName').textContent = vmName;
    document.getElementById('expiryTimeLeft').textContent = formatCountdown(diffMs);
    document.getElementById('expiryAlertModal').classList.add('active');
    startAutoDeleteCountdown();
  }

  function startAutoDeleteCountdown(){
    let left = AUTO_DELETE_SECONDS;
    const el = document.getElementById('expiryAutoDelete');
    if(expiryAutoDeleteTimer) clearInterval(expiryAutoDeleteTimer);
    expiryAutoDeleteTimer = setInterval(()=>{
      left--;
      const m = Math.floor(left/60);
      const s = left%60;
      el.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
      if(left <= 0){
        clearInterval(expiryAutoDeleteTimer);
        expiryAutoDeleteTimer = null;
        document.getElementById('expiryAlertModal').classList.remove('active');
        expiryModalActive = false;
        // Tự động dừng rồi xóa
        if(currentExpiryVmId){
          fetch('/api/vm/'+currentExpiryVmId+'/stop',{method:'POST'})
          .then(()=>{
             setTimeout(()=>{
               fetch('/api/vm/'+currentExpiryVmId+'/delete',{method:'POST'})
               .then(()=>{ showCenterNotice('VM đã tự động dừng và xóa do hết hạn.',false,2000,()=>location.reload()); })
               .catch(()=>showCenterNotice('Lỗi tự động xóa VM!',true));
             }, 2000);
          })
          .catch(()=>showCenterNotice('Lỗi tự động dừng VM!',true));
        }
      }
    }, 1000);
  }

  window.expiryChooseRenew = function(){
    if(expiryAutoDeleteTimer){ clearInterval(expiryAutoDeleteTimer); expiryAutoDeleteTimer=null; }
    document.getElementById('expiryAlertModal').classList.remove('active');
    expiryModalActive = false;
    // Mở renewModal với vmId hiện tại
    const vm = document.querySelector('.vm-card[data-vm-id="'+currentExpiryVmId+'"]');
    if(vm){
      const cfgKey = vm.querySelector('.config-option')?.dataset?.config; // không có sẵn
      // Lấy giá từ card text
      openRenewModal(currentExpiryVmId, 0,0,0); // giá sẽ lấy từ server khi gọi? Không, ta truyền 0 và để renewModal tự fill từ vm data? Hiện tại openRenewModal cần giá. 
      // Thay vào đó, gọi API lấy giá hoặc dùng giá mặc định. Đơn giản: reload trang để lấy giá chuẩn.
      // Nhưng tốt hơn: ta sẽ gọi API lấy vm info
      fetch('/api/vm/'+currentExpiryVmId+'/info').then(r=>r.json()).then(d=>{
        if(d.success && d.config){
          openRenewModal(currentExpiryVmId, d.config.price_minutely||0, d.config.price_hourly||0, d.config.price_daily||0, d.config.price_weekly||0, d.config.price_monthly||0);
        } else {
          showCenterNotice('Không lấy được thông tin giá, vui lòng gia hạn thủ công.',true);
        }
      }).catch(()=>showCenterNotice('Lỗi kết nối khi lấy giá gia hạn.',true));
    }
  };

  window.expiryChooseNoRenew = function(){
    if(expiryAutoDeleteTimer){ clearInterval(expiryAutoDeleteTimer); expiryAutoDeleteTimer=null; }
    document.getElementById('expiryAlertModal').classList.remove('active');
    expiryModalActive = false;
    if(currentExpiryVmId){
      deleteVM(currentExpiryVmId);
    }
  };

  setInterval(updateCountdowns, 1000);
  updateCountdowns();
})();
</script>
</body>
</html>"""

MARKETPLACE_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chợ VPS - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;min-height:100vh;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e0e0e0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e0e0e0;color:{{ settings.primary_color }};}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#555;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:{{ settings.primary_color }};border-left:4px solid {{ settings.primary_color }};}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e0e0e0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:{{ settings.primary_color }};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.section-heading{font-size:20px;font-weight:700;margin:25px 0 15px;color:#1e293b;display:flex;align-items:center;gap:10px}
.vm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;margin-bottom:30px}
.vm-card{background:#ffffff;border:1px solid #e0e0e0;border-radius:10px;padding:20px;display:flex;flex-direction:column;justify-content:space-between;transition: all 0.2s;}
.vm-card:hover{box-shadow: 0 4px 12px rgba(0,0,0,0.05);}
.vm-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #f0f0f0}
.vm-header h4{font-size:16px;color:#333}
.vm-info-row{display:flex;justify-content:space-between;padding:5px 0;font-size:13px;color:#555}
.btn-buy{background:{{ settings.primary_color }};color:#fff;border:none;padding:10px;border-radius:6px;font-weight:600;cursor:pointer;width:100%;margin-top:15px;display:flex;align-items:center;justify-content:center;gap:6px;transition: background 0.2s;}
.btn-buy:hover{opacity:0.9}
.btn-buy.soldout{background:#ccc;cursor:not-allowed}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{background:#ffffff;border-radius:12px;padding:30px;width:480px;text-align:center;transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.modal-overlay.active .modal{transform: scale(1);}
.center-notif-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;z-index:3000;opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}
.btn-submit{width:100%;padding:12px;background:{{ settings.primary_color }};color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<div class="sidebar-menu">
<a href="/dashboard"><i class="fas fa-bullhorn"></i> Bảng tin chính</a>
<a href="/my-vms"><i class="fas fa-server"></i> Máy ảo của tôi</a>
<a href="/marketplace" class="active"><i class="fas fa-store"></i> Chợ VPS</a>
<a href="/deposit"><i class="fas fa-wallet"></i> Nạp tiền</a>
{% if role == 'admin' %}
<a href="/admin" style="color:#d97706"><i class="fas fa-user-shield"></i> Trang Quản Trị (Admin)</a>
{% endif %}
<a href="/logout"><i class="fas fa-sign-out-alt"></i> Đăng xuất</a>
</div>
<div class="sidebar-footer">
<div class="user-info">
<div class="user-avatar">{{ username[0]|upper }}</div>
<div>
<div style="font-weight:600;font-size:14px">{{ username }}</div>
<div style="font-size:12px;color:#666">Số dư: {{ balance|vnd }}</div>
</div>
</div>
</div>
</div>
<div class="main-content">
<div class="top-bar">
<h1><i class="fas fa-store"></i> Chợ VPS & Key Giảm Giá</h1>
</div>
<div class="section-heading"><i class="fas fa-key" style="color:#FF9800"></i> Gian Hàng Key / Giftcode (Mua để nhập vào Hộp Quà)</div>
<div class="vm-grid">
{% if shop_keys %}
{% for sk_code, sk in shop_keys.items() %}
<div class="vm-card">
<div>
<div class="vm-header">
<h4><i class="fas fa-key" style="color:#FF9800"></i> {{ sk.vps_name if sk.type == 'vps' else 'Key Cộng Tiền' }}</h4>
<span style="font-weight:700;color:#2e7d32">{{ sk.shop_price|vnd }}</span>
</div>
<div class="vm-info">
<div class="vm-info-row"><span>Loại Key:</span><strong>{{ 'Cấp VPS Nhập Tay' if sk.type == 'vps' else 'Cộng Số Tiền VNĐ' }}</strong></div>
{% if sk.type == 'money' %}
<div class="vm-info-row"><span>Giá trị nhận:</span><strong style="color:#2e7d32">+{{ sk.amount|vnd }}</strong></div>
{% else %}
<div class="vm-info-row"><span>Cấu hình:</span><strong>{{ sk.vps_cpu }}C / {{ sk.vps_ram }}G / {{ sk.vps_disk }}G</strong></div>
{% endif %}
<div class="vm-info-row"><span>Trạng thái:</span>
{% if sk._is_sold_out %}
<strong style="color:#c62828">Đã hết hàng</strong>
{% else %}
<strong style="color:#2e7d32">Còn hàng ({{ sk._shop_stock|default(1) }} Key)</strong>
{% endif %}
</div>
{% if sk._is_sold_out and sk.sold_out_at %}
<div class="vm-info-row"><span>Gỡ Shop sau:</span>
<strong class="shop-countdown" style="color:#d97706;font-family:monospace" data-start="{{ sk.sold_out_at }}" data-duration="{{ sk.shop_grace_minutes|default(2) }}">--</strong>
</div>
{% endif %}
</div>
</div>
{% if sk._is_sold_out %}
<button class="btn-buy soldout" disabled><i class="fas fa-ban"></i> Đã hết hàng</button>
{% else %}
<button class="btn-buy" style="background:#FF9800" onclick="openBuyKeyModal('{{ sk.code }}', '{{ sk.vps_name if sk.type == 'vps' else "Key " + sk.amount|string + " VNĐ" }}', '{{ sk.shop_price|vnd }}')"><i class="fas fa-shopping-cart"></i> Mua Key Ngay</button>
{% endif %}
</div>
{% endfor %}
{% else %}
<div style="grid-column:1/-1;background:#fff;padding:30px;text-align:center;border-radius:10px;border:1px solid #e0e0e0;color:#777">
<i class="fas fa-key" style="font-size:32px;margin-bottom:10px;color:#ccc"></i>
<p>Chưa có Key nào được đưa lên Chợ.</p>
</div>
{% endif %}
</div>
<div class="section-heading"><i class="fas fa-server" style="color:{{ settings.primary_color }}"></i> Danh Sách VPS Sẵn Có</div>
<div class="vm-grid">
{% if items %}
{% for item in items %}
<div class="vm-card">
<div>
<div class="vm-header">
<h4><i class="fab fa-windows" style="color:{{ settings.primary_color }}"></i> {{ item.name }}</h4>
<span style="font-weight:700;color:#2e7d32">{{ item.price_val|vnd }}</span>
</div>
<div class="vm-info">
<div class="vm-info-row"><span>Tên VPS:</span><strong>{{ item.name }}</strong></div>
<div class="vm-info-row"><span>Hệ điều hành:</span><strong>{{ item.os_name }}</strong></div>
<div class="vm-info-row"><span>Cấu hình máy:</span><strong>{{ item.cpu }} vCPU / {{ item.ram }} GB RAM / {{ item.disk }} GB SSD</strong></div>
<div class="vm-info-row"><span>Số lượng còn lại:</span><strong style="color: {% if item.quantity > 0 %}#2e7d32{% else %}#c62828{% endif %}">{{ item.quantity }}</strong></div>
</div>
</div>
{% if item.quantity > 0 %}
<button class="btn-buy" onclick="openBuyModal('{{ item.id }}', '{{ item.name }}', '{{ item.price_val|vnd }}')"><i class="fas fa-shopping-cart"></i> Mua ngay VPS này</button>
{% else %}
<button class="btn-buy soldout" disabled><i class="fas fa-ban"></i> Hết hàng</button>
{% endif %}
</div>
{% endfor %}
{% else %}
<div style="grid-column:1/-1;background:#fff;padding:30px;text-align:center;border-radius:10px;border:1px solid #e0e0e0;color:#777">
<i class="fas fa-store-slash" style="font-size:32px;margin-bottom:10px;color:#ccc"></i>
<p>Hiện chưa có VPS có sẵn nào trên Chợ.</p>
</div>
{% endif %}
</div>
</div>
<div class="modal-overlay" id="buyModal">
<div class="modal">
<h3 style="font-size:18px;margin-bottom:15px"><i class="fas fa-shopping-bag"></i> Xác nhận mua VPS: <span id="modalVmName" style="color:{{ settings.primary_color }}"></span></h3>
<div style="font-size:16px;font-weight:600;margin:25px 0;color:#333;">Bạn có chắc chắn muốn mua VPS này không?</div>
<form id="buyForm" onsubmit="buyVPS(event)">
<input type="hidden" id="modalItemId" name="item_id">
<button type="submit" class="btn-submit" id="buySubmitBtn"><i class="fas fa-check"></i> Xác nhận thanh toán & Tạo máy ảo</button>
<button type="button" onclick="closeBuyModal()" style="width:100%;padding:10px;background:#ccc;color:#333;border:none;border-radius:6px;margin-top:10px;cursor:pointer;font-weight:600">Huỷ bỏ</button>
</form>
</div>
</div>
<div class="modal-overlay" id="buyKeyModal">
<div class="modal">
<h3 style="font-size:18px;margin-bottom:15px"><i class="fas fa-key" style="color:#FF9800"></i> Mua Key: <span id="modalKeyName" style="color:#FF9800"></span></h3>
<div style="font-size:15px;margin:20px 0;color:#555;line-height:1.6">Sau khi mua, hệ thống sẽ cung cấp mã Key. Bạn có thể sao chép mã này và nhập vào phần **Hộp Quà** để nhận thưởng ngay lập tức!</div>
<form id="buyKeyForm" onsubmit="buyKeyShop(event)">
<input type="hidden" id="modalKeyCode" name="key_code">
<button type="submit" class="btn-submit" id="buyKeySubmitBtn" style="background:#FF9800"><i class="fas fa-check"></i> Xác nhận thanh toán mua Key</button>
<button type="button" onclick="closeBuyKeyModal()" style="width:100%;padding:10px;background:#ccc;color:#333;border:none;border-radius:6px;margin-top:10px;cursor:pointer;font-weight:600">Huỷ bỏ</button>
</form>
</div>
</div>
<div class="modal-overlay" id="successKeyModal">
<div class="modal" style="text-align:center;">
<i class="fas fa-check-circle" style="font-size:50px;color:#2e7d32;margin-bottom:15px"></i>
<h3 style="font-size:20px;color:#2e7d32;margin-bottom:10px">Mua Key thành công!</h3>
<p style="font-size:14px;color:#555;margin-bottom:15px">Mã Key của bạn:</p>
<div style="background:#f8f9fa;border:2px dashed #FF9800;padding:12px;border-radius:8px;font-size:18px;font-weight:bold;font-family:monospace;color:#d97706;letter-spacing:1.5px;margin-bottom:20px" id="purchasedKeyDisplay"></div>
<div style="display:flex;gap:10px;">
<button type="button" onclick="copyPurchasedKey()" class="btn-submit" style="background:{{ settings.primary_color }}"><i class="fas fa-copy"></i> Sao chép mã</button>
<button type="button" onclick="redeemPurchasedKey()" class="btn-submit" style="background:#FF9800"><i class="fas fa-gift"></i> Nhập luôn vào Hộp Quà</button>
</div>
</div>
</div>
<div class="modal-overlay" id="renewModal">
<div class="modal" style="width:520px">
<div class="modal-header">
<h3><i class="fas fa-sync-alt" style="color:{{ settings.primary_color }}"></i> Gia hạn Máy ảo</h3>
<div class="modal-close" onclick="closeRenewModal()">&times;</div>
</div>
<form id="renewForm" onsubmit="return renewVM(event)">
<input type="hidden" name="vm_id" id="renewVmId">
<div class="form-group">
<label><i class="fas fa-clock" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn đơn vị gia hạn:</label>
<div class="cycle-options" style="grid-template-columns:repeat(5,1fr)">
<div class="cycle-option selected" data-cycle="minutely" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-stopwatch"></i> Phút</div>
<div class="cycle-price" id="renewPriceMinutely">--</div>
</div>
<div class="cycle-option" data-cycle="hourly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-hourglass-half"></i> Giờ</div>
<div class="cycle-price" id="renewPriceHourly">--</div>
</div>
<div class="cycle-option" data-cycle="daily" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-sun"></i> Ngày</div>
<div class="cycle-price" id="renewPriceDaily">--</div>
</div>
<div class="cycle-option" data-cycle="weekly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-week"></i> Tuần</div>
<div class="cycle-price" id="renewPriceWeekly">--</div>
</div>
<div class="cycle-option" data-cycle="monthly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-alt"></i> Tháng</div>
<div class="cycle-price" id="renewPriceMonthly">--</div>
</div>
</div>
<div class="form-group" style="margin-top:12px;display:flex;align-items:center;gap:12px">
<label style="margin:0;white-space:nowrap;font-weight:600">Số lượng gia hạn:</label>
<input type="number" id="renewDurationInput" name="duration" value="1" min="1" style="width:100px;padding:10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px" oninput="updateRenewTotal()">
<span style="color:#64748b;font-size:13px" id="renewDurationLabel">phút</span>
</div>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<span style="font-weight:600;color:#1e293b">Tổng tiền gia hạn:</span>
<span id="renewTotalDisplay" style="font-size:18px;font-weight:800;color:#2563eb">0 VNĐ</span>
</div>
<input type="hidden" name="billing_cycle" id="selectedRenewCycle" value="minutely">
</div>
<button type="submit" class="btn-submit" id="renewSubmitBtn"><i class="fas fa-check-circle"></i> Xác nhận Gia hạn</button>
</form>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:{{ settings.primary_color }}"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>
<script>
let lastPurchasedCode = '';
function openBuyModal(id, name, priceFormatted){
    document.getElementById('modalItemId').value = id;
    document.getElementById('modalVmName').innerText = name + " (" + priceFormatted + ")";
    document.getElementById('buyModal').classList.add('active');
}
function closeBuyModal(){ document.getElementById('buyModal').classList.remove('active'); }
function openBuyKeyModal(code, name, priceFormatted){
    document.getElementById('modalKeyCode').value = code;
    document.getElementById('modalKeyName').innerText = name + " (" + priceFormatted + ")";
    document.getElementById('buyKeyModal').classList.add('active');
}
function closeBuyKeyModal(){ document.getElementById('buyKeyModal').classList.remove('active'); }
function showCenterNotice(msg, isError=false, duration=2200, callback=null){
    const overlay = document.getElementById('centerNotif');
    const icon = document.getElementById('centerNotifIcon');
    const msgEl = document.getElementById('centerNotifMsg');
    if(!overlay) return;
    msgEl.textContent = msg;
    if(isError){ icon.className = 'fas fa-exclamation-circle'; icon.style.color = '#c62828'; }
    else { icon.className = 'fas fa-check-circle'; icon.style.color = '#2e7d32'; }
    overlay.classList.add('active');
    setTimeout(() => { overlay.classList.remove('active'); if(callback) setTimeout(callback, 300); }, duration);
}
function buyVPS(e){
    e.preventDefault();
    const btn = document.getElementById('buySubmitBtn');
    btn.disabled = true;
    btn.innerText = 'Đang xử lý mua & khởi tạo...';
    const form = new FormData(e.target);
    const itemId = document.getElementById('modalItemId').value;
    fetch('/api/marketplace/' + itemId + '/buy', {method: 'POST', body: form})
    .then(r => r.json())
    .then(d => {
        if(d.success){ closeBuyModal(); showCenterNotice('Mua và khởi tạo VPS thành công!', false, 1800, () => { window.location.href = '/my-vms'; }); }
        else { showCenterNotice(d.error || 'Lỗi mua VPS!', true); btn.disabled = false; btn.innerText = 'Xác nhận thanh toán & Tạo máy ảo'; }
    })
    .catch(err => { showCenterNotice('Lỗi kết nối máy chủ!', true); btn.disabled = false; btn.innerText = 'Xác nhận thanh toán & Tạo máy ảo'; });
    return false;
}
function buyKeyShop(e){
    e.preventDefault();
    const btn = document.getElementById('buyKeySubmitBtn');
    btn.disabled = true;
    btn.innerText = 'Đang xử lý thanh toán...';
    const keyCode = document.getElementById('modalKeyCode').value;
    const form = new FormData();
    form.append('code', keyCode);
    fetch('/api/marketplace/buy-key', {method: 'POST', body: form})
    .then(r => r.json())
    .then(d => {
        closeBuyKeyModal();
        if(d.success){
            lastPurchasedCode = keyCode;
            document.getElementById('purchasedKeyDisplay').innerText = keyCode;
            document.getElementById('successKeyModal').classList.add('active');
        } else {
            showCenterNotice(d.error || 'Lỗi mua Key!', true);
            btn.disabled = false;
            btn.innerText = 'Xác nhận thanh toán mua Key';
        }
    })
    .catch(err => {
        closeBuyKeyModal();
        showCenterNotice('Lỗi kết nối máy chủ!', true);
        btn.disabled = false;
        btn.innerText = 'Xác nhận thanh toán mua Key';
    });
    return false;
}
function copyPurchasedKey(){
    navigator.clipboard.writeText(lastPurchasedCode).then(() => {
        showCenterNotice('Đã sao chép mã Key vào bộ nhớ tạm!', false, 1500);
    });
}
function redeemPurchasedKey(){
    window.location.href = '/dashboard?code=' + encodeURIComponent(lastPurchasedCode);
}

// Shop countdown updater
(function(){
  function updateShopCountdowns(){
    const now = Math.floor(Date.now()/1000);
    document.querySelectorAll('.shop-countdown').forEach(el=>{
      const start = parseFloat(el.dataset.start);
      const duration = parseInt(el.dataset.duration) || 2;
      const elapsed = now - start;
      const left = duration*60 - elapsed;
      if(left <= 0){
        el.textContent = "Đang gỡ...";
        el.style.color = "#999";
      } else {
        const m = Math.floor(left/60);
        const s = Math.floor(left%60);
        el.textContent = `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
      }
    });
  }
  setInterval(updateShopCountdowns, 1000);
  updateShopCountdowns();
})();
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

DEPOSIT_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nạp tiền tài khoản - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;min-height:100vh;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e0e0e0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e0e0e0;color:{{ settings.primary_color }};}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#555;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:{{ settings.primary_color }};border-left:4px solid {{ settings.primary_color }};}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e0e0e0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:{{ settings.primary_color }};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.deposit-container{display:grid;grid-template-columns: 1fr 1fr;gap:25px}
@media(max-width:900px){.deposit-container{grid-template-columns:1fr}}
.card{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:25px;box-shadow:0 4px 12px rgba(0,0,0,0.03)}
.card h3{font-size:18px;font-weight:700;color:#1e293b;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.amounts-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:20px}
.amount-btn{padding:16px;border:2px solid #e2e8f0;border-radius:10px;background:#fafafa;cursor:pointer;text-align:center;transition:all 0.2s ease;display:flex;flex-direction:column;gap:5px;}
.amount-btn:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-2px)}
.amount-btn.selected{border-color:{{ settings.primary_color }};background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15)}
.amount-btn .real-val{font-size:18px;font-weight:800;color:#1e293b}
.amount-btn .web-val{font-size:13px;font-weight:600;color:#2e7d32}
.bank-info-box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:15px;margin-bottom:15px;font-size:14px;line-height:1.6}
.bank-info-row{display:flex;justify-content:space-between;margin-bottom:8px}
.qr-box{text-align:center;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:20px}
.qr-box img{max-width:260px;height:auto;border-radius:8px;border:1px solid #eee;margin-bottom:15px}
.transfer-note{background:#fffbeb;border:1px solid #fde68a;color:#92400e;padding:12px;border-radius:8px;font-size:13.5px;font-weight:600;text-align:center;margin-top:15px}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> {{ settings.site_name }}</div>
<div class="sidebar-menu">
<a href="/dashboard"><i class="fas fa-bullhorn"></i> Bảng tin chính</a>
<a href="/my-vms"><i class="fas fa-server"></i> Máy ảo của tôi</a>
<a href="/marketplace"><i class="fas fa-store"></i> Chợ VPS</a>
<a href="/deposit" class="active"><i class="fas fa-wallet"></i> Nạp tiền</a>
{% if role == 'admin' %}
<a href="/admin" style="color:#d97706"><i class="fas fa-user-shield"></i> Trang Quản Trị (Admin)</a>
{% endif %}
<a href="/logout"><i class="fas fa-sign-out-alt"></i> Đăng xuất</a>
</div>
<div class="sidebar-footer">
<div class="user-info">
<div class="user-avatar">{{ username[0]|upper }}</div>
<div>
<div style="font-weight:600;font-size:14px">{{ username }}</div>
<div style="font-size:12px;color:#666">Số dư: {{ balance|vnd }}</div>
</div>
</div>
</div>
</div>
<div class="main-content">
<div class="top-bar">
<h1><i class="fas fa-wallet" style="color:{{ settings.primary_color }}"></i> Nạp tiền vào tài khoản</h1>
</div>
<div style="background:linear-gradient(135deg, #e0f2fe 0%, #dbeafe 100%);border:1px solid #93c5fd;color:#1e40af;padding:15px 20px;border-radius:10px;margin-bottom:25px;font-weight:600;display:flex;align-items:center;gap:12px">
<i class="fas fa-bolt" style="font-size:24px;color:#2563eb"></i>
<div>
Ưu đãi nạp tiền tự động: <strong>10.000 VNĐ tiền thật = 12.000 VNĐ tiền web</strong> (+20% giá trị). Hệ thống cộng tiền tự động qua web ngay khi chuyển khoản thành công!
</div>
</div>
<div class="deposit-container">
<div class="card">
<h3><i class="fas fa-hand-pointer" style="color:{{ settings.primary_color }}"></i> Bước 1: Chọn mệnh giá nạp</h3>
<div class="amounts-grid">
<div class="amount-btn selected" data-amount="10000" onclick="selectAmount(10000)">
<div class="real-val">10.000 VNĐ</div>
<div class="web-val">Nhận 12.000 VNĐ web</div>
</div>
<div class="amount-btn" data-amount="20000" onclick="selectAmount(20000)">
<div class="real-val">20.000 VNĐ</div>
<div class="web-val">Nhận 24.000 VNĐ web</div>
</div>
<div class="amount-btn" data-amount="50000" onclick="selectAmount(50000)">
<div class="real-val">50.000 VNĐ</div>
<div class="web-val">Nhận 60.000 VNĐ web</div>
</div>
<div class="amount-btn" data-amount="100000" onclick="selectAmount(100000)">
<div class="real-val">100.000 VNĐ</div>
<div class="web-val">Nhận 120.000 VNĐ web</div>
</div>
</div>
<div class="bank-info-box">
<div class="bank-info-row"><span>Ngân hàng:</span><strong>BIDV</strong></div>
<div class="bank-info-row"><span>Số tài khoản:</span><strong style="color:#2563eb;font-family:monospace">96247JBL40</strong></div>
<div class="bank-info-row"><span>Chủ tài khoản:</span><strong>TRAN THANH TRUNG</strong></div>
<div class="bank-info-row"><span>Nội dung chuyển khoản:</span><strong style="color:#d97706;font-family:monospace" id="transferSyntax">NAP {{ username }}</strong></div>
</div>
<div style="font-size:12.5px;color:#64748b;line-height:1.5">
<i class="fas fa-info-circle"></i> Vui lòng quét mã QR bên cạnh và giữ nguyên nội dung chuyển khoản để hệ thống tự động ghi có vào tài khoản trong vòng 1-3 phút.
</div>
</div>
<div class="card">
<h3><i class="fas fa-qrcode" style="color:{{ settings.primary_color }}"></i> Bước 2: Quét mã QR thanh toán</h3>
<div class="qr-box">
<img id="qrImage" src="https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=10000&showinfo=true&holder=TRAN%20THANH%20TRUNG&des=NAP%20{{ username|urlencode }}" alt="VietQR Nạp tiền">
<div style="font-weight:700;font-size:16px;color:#1e293b" id="qrAmountText">Số tiền: 10.000 VNĐ</div>
<div class="transfer-note" id="qrSyntaxNote">Nội dung: NAP {{ username }}</div>
</div>
</div>
</div>
</div>
<script>
const username = "{{ username }}";
const qrLinks = {
    "10000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=10000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "20000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=20000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "50000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=50000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "100000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=100000&showinfo=true&holder=TRAN%20THANH%20TRUNG"
};
function buildQrUrl(amount){
    const baseUrl = qrLinks[String(amount)] || qrLinks["10000"];
    return baseUrl + "&des=" + encodeURIComponent("NAP " + username);
}
function selectAmount(amount){
    document.querySelectorAll('.amount-btn').forEach(btn => {
        btn.classList.remove('selected');
        if(btn.dataset.amount == amount){ btn.classList.add('selected'); }
    });
    document.getElementById('qrImage').src = buildQrUrl(amount);
    document.getElementById('qrAmountText').innerText = "Số tiền: " + Number(amount).toLocaleString('vi-VN') + " VNĐ";
    document.getElementById('qrSyntaxNote').innerText = "Nội dung: NAP " + username;
}
document.addEventListener('DOMContentLoaded', function(){
    const selected = document.querySelector('.amount-btn.selected');
    selectAmount(selected ? selected.dataset.amount : 10000);
});
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""


ADMIN_USER_VMS_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VM của User: {{ target_user.username }} - Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;padding:20px;}
.container{max-width:1200px;margin:0 auto;background:#fff;padding:30px;border-radius:10px;border:1px solid #e0e0e0;box-shadow:0 4px 6px rgba(0,0,0,0.05)}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}
h1{font-size:22px;color:#1a237e}
.btn-back{background:{{ settings.primary_color }};color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.badge-admin{background:#ffebee;color:#c62828;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700}
.badge-user{background:#e3f2fd;color:#1565c0;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700}
.user-info-bar{background:#f8f9fa;border:1px solid #e0e0e0;border-radius:8px;padding:15px;margin-bottom:25px;display:flex;gap:30px;flex-wrap:wrap}
.user-info-bar div{font-size:14px}
.user-info-bar strong{color:#1a237e}
.vm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
.vm-card{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:20px;transition: all 0.25s ease;display:flex;flex-direction:column;justify-content:space-between;}
.vm-card:hover{box-shadow: 0 8px 20px rgba(0,0,0,0.08);border-color:{{ settings.primary_color }};}
.vm-header{display:flex;justify-content:space-between;align-items:center;padding-bottom:12px;margin-bottom:12px;border-bottom:1px solid #f1f5f9}
.vm-header h4{font-size:16px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:8px}
.vm-status{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600}
.vm-status .status-dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.vm-status.running{background:#dcfce7;color:#15803d}
.vm-status.running .status-dot{background:#22c55e;animation: pulse 1.8s infinite;}
.vm-status.creating{background:#fef3c7;color:#b45309}
.vm-status.creating .status-dot{background:#f59e0b}
.vm-status.stopped{background:#fee2e2;color:#b91c1c}
.vm-status.stopped .status-dot{background:#ef4444}
.vm-status.expired{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}
.vm-status.expired .status-dot{background:#ef4444;animation: none;}
.btn-renew{background:#dcfce7;color:#15803d;flex:1}
.btn-renew:hover{opacity:0.88;transform:translateY(-1px)}
@keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } 100% { opacity: 1; transform: scale(1); } }
.vm-info{display:flex;flex-direction:column;gap:8px;font-size:13px}
.vm-info-row{display:flex;justify-content:space-between;color:#64748b}
.vm-actions{display:flex;gap:8px;margin-top:16px}
.vm-actions a,.vm-actions button{flex:1;padding:8px 12px;border-radius:6px;border:none;font-size:12px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:5px;transition: all 0.2s;text-decoration:none}
.vm-actions a:hover,.vm-actions button:hover{opacity:0.88;transform:translateY(-1px)}
.btn-view{background:#dbeafe;color:#1d4ed8}
.btn-log{background:#e0f2f1;color:#00695c}
.btn-start{background:#dcfce7;color:#15803d}
.btn-stop{background:#fef3c7;color:#b45309}
.btn-delete{background:#fee2e2;color:#dc2626}
.empty-state{grid-column:1/-1;background:#fff;padding:40px;text-align:center;border-radius:12px;border:1px solid #e0e0e0;color:#777}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1><i class="fas fa-server"></i> Danh sách Máy ảo của User: <span style="color:{{ settings.primary_color }}">{{ target_user.username }}</span></h1>
<a href="/admin" class="btn-back"><i class="fas fa-arrow-left"></i> Quay lại Admin Panel</a>
</div>
<div class="user-info-bar">
<div><strong>User ID:</strong> <code>{{ target_user.id }}</code></div>
<div><strong>Email:</strong> {{ target_user.email }}</div>
<div><strong>Vai trò:</strong> {% if target_user.role == 'admin' %}<span class="badge-admin">Admin</span>{% else %}<span class="badge-user">User</span>{% endif %}</div>
<div><strong>Số dư:</strong> <span style="color:#2e7d32;font-weight:700">{{ target_user.balance|vnd }}</span></div>
<div><strong>Ngày tạo:</strong> {{ target_user.created_at[:10] if target_user.created_at else 'N/A' }}</div>
</div>
<div class="vm-grid">
{% if vms %}
{% for vm in vms %}
<div class="vm-card" data-vm-id="{{ vm.id }}" data-expiry="{{ vm.expiry_time }}" data-name="{{ vm.name }}">
<div>
<div class="vm-header">
<h4><i class="fab fa-windows" style="color:{{ settings.primary_color }};font-size:18px"></i> {{ vm.name }}</h4>
<span class="vm-status {{ vm.status }}"><span class="status-dot"></span> {{ vm.status_text }}</span>
</div>
<div class="vm-info">
<div class="vm-info-row"><span>VM ID:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.id }}</strong></div>
<div class="vm-info-row"><span>Hết hạn:</span><strong style="color:{% if vm.is_expired %}#dc2626{% else %}#d97706{% endif %}">{{ vm.expiry_text }}</strong></div>
<div class="vm-info-row"><span>Cấu hình:</span><strong style="color:#0f172a">{{ vm.cpu }} vCPU / {{ vm.ram }} GB RAM / {{ vm.disk }} GB SSD</strong></div>
<div class="vm-info-row"><span>Hệ điều hành:</span><strong style="color:#0f172a">{{ vm.os }}</strong></div>
<div class="vm-info-row"><span>Server:</span><strong style="color:#0f172a">{{ vm.node_name }}</strong></div>
<div class="vm-info-row"><span>Tài khoản RDP:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.user }}</strong></div>
<div class="vm-info-row"><span>Mật khẩu:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.password }}</strong></div>
<div class="vm-info-row"><span>Chu kỳ thuê:</span><strong style="color:#0f172a">{{ vm.billing_cycle }}</strong></div>
<div class="vm-info-row"><span>Tailscale Key:</span><strong style="color:#0f172a;font-family:monospace;font-size:11px">{{ vm.tailscale_key[:20] + '...' if vm.tailscale_key else 'N/A' }}</strong></div>
<div class="vm-info-row" style="background:#f1f5f9;padding:8px 10px;border-radius:6px;margin-top:4px">
<span>IP (Tailscale):</span>
{% if vm.tailscale_ip %}
<strong style="color:#16a34a;font-family:monospace">{{ vm.tailscale_ip }}</strong>
{% else %}
<span style="color:#d97706">Chưa có IP</span>
{% endif %}
</div>
<div class="vm-info-row"><span>Logs khóa:</span><strong style="color:{% if vm.logs_locked %}#c62828{% else %}#2e7d32{% endif %}">{% if vm.logs_locked %}Đang khóa{% else %}Đang mở{% endif %}</strong></div>
</div>
</div>
<div class="vm-actions">
<a href="/admin/vm/{{ target_user.id }}/{{ vm.id }}/view" class="btn-view"><i class="fas fa-eye"></i> Chi tiết</a>
<a href="/admin/vm/{{ target_user.id }}/{{ vm.id }}/logs" target="_blank" class="btn-log"><i class="fas fa-terminal"></i> Xem Log</a>
<button class="btn-delete" onclick="adminDeleteVM('{{ target_user.id }}', '{{ vm.id }}', '{{ vm.name }}')" title="Xóa VM"><i class="fas fa-trash"></i> Xóa</button>
</div>
</div>
{% endfor %}
{% else %}
<div class="empty-state">
<i class="fas fa-server" style="font-size:40px;margin-bottom:10px;color:#cbd5e1"></i>
<p>User này chưa có máy ảo nào.</p>
</div>
{% endif %}
</div>
</div>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""


ADMIN_VM_DETAIL_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>[Admin] Chi tiết VM: {{ vm.name }} - {{ settings.site_name }}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;padding:20px;}
.container{max-width:900px;margin:0 auto;background:#fff;padding:30px;border-radius:10px;border:1px solid #e0e0e0;box-shadow:0 4px 6px rgba(0,0,0,0.05)}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}
h1{font-size:22px;color:#1a237e}
.btn-back{background:{{ settings.primary_color }};color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:13px;text-decoration:none;display:inline-flex;align-items:center;gap:6px}
.badge-admin{background:#ffebee;color:#c62828;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:700}
.info-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px;margin-bottom:25px}
.info-card{background:#f8f9fa;border:1px solid #e0e0e0;border-radius:8px;padding:15px}
.info-card label{font-size:12px;color:#666;display:block;margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px}
.info-card .value{font-size:15px;font-weight:600;color:#1a237e}
.info-card .value-mono{font-family:monospace;font-size:14px;color:#0f172a;word-break:break-all}
.status-running{color:#15803d;font-weight:700}
.status-stopped{color:#b91c1c;font-weight:700}
.status-creating{color:#b45309;font-weight:700}
.logs-box{background:#0f172a;color:#38bdf8;padding:20px;border-radius:8px;font-family:monospace;font-size:13px;line-height:1.6;max-height:500px;overflow-y:auto;white-space:pre-wrap;word-wrap:break-word;margin-top:15px}
.actions-bar{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.actions-bar a,.actions-bar button{padding:10px 16px;border-radius:6px;border:none;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px;text-decoration:none;transition:all 0.2s}
.actions-bar a:hover,.actions-bar button:hover{opacity:0.88;transform:translateY(-1px)}
.btn-log{background:#1e293b;color:#fff}
.btn-user{background:#e3f2fd;color:#1565c0}
.btn-start{background:#dcfce7;color:#15803d}
.btn-stop{background:#fef3c7;color:#b45309}
.btn-toggle{background:#fff3e0;color:#e65100}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1><span class="badge-admin">ADMIN</span> Chi tiết Máy ảo: <span style="color:{{ settings.primary_color }}">{{ vm.name }}</span></h1>
<div style="display:flex;gap:10px">
<a href="/admin/user/{{ target_user.id }}/vms" class="btn-back"><i class="fas fa-arrow-left"></i> Quay lại</a>
<a href="/admin" class="btn-back" style="background:#475569"><i class="fas fa-user-shield"></i> Admin Panel</a>
</div>
</div>
<div class="info-grid">
<div class="info-card">
<label>User sở hữu</label>
<div class="value">{{ target_user.username }} <span style="font-size:12px;color:#666">({{ target_user.id }})</span></div>
</div>
<div class="info-card">
<label>Trạng thái VM</label>
<div class="value {% if realtime_status == 'running' %}status-running{% elif realtime_status == 'creating' %}status-creating{% else %}status-stopped{% endif %}">
<i class="fas fa-circle" style="font-size:8px"></i> {{ realtime_status|upper }}
</div>
</div>
<div class="info-card">
<label>VM ID</label>
<div class="value-mono">{{ vm_id }}</div>
</div>
<div class="info-card">
<label>Cấu hình</label>
<div class="value">{{ vm.config.cpu }} vCPU / {{ vm.config.ram }} GB RAM / {{ vm.config.disk }} GB SSD</div>
</div>
<div class="info-card">
<label>Hệ điều hành</label>
<div class="value">{{ vm.windows.name if vm.windows is mapping else vm.windows }}</div>
</div>
<div class="info-card">
<label>Tài khoản RDP</label>
<div class="value-mono">{{ vm.windows.user if vm.windows is mapping else 'Admin' }}</div>
</div>
<div class="info-card">
<label>Mật khẩu RDP</label>
<div class="value-mono" style="color:#c62828">{{ vm.windows.pass if vm.windows is mapping else 'Tam255Z' }}</div>
</div>
<div class="info-card">
<label>Tailscale IP</label>
<div class="value-mono" style="color:#15803d">{{ vm.tailscale_ip or 'Chưa có IP' }}</div>
</div>
<div class="info-card">
<label>Tailscale Auth Key</label>
<div class="value-mono" style="font-size:12px">{{ vm.tailscale_key or 'N/A' }}</div>
</div>
<div class="info-card">
<label>Chu kỳ thuê</label>
<div class="value">{{ vm.billing_cycle }} — Hết hạn: {{ vm.expiry_time[:16] if vm.expiry_time else 'Không giới hạn' }}</div>
</div>
<div class="info-card">
<label>Logs Lock</label>
<div class="value" style="color:{% if vm.logs_locked %}#c62828{% else %}#2e7d32{% endif %}">
{% if vm.logs_locked %}<i class="fas fa-lock"></i> Đang khóa{% else %}<i class="fas fa-lock-open"></i> Đang mở{% endif %}
</div>
</div>
<div class="info-card">
<label>Ngày tạo</label>
<div class="value">{{ vm.created_at[:16] if vm.created_at else 'N/A' }}</div>
</div>
<div class="info-card">
<label>Thời gian còn lại</label>
<div class="value" id="adminVmDetailCountdown" data-expiry="{{ vm.expiry_time }}" style="font-family:monospace;color:#0369a1">--</div>
</div>
</div>
<div class="actions-bar">
<a href="/admin/vm/{{ target_user.id }}/{{ vm_id }}/logs" target="_blank" class="btn-log"><i class="fas fa-terminal"></i> Mở Logs trong tab mới</a>
<a href="/admin/user/{{ target_user.id }}/vms" class="btn-user"><i class="fas fa-list"></i> Xem tất cả VM của user</a>
{% if vm.logs_locked %}
<button class="btn-toggle" onclick="toggleLogs(false)"><i class="fas fa-lock-open"></i> Mở khóa Logs</button>
{% else %}
<button class="btn-toggle" onclick="toggleLogs(true)"><i class="fas fa-lock"></i> Khóa Logs</button>
{% endif %}
<button class="btn-toggle" style="background:#fee2e2;color:#dc2626" onclick="adminDeleteVM()"><i class="fas fa-trash"></i> Xóa VM này</button>
</div>
<h3 style="font-size:16px;margin-bottom:10px;color:#1a237e"><i class="fas fa-file-alt"></i> Logs trực tiếp (Real-time view)</h3>
<div class="logs-box">{{ logs }}</div>
</div>
<script>
function toggleLogs(lock){
    const form = new FormData();
    form.append('user_id', '{{ target_user.id }}');
    form.append('vm_id', '{{ vm_id }}');
    form.append('lock', lock ? '1' : '0');
    fetch('/api/admin/vm/toggle-logs', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{ if(d.success) location.reload(); else alert(d.error||'Thất bại'); });
}
function adminDeleteVM(){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "{{ vm.name }}"?\n\nHành động này KHÔNG THỂ hoàn tác. Toàn bộ dữ liệu VM sẽ bị xóa vĩnh viễn.')) return;
    const form = new FormData();
    form.append('user_id', '{{ target_user.id }}');
    form.append('vm_id', '{{ vm_id }}');
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); window.location.href = '/admin/user/{{ target_user.id }}/vms'; }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

ADMIN_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quản trị hệ thống - {{ settings.site_name }} Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;padding:20px;}
.container{max-width:1200px;margin:0 auto;background:#fff;padding:30px;border-radius:10px;border:1px solid #e0e0e0;box-shadow:0 4px 6px rgba(0,0,0,0.05)}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}
h1{font-size:24px;color:#1a237e}
table{width:100%;border-collapse:collapse;margin-bottom:30px;font-size:13px}
th,td{padding:10px 12px;border:1px solid #eee;text-align:left;vertical-align:middle}
th{background:#f9f9f9;font-weight:600;color:#555}
.btn-action{padding:5px 10px;border-radius:4px;border:none;cursor:pointer;font-size:12px;font-weight:600;margin-right:2px;display:inline-flex;align-items:center;gap:4px;transition: opacity 0.2s;}
.btn-action:hover{opacity: 0.85;}
.btn-add{background:#4CAF50;color:#fff}
.btn-edit{background:{{ settings.primary_color }};color:#fff}
.btn-deduct{background:#FF9800;color:#fff}
.btn-role{background:#9C27B0;color:#fff}
.btn-del{background:#F44336;color:#fff}
.btn-lock{background:#607D8B;color:#fff}
.btn-unlock{background:#2e7d32;color:#fff}
.form-box{background:#f8f9fa;border:1px solid #e0e0e0;padding:20px;border-radius:8px;margin-bottom:30px}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:15px;margin-bottom:15px}
.form-group label{display:block;margin-bottom:6px;font-weight:500;font-size:13px}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:9px;border:1px solid #ccc;border-radius:6px;font-size:13px;outline:none}
.badge-admin{background:#ffebee;color:#c62828;padding:2px 6px;border-radius:4px;font-weight:700}
.badge-user{background:#e3f2fd;color:#1565c0;padding:2px 6px;border-radius:4px;font-weight:700}
.section-title{display:flex;justify-content:space-between;align-items:center;font-size:18px;margin-bottom:15px;color:#333}
.btn-plus{background:{{ settings.primary_color }};color:#fff;border:none;padding:6px 14px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{background:#ffffff;border-radius:12px;padding:25px;width:500px;max-height:90vh;overflow-y:auto;transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.modal-overlay.active .modal{transform: scale(1);}
.center-notif-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);display:flex;align-items:center;justify-content:center;z-index:3000;opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}
.config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:15px;margin-bottom:20px}
.config-card{border:1px solid #e0e0e0;border-radius:10px;padding:18px;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.04)}
.config-card h3{font-size:16px;color:#1a237e;margin-bottom:8px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.config-meta{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0;font-size:13px}
.config-meta div{background:#f7f9fc;padding:8px;border-radius:6px}
.config-price{font-size:20px;font-weight:800;color:{{ settings.primary_color }};margin:10px 0}
.small-note{font-size:12px;color:#777;margin-top:5px;line-height:1.5}
.badge-custom{background:#fff3e0;color:#e65100;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700}
.settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:15px;margin-bottom:20px}
.toggle-switch{position:relative;display:inline-block;width:44px;height:24px}
.toggle-switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background-color:#ccc;transition:.4s;border-radius:24px}
.slider:before{position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background-color:white;transition:.4s;border-radius:50%}
input:checked + .slider{background-color:{{ settings.primary_color }};}
input:checked + .slider:before{transform:translateX(20px)}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1><i class="fas fa-user-shield"></i> Trang Quản Trị Hệ Thống (Admin Panel)</h1>
<a href="/dashboard" style="text-decoration:none;color:{{ settings.primary_color }};font-weight:600"><i class="fas fa-arrow-left"></i> Quay lại Dashboard</a>
</div>

<!-- QUẢN LÝ NODE / WORKER -->
<div class="section-title">
<h2><i class="fas fa-network-wired" style="color:#2196F3"></i> Quản lý Máy chủ / Worker Nodes</h2>
<button class="btn-plus" type="button" onclick="openNodeModal()"><i class="fas fa-plus"></i> Thêm Worker Node</button>
</div>
<div class="form-box">
<div class="small-note" style="margin-bottom:15px">
<strong>Worker Node</strong> là máy chủ phụ chạy QEMU/KVM. Khi thêm node, hãy chạy file này ở mode <b>Worker (2)</b> trên máy phụ, sau đó nhập IP và Token vào đây.
</div>
<table>
<thead>
<tr>
<th>ID</th>
<th>Tên Server</th>
<th>Tunnel URL / Kết nối</th>
<th>Loại</th>
<th>Trạng thái</th>
<th>Hành động</th>
</tr>
</thead>
<tbody>
{% for node_id, node in nodes.items() %}
<tr>
<td><code>{{ node_id }}</code></td>
<td><strong>{{ node.name }}</strong></td>
<td>
{% if node.tunnel_url %}
<a href="{{ node.tunnel_url }}" target="_blank" style="color:#2196F3;font-size:12px;word-break:break-all">{{ node.tunnel_url }}</a>
{% elif node.type == 'local' %}
<span style="color:#666;font-size:12px">127.0.0.1:5000</span>
{% else %}
<span style="color:#999;font-size:12px"><i class="fas fa-hourglass-half"></i> Chờ Worker kết nối...</span>
{% endif %}
</td>
<td>{% if node.type == 'local' %}<span class="badge-user">Local</span>{% else %}<span class="badge-admin">Worker</span>{% endif %}</td>
<td>
{% if node._status.success %}
<span style="color:#2e7d32;font-weight:600"><i class="fas fa-check-circle"></i> Online</span>
<small style="color:#666;display:block">CPU: {{ node._status.cpu_percent }}% | RAM: {{ node._status.ram_percent }}%</small>
{% else %}
<span style="color:#c62828;font-weight:600"><i class="fas fa-times-circle"></i> Offline</span>
{% endif %}
</td>
<td>
{% if node_id != 'local' %}
<button class="btn-action btn-edit" onclick="testNode('{{ node_id }}')"><i class="fas fa-plug"></i> Test</button>
<button class="btn-action btn-del" onclick="deleteNode('{{ node_id }}')"><i class="fas fa-trash"></i> Xóa</button>
{% else %}
<span style="color:#888;font-size:12px">Mặc định</span>
{% endif %}
</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>

<!-- MODAL THÊM / SỬA NODE -->
<div class="modal-overlay" id="nodeModal">
<div class="modal">
<div class="modal-header">
<h3 id="nodeModalTitle" style="font-size:18px"><i class="fas fa-server" style="color:#2196F3"></i> Thêm Worker Node</h3>
<button type="button" onclick="closeNodeModal()" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
</div>
<form id="nodeForm" onsubmit="saveNode(event)">
<div class="form-group" style="margin-bottom:12px"><label>ID Node (vd: node1)</label><input id="nodeId" name="node_id" pattern="[A-Za-z0-9_-]+" required placeholder="node1"></div>
<div class="form-group" style="margin-bottom:12px"><label>Tên hiển thị</label><input id="nodeName" name="name" required placeholder="Server 1 - VPS HCM"></div>
<div class="form-group" style="margin-bottom:12px"><label>Worker Token (lấy từ máy Worker)</label><input id="nodeToken" name="token" placeholder="abc123..." required></div>
<div class="form-group" style="margin-bottom:15px">
<label style="display:flex;align-items:center;gap:8px;cursor:pointer">
<input type="checkbox" id="nodeEnabled" name="enabled" checked style="width:18px;height:18px"> Kích hoạt node
</label>
</div>
<div style="background:#fff3e0;border:1px solid #ffcc80;padding:10px;border-radius:6px;font-size:12px;color:#e65100;margin-bottom:12px">
<i class="fas fa-info-circle"></i> <strong>Không cần nhập IP!</strong> Worker sẽ tự động chạy tunnel và gửi URL về Master khi khởi động.
</div>
<button type="submit" class="btn-action btn-add" style="width:100%;padding:11px;justify-content:center;font-size:14px;margin-top:5px"><i class="fas fa-save"></i> Lưu Node</button>
</form>
</div>
</div>

<!-- CẤU HÌNH HỆ THỐNG -->
<div class="section-title">
<h2><i class="fas fa-cogs" style="color:#673AB7"></i> Cấu hình Hệ thống & Giao diện Web</h2>
</div>
<div class="form-box">
<form id="settingsForm" onsubmit="saveSettings(event)">
<div class="settings-grid">
<div class="form-group">
<label>Tên Website</label>
<input type="text" name="site_name" value="{{ settings.site_name }}" required>
</div>
<div class="form-group">
<label>Màu chủ đạo (hex)</label>
<input type="text" name="primary_color" value="{{ settings.primary_color }}" placeholder="#2196F3" required>
</div>
<div class="form-group">
<label>Thời gian gỡ đơn hàng Shop (phút)</label>
<input type="number" name="marketplace_cleanup_minutes" value="{{ settings.marketplace_cleanup_minutes|default(2) }}" min="1" required>
<small style="color:#64748b;font-size:12px">Sau số phút này, đơn hết hàng sẽ tự động biến mất khỏi Chợ VPS.</small>
</div>
<div class="form-group">
<label>Khóa logs VM mặc định</label>
<div style="display:flex;align-items:center;gap:10px;margin-top:8px">
<label class="toggle-switch">
<input type="checkbox" name="default_logs_locked" {% if settings.default_logs_locked %}checked{% endif %}>
<span class="slider"></span>
</label>
<span style="font-size:13px;color:#555">Bật = Khóa logs khi tạo VM mới</span>
</div>
</div>
<div class="form-group">
<label>Cho phép đăng ký</label>
<div style="display:flex;align-items:center;gap:10px;margin-top:8px">
<label class="toggle-switch">
<input type="checkbox" name="allow_registration" {% if settings.allow_registration %}checked{% endif %}>
<span class="slider"></span>
</label>
<span style="font-size:13px;color:#555">Bật = User mới có thể đăng ký</span>
</div>
</div>
<div class="form-group">
<label>Chế độ bảo trì</label>
<div style="display:flex;align-items:center;gap:10px;margin-top:8px">
<label class="toggle-switch">
<input type="checkbox" name="maintenance_mode" {% if settings.maintenance_mode %}checked{% endif %}>
<span class="slider"></span>
</label>
<span style="font-size:13px;color:#555">Bật = Chỉ Admin truy cập được</span>
</div>
</div>
</div>
<button type="submit" class="btn-action btn-add" style="padding:10px 20px;font-size:14px;"><i class="fas fa-save"></i> Lưu Cấu hình Hệ thống</button>
</form>
</div>

<!-- BẢNG TIN CHÍNH -->
<div class="section-title">
<h2><i class="fas fa-bullhorn" style="color:{{ settings.primary_color }}"></i> Quản lý Bảng tin chính (Thông báo Admin)</h2>
</div>
<div class="form-box">
<form id="announcementForm" onsubmit="saveAnnouncement(event)">
<div class="form-group" style="margin-bottom:12px;">
<label>Tiêu đề thông báo bảng tin:</label>
<input type="text" name="title" value="{{ announcement.title }}" placeholder="Nhập tiêu đề thông báo..." required>
</div>
<div class="form-group" style="margin-bottom:15px;">
<label>Nội dung thông báo:</label>
<textarea name="content" rows="4" placeholder="Nhập nội dung thông báo hệ thống..." required style="width:100%;padding:10px;border:1px solid #ccc;border-radius:6px;font-size:13px;outline:none;font-family:inherit;">{{ announcement.content }}</textarea>
</div>
<button type="submit" class="btn-action btn-add" style="padding:10px 20px;font-size:14px;"><i class="fas fa-paper-plane"></i> Đăng / Cập nhật Bảng tin</button>
</form>
</div>

<!-- QUẢN LÝ CẤU HÌNH VM / GIÁ BÁN -->
<div class="section-title">
<h2><i class="fas fa-sliders-h" style="color:#673AB7"></i> Quản lý cấu hình VM & Giá thuê</h2>
<button class="btn-plus" type="button" onclick="openConfigModal()"><i class="fas fa-plus"></i> Thêm cấu hình</button>
</div>
<div class="form-box">
<div class="small-note" style="margin-bottom:15px"><strong>Thay đổi tại đây sẽ áp dụng ngay cho ngườidùng.</strong> Giá theo giờ, ngày, tháng được dùng trực tiếp khi user bấm <b>Tạo VM mới</b>.</div>
<div class="config-grid">
{% for cfg_key, cfg in vm_configs.items() %}
<div class="config-card">
<h3><span>{{ cfg.name }} <span class="badge-custom">{{ cfg_key }}</span></span>
<span style="display:flex;gap:4px"><button class="btn-action btn-edit" type="button" onclick='editConfig({{ cfg_key|tojson }}, {{ cfg|tojson }})'><i class="fas fa-edit"></i></button>
<button class="btn-action btn-del" type="button" onclick='deleteConfig({{ cfg_key|tojson }})'><i class="fas fa-trash"></i></button></span></h3>
<div class="config-meta">
<div><b>CPU</b><br>{{ cfg.cpu }} vCPU</div>
<div><b>RAM</b><br>{{ cfg.ram }} GB</div>
<div><b>SSD</b><br>{{ cfg.disk }} GB</div>
<div><b>Mã gói</b><br><code>{{ cfg_key }}</code></div>
</div>
<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:10px;font-size:11px">
<div style="background:#f3e8ff;padding:6px;border-radius:6px;text-align:center"><div style="color:#7c3aed;font-weight:700">{{ cfg.price_minutely|vnd }}</div><div style="color:#555">/phút</div></div>
<div style="background:#e8f5e9;padding:6px;border-radius:6px;text-align:center"><div style="color:#2e7d32;font-weight:700">{{ cfg.price_hourly|vnd }}</div><div style="color:#555">/giờ</div></div>
<div style="background:#fff3e0;padding:6px;border-radius:6px;text-align:center"><div style="color:#e65100;font-weight:700">{{ cfg.price_daily|vnd }}</div><div style="color:#555">/ngày</div></div>
<div style="background:#fce7f3;padding:6px;border-radius:6px;text-align:center"><div style="color:#db2777;font-weight:700">{{ cfg.price_weekly|vnd }}</div><div style="color:#555">/tuần</div></div>
<div style="background:#e3f2fd;padding:6px;border-radius:6px;text-align:center"><div style="color:#1565c0;font-weight:700">{{ cfg.price_monthly|vnd }}</div><div style="color:#555">/tháng</div></div>
</div>
</div>
{% endfor %}
</div>
</div>

<!-- MODAL THÊM / SỬA CẤU HÌNH VM -->
<div class="modal-overlay" id="configModal">
<div class="modal">
<div class="modal-header">
<h3 id="configModalTitle" style="font-size:18px">Thêm cấu hình VM</h3>
<button type="button" onclick="closeConfigModal()" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
</div>
<form id="configForm" onsubmit="saveConfig(event)">
<input type="hidden" id="configOriginalKey" name="original_key">
<div class="form-group" style="margin-bottom:12px"><label>Mã cấu hình</label><input id="configKey" name="key" pattern="[A-Za-z0-9_-]+" required placeholder="vd: basic2"></div>
<div class="form-group" style="margin-bottom:12px"><label>Tên hiển thị</label><input id="configName" name="name" required placeholder="vd: Basic 2"></div>
<div class="form-row">
<div class="form-group"><label>vCPU</label><input id="configCpu" type="number" name="cpu" min="1" required></div>
<div class="form-group"><label>RAM (GB)</label><input id="configRam" type="number" name="ram" min="1" required></div>
<div class="form-group"><label>SSD (GB)</label><input id="configDisk" type="number" name="disk" min="1" required></div>
</div>
<div class="form-row">
<div class="form-group"><label>Giá / phút (VNĐ)</label><input id="configPriceMinutely" type="number" name="price_minutely" min="0" step="1" required></div>
<div class="form-group"><label>Giá / giờ (VNĐ)</label><input id="configPriceHourly" type="number" name="price_hourly" min="0" step="1" required></div>
<div class="form-group"><label>Giá / ngày (VNĐ)</label><input id="configPriceDaily" type="number" name="price_daily" min="0" step="1" required></div>
</div>
<div class="form-row">
<div class="form-group"><label>Giá / tuần (VNĐ)</label><input id="configPriceWeekly" type="number" name="price_weekly" min="0" step="1" required></div>
<div class="form-group"><label>Giá / tháng (VNĐ)</label><input id="configPriceMonthly" type="number" name="price_monthly" min="0" step="1" required></div>
</div>
<div class="small-note">Nhập đúng giá cho 5 đơn vị thuê: phút / giờ / ngày / tuần / tháng.</div>
<button type="submit" class="btn-action btn-add" style="width:100%;padding:11px;justify-content:center;font-size:14px;margin-top:15px"><i class="fas fa-save"></i> Lưu cấu hình</button>
</form>
</div>
</div>

<!-- QUẢN LÝ GIFTCODE / KEYS -->
<div class="section-title">
<h2><i class="fas fa-gift" style="color:#FF9800"></i> Quản lý Giftcode / Random Keys</h2>
</div>
<div class="form-box">
<h3 style="font-size:16px;margin-bottom:15px;color:#FF9800"><i class="fas fa-key"></i> Tạo Key Mới & Tùy chọn Đưa lên Chợ (Shop)</h3>
<form id="createKeyForm" onsubmit="createKey(event)">
<div class="form-row">
<div class="form-group" style="grid-column: span 2;">
<label>Mã Key (Nhập hoặc Bấm tạo Random)</label>
<div style="display:flex;gap:10px;">
<input type="text" name="code" id="key_code_input" placeholder="Ví dụ: WINBOX-8888-9999" style="font-weight:700;letter-spacing:1px;text-transform:uppercase;" required>
<button type="button" class="btn-action btn-edit" onclick="generateRandomKey()" style="white-space:nowrap;padding:0 15px;"><i class="fas fa-random"></i> Random Key</button>
</div>
</div>
<div class="form-group">
<label>Loại Key</label>
<select name="key_type" id="key_type_select" onchange="toggleKeyFields(this)" required>
<option value="money">Mục 1: Số tiền VNĐ (Money Key)</option>
<option value="vps">Mục 2: VPS Nhập Tay (VPS Key)</option>
</select>
</div>
</div>
<div id="key_money_fields" class="form-row">
<div class="form-group">
<label>Số tiền cộng khi user nhập (VNĐ)</label>
<input type="number" name="amount" placeholder="Ví dụ: 315000" value="315000">
</div>
</div>
<div id="key_vps_fields" style="display:none;">
<div class="form-row">
<div class="form-group"><label>Tên VPS</label><input type="text" name="vps_name" placeholder="VPS Gift VIP 01" value="VPS Gift Custom"></div>
<div class="form-group"><label>Tên OS</label><input type="text" name="vps_os" placeholder="Windows 10 LTSB" value="Windows 10 LTSB"></div>
<div class="form-group"><label>Địa chỉ IP</label><input type="text" name="vps_ip" placeholder="103.x.x.x"></div>
</div>
<div class="form-row">
<div class="form-group"><label>User VPS</label><input type="text" name="vps_user" placeholder="Administrator" value="Administrator"></div>
<div class="form-group"><label>Pass VPS</label><input type="text" name="vps_pass" placeholder="Pass123456" value="Pass123456"></div>
<div class="form-row">
<div class="form-group"><label>vCPU</label><input type="number" name="vps_cpu" value="2"></div>
<div class="form-group"><label>RAM (GB)</label><input type="number" name="vps_ram" value="4"></div>
<div class="form-group"><label>Disk (GB)</label><input type="number" name="vps_disk" value="50"></div>
</div>
</div>
</div>
<div class="form-row" style="margin-top:15px;background:#fff;padding:15px;border-radius:6px;border:1px solid #ddd">
<div class="form-group" style="display:flex;align-items:center;gap:10px;grid-column:span 2;">
<input type="checkbox" id="put_on_shop" name="put_on_shop" style="width:20px;height:20px;cursor:pointer">
<label for="put_on_shop" style="margin:0;font-weight:700;color:#2e7d32;cursor:pointer">Đưa Key này lên Chợ VPS để ngườidùng mua bằng số dư</label>
</div>
<div class="form-group" id="shop_price_group" style="display:none;">
<label>Giá bán trên Chợ (VNĐ)</label>
<input type="number" name="shop_price" placeholder="Ví dụ: 50000" value="50000">
</div>
<div class="form-group" id="shop_quantity_group" style="display:none;">
<label>Số lượng Key đưa lên Shop</label>
<input type="number" name="quantity" min="1" value="1" placeholder="Ví dụ: 10">
</div>
<div class="form-group" id="shop_grace_group" style="display:none;">
<label>Thờigian gỡ Shop khi hết hàng (phút)</label>
<input type="number" name="shop_grace_minutes" min="1" value="2" placeholder="Ví dụ: 2">
<small style="color:#64748b;font-size:12px">Key bán hết trên Chợ → chờ số phút này rồi gỡ xuống (Key vẫn còn để nhập).</small>
</div>
<div class="form-group">
<label>Thờigian sống Key sau khi nhập (phút)</label>
<input type="number" name="key_lifetime_minutes" min="1" value="60" placeholder="Ví dụ: 60">
<small style="color:#64748b;font-size:12px">Từ lần đầu user nhập Key, sau số phút này Key sẽ tự động bị XÓA hoàn toàn.</small>
</div>
<div class="form-group">
<label>Thờigian hiệu lực Key (ngày)</label>
<input type="number" name="key_validity_days" min="1" value="30" placeholder="Ví dụ: 30">
<small style="color:#64748b;font-size:12px">Key chỉ có thể nhập trong vòng X ngày kể từ khi tạo. Quá hạn = không nhập được.</small>
</div>
<div class="form-group">
<label>Số lần 1 User được nhập Key này</label>
<input type="number" name="max_uses_per_user" min="1" value="1" placeholder="Ví dụ: 3">
</div>
<div class="form-group">
<label>Tổng số lượt nhập tối đa (tất cả User)</label>
<input type="number" name="max_total_uses" min="1" value="1" placeholder="Ví dụ: 3">
<small style="color:#64748b;font-size:12px">Tổng số lần Key này có thể được nhập. Ví dụ: 3 = cho phép 3 ngườinhập (dùng chung 1 code).</small>
</div>
</div>
<button type="submit" class="btn-action btn-add" style="padding:10px 25px;font-size:14px;margin-top:10px;"><i class="fas fa-plus"></i> Tạo Key Mới</button>
</form>
</div>

<!-- DANH SÁCH KEYS -->
<div class="section-title">
<h2><i class="fas fa-key" style="color:{{ settings.primary_color }}"></i> Danh sách Giftcode / Keys hiện có</h2>
</div>
<table>
<thead>
<tr>
<th>Mã Code</th>
<th>Loại</th>
<th>Giá trị / Cấu hình</th>
<th>Trạng thái Shop</th>
<th>Gỡ Shop (phút)</th>
<th>Sống Key (phút)</th>
<th>Hiệu lực (ngày)</th>
<th>Số lần / User</th>
<th>Tổng lượt tối đa</th>
<th>Trạng thái sử dụng</th>
<th>Hành động</th>
</tr>
</thead>
<tbody>
{% if keys %}
{% for k_code, k in keys.items() %}
<tr>
<td><strong style="font-family:monospace;color:{{ settings.primary_color }}">{{ k_code }}</strong></td>
<td>{{ 'Tiền VNĐ' if k.type == 'money' else 'VPS Nhập Tay' }}</td>
<td>
{% if k.type == 'money' %}
+{{ k.amount|vnd }}
{% else %}
{{ k.vps_name }} ({{ k.vps_cpu }}C/{{ k.vps_ram }}G/{{ k.vps_disk }}G)
{% endif %}
</td>
<td>
{% if k.on_shop %}
<span style="color:#2e7d32;font-weight:600">Đang bán trên Chợ ({{ k.shop_price|vnd }})</span>
{% else %}
<span style="color:#666">Chỉ làm Giftcode</span>
{% endif %}
</td>
<td>
<span style="font-weight:600;color:#d97706">{{ k.shop_grace_minutes|default(2) }} phút</span>
{% if k.on_shop and k.used and k.sold_out_at %}
<div class="key-countdown" data-start="{{ k.sold_out_at }}" data-duration="{{ k.shop_grace_minutes|default(2) }}" data-mode="soldout" style="font-family:monospace;font-size:12px;color:#dc2626;margin-top:2px">--</div>
{% endif %}
</td>
<td>
<span style="font-weight:600;color:#0369a1">{{ k.key_lifetime_minutes|default(60) }} phút</span>
{% if k.redeemed_at %}
<div class="key-countdown" data-start="{{ k.redeemed_at }}" data-duration="{{ k.key_lifetime_minutes|default(60) }}" data-mode="redeemed" style="font-family:monospace;font-size:12px;color:#dc2626;margin-top:2px">--</div>
{% endif %}
</td>
<td>
<span style="font-weight:600;color:#7c3aed">{{ k.key_validity_days|default(30) }} ngày</span>
</td>
<td>
<strong style="color:#7c3aed">{{ k.max_uses_per_user|default(1) }} lần</strong>
</td>
<td>
<strong style="color:#d97706">{{ k.max_total_uses|default(1) }} lượt</strong><br>
<small style="color:#666">Đã dùng: {{ k.uses_by_user.values()|sum if k.uses_by_user else 0 }}</small>
</td>
<td>
{% if k.used %}
<span style="color:#c62828;font-weight:600">Đã dùng bởi {{ k.used_by }}</span>
{% else %}
<span style="color:#2e7d32;font-weight:600">Chưa sử dụng</span>
{% endif %}
</td>
<td>
<button class="btn-action btn-del" onclick="deleteKey('{{ k_code }}')"><i class="fas fa-trash"></i> Xóa</button>
</td>
</tr>
{% endfor %}
{% else %}
<tr><td colspan="11" style="text-align:center;color:#777">Chưa có Key nào trong hệ thống.</td></tr>
{% endif %}
</tbody>
</table>

<!-- QUẢN LÝ USER -->
<div class="section-title">
<h2><i class="fas fa-users" style="color:{{ settings.primary_color }}"></i> Quản lý Tài khoản ngườidùng</h2>
</div>
<table>
<thead>
<tr>
<th>Tên đăng nhập</th>
<th>Email</th>
<th>Vai trò</th>
<th>Số dư tài khoản</th>
<th>Ngày tạo</th>
<th>Hành động quản lý</th>
</tr>
</thead>
<tbody>
{% for uid, u in users.items() %}
<tr>
<td><strong>{{ u.username }}</strong></td>
<td>{{ u.email }}</td>
<td>
{% if u.role == 'admin' %}
<span class="badge-admin">Admin</span>
{% else %}
<span class="badge-user">User</span>
{% endif %}
</td>
<td style="font-weight:700;color:#2e7d32">{{ u.balance|vnd }}</td>
<td>{{ u.created_at[:10] if u.created_at else 'N/A' }}</td>
<td>
<button class="btn-action btn-add" onclick="openBalanceModal('{{ uid }}', '{{ u.username }}', 'add')"><i class="fas fa-plus"></i> Cộng tiền</button>
<button class="btn-action btn-deduct" onclick="openBalanceModal('{{ uid }}', '{{ u.username }}', 'deduct')"><i class="fas fa-minus"></i> Trừ tiền</button>
<button class="btn-action btn-edit" onclick="openPasswordModal('{{ uid }}', '{{ u.username }}')"><i class="fas fa-key"></i> Đổi Pass</button>
<a href="/admin/user/{{ uid }}/vms" class="btn-action btn-add" style="text-decoration:none;background:#1e293b"><i class="fas fa-server"></i> Xem VM</a>
{% if u.username != 'admin' %}
<button class="btn-action btn-role" onclick="toggleRole('{{ uid }}')"><i class="fas fa-user-shield"></i> Đổi Role</button>
<button class="btn-action btn-del" onclick="deleteUser('{{ uid }}')"><i class="fas fa-trash"></i> Xóa</button>
{% endif %}
</td>
</tr>
{% endfor %}
</tbody>
</table>

<!-- QUẢN LÝ LOGS VM -->
<div class="section-title">
<h2><i class="fas fa-lock" style="color:#c62828"></i> Quản lý Khóa / Mở Logs Máy ảo User</h2>
</div>
<div class="form-box">
<div class="small-note" style="margin-bottom:15px">Admin có thể khóa hoặc mở quyền xem logs cho từng VM. User chỉ xem được logs khi Admin mở khóa.</div>
<table>
<thead>
<tr>
<th>User</th>
<th>Tên VM</th>
<th>VM ID</th>
<th>Thời gian còn lại</th>
<th>Trạng thái Logs</th>
<th colspan="4">Hành động Quản lý</th>
</tr>
</thead>
<tbody>
{% for vm_info in all_vms %}
<tr>
<td><strong>{{ vm_info.username }}</strong></td>
<td>{{ vm_info.vm_name }}</td>
<td><code>{{ vm_info.vm_id }}</code></td>
<td data-expiry="{{ vm_info.expiry_time }}">
{% if vm_info.expiry_time %}
<span class="admin-countdown" style="font-family:monospace;font-weight:600;color:#0369a1">--</span>
{% else %}
<span style="color:#999;font-size:12px">Không giới hạn</span>
{% endif %}
</td>
<td>
{% if vm_info.logs_locked %}
<span style="color:#c62828;font-weight:600"><i class="fas fa-lock"></i> Đang khóa</span>
{% else %}
<span style="color:#2e7d32;font-weight:600"><i class="fas fa-lock-open"></i> Đang mở</span>
{% endif %}
</td>
<td data-expiry="{{ vm_info.expiry_time }}">
{% if vm_info.expiry_time %}
<span class="admin-countdown" style="font-family:monospace;font-weight:600;color:#0369a1">--</span>
{% else %}
<span style="color:#999;font-size:12px">Không giới hạn</span>
{% endif %}
</td>
<td>
{% if vm_info.logs_locked %}
<button class="btn-action btn-unlock" onclick="toggleVmLogs('{{ vm_info.user_id }}', '{{ vm_info.vm_id }}', false)"><i class="fas fa-lock-open"></i> Mở khóa</button>
{% else %}
<button class="btn-action btn-lock" onclick="toggleVmLogs('{{ vm_info.user_id }}', '{{ vm_info.vm_id }}', true)"><i class="fas fa-lock"></i> Khóa Logs</button>
{% endif %}
</td>
<td>
<a href="/admin/vm/{{ vm_info.user_id }}/{{ vm_info.vm_id }}/view" class="btn-action btn-edit" style="text-decoration:none"><i class="fas fa-eye"></i> Xem VM</a>
</td>
<td>
<a href="/admin/vm/{{ vm_info.user_id }}/{{ vm_info.vm_id }}/logs" target="_blank" class="btn-action btn-add" style="text-decoration:none;background:#1e293b"><i class="fas fa-terminal"></i> Xem Logs</a>
</td>
<td>
<button class="btn-action btn-del" onclick="adminDeleteVM('{{ vm_info.user_id }}', '{{ vm_info.vm_id }}', '{{ vm_info.vm_name }}')"><i class="fas fa-trash"></i> Xóa VM</button>
</td>
</tr>
{% endfor %}
</tbody>
</table>
</div>
</div>

<!-- MODAL CỘNG / TRỪ TIỀN -->
<div class="modal-overlay" id="balanceModal">
<div class="modal">
<div class="modal-header">
<h3 id="balanceModalTitle" style="font-size:18px">Cộng / Trừ tiền tài khoản</h3>
<button onclick="closeBalanceModal()" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
</div>
<form id="balanceForm" onsubmit="submitBalance(event)">
<input type="hidden" id="balanceUserId" name="user_id">
<input type="hidden" id="balanceActionType" name="action_type">
<div class="form-group" style="margin-bottom:15px">
<label id="balanceLabelText">Số tiền VNĐ:</label>
<input type="number" name="amount" placeholder="Ví dụ: 100000" required style="width:100%;padding:9px;border:1px solid #ccc;border-radius:6px">
</div>
<button type="submit" class="btn-action btn-add" style="width:100%;padding:10px;justify-content:center;font-size:14px">Xác nhận</button>
</form>
</div>
</div>

<!-- MODAL ĐỔI MẬT KHẨU -->
<div class="modal-overlay" id="passwordModal">
<div class="modal">
<div class="modal-header">
<h3 style="font-size:18px">Đổi mật khẩu ngườidùng</h3>
<button onclick="closePasswordModal()" style="background:none;border:none;font-size:20px;cursor:pointer">&times;</button>
</div>
<form id="passwordForm" onsubmit="submitPassword(event)">
<input type="hidden" id="passwordUserId" name="user_id">
<div class="form-group" style="margin-bottom:15px">
<label>Mật khẩu mới:</label>
<input type="password" name="new_password" placeholder="Nhập mật khẩu mới" required style="width:100%;padding:9px;border:1px solid #ccc;border-radius:6px">
</div>
<button type="submit" class="btn-action btn-edit" style="width:100%;padding:10px;justify-content:center;font-size:14px">Đổi Mật Khẩu</button>
</form>
</div>
</div>

<div class="modal-overlay" id="renewModal">
<div class="modal" style="width:520px">
<div class="modal-header">
<h3><i class="fas fa-sync-alt" style="color:{{ settings.primary_color }}"></i> Gia hạn Máy ảo</h3>
<div class="modal-close" onclick="closeRenewModal()">&times;</div>
</div>
<form id="renewForm" onsubmit="return renewVM(event)">
<input type="hidden" name="vm_id" id="renewVmId">
<div class="form-group">
<label><i class="fas fa-clock" style="color:{{ settings.primary_color }};margin-right:6px"></i> Chọn đơn vị gia hạn:</label>
<div class="cycle-options" style="grid-template-columns:repeat(5,1fr)">
<div class="cycle-option selected" data-cycle="minutely" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-stopwatch"></i> Phút</div>
<div class="cycle-price" id="renewPriceMinutely">--</div>
</div>
<div class="cycle-option" data-cycle="hourly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-hourglass-half"></i> Giờ</div>
<div class="cycle-price" id="renewPriceHourly">--</div>
</div>
<div class="cycle-option" data-cycle="daily" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-sun"></i> Ngày</div>
<div class="cycle-price" id="renewPriceDaily">--</div>
</div>
<div class="cycle-option" data-cycle="weekly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-week"></i> Tuần</div>
<div class="cycle-price" id="renewPriceWeekly">--</div>
</div>
<div class="cycle-option" data-cycle="monthly" onclick="selectRenewCycle(this)">
<div class="cycle-name"><i class="fas fa-calendar-alt"></i> Tháng</div>
<div class="cycle-price" id="renewPriceMonthly">--</div>
</div>
</div>
<div class="form-group" style="margin-top:12px;display:flex;align-items:center;gap:12px">
<label style="margin:0;white-space:nowrap;font-weight:600">Số lượng gia hạn:</label>
<input type="number" id="renewDurationInput" name="duration" value="1" min="1" style="width:100px;padding:10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px" oninput="updateRenewTotal()">
<span style="color:#64748b;font-size:13px" id="renewDurationLabel">phút</span>
</div>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<span style="font-weight:600;color:#1e293b">Tổng tiền gia hạn:</span>
<span id="renewTotalDisplay" style="font-size:18px;font-weight:800;color:#2563eb">0 VNĐ</span>
</div>
<input type="hidden" name="billing_cycle" id="selectedRenewCycle" value="minutely">
</div>
<button type="submit" class="btn-submit" id="renewSubmitBtn"><i class="fas fa-check-circle"></i> Xác nhận Gia hạn</button>
</form>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:{{ settings.primary_color }}"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>

<script>
window.addEventListener('DOMContentLoaded', () => {
    const shopCheckbox = document.getElementById('put_on_shop');
    const priceGroup = document.getElementById('shop_price_group');
    const quantityGroup = document.getElementById('shop_quantity_group');
    const graceGroup = document.getElementById('shop_grace_group');
    if(shopCheckbox){
        shopCheckbox.addEventListener('change', (e) => {
            priceGroup.style.display = e.target.checked ? 'block' : 'none';
            quantityGroup.style.display = e.target.checked ? 'block' : 'none';
            graceGroup.style.display = e.target.checked ? 'block' : 'none';
        });
    }
});
function toggleKeyFields(select){
    const type = select.value;
    document.getElementById('key_money_fields').style.display = type === 'money' ? 'flex' : 'none';
    document.getElementById('key_vps_fields').style.display = type === 'vps' ? 'block' : 'none';
}
function generateRandomKey(){
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
    let part1 = '', part2 = '', part3 = '';
    for(let i=0; i<4; i++) part1 += chars.charAt(Math.floor(Math.random() * chars.length));
    for(let i=0; i<4; i++) part2 += chars.charAt(Math.floor(Math.random() * chars.length));
    for(let i=0; i<4; i++) part3 += chars.charAt(Math.floor(Math.random() * chars.length));
    document.getElementById('key_code_input').value = `WINBOX-${part1}-${part2}-${part3}`;
}
function showCenterNotice(msg, isError=false, duration=2200, callback=null){
    const overlay = document.getElementById('centerNotif');
    const icon = document.getElementById('centerNotifIcon');
    const msgEl = document.getElementById('centerNotifMsg');
    if(!overlay) return;
    msgEl.textContent = msg;
    if(isError){ icon.className = 'fas fa-exclamation-circle'; icon.style.color = '#c62828'; }
    else { icon.className = 'fas fa-check-circle'; icon.style.color = '#2e7d32'; }
    overlay.classList.add('active');
    setTimeout(() => { overlay.classList.remove('active'); if(callback) setTimeout(callback, 300); }, duration);
}
function openConfigModal(){
    document.getElementById('configModalTitle').innerText='Thêm cấu hình VM';
    document.getElementById('configForm').reset();
    document.getElementById('configOriginalKey').value='';
    document.getElementById('configKey').disabled=false;
    document.getElementById('configModal').classList.add('active');
}
function editConfig(key,cfg){
    document.getElementById('configModalTitle').innerText='Sửa cấu hình: '+key;
    document.getElementById('configOriginalKey').value=key;
    document.getElementById('configKey').value=key;
    document.getElementById('configKey').disabled=true;
    document.getElementById('configName').value=cfg.name || key;
    document.getElementById('configCpu').value=cfg.cpu || 1;
    document.getElementById('configRam').value=cfg.ram || 1;
    document.getElementById('configDisk').value=cfg.disk || 1;
    document.getElementById('configPriceMinutely').value=cfg.price_minutely || 0;
    document.getElementById('configPriceHourly').value=cfg.price_hourly || 0;
    document.getElementById('configPriceDaily').value=cfg.price_daily || 0;
    document.getElementById('configPriceWeekly').value=cfg.price_weekly || 0;
    document.getElementById('configPriceMonthly').value=cfg.price_monthly || 0;
    document.getElementById('configModal').classList.add('active');
}
function closeConfigModal(){ document.getElementById('configModal').classList.remove('active'); }
function saveConfig(e){
    e.preventDefault();
    const form=new FormData(e.target);
    if(document.getElementById('configKey').disabled) form.set('key',document.getElementById('configKey').value);
    fetch('/api/admin/config/save',{method:'POST',body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success){ closeConfigModal(); showCenterNotice('Đã lưu cấu hình VM thành công!',false,1200,()=>location.reload()); }
        else showCenterNotice(d.error||'Lỗi lưu cấu hình!',true);
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!',true));
}
function deleteConfig(key){
    if(!confirm('Xóa cấu hình '+key+'? Ngườidùng sẽ không còn thấy gói này. Các VM đã tạo trước đó không bị xóa.')) return;
    const form=new FormData(); form.append('key',key);
    fetch('/api/admin/config/delete',{method:'POST',body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success) showCenterNotice('Đã xóa cấu hình.',false,1200,()=>location.reload());
        else showCenterNotice(d.error||'Không thể xóa!',true);
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!',true));
}
function saveAnnouncement(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/announcement', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã cập nhật Bảng tin chính thành công!', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Lỗi cập nhật!', true); }
    });
}
function saveSettings(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/settings', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã lưu Cấu hình Hệ thống thành công!', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Lỗi lưu cấu hình!', true); }
    });
}
function createKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/keys/create', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice(d.message || 'Đã tạo Key thành công!', false, 1800, () => location.reload()); }
        else { showCenterNotice(d.error || 'Lỗi tạo Key!', true); }
    });
}
function deleteKey(code){
    if(!confirm('Bạn có chắc muốn xóa Key này?')) return;
    const form = new FormData();
    form.append('code', code);
    fetch('/api/admin/keys/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã xóa Key thành công.', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function openBalanceModal(uid, username, actionType){
    document.getElementById('balanceUserId').value = uid;
    document.getElementById('balanceActionType').value = actionType;
    document.getElementById('balanceModalTitle').innerText = (actionType === 'add' ? 'Cộng tiền' : 'Trừ tiền') + ' tài khoản: ' + username;
    document.getElementById('balanceLabelText').innerText = 'Số tiền VNĐ cần ' + (actionType === 'add' ? 'cộng' : 'trừ') + ':';
    document.getElementById('balanceModal').classList.add('active');
}
function closeBalanceModal(){ document.getElementById('balanceModal').classList.remove('active'); }
function submitBalance(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/user/balance', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ closeBalanceModal(); showCenterNotice('Cập nhật số dư thành công!', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function openPasswordModal(uid, username){
    document.getElementById('passwordUserId').value = uid;
    document.getElementById('passwordModal').classList.add('active');
}
function closePasswordModal(){ document.getElementById('passwordModal').classList.remove('active'); }
function submitPassword(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/user/password', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ closePasswordModal(); showCenterNotice('Đổi mật khẩu thành công!', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function toggleRole(uid){
    if(!confirm('Bạn có chắc muốn đổi quyền của tài khoản này?')) return;
    const form = new FormData();
    form.append('user_id', uid);
    fetch('/api/admin/user/role', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã đổi quyền thành công.', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function deleteUser(uid){
    if(!confirm('Bạn có chắc muốn xóa tài khoản này?')) return;
    const form = new FormData();
    form.append('user_id', uid);
    fetch('/api/admin/user/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã xóa tài khoản thành công.', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function toggleVmLogs(userId, vmId, lock){
    const actionText = lock ? 'khóa' : 'mở khóa';
    if(!confirm(`Bạn có chắc muốn ${actionText} logs cho VM này?`)) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    form.append('lock', lock ? '1' : '0');
    fetch('/api/admin/vm/toggle-logs', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice(`Đã ${actionText} logs VM thành công.`, false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    });
}
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm(`BẠN CHẮC CHẮN MUỐN XÓA VM "${vmName}" (ID: ${vmId})?\n\nHành động này KHÔNG THỂ hoàn tác. Toàn bộ dữ liệu VM sẽ bị xóa vĩnh viễn.`)) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ showCenterNotice('Đã xóa VM thành công.', false, 1500, () => location.reload()); }
        else { showCenterNotice(d.error || 'Thất bại!', true); }
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!', true));
}
function openNodeModal(){
    document.getElementById('nodeModalTitle').innerText='Thêm Worker Node';
    document.getElementById('nodeForm').reset();
    document.getElementById('nodeId').disabled=false;
    document.getElementById('nodeModal').classList.add('active');
}
function closeNodeModal(){ document.getElementById('nodeModal').classList.remove('active'); }
function saveNode(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/node/save', {method:'POST', body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success){ closeNodeModal(); showCenterNotice('Đã lưu Node thành công!', false, 1500, ()=>location.reload()); }
        else showCenterNotice(d.error || 'Lỗi lưu Node!', true);
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!', true));
}
function deleteNode(nodeId){
    if(!confirm('Xóa Worker Node '+nodeId+'?')) return;
    const form = new FormData(); form.append('node_id', nodeId);
    fetch('/api/admin/node/delete', {method:'POST', body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success) showCenterNotice('Đã xóa Node.', false, 1200, ()=>location.reload());
        else showCenterNotice(d.error || 'Thất bại!', true);
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!', true));
}
function testNode(nodeId){
    showCenterNotice('Đang kiểm tra kết nối...', false, 1500);
    const form = new FormData(); form.append('node_id', nodeId);
    fetch('/api/admin/node/test', {method:'POST', body:form})
    .then(r=>r.json()).then(d=>{
        if(d.success) showCenterNotice(d.message || 'Kết nối thành công!', false, 2500);
        else showCenterNotice(d.error || 'Kết nối thất bại!', true, 3000);
    }).catch(()=>showCenterNotice('Không thể kết nối máy chủ!', true));
}

// Key shop countdown updater
(function(){
  function updateKeyCountdowns(){
    const now = Math.floor(Date.now()/1000);
    document.querySelectorAll('.key-countdown').forEach(el=>{
      const start = parseFloat(el.dataset.start);
      const duration = parseInt(el.dataset.duration) || 2;
      const mode = el.dataset.mode || 'soldout';
      const elapsed = now - start;
      const left = duration*60 - elapsed;
      const label = mode === 'redeemed' ? 'để xóa' : 'để gỡ';
      if(left <= 0){
        el.textContent = mode === 'redeemed' ? "Đang xóa..." : "Đang gỡ...";
        el.style.color = "#999";
      } else {
        const m = Math.floor(left/60);
        const s = Math.floor(left%60);
        el.textContent = `Còn ${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')} ${label}`;
      }
    });
  }
  setInterval(updateKeyCountdowns, 1000);
  updateKeyCountdowns();
})();

// Admin countdown updater
(function(){
  function formatCountdown(ms){
    if(ms <= 0) return "HẾT HẠN";
    const totalSec = Math.floor(ms/1000);
    const h = Math.floor(totalSec/3600);
    const m = Math.floor((totalSec%3600)/60);
    const s = totalSec%60;
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  function updateAdminCountdowns(){
    const now = new Date().getTime();
    document.querySelectorAll('td[data-expiry]').forEach(td=>{
      const expiry = td.dataset.expiry;
      const span = td.querySelector('.admin-countdown');
      if(!expiry || !span) return;
      const end = new Date(expiry).getTime();
      const diff = end - now;
      span.textContent = formatCountdown(diff);
      if(diff <= 600000) span.style.color = '#dc2626';
      else if(diff <= 3600000) span.style.color = '#d97706';
      else span.style.color = '#0369a1';
    });
  }
  setInterval(updateAdminCountdowns, 1000);
  updateAdminCountdowns();
})();
</script>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm('BẠN CHẮC CHẮN MUỐN XÓA VM "' + vmName + '" (ID: ' + vmId + ')?\n\nHành động này KHÔNG THỂ hoàn tác.')) return;
    const form = new FormData();
    form.append('user_id', userId);
    form.append('vm_id', vmId);
    fetch('/api/admin/vm/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert('Đã xóa VM thành công.'); location.reload(); }
        else { alert(d.error || 'Thất bại!'); }
    }).catch(()=>alert('Không thể kết nối máy chủ!'));
}
</script>
</body>
</html>"""

# ==================== FLASK ROUTES ====================

@app.route("/")
def index():
    if is_logged_in():
        return redirect("/dashboard")
    return render_template_string(LANDING_PAGE, vm_configs=get_vm_configs(), settings=get_settings())

@app.route("/login", methods=["GET", "POST"])
def login():
    settings = get_settings()
    error = None
    success = request.args.get("success")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user = find_user_by_username(username)
        if user and user.get("password") == hash_password(password):
            session["user_id"] = user["id"]
            return redirect("/dashboard")
        else:
            error = "Tên đăng nhập hoặc mật khẩu không chính xác."
    return render_template_string(LOGIN_PAGE, error=error, success=success, settings=settings)

@app.route("/register", methods=["GET", "POST"])
def register():
    settings = get_settings()
    if not settings.get("allow_registration", True):
        return "Đăng ký tạm thờibị tắt bởi Admin.", 403
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        password_confirm = request.form.get("password_confirm", "").strip()
        if not username or not email or not password:
            error = "Vui lòng điền đầy đủ thông tin đăng ký."
        elif password != password_confirm:
            error = "Mật khẩu xác nhận không khớp."
        elif len(password) < 6:
            error = "Mật khẩu phải có ít nhất 6 ký tự."
        else:
            existing = find_user_by_username(username)
            if existing:
                error = "Tên đăng nhập hoặc Email đã tồn tại trong hệ thống."
            else:
                uid = str(uuid.uuid4())
                user_data = {
                    "id": uid,
                    "username": username,
                    "email": email,
                    "password": hash_password(password),
                    "role": "user",
                    "balance": 0.0,
                    "created_at": datetime.now().isoformat()
                }
                save_user(uid, user_data)
                return redirect("/login?success=Đăng ký thành công! Vui lòng đăng nhập.")
    return render_template_string(REGISTER_PAGE, error=error, settings=settings)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
    settings = get_settings()
    if settings.get("maintenance_mode") and not is_admin():
        return "Hệ thống đang bảo trì. Vui lòng quay lại sau.", 503
    anc = get_announcement()
    return render_template_string(
        ANNOUNCEMENT_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        announcement=anc,
        settings=settings
    )

@app.route("/my-vms")
def my_vms():
    if not is_logged_in():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
    settings = get_settings()
    user_vms_raw = get_user_vms(user["id"])
    user_vms = []
    running_count = 0
    creating_count = 0
    for vid, vm in user_vms_raw.items():
        if vm.get("user_id") == user["id"]:
            st = vm.get("status", "stopped")
            if st == "running":
                running_count += 1
                status_text = "VM đang được khởi động lên"
            elif st == "creating":
                creating_count += 1
                status_text = "Đang Tạo VM"
            else:
                status_text = "VM Đã Dừng"
            os_name = vm.get("windows", {}).get("name", "Windows Server") if isinstance(vm.get("windows"), dict) else str(vm.get("windows"))
            billing = vm.get("billing_cycle", "monthly")
            try:
                duration = max(1, int(vm.get("duration", 1) or 1))
            except (ValueError, TypeError):
                duration = 1
            unit_labels = {"minutely": "phút", "hourly": "giờ", "daily": "ngày", "weekly": "tuần", "monthly": "tháng"}
            billing_text = f"{duration} {unit_labels.get(billing, billing)}"
            expiry = vm.get("expiry_time", "")
            expiry_text = "Không giới hạn"
            is_expired = False
            if expiry:
                try:
                    dt = datetime.fromisoformat(expiry)
                    expiry_text = dt.strftime("%d/%m/%Y %H:%M")
                    is_expired = datetime.now() > dt
                except Exception:
                    expiry_text = str(expiry)
                    is_expired = False
            user_vms.append({
                "id": vid,
                "name": vm.get("name", "VM"),
                "status": st,
                "status_text": status_text,
                "cpu": vm.get("config", {}).get("cpu", 2),
                "ram": vm.get("config", {}).get("ram", 4),
                "disk": vm.get("config", {}).get("disk", 50),
                "os": os_name,
                "user": vm.get("windows", {}).get("user", "Admin") if isinstance(vm.get("windows"), dict) else "Admin",
                "password": vm.get("windows", {}).get("pass", "Tam255Z") if isinstance(vm.get("windows"), dict) else "Tam255Z",
                "tailscale_ip": vm.get("tailscale_ip"),
                "billing_cycle": billing,
                "billing_text": billing_text,
                "expiry_text": expiry_text,
                "expiry_time": expiry,
                "is_expired": is_expired,
                "config": vm.get("config", {}),
                "logs_locked": vm.get("logs_locked", settings.get("default_logs_locked", True))
            })
    nodes = get_nodes()
    for vm in user_vms:
        nid = vm.get("node_id", "local")
        vm["node_name"] = nodes.get(nid, {}).get("name", nid) if nid != "local" else "Local (Master)"
    return render_template_string(
        MY_VMS_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        vms=user_vms,
        vm_count=len(user_vms),
        running_count=running_count,
        creating_count=creating_count,
        vm_configs=get_vm_configs(),
        windows_images=get_windows_images(),
        nodes=nodes,
        settings=settings
    )

@app.route("/marketplace")
def marketplace():
    if not is_logged_in():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
    cleanup_marketplace()
    market_items = load_json(MARKETPLACE_FILE)
    keys_data = load_json(KEYS_FILE)
    shop_keys = {}
    batch_counts = {}
    now = datetime.now()
    for k_code, k in keys_data.items():
        if k.get("on_shop"):
            # Kiểm tra hết hạn validity
            valid = True
            created_at = k.get("created_at")
            validity_days = int(k.get("key_validity_days", 30) or 30)
            if created_at:
                try:
                    if now > datetime.fromisoformat(created_at) + timedelta(days=validity_days):
                        valid = False
                except Exception:
                    pass
            if not valid:
                continue
            # Đếm stock: key chưa used = còn hàng, key đã used = hết hàng nhưng vẫn hiển thị để đếm ngược gỡ
            batch_id = k.get("batch_id", k_code)
            if not k.get("used"):
                batch_counts[batch_id] = batch_counts.get(batch_id, 0) + 1
    for k_code, k in keys_data.items():
        if k.get("on_shop"):
            # Kiểm tra hết hạn validity
            valid = True
            created_at = k.get("created_at")
            validity_days = int(k.get("key_validity_days", 30) or 30)
            if created_at:
                try:
                    if now > datetime.fromisoformat(created_at) + timedelta(days=validity_days):
                        valid = False
                except Exception:
                    pass
            if not valid:
                continue
            batch_id = k.get("batch_id", k_code)
            stock = batch_counts.get(batch_id, 0)
            k["_shop_stock"] = stock
            k["_is_sold_out"] = k.get("used", False)
            shop_keys[k_code] = k
    return render_template_string(
        MARKETPLACE_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        items=market_items.values(),
        shop_keys=shop_keys,
        settings=get_settings()
    )

@app.route("/deposit")
def deposit_page():
    if not is_logged_in():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
    return render_template_string(
        DEPOSIT_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        settings=get_settings()
    )

@app.route("/admin")
def admin_panel():
    if not is_admin():
        return redirect("/dashboard")
    user = get_current_user()
    users = load_all_users()
    keys = load_json(KEYS_FILE)
    anc = get_announcement()
    settings = get_settings()
    all_vms = []
    for uid, u in users.items():
        user_vms = get_user_vms(uid)
        for vid, vm in user_vms.items():
            all_vms.append({
                "user_id": uid,
                "username": u.get("username", "Unknown"),
                "vm_id": vid,
                "vm_name": vm.get("name", "VM"),
                "expiry_time": vm.get("expiry_time", ""),
                "logs_locked": vm.get("logs_locked", settings.get("default_logs_locked", True))
            })
    nodes = get_nodes()
    for node_id, node in nodes.items():
        node["_status"] = get_node_status(node)
    return render_template_string(
        ADMIN_PAGE,
        username=user["username"],
        balance=user["balance"],
        users=users,
        keys=keys,
        announcement=anc,
        vm_configs=get_vm_configs(),
        os_images=get_windows_images(),
        settings=settings,
        all_vms=all_vms,
        nodes=nodes
    )

# ==================== API ENDPOINTS ====================

@app.route("/api/vm/create", methods=["POST"])
def api_create_vm():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_name = request.form.get("vm_name", "").strip()
    config_key = request.form.get("config", "").strip()
    os_key = request.form.get("windows", "").strip()
    tailscale_key = request.form.get("tailscale_key", "").strip()
    billing_cycle = request.form.get("billing_cycle", "monthly").strip()
    try:
        duration = max(1, int(request.form.get("duration", 1)))
    except (ValueError, TypeError):
        duration = 1
    node_id = request.form.get("node_id", "local").strip()
    if billing_cycle not in ("minutely", "hourly", "daily", "weekly", "monthly"):
        billing_cycle = "monthly"
    if not vm_name or not config_key or not os_key or not tailscale_key:
        return jsonify({"success": False, "error": "Vui lòng điền đầy đủ thông tin cấu hình và Tailscale Key."})
    configs = get_vm_configs()
    if config_key not in configs:
        return jsonify({"success": False, "error": "Cấu hình VPS không hợp lệ."})
    cfg = configs[config_key]
    images = get_windows_images()
    if os_key not in images:
        return jsonify({"success": False, "error": "Hệ điều hành không hợp lệ."})
    win_img = images[os_key]
    unit_price = get_price_for_cycle(cfg, billing_cycle)
    price = unit_price * duration
    if user["balance"] < price:
        return jsonify({"success": False, "error": f"Số dư tài khoản không đủ ({user['balance']:,.0f} VNĐ). Cần {price:,.0f} VNĐ để tạo gói này."})
    nodes = get_nodes()
    if node_id not in nodes or not nodes[node_id].get("enabled", True):
        return jsonify({"success": False, "error": "Server được chọn không hợp lệ hoặc đang tắt."})
    node = nodes[node_id]
    users = load_all_users()
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_user(user["id"], users[user["id"]])
    vid = str(uuid.uuid4())[:8]
    vm_dir = get_user_vm_dir(user["id"], vid)
    expiry = calculate_expiry(billing_cycle, duration).isoformat()
    vm_data = {
        "id": vid,
        "user_id": user["id"],
        "name": vm_name,
        "config": cfg,
        "windows": win_img,
        "windows_key": os_key,
        "status": "creating",
        "tailscale_key": tailscale_key,
        "tailscale_ip": None,
        "billing_cycle": billing_cycle,
        "duration": duration,
        "expiry_time": expiry,
        "logs_locked": get_settings().get("default_logs_locked", True),
        "node_id": node_id,
        "created_at": datetime.now().isoformat()
    }
    save_vm_data(user["id"], vid, vm_data)
    if node_id == "local" or node.get("type") == "local":
        t = threading.Thread(target=run_winbox_script, args=(user["id"], vid, cfg, win_img, tailscale_key, vm_name, os_key))
        t.daemon = True
        t.start()
    else:
        # Gửi request đến worker node
        worker_data = {
            "user_id": user["id"],
            "vm_id": vid,
            "vm_name": vm_name,
            "config": json.dumps(cfg),
            "windows_key": os_key,
            "tailscale_key": tailscale_key,
            "billing_cycle": billing_cycle
        }
        t = threading.Thread(target=lambda: worker_request(node, "/worker/create-vm", data=worker_data))
        t.daemon = True
        t.start()
    return jsonify({"success": True, "message": f"Đang khởi tạo máy ảo trên {node.get('name', node_id)}..."})

@app.route("/api/vm/<vid>/start", methods=["POST"])
def api_start_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
    node_id = vm_data.get("node_id", "local")
    nodes = get_nodes()
    node = nodes.get(node_id)
    if node_id != "local" and node:
        # Gửi lệnh start đến worker
        worker_data = {
            "user_id": user["id"],
            "vm_id": vid,
            "vm_name": vm_data.get("name", "VM"),
            "config": json.dumps(vm_data.get("config", {})),
            "windows_key": vm_data.get("windows_key", "win11"),
            "tailscale_key": vm_data.get("tailscale_key", "")
        }
        resp = worker_request(node, "/worker/start-vm", data=worker_data)
        if resp.get("success"):
            vm_data["status"] = "running"
            save_vm_data(user["id"], vid, vm_data)
            return jsonify({"success": True, "message": f"Đã phát lệnh bật VM trên {node.get('name', node_id)}."})
        else:
            return jsonify({"success": False, "error": resp.get("error", "Worker lỗi")})
    vm_dir = get_user_vm_dir(user["id"], vid)
    win_img_path = vm_dir / "win.img"
    if win_img_path.exists():
        ok, msg = start_vm_existing(
            user["id"], vid,
            vm_data.get("config"),
            vm_dir,
            vm_data.get("name", "VM"),
            vm_data.get("windows_key", "win11"),
            vm_data.get("tailscale_key", "")
        )
        if ok:
            return jsonify({"success": True, "message": msg})
        else:
            return jsonify({"success": False, "error": msg})
    else:
        win_key = vm_data.get("windows_key", "win11")
        t = threading.Thread(target=run_winbox_script, args=(user["id"], vid, vm_data.get("config"), vm_data.get("windows"), vm_data.get("tailscale_key"), vm_data.get("name"), win_key))
        t.daemon = True
        t.start()
        return jsonify({"success": True, "message": "Đang tải và khởi tạo lại máy ảo..."})

@app.route("/api/vm/<vid>/stop", methods=["POST"])
def api_stop_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
    node_id = vm_data.get("node_id", "local")
    nodes = get_nodes()
    node = nodes.get(node_id)
    if node_id != "local" and node:
        worker_data = {"user_id": user["id"], "vm_id": vid}
        resp = worker_request(node, "/worker/stop-vm", data=worker_data)
        if resp.get("success"):
            vm_data["status"] = "stopped"
            save_vm_data(user["id"], vid, vm_data)
            return jsonify({"success": True, "message": f"Đã dừng máy ảo trên {node.get('name', node_id)}."})
        else:
            return jsonify({"success": False, "error": resp.get("error", "Worker lỗi")})
    vm_dir = get_user_vm_dir(user["id"], vid)
    _stop_vm_logged(user["id"], vid, vm_dir)
    vm_data["status"] = "stopped"
    save_vm_data(user["id"], vid, vm_data)
    return jsonify({"success": True, "message": "Đã dừng máy ảo và kill tiến trình QEMU."})

@app.route("/api/vm/<vid>/delete", methods=["POST"])
def api_delete_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
    node_id = vm_data.get("node_id", "local")
    nodes = get_nodes()
    node = nodes.get(node_id)
    if node_id != "local" and node:
        worker_data = {"user_id": user["id"], "vm_id": vid}
        resp = worker_request(node, "/worker/delete-vm", data=worker_data)
        if resp.get("success"):
            return jsonify({"success": True, "message": f"Đã xóa máy ảo trên {node.get('name', node_id)}."})
        else:
            return jsonify({"success": False, "error": resp.get("error", "Worker lỗi")})
    vm_dir = get_user_vm_dir(user["id"], vid)
    windows_key = vm_data.get("windows_key", "win11")
    _delete_vm_logged(user["id"], vid, vm_dir, windows_key)
    return jsonify({"success": True, "message": "Đã xóa toàn bộ dữ liệu máy ảo."})


@app.route("/api/vm/<vid>/renew", methods=["POST"])
def api_renew_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
    billing_cycle = request.form.get("billing_cycle", "hourly").strip()
    if billing_cycle not in ("minutely", "hourly", "daily", "weekly", "monthly"):
        billing_cycle = "hourly"
    try:
        duration = max(1, int(request.form.get("duration", 1)))
    except (ValueError, TypeError):
        duration = 1
    cfg = vm_data.get("config", {})
    unit_price = get_price_for_cycle(cfg, billing_cycle)
    price = unit_price * duration
    if user["balance"] < price:
        return jsonify({"success": False, "error": f"Số dư không đủ ({user['balance']:,.0f} VNĐ). Cần {price:,.0f} VNĐ để gia hạn."})
    users = load_all_users()
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_user(user["id"], users[user["id"]])
    new_expiry = calculate_expiry(billing_cycle, duration).isoformat()
    vm_data["billing_cycle"] = billing_cycle
    vm_data["duration"] = duration
    vm_data["expiry_time"] = new_expiry
    save_vm_data(user["id"], vid, vm_data)
    append_vm_log(user["id"], vid, f"[GIA HẠN] User gia hạn thêm {duration} x {billing_cycle}. Hết hạn mới: {new_expiry[:16]}")
    return jsonify({"success": True, "message": f"Gia hạn thành công! Hết hạn mới: {new_expiry[:16].replace('T', ' ')}"})


@app.route("/api/vm/<vid>/info", methods=["GET"])
def api_vm_info(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
    cfg = vm_data.get("config", {})
    return jsonify({
        "success": True,
        "config": {
            "price_minutely": cfg.get("price_minutely", 0),
            "price_hourly": cfg.get("price_hourly", 0),
            "price_daily": cfg.get("price_daily", 0),
            "price_weekly": cfg.get("price_weekly", 0),
            "price_monthly": cfg.get("price_monthly", 0)
        },
        "expiry_time": vm_data.get("expiry_time", "")
    })

@app.route("/vm/<vid>/logs")
def vm_logs_page(vid):
    if not is_logged_in():
        return "Unauthorized", 401
    user = get_current_user()
    vm_data = get_vm_data(user["id"], vid)
    if not vm_data or vm_data.get("user_id") != user["id"]:
        return "Not found", 404
    if vm_data.get("logs_locked", True) and not is_admin():
        return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Logs bị khóa</title>
        <style>body{font-family:sans-serif;text-align:center;padding:50px;color:#c62828}</style></head>
        <body><h1><i class="fas fa-lock"></i> Logs đang bị khóa</h1><p>Admin chưa mở khóa logs cho máy ảo này. Vui lòng liên hệ Admin.</p></body></html>""", 403
    node_id = vm_data.get("node_id", "local")
    nodes = get_nodes()
    node = nodes.get(node_id)
    if node_id != "local" and node:
        try:
            r = requests.get(
                f"http://{node['host']}:{node['port']}/worker/vm/{vid}/logs",
                headers={"X-Worker-Token": node.get("token", "")},
                timeout=10
            )
            logs = r.text if r.status_code == 200 else "Không thể lấy logs từ worker."
        except Exception as e:
            logs = f"Lỗi kết nối worker: {e}"
    else:
        logs = get_vm_logs(user["id"], vid)
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><title>Log VM - """ + vid + """</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
body{font-family:'Inter',sans-serif;background:#0f172a;color:#38bdf8;padding:20px;margin:0}
pre{background:#1e293b;padding:20px;border-radius:8px;overflow-x:auto;font-family:monospace;font-size:13px;line-height:1.5;color:#e2e8f0;white-space:pre-wrap;word-wrap:break-word}
h2{color:#fff;font-size:18px;margin-bottom:15px;display:flex;justify-content:space-between;align-items:center}
.btn-refresh{background:#2563eb;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}
</style>
</head>
<body>
<h2><span>Log hệ thống VM: """ + vid + """</span> <button class="btn-refresh" onclick="location.reload()">Tải lại</button></h2>
<pre>""" + logs + """</pre>
</body>
</html>"""

@app.route("/api/keys/redeem", methods=["POST"])
def api_redeem_key():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    code = request.form.get("code", "").strip().upper()
    if not code:
        return jsonify({"success": False, "error": "Vui lòng nhập mã Key."})
    keys = load_json(KEYS_FILE)
    if code not in keys:
        return jsonify({"success": False, "error": "Mã Key không tồn tại trong hệ thống."})
    k = keys[code]
    # Kiểm tra thờigian hiệu lực từ khi tạo
    validity_days = int(k.get("key_validity_days", 30) or 30)
    created_at = k.get("created_at", "")
    if created_at:
        try:
            created_dt = datetime.fromisoformat(created_at)
            if datetime.now() > created_dt + timedelta(days=validity_days):
                return jsonify({"success": False, "error": f"Mã Key này đã hết hạn sử dụng (hiệu lực {validity_days} ngày)."})
        except Exception:
            pass
    uses_by_user = k.get("uses_by_user", {})
    if not isinstance(uses_by_user, dict):
        uses_by_user = {}
    user_key = str(user["id"])
    current_user_uses = int(uses_by_user.get(user_key, 0) or 0)
    max_uses_per_user = int(k.get("max_uses_per_user", 1) or 1)
    max_total_uses = int(k.get("max_total_uses", 1) or 1)
    if max_uses_per_user < 1:
        max_uses_per_user = 1
    if max_total_uses < 1:
        max_total_uses = 1
    if current_user_uses >= max_uses_per_user:
        return jsonify({"success": False, "error": f"Bạn đã nhập Key này đủ {max_uses_per_user} lần."})
    total_uses = sum(int(v or 0) for v in uses_by_user.values())
    if total_uses >= max_total_uses:
        return jsonify({"success": False, "error": f"Key này đã đạt giới hạn {max_total_uses} lượt sử dụng."})
    if k.get("used") and max_uses_per_user <= 1 and max_total_uses <= 1:
        return jsonify({"success": False, "error": "Mã Key này đã được sử dụng trước đó."})
    uses_by_user[user_key] = current_user_uses + 1
    k["uses_by_user"] = uses_by_user
    k["last_used_by"] = user["username"]
    k["last_used_at"] = datetime.now().isoformat()
    new_total = sum(int(v or 0) for v in uses_by_user.values())
    # Bắt đầu countdown thờigian sống khi lần đầu được nhập
    if not k.get("redeemed_at"):
        k["redeemed_at"] = time.time()
    # Nếu đạt tổng số lượt tối đa → đánh dấu đã dùng hết để không cho nhập nữa
    if new_total >= max_total_uses:
        k["used"] = True
        k["used_by"] = user["username"]
        k["used_at"] = datetime.now().isoformat()
    elif max_uses_per_user == 1 and max_total_uses == 1:
        k["used"] = True
        k["used_by"] = user["username"]
        k["used_at"] = datetime.now().isoformat()
    else:
        k["used"] = False
        k["used_by"] = None
    save_json(KEYS_FILE, keys)
    users = load_all_users()
    if k["type"] == "money":
        amt = float(k.get("amount", 0))
        if user["id"] in users:
            users[user["id"]]["balance"] += amt
            save_user(user["id"], users[user["id"]])
        return jsonify({"success": True, "message": f"Nhập Key thành công lần {current_user_uses + 1}/{max_uses_per_user}! Cộng +{amt:,.0f} VNĐ vào tài khoản."})
    elif k["type"] == "vps":
        vid = str(uuid.uuid4())[:8]
        cfg = {"cpu": k.get("vps_cpu", 2), "ram": k.get("vps_ram", 4), "disk": k.get("vps_disk", 50)}
        win_img = {"name": k.get("vps_os", "Windows Server"), "user": k.get("vps_user", "Administrator"), "pass": k.get("vps_pass", "Pass123456")}
        vm_data = {
            "id": vid,
            "user_id": user["id"],
            "name": k.get("vps_name", "VPS Gift"),
            "config": cfg,
            "windows": win_img,
            "status": "stopped",
            "tailscale_key": "",
            "tailscale_ip": k.get("vps_ip"),
            "billing_cycle": "monthly",
            "expiry_time": "",
            "logs_locked": get_settings().get("default_logs_locked", True),
            "created_at": datetime.now().isoformat()
        }
        save_vm_data(user["id"], vid, vm_data)
        return jsonify({"success": True, "message": f"Nhập Key thành công lần {current_user_uses + 1}/{max_uses_per_user}! Đã thêm VPS vào danh sách Máy ảo của bạn."})
    return jsonify({"success": False, "error": "Loại Key không hợp lệ."})

@app.route("/api/marketplace/buy-key", methods=["POST"])
def api_buy_key_shop():
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    code = request.form.get("code", "").strip().upper()
    keys = load_json(KEYS_FILE)
    if code not in keys or not keys[code].get("on_shop") or keys[code].get("used"):
        return jsonify({"success": False, "error": "Key không tồn tại hoặc đã được bán."})
    k = keys[code]
    price = float(k.get("shop_price", 0))
    if user["balance"] < price:
        return jsonify({"success": False, "error": f"Số dư không đủ ({user['balance']:,.0f} VNĐ). Cần {price:,.0f} VNĐ để mua Key này."})
    users = load_all_users()
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_user(user["id"], users[user["id"]])
    k["used"] = True
    k["used_by"] = user["username"]
    k["used_at"] = datetime.now().isoformat()
    k["sold_out_at"] = time.time()
    # KHÔNG đặt on_shop = False ngay — để cleanup worker gỡ sau shop_grace_minutes
    save_json(KEYS_FILE, keys)
    return jsonify({"success": True})

@app.route("/api/marketplace/<item_id>/buy", methods=["POST"])
def api_buy_marketplace_vps(item_id):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    market_data = load_json(MARKETPLACE_FILE)
    if item_id not in market_data or market_data[item_id].get("quantity", 0) <= 0:
        return jsonify({"success": False, "error": "VPS này đã hết hàng."})
    item = market_data[item_id]
    price = float(item.get("price_val", 0))
    if user["balance"] < price:
        return jsonify({"success": False, "error": f"Số dư không đủ ({user['balance']:,.0f} VNĐ). Cần {price:,.0f} VNĐ để mua VPS này."})
    users = load_all_users()
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_user(user["id"], users[user["id"]])
    item["quantity"] -= 1
    if item["quantity"] <= 0:
        item["sold_out_at"] = time.time()
    save_json(MARKETPLACE_FILE, market_data)
    vid = str(uuid.uuid4())[:8]
    cfg = {"cpu": item.get("cpu", 2), "ram": item.get("ram", 4), "disk": item.get("disk", 50)}
    win_img = {"name": item.get("os_name", "Windows Server"), "user": item.get("user", "Admin"), "pass": item.get("password", "Tam255Z")}
    vm_data = {
        "id": vid,
        "user_id": user["id"],
        "name": item.get("name", "VPS Marketplace"),
        "config": cfg,
        "windows": win_img,
        "status": "stopped",
        "tailscale_key": "",
        "tailscale_ip": item.get("ip"),
        "billing_cycle": "monthly",
        "expiry_time": "",
        "logs_locked": get_settings().get("default_logs_locked", True),
        "created_at": datetime.now().isoformat()
    }
    save_vm_data(user["id"], vid, vm_data)
    return jsonify({"success": True})

# ==================== SEPAY WEBHOOK ENDPOINT ====================
SEPAY_LOCK = threading.Lock()

def _find_username_from_sepay(data, users):
    content = str(data.get("content", "") or "")
    code = str(data.get("code", "") or "")
    description = str(data.get("description", "") or "")
    search_text = " ".join([content, code, description]).strip()
    match = re.search(
        r"(?:^|[^A-Z0-9_-])(?:NAP|WINBOX)[\s:_-]+([a-zA-Z0-9_-]+)(?:$|[^a-zA-Z0-9_-])",
        search_text,
        re.IGNORECASE
    )
    if match:
        candidate = match.group(1).strip()
        for uid, user in users.items():
            if str(user.get("username", "")).strip().lower() == candidate.lower():
                return uid, user.get("username", "")
    upper_text = search_text.upper()
    matches = []
    for uid, user in users.items():
        uname = str(user.get("username", "")).strip()
        if not uname or uname.lower() == "admin":
            continue
        pattern = r"(?<![A-Z0-9_-])" + re.escape(uname.upper()) + r"(?![A-Z0-9_-])"
        if re.search(pattern, upper_text):
            matches.append((uid, uname))
    if len(matches) == 1:
        return matches[0]
    return None, None

@app.route("/api/sepay/webhook", methods=["POST"])
def sepay_webhook():
    try:
        data = request.get_json(silent=True)
        if not data:
            data = request.form.to_dict()
        if not data:
            return jsonify({"success": False, "error": "No data received"}), 400
        transaction_id = str(data.get("id", "") or "").strip()
        transfer_type = str(data.get("transferType", "") or "").strip().lower()
        content = str(data.get("content", "") or data.get("description", "") or "").strip()
        reference_code = str(data.get("referenceCode", "") or "").strip()
        try:
            transfer_amount = float(data.get("transferAmount", 0) or data.get("amount", 0) or 0)
        except (TypeError, ValueError):
            transfer_amount = 0
        if transfer_type and transfer_type != "in":
            return jsonify({"success": True, "message": "Ignored non-incoming transaction"})
        if transfer_amount <= 0:
            return jsonify({"success": False, "error": "Invalid amount"}), 400
        web_amount = transfer_amount * 1.2
        with SEPAY_LOCK:
            users = load_all_users()
            deposits = load_json(DEPOSITS_FILE, [])
            if not isinstance(deposits, list):
                deposits = []
            if transaction_id:
                for old in deposits:
                    if str(old.get("transaction_id", "")).strip() == transaction_id:
                        return jsonify({"success": True, "message": "Transaction already processed"})
            target_uid, matched_username = _find_username_from_sepay(data, users)
            if not target_uid:
                deposits.append({
                    "transaction_id": transaction_id,
                    "reference_code": reference_code,
                    "raw_data": data,
                    "content": content,
                    "real_amount": transfer_amount,
                    "web_amount": web_amount,
                    "status": "failed_user_not_found",
                    "time": datetime.now().isoformat()
                })
                save_json(DEPOSITS_FILE, deposits)
                return jsonify({"success": True, "credited": False, "message": "Webhook received but no matching username was found"})
            current_balance = float(users[target_uid].get("balance", 0) or 0)
            users[target_uid]["balance"] = current_balance + web_amount
            save_user(target_uid, users[target_uid])
            user_deposits = get_user_deposits(target_uid)
            user_deposits.append({
                "transaction_id": transaction_id,
                "reference_code": reference_code,
                "real_amount": transfer_amount,
                "web_amount": web_amount,
                "content": content,
                "status": "success",
                "time": datetime.now().isoformat()
            })
            save_user_deposits(target_uid, user_deposits)
            deposits.append({
                "transaction_id": transaction_id,
                "reference_code": reference_code,
                "user_id": target_uid,
                "username": users[target_uid].get("username", matched_username),
                "real_amount": transfer_amount,
                "web_amount": web_amount,
                "content": content,
                "status": "success",
                "time": datetime.now().isoformat()
            })
            save_json(DEPOSITS_FILE, deposits)
            return jsonify({"success": True, "credited": True, "message": f"Credited {web_amount} to {users[target_uid]['username']}"})
    except Exception as e:
        print(f"[SEPAY WEBHOOK ERROR] {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== ADMIN API ENDPOINTS ====================

@app.route("/api/admin/settings", methods=["POST"])
def api_admin_settings():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    settings = get_settings()
    settings["site_name"] = request.form.get("site_name", settings["site_name"]).strip()
    settings["primary_color"] = request.form.get("primary_color", settings["primary_color"]).strip()
    settings["default_logs_locked"] = request.form.get("default_logs_locked") == "on"
    settings["allow_registration"] = request.form.get("allow_registration") == "on"
    settings["maintenance_mode"] = request.form.get("maintenance_mode") == "on"
    try:
        settings["marketplace_cleanup_minutes"] = max(1, int(request.form.get("marketplace_cleanup_minutes", 2)))
    except (ValueError, TypeError):
        settings["marketplace_cleanup_minutes"] = 2
    save_settings(settings)
    return jsonify({"success": True})

@app.route("/api/admin/config/save", methods=["POST"])
def api_admin_config_save():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    key = request.form.get("key", "").strip()
    original_key = request.form.get("original_key", "").strip()
    name = request.form.get("name", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return jsonify({"success": False, "error": "Mã cấu hình chỉ được dùng chữ, số, _ hoặc -."})
    if not name:
        return jsonify({"success": False, "error": "Tên cấu hình không được để trống."})
    try:
        cpu = int(request.form.get("cpu", 0))
        ram = int(request.form.get("ram", 0))
        disk = int(request.form.get("disk", 0))
        price_minutely = float(request.form.get("price_minutely", 0))
        price_hourly = float(request.form.get("price_hourly", 0))
        price_daily = float(request.form.get("price_daily", 0))
        price_weekly = float(request.form.get("price_weekly", 0))
        price_monthly = float(request.form.get("price_monthly", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "CPU/RAM/SSD/Giá phải là số hợp lệ."})
    if cpu < 1 or ram < 1 or disk < 1 or price_minutely < 0 or price_hourly < 0 or price_daily < 0 or price_weekly < 0 or price_monthly < 0:
        return jsonify({"success": False, "error": "CPU, RAM, SSD phải >= 1 và giá không được âm."})
    configs = load_json(CONFIGS_FILE)
    target_key = original_key or key
    if not original_key and key in configs:
        return jsonify({"success": False, "error": "Mã cấu hình đã tồn tại."})
    if original_key and original_key not in configs:
        return jsonify({"success": False, "error": "Không tìm thấy cấu hình cần sửa."})
    cfg = dict(configs.get(target_key, {}))
    cfg.update({
        "name": name,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "price_minutely": price_minutely,
        "price_hourly": price_hourly,
        "price_daily": price_daily,
        "price_weekly": price_weekly,
        "price_monthly": price_monthly
    })
    configs[target_key] = cfg
    save_json(CONFIGS_FILE, configs)
    return jsonify({"success": True, "config": cfg})

@app.route("/api/admin/config/delete", methods=["POST"])
def api_admin_config_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    key = request.form.get("key", "").strip()
    configs = load_json(CONFIGS_FILE)
    if key not in configs:
        return jsonify({"success": False, "error": "Không tìm thấy cấu hình."})
    if len(configs) <= 1:
        return jsonify({"success": False, "error": "Không thể xóa cấu hình cuối cùng."})
    del configs[key]
    save_json(CONFIGS_FILE, configs)
    return jsonify({"success": True})

@app.route("/api/admin/announcement", methods=["POST"])
def api_admin_announcement():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    anc = {
        "title": title,
        "content": content,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M")
    }
    save_json(ANNOUNCEMENT_FILE, anc)
    return jsonify({"success": True})

@app.route("/api/admin/vm/toggle-logs", methods=["POST"])
def api_admin_toggle_logs():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    lock = request.form.get("lock", "1") == "1"
    vm_data = get_vm_data(user_id, vm_id)
    if not vm_data:
        return jsonify({"success": False, "error": "Không tìm thấy VM."})
    vm_data["logs_locked"] = lock
    save_vm_data(user_id, vm_id, vm_data)
    return jsonify({"success": True, "locked": lock})

@app.route("/api/admin/vm/delete", methods=["POST"])
def api_admin_delete_vm():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    vm_data = get_vm_data(user_id, vm_id)
    if not vm_data:
        return jsonify({"success": False, "error": "Không tìm thấy VM."})
    vm_dir = get_user_vm_dir(user_id, vm_id)
    windows_key = vm_data.get("windows_key", "win11")
    _delete_vm_logged(user_id, vm_id, vm_dir, windows_key)
    return jsonify({"success": True, "message": "Đã xóa VM thành công."})

@app.route("/api/admin/keys/create", methods=["POST"])
def api_admin_create_key():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    code = request.form.get("code", "").strip().upper()
    key_type = request.form.get("key_type", "money").strip()
    put_on_shop = request.form.get("put_on_shop") == "on"
    try:
        shop_price = float(request.form.get("shop_price", 0))
        quantity = int(request.form.get("quantity", 1))
        shop_grace_minutes = int(request.form.get("shop_grace_minutes", 2))
        key_lifetime_minutes = int(request.form.get("key_lifetime_minutes", 60))
        key_validity_days = int(request.form.get("key_validity_days", 30))
        max_uses_per_user = int(request.form.get("max_uses_per_user", 1))
        max_total_uses = int(request.form.get("max_total_uses", 1))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Giá, số lượng Key, thờigian và số lần/User phải là số hợp lệ."})
    if not code:
        return jsonify({"success": False, "error": "Vui lòng nhập mã Key."})
    if quantity < 1:
        return jsonify({"success": False, "error": "Số lượng Key phải >= 1."})
    if shop_grace_minutes < 1:
        shop_grace_minutes = 2
    if key_lifetime_minutes < 1:
        key_lifetime_minutes = 60
    if key_validity_days < 1:
        key_validity_days = 30
    if max_uses_per_user < 1:
        return jsonify({"success": False, "error": "Số lần 1 User nhập Key phải >= 1."})
    if max_total_uses < 1:
        return jsonify({"success": False, "error": "Tổng số lượt nhập Key phải >= 1."})
    if not put_on_shop:
        quantity = 1
    keys = load_json(KEYS_FILE)
    batch_id = str(uuid.uuid4())[:12]
    codes_to_create = []
    for i in range(quantity):
        new_code = code if quantity == 1 else f"{code}-{i + 1:04d}"
        if new_code in keys or new_code in codes_to_create:
            return jsonify({"success": False, "error": f"Mã Key {new_code} đã tồn tại. Hãy dùng mã gốc khác."})
        codes_to_create.append(new_code)
    common_data = {
        "type": key_type,
        "on_shop": put_on_shop,
        "shop_price": shop_price,
        "shop_grace_minutes": shop_grace_minutes,
        "key_lifetime_minutes": key_lifetime_minutes,
        "key_validity_days": key_validity_days,
        "used": False,
        "used_by": None,
        "max_uses_per_user": max_uses_per_user,
        "max_total_uses": max_total_uses,
        "uses_by_user": {},
        "batch_id": batch_id,
        "batch_quantity": quantity,
        "created_at": datetime.now().isoformat()
    }
    if key_type == "money":
        common_data["amount"] = float(request.form.get("amount", 0))
    else:
        common_data["vps_name"] = request.form.get("vps_name", "VPS Custom")
        common_data["vps_os"] = request.form.get("vps_os", "Windows 10")
        common_data["vps_ip"] = request.form.get("vps_ip", "")
        common_data["vps_user"] = request.form.get("vps_user", "Administrator")
        common_data["vps_pass"] = request.form.get("vps_pass", "Pass123456")
        common_data["vps_cpu"] = int(request.form.get("vps_cpu", 2))
        common_data["vps_ram"] = int(request.form.get("vps_ram", 4))
        common_data["vps_disk"] = int(request.form.get("vps_disk", 50))
    for new_code in codes_to_create:
        key_data = dict(common_data)
        key_data["code"] = new_code
        key_data["uses_by_user"] = {}
        keys[new_code] = key_data
    save_json(KEYS_FILE, keys)
    if quantity > 1:
        return jsonify({"success": True, "message": f"Đã tạo {quantity} Key và đưa lên Shop. Mỗi User được nhập tối đa {max_uses_per_user} lần/Key."})
    return jsonify({"success": True, "message": f"Đã tạo Key thành công. Mỗi User được nhập tối đa {max_uses_per_user} lần."})

@app.route("/api/admin/keys/delete", methods=["POST"])
def api_admin_delete_key():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    code = request.form.get("code", "").strip().upper()
    keys = load_json(KEYS_FILE)
    if code in keys:
        del keys[code]
        save_json(KEYS_FILE, keys)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Key không tồn tại."})

@app.route("/api/admin/user/balance", methods=["POST"])
def api_admin_user_balance():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    action_type = request.form.get("action_type", "add").strip()
    amount = float(request.form.get("amount", 0))
    users = load_all_users()
    if user_id in users:
        if action_type == "add":
            users[user_id]["balance"] += amount
        else:
            users[user_id]["balance"] = max(0.0, users[user_id]["balance"] - amount)
        save_user(user_id, users[user_id])
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "User không tồn tại."})

@app.route("/api/admin/user/password", methods=["POST"])
def api_admin_user_password():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    new_password = request.form.get("new_password", "").strip()
    users = load_all_users()
    if user_id in users and new_password:
        users[user_id]["password"] = hash_password(new_password)
        save_user(user_id, users[user_id])
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Thất bại."})

@app.route("/api/admin/user/role", methods=["POST"])
def api_admin_user_role():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    users = load_all_users()
    if user_id in users:
        current_role = users[user_id].get("role", "user")
        users[user_id]["role"] = "admin" if current_role == "user" else "user"
        save_user(user_id, users[user_id])
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Thất bại."})

@app.route("/api/admin/user/delete", methods=["POST"])
def api_admin_user_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    users = load_all_users()
    if user_id in users and users[user_id].get("username") != "admin":
        user_dir = get_user_dir(user_id)
        if user_dir.exists():
            shutil.rmtree(user_dir, ignore_errors=True)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Không thể xóa tài khoản Admin chính."})

# ==================== ADMIN NODE MANAGEMENT ====================
@app.route("/api/admin/node/save", methods=["POST"])
def api_admin_node_save():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    node_id = request.form.get("node_id", "").strip()
    name = request.form.get("name", "").strip()
    host = request.form.get("host", "").strip()
    port = request.form.get("port", str(WORKER_PORT)).strip()
    token = request.form.get("token", "").strip()
    tunnel_url = request.form.get("tunnel_url", "").strip()
    enabled = request.form.get("enabled") == "on"
    if not node_id or not name or not host:
        return jsonify({"success": False, "error": "Vui lòng điền đầy đủ thông tin node."})
    if not re.fullmatch(r"[A-Za-z0-9_-]+", node_id):
        return jsonify({"success": False, "error": "ID node chỉ được dùng chữ, số, _ hoặc -."})
    try:
        port = int(port)
    except ValueError:
        port = WORKER_PORT
    nodes = get_nodes()
    node_data = {
        "name": name,
        "host": host,
        "port": port,
        "type": "worker",
        "enabled": enabled,
        "token": token
    }
    if tunnel_url:
        node_data["tunnel_url"] = tunnel_url
    nodes[node_id] = node_data
    save_nodes(nodes)
    return jsonify({"success": True})

@app.route("/api/admin/node/delete", methods=["POST"])
def api_admin_node_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    node_id = request.form.get("node_id", "").strip()
    if node_id == "local":
        return jsonify({"success": False, "error": "Không thể xóa node Local."})
    nodes = get_nodes()
    if node_id in nodes:
        del nodes[node_id]
        save_nodes(nodes)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Node không tồn tại."})

@app.route("/api/admin/node/test", methods=["POST"])
def api_admin_node_test():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    node_id = request.form.get("node_id", "").strip()
    nodes = get_nodes()
    if node_id not in nodes:
        return jsonify({"success": False, "error": "Node không tồn tại."})
    node = nodes[node_id]
    status = get_node_status(node)
    if status.get("success"):
        return jsonify({"success": True, "status": status, "message": f"Kết nối thành công đến {node['name']}!"})
    else:
        return jsonify({"success": False, "error": f"Không thể kết nối đến {node['name']} ({node['host']}:{node['port']})."})

@app.route("/api/worker/register", methods=["POST"])
def api_worker_register():
    """Worker tự đăng ký với Master, dùng worker token để xác thực."""
    token = request.form.get("worker_token", "").strip()
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    node_id = request.form.get("node_id", "").strip()
    name = request.form.get("name", "").strip()
    host = request.form.get("host", "").strip()
    port = request.form.get("port", str(WORKER_PORT)).strip()
    tunnel_url = request.form.get("tunnel_url", "").strip()
    if not node_id or not name or not host:
        return jsonify({"success": False, "error": "Thiếu thông tin node."})
    try:
        port = int(port)
    except ValueError:
        port = WORKER_PORT
    nodes = get_nodes()
    node_data = {
        "name": name,
        "host": host,
        "port": port,
        "type": "worker",
        "enabled": True,
        "token": token
    }
    if tunnel_url:
        node_data["tunnel_url"] = tunnel_url
    nodes[node_id] = node_data
    save_nodes(nodes)
    return jsonify({"success": True, "message": "Worker đã đăng ký thành công."})


# ==================== ADMIN VM MANAGEMENT ====================

@app.route("/admin/user/<user_id>/vms")
def admin_user_vms(user_id):
    if not is_admin():
        return redirect("/dashboard")
    users = load_all_users()
    target_user = users.get(user_id)
    if not target_user:
        return "Không tìm thấy user.", 404
    user_vms_raw = get_user_vms(user_id)
    vms = []
    for vid, vm in user_vms_raw.items():
        st = vm.get("status", "stopped")
        status_text = {"running": "VM đang được khởi động lên", "creating": "Đang Tạo VM"}.get(st, "VM Đã Dừng")
        os_name = vm.get("windows", {}).get("name", "Windows Server") if isinstance(vm.get("windows"), dict) else str(vm.get("windows"))
        vms.append({
            "id": vid,
            "name": vm.get("name", "VM"),
            "status": st,
            "status_text": status_text,
            "cpu": vm.get("config", {}).get("cpu", 2),
            "ram": vm.get("config", {}).get("ram", 4),
            "disk": vm.get("config", {}).get("disk", 50),
            "os": os_name,
            "user": vm.get("windows", {}).get("user", "Admin") if isinstance(vm.get("windows"), dict) else "Admin",
            "password": vm.get("windows", {}).get("pass", "Tam255Z") if isinstance(vm.get("windows"), dict) else "Tam255Z",
            "tailscale_ip": vm.get("tailscale_ip"),
            "tailscale_key": vm.get("tailscale_key", ""),
            "billing_cycle": vm.get("billing_cycle", "monthly"),
            "expiry_time": vm.get("expiry_time", ""),
            "logs_locked": vm.get("logs_locked", True),
            "created_at": vm.get("created_at", "")
        })
    settings = get_settings()
    current_user = get_current_user()
    return render_template_string(ADMIN_USER_VMS_PAGE,
        username=current_user["username"],
        balance=current_user["balance"],
        target_user=target_user,
        vms=vms,
        settings=settings)

@app.route("/admin/vm/<user_id>/<vid>/view")
def admin_view_vm(user_id, vid):
    if not is_admin():
        return redirect("/dashboard")
    vm_data = get_vm_data(user_id, vid)
    if not vm_data:
        return "Không tìm thấy máy ảo.", 404
    users = load_all_users()
    target_user = users.get(user_id, {"username": "Unknown"})
    settings = get_settings()
    current_user = get_current_user()
    logs = get_vm_logs(user_id, vid)
    # Lấy trạng thái real-time từ active_vms nếu có
    realtime_status = "unknown"
    with vm_lock:
        if vid in active_vms:
            realtime_status = active_vms[vid].get("status", "unknown")
    return render_template_string(ADMIN_VM_DETAIL_PAGE,
        username=current_user["username"],
        balance=current_user["balance"],
        target_user=target_user,
        vm=vm_data,
        vm_id=vid,
        logs=logs,
        realtime_status=realtime_status,
        settings=settings)

@app.route("/admin/vm/<user_id>/<vid>/logs")
def admin_view_vm_logs(user_id, vid):
    if not is_admin():
        return "Unauthorized", 401
    vm_data = get_vm_data(user_id, vid)
    if not vm_data:
        return "Not found", 404
    logs = get_vm_logs(user_id, vid)
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><title>[Admin] Log VM - """ + vid + """</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
body{font-family:'Inter',sans-serif;background:#0f172a;color:#38bdf8;padding:20px;margin:0}
pre{background:#1e293b;padding:20px;border-radius:8px;overflow-x:auto;font-family:monospace;font-size:13px;line-height:1.5;color:#e2e8f0;white-space:pre-wrap;word-wrap:break-word}
h2{color:#fff;font-size:18px;margin-bottom:15px;display:flex;justify-content:space-between;align-items:center}
.btn-refresh{background:#2563eb;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}
.btn-back{background:#475569;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;text-decoration:none}
.badge{background:#ef4444;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700}
</style>
</head>
<body>
<h2>
<span><span class="badge">ADMIN</span> Log hệ thống VM: """ + vid + """ <span style="font-size:13px;color:#94a3b8">(User: """ + user_id + """)</span></span>
<div style="display:flex;gap:8px">
<a href="/admin/vm/""" + user_id + """/""" + vid + """/view" class="btn-back"><i class="fas fa-arrow-left"></i> Quay lại VM</a>
<button class="btn-refresh" onclick="location.reload()">Tải lại</button>
</div>
</h2>
<pre>""" + logs + """</pre>
<script>
function adminDeleteVM(userId, vmId, vmName){
    if(!confirm("BẠN CHẮC CHẮN MUỐN XÓA VM "" + vmName + "" (ID: " + vmId + ")?\n\nHành động này KHÔNG THỂ hoàn tác.")) return;
    const form = new FormData();
    form.append("user_id", userId);
    form.append("vm_id", vmId);
    fetch("/api/admin/vm/delete", {method:"POST", body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){ alert("Đã xóa VM thành công."); location.reload(); }
        else { alert(d.error || "Thất bại!"); }
    }).catch(()=>alert("Không thể kết nối máy chủ!"));
}
</script>
</body>
</html>"""

# ==================== WORKER NODE APP ====================
worker_app = Flask(__name__)
worker_app.secret_key = secrets.token_hex(32)

@worker_app.route("/worker/create-vm", methods=["POST"])
def worker_create_vm():
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    vm_name = request.form.get("vm_name", "VM").strip()
    config_json = request.form.get("config", "{}")
    windows_key = request.form.get("windows_key", "win11").strip()
    tailscale_key = request.form.get("tailscale_key", "").strip()
    billing_cycle = request.form.get("billing_cycle", "monthly").strip()
    if billing_cycle not in ("hourly", "daily", "monthly"):
        billing_cycle = "monthly"
    try:
        config = json.loads(config_json)
    except Exception:
        config = {"cpu": 2, "ram": 4, "disk": 50}
    images = get_windows_images()
    win_img = images.get(windows_key, list(images.values())[0])
    vm_dir = get_user_vm_dir(user_id, vm_id)
    expiry = calculate_expiry(billing_cycle, duration).isoformat()
    vm_data = {
        "id": vm_id,
        "user_id": user_id,
        "name": vm_name,
        "config": config,
        "windows": win_img,
        "windows_key": windows_key,
        "status": "creating",
        "tailscale_key": tailscale_key,
        "tailscale_ip": None,
        "billing_cycle": billing_cycle,
        "duration": duration,
        "expiry_time": expiry,
        "logs_locked": True,
        "node_id": "local",
        "created_at": datetime.now().isoformat()
    }
    save_vm_data(user_id, vm_id, vm_data)
    t = threading.Thread(target=run_winbox_script, args=(user_id, vm_id, config, win_img, tailscale_key, vm_name, windows_key))
    t.daemon = True
    t.start()
    return jsonify({"success": True, "message": "Worker đang khởi tạo VM..."})

@worker_app.route("/worker/start-vm", methods=["POST"])
def worker_start_vm():
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    vm_name = request.form.get("vm_name", "VM").strip()
    config_json = request.form.get("config", "{}")
    windows_key = request.form.get("windows_key", "win11").strip()
    tailscale_key = request.form.get("tailscale_key", "").strip()
    try:
        config = json.loads(config_json)
    except Exception:
        config = {"cpu": 2, "ram": 4, "disk": 50}
    vm_dir = get_user_vm_dir(user_id, vm_id)
    win_img_path = vm_dir / "win.img"
    if win_img_path.exists():
        ok, msg = start_vm_existing(user_id, vm_id, config, vm_dir, vm_name, windows_key, tailscale_key)
    else:
        images = get_windows_images()
        win_img = images.get(windows_key, list(images.values())[0])
        t = threading.Thread(target=run_winbox_script, args=(user_id, vm_id, config, win_img, tailscale_key, vm_name, windows_key))
        t.daemon = True
        t.start()
        ok, msg = True, "Đang tải và khởi tạo lại máy ảo..."
    if ok:
        vm_data = get_vm_data(user_id, vm_id)
        if vm_data:
            vm_data["status"] = "running"
            save_vm_data(user_id, vm_id, vm_data)
        return jsonify({"success": True, "message": msg})
    return jsonify({"success": False, "error": msg})

@worker_app.route("/worker/stop-vm", methods=["POST"])
def worker_stop_vm():
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    vm_dir = get_user_vm_dir(user_id, vm_id)
    _stop_vm_logged(user_id, vm_id, vm_dir)
    vm_data = get_vm_data(user_id, vm_id)
    if vm_data:
        vm_data["status"] = "stopped"
        save_vm_data(user_id, vm_id, vm_data)
    return jsonify({"success": True, "message": "Đã dừng máy ảo."})

@worker_app.route("/worker/delete-vm", methods=["POST"])
def worker_delete_vm():
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    user_id = request.form.get("user_id", "").strip()
    vm_id = request.form.get("vm_id", "").strip()
    vm_dir = get_user_vm_dir(user_id, vm_id)
    windows_key = request.form.get("windows_key", "win11").strip()
    _delete_vm_logged(user_id, vm_id, vm_dir, windows_key)
    return jsonify({"success": True, "message": "Đã xóa máy ảo."})

@worker_app.route("/worker/vm/<vid>/logs", methods=["GET"])
def worker_vm_logs(vid):
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return "Invalid token", 403
    # user_id không có trong URL, nhưng logs lưu theo user_id/vm_id
    # Ta sẽ tìm trong tất cả users để lấy logs
    logs = "Không tìm thấy logs."
    if USERS_DIR.exists():
        for user_dir in USERS_DIR.iterdir():
            if user_dir.is_dir():
                log_path = user_dir / "vms" / vid / "logs.txt"
                if log_path.exists():
                    try:
                        with open(log_path, "r", encoding="utf-8") as f:
                            logs = f.read()
                        break
                    except Exception:
                        pass
    return logs

@worker_app.route("/worker/status", methods=["GET"])
def worker_status():
    token = request.headers.get("X-Worker-Token", "")
    if token != get_worker_token():
        return jsonify({"success": False, "error": "Invalid worker token"}), 403
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return jsonify({
            "success": True,
            "online": True,
            "cpu_percent": cpu,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "ram_percent": mem.percent,
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_percent": disk.percent
        })
    except ImportError:
        return jsonify({"success": True, "online": True, "note": "psutil not installed"})

# ==================== WORKER AUTO SETUP ====================
def get_local_ip():
    try:
        s = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
        ips = s.stdout.strip().split()
        return ips[0] if ips else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

def start_worker_tunnel(port=5001, timeout=60):
    """Start cloudflared tunnel for worker and return the public URL."""
    cf_path = get_cloudflared_path()
    if not cf_path:
        return None
    print(f"[WORKER TUNNEL] Đang khởi động Cloudflare Tunnel cho Worker trên port {port}...")
    try:
        proc = subprocess.Popen(
            [cf_path, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        url_pattern = re.compile(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)')
        start_time = time.time()
        for line in proc.stdout:
            line = line.strip()
            if line:
                print(f"[CLOUDFLARED] {line}")
                match = url_pattern.search(line)
                if match:
                    return match.group(1), proc
            if time.time() - start_time > timeout:
                print("[WORKER TUNNEL] Hết thờigian chờ tunnel.")
                proc.terminate()
                return None, None
    except Exception as e:
        print(f"[WORKER TUNNEL] Lỗi: {e}")
    return None, None

def register_worker_to_master(master_url, node_info, tunnel_url=""):
    try:
        payload = dict(node_info)
        payload["worker_token"] = get_worker_token()
        if tunnel_url:
            payload["tunnel_url"] = tunnel_url
        r = requests.post(
            f"{master_url.rstrip('/')}/api/worker/register",
            data=payload,
            timeout=15
        )
        return r.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== CLOUDFLARE TUNNEL (FREE) ====================
def get_cloudflared_path():
    if shutil.which("cloudflared"):
        return "cloudflared"
    system = platform.system().lower()
    machine = platform.machine().lower()
    cf_dir = DATA_DIR / "cloudflared_bin"
    cf_dir.mkdir(exist_ok=True)
    if system == "windows":
        bin_name = "cloudflared.exe"
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
    elif system == "darwin":
        bin_name = "cloudflared"
        url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"
    else:
        if "arm64" in machine or "aarch64" in machine:
            arch = "arm64"
        elif "arm" in machine:
            arch = "arm"
        elif "64" in machine:
            arch = "amd64"
        else:
            arch = "386"
        bin_name = "cloudflared"
        url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    bin_path = cf_dir / bin_name
    if bin_path.exists():
        return str(bin_path)
    print(f"[TUNNEL] Đang tải cloudflared ({system}/{machine}) lần đầu, vui lòng chờ...")
    try:
        import urllib.request
        tmp_file = str(cf_dir / "download.tmp")
        urllib.request.urlretrieve(url, tmp_file)
        if system == "darwin" and url.endswith(".tgz"):
            import tarfile
            with tarfile.open(tmp_file, "r:gz") as tar:
                tar.extract("cloudflared", path=str(cf_dir))
            os.remove(tmp_file)
        else:
            os.replace(tmp_file, str(bin_path))
        os.chmod(str(bin_path), 0o755)
        print("[TUNNEL] Tải cloudflared thành công.")
        return str(bin_path)
    except Exception as e:
        print(f"[TUNNEL] Lỗi tải cloudflared: {e}")
        return None

def start_cloudflare_tunnel(port=5000):
    cf_path = get_cloudflared_path()
    if not cf_path:
        print("[TUNNEL] Không thể khởi động tunnel. Bạn vẫn có thể dùng Local: http://127.0.0.1:5000")
        return
    print(f"[TUNNEL] Đang khởi động Cloudflare Tunnel đến http://localhost:{port} ...")
    try:
        proc = subprocess.Popen(
            [cf_path, "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        url_pattern = re.compile(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)')
        for line in proc.stdout:
            line = line.strip()
            if line:
                print(f"[CLOUDFLARED] {line}")
                match = url_pattern.search(line)
                if match:
                    tunnel_url = match.group(1)
                    print("\n" + "="*70)
                    print(f"TRUY CẬP WEB QUA TUNNEL: {tunnel_url}")
                    print("="*70 + "\n")
    except Exception as e:
        print(f"[TUNNEL] Lỗi chạy cloudflared: {e}")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    print("=" * 65)
    print("  WINBOX MANAGER - MULTI-NODE SYSTEM")
    print("=" * 65)
    print("  [1] Chạy Web Server (Master Node)  -> Port 5000")
    print("  [2] Chạy Worker Node (Máy host QEMU) -> Port 5001")
    print("=" * 65)
    choice = input("  Chọn mode (1/2) [mặc định: 1]: ").strip()
    if choice == "2":
        # WORKER MODE
        init_default_admin()
        print("\n[WORKER] Khởi động Worker Node...")
        print("=" * 65)
        print("[WORKER] Bạn có thể nhập Tunnel URL sẵn hoặc để trống để tự động tạo.")
        manual_tunnel = input("  Nhập Tunnel URL (để trống = tự tạo): ").strip()
        master_url = input("  Nhập Master URL (để trống nếu tự thêm tay): ").strip()

        node_name = f"Worker-{secrets.token_hex(3).upper()}"
        local_ip = get_local_ip()
        tunnel_url = manual_tunnel
        tunnel_proc = None

        if not tunnel_url:
            tunnel_url, tunnel_proc = start_worker_tunnel(WORKER_PORT)
            if not tunnel_url:
                print("[WORKER] Không thể tạo tunnel tự động. Bạn cần cung cấp Tunnel URL thủ công.")
                tunnel_url = input("  Nhập Tunnel URL thủ công: ").strip()

        node_id = f"worker_{secrets.token_hex(4)}"
        node_info = {
            "node_id": node_id,
            "name": node_name,
            "host": local_ip,
            "port": str(WORKER_PORT),
            "token": get_worker_token(),
            "enabled": "on"
        }

        print("\n" + "=" * 65)
        print("  THÔNG TIN WORKER NODE (Copy vào Admin Panel nếu cần)")
        print("=" * 65)
        print(f"  Node ID   : {node_id}")
        print(f"  Name      : {node_name}")
        print(f"  Host      : {local_ip}")
        print(f"  Port      : {WORKER_PORT}")
        print(f"  Token     : {get_worker_token()}")
        print(f"  Tunnel URL: {tunnel_url or 'Không có'}")
        print("=" * 65)

        if master_url and tunnel_url:
            print("[WORKER] Đang tự động đăng ký với Master...")
            reg = register_worker_to_master(master_url, node_info, tunnel_url)
            if reg.get("success"):
                print("[WORKER] Đăng ký với Master thành công!")
            else:
                print(f"[WORKER] Đăng ký thất bại: {reg.get('error','Unknown error')}")
                print("[WORKER] Vui lòng thêm node thủ công qua Admin Panel.")
        else:
            print("[WORKER] Hãy thêm node này vào Master qua Admin Panel (hoặc cung cấp Master URL lần sau).")
        print("=" * 65)

        worker_app.run(host="0.0.0.0", port=WORKER_PORT, debug=False, use_reloader=False)
        if tunnel_proc:
            tunnel_proc.terminate()
    else:
        # MASTER MODE
        init_default_admin()
        cleanup_thread = threading.Thread(target=marketplace_cleanup_worker, daemon=True)
        cleanup_thread.start()
        expired_cleanup_thread = threading.Thread(target=expired_vm_cleanup_worker, daemon=True)
        expired_cleanup_thread.start()
        tunnel_thread = threading.Thread(target=start_cloudflare_tunnel, args=(5000,), daemon=True)
        tunnel_thread.start()
        print("=" * 65)
        print("  WINBOX MANAGER - MASTER NODE KHỞI ĐỘNG THÀNH CÔNG")
        print("  Truy cập Local: http://127.0.0.1:5000")
        print("  Đang chờ Cloudflare Tunnel khởi động (khoảng 5-10 giây)...")
        print("=" * 65)
        app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
