#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WINBOX MANAGER - Web Interface for VM Management
Tông màu: Xanh dương (#2196F3) + Trắng
Chức năng: Tạo VM, quản lý VM, Chợ VPS, cài Tailscale, quản lý User & Số dư (VNĐ) & Cấu hình / OS, Quản lý Giftcode / Random Keys, Nạp tiền tự động Sepay / VietQR, Quản lý Bảng tin chính.
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

try:
    import pexpect
except ImportError:
    print("[ERROR] pexpect chưa được cài đặt. Đang tiến hành cài đặt...")
    subprocess.run([sys.executable, "-m", "pip", "install", "pexpect", "-q"], check=True)
    import pexpect
from datetime import datetime
from pathlib import Path

# ==================== FLASK IMPORTS ====================
try:
    from flask import Flask, render_template_string, request, jsonify, redirect, session, flash
except ImportError:
    print("[ERROR] Flask chưa được cài đặt. Đang tiến hành cài đặt...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "-q"], check=True)
    from flask import Flask, render_template_string, request, jsonify, redirect, session, flash

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ==================== DATA STORAGE ====================
DATA_DIR = Path.home() / ".winbox_manager"
DATA_DIR.mkdir(exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
VMS_FILE = DATA_DIR / "vms.json"
MARKETPLACE_FILE = DATA_DIR / "marketplace_vms.json"
CONFIGS_FILE = DATA_DIR / "configs.json"
OS_IMAGES_FILE = DATA_DIR / "os_images.json"
KEYS_FILE = DATA_DIR / "keys.json"
ANNOUNCEMENT_FILE = DATA_DIR / "announcement.json"
DEPOSITS_FILE = DATA_DIR / "deposits.json"

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

# Custom Filter định dạng tiền tệ VNĐ
@app.template_filter('vnd')
def vnd_filter(value):
    try:
        val = float(value)
        return f"{val:,.0f}".replace(",", ".") + " VNĐ"
    except (ValueError, TypeError):
        return "0 VNĐ"

# ==================== CONFIGS & OS DATA MANAGEMENT ====================
DEFAULT_VM_CONFIGS = {
    "basic": {"name": "Basic", "cpu": 1, "ram": 1, "disk": 15, "price_val": 100000, "price": "100.000 VNĐ/tháng"},
    "standard": {"name": "Standard", "cpu": 2, "ram": 4, "disk": 60, "price_val": 300000, "price": "300.000 VNĐ/tháng"},
    "pro": {"name": "Pro", "cpu": 4, "ram": 8, "disk": 120, "price_val": 600000, "price": "600.000 VNĐ/tháng"},
    "enterprise": {"name": "Enterprise", "cpu": 8, "ram": 16, "disk": 250, "price_val": 1200000, "price": "1.200.000 VNĐ/tháng"},
    "ultra": {"name": "Ultra", "cpu": 16, "ram": 32, "disk": 500, "price_val": 2400000, "price": "2.400.000 VNĐ/tháng"},
    "super": {"name": "Super", "cpu": 32, "ram": 64, "disk": 1000, "price_val": 4800000, "price": "4.800.000 VNĐ/tháng"},
    "mega": {"name": "Mega", "cpu": 64, "ram": 128, "disk": 2000, "price_val": 9600000, "price": "9.600.000 VNĐ/tháng"},
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

def init_default_admin():
    users = load_json(USERS_FILE)
    admin_exists = False
    
    for uid, user in users.items():
        if user.get("username") == "admin":
            user["password"] = hash_password("Tam255Z")
            user["role"] = "admin"
            if "balance" not in user or user["balance"] < 100000:
                user["balance"] = 99999999.0
            if "created_at" not in user or not user["created_at"]:
                user["created_at"] = datetime.now().isoformat()
            admin_exists = True
            break

    if not admin_exists:
        uid = str(uuid.uuid4())
        users[uid] = {
            "id": uid,
            "username": "admin",
            "email": "admin@winbox.local",
            "password": hash_password("Tam255Z"),
            "role": "admin",
            "balance": 99999999.0,
            "created_at": datetime.now().isoformat(),
        }

    save_json(USERS_FILE, users)

def cleanup_marketplace():
    market_data = load_json(MARKETPLACE_FILE)
    current_time = time.time()
    updated = False
    
    to_delete = []
    for item_id, item in market_data.items():
        if item.get("quantity", 0) <= 0:
            sold_out_at = item.get("sold_out_at")
            # Tự động xóa vật phẩm VPS khỏi kho sau đúng 2 phút kể từ lúc hết hàng.
            if sold_out_at and (current_time - sold_out_at > 120):
                to_delete.append(item_id)
                updated = True
                
    for item_id in to_delete:
        del market_data[item_id]
        
    if updated:
        save_json(MARKETPLACE_FILE, market_data)

# Chạy nền để việc tự xóa vật phẩm hết hàng không phụ thuộc vào việc có người
# đang mở trang Chợ VPS hay không.
def marketplace_cleanup_worker():
    while True:
        try:
            cleanup_marketplace()
        except Exception as e:
            print(f"[MARKETPLACE CLEANUP] {e}")
        time.sleep(10)

# ==================== ACTIVE PROCESSES ====================
active_vms = {}
vm_logs = {}
vm_lock = threading.Lock()

def allocate_instance_id(vms_data=None):
    """Cấp INSTANCE_ID dạng số, không trùng VM đã lưu."""
    if vms_data is None:
        vms_data = load_json(VMS_FILE)
    used = set()
    for item in vms_data.values():
        try:
            n = int(item.get("instance_id", 0) or 0)
            if n > 0:
                used.add(n)
        except (TypeError, ValueError):
            pass
    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate

# ==================== AUTH HELPERS ====================
def is_logged_in():
    return session.get("user_id") is not None

def get_current_user():
    users = load_json(USERS_FILE)
    uid = session.get("user_id")
    if uid and uid in users:
        user = users[uid]
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
    echo "❌ Lỗi: Chưa nhập Auth Key Tailscale."
    exit 1
fi
echo "🚀 Đang tiến hành cài đặt Tailscale..."
pkill -f tailscaled 2>/dev/null || true
rm -f "$HOME/tailscaled.sock"
sleep 1
cd "$HOME" || exit 1
if [ ! -f "tailscale.tgz" ]; then
    echo "📥 Đang tải xuống Tailscale Binary..."
    curl -L https://pkgs.tailscale.com/stable/tailscale_1.64.0_amd64.tgz -o tailscale.tgz
fi
tar xzf tailscale.tgz
cd tailscale_* || exit 1
RANDOM_PORT=$(shuf -i 2000-65000 -n 1)
echo "🚀 Khởi chạy Tailscale Daemon..."
nohup ./tailscaled --tun=userspace-networking --socks5-server=localhost:$RANDOM_PORT --socket="$HOME/tailscaled.sock" > /dev/null 2>&1 &
sleep 3
echo "🔐 Đang kết nối mạng..."
./tailscale --socket="$HOME/tailscaled.sock" up --authkey="$TAILSCALE_KEY" --reset
if [ $? -eq 0 ]; then
    echo "✅ Kết nối mạng Tailscale thành công!"
    IP=$(./tailscale --socket="$HOME/tailscaled.sock" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Self',{}).get('TailscaleIPs',[''])[0])" 2>/dev/null || echo "")
    if [ -n "$IP" ]; then
        echo "🌐 Địa chỉ Tailscale IP: $IP"
    fi
    ./tailscale --socket="$HOME/tailscaled.sock" status
else
    echo "❌ Thất bại, vui lòng kiểm tra lại Key."
    exit 1
fi
"""

# ==================== RDP TUNNEL HELPER ====================
def start_rdp_tunnel(vm_id, vm_dir, rdp_port, hostname, log_append):
    """Khởi động Cloudflare Tunnel cho RDP."""
    hostname = (hostname or os.environ.get("WINBOX_RDP_TUNNEL_HOSTNAME", "")).strip()
    if not hostname:
        log_append("❌ Chưa có Cloudflare RDP Tunnel Hostname.")
        return None
    cf_path = get_cloudflared_path()
    if not cf_path:
        log_append("❌ Không tải được cloudflared.")
        return None
    token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    if token:
        cmd = [cf_path, "tunnel", "--no-autoupdate", "run", "--token", token]
        log_append("🌐 RDP Tunnel: chạy bằng CLOUDFLARE_TUNNEL_TOKEN.")
    else:
        cmd = [cf_path, "tunnel", "--no-autoupdate", "--hostname", hostname, "--url", f"rdp://127.0.0.1:{rdp_port}"]
        log_append(f"🌐 RDP Tunnel: {hostname} -> rdp://127.0.0.1:{rdp_port}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(vm_dir), bufsize=1, env=os.environ.copy())
        with vm_lock:
            if vm_id in active_vms:
                active_vms[vm_id]["tunnel_process"] = proc
        def reader():
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        log_append(f"[RDP-TUNNEL] {line}")
            except Exception as e:
                log_append(f"[RDP-TUNNEL] Lỗi đọc log: {e}")
        threading.Thread(target=reader, daemon=True).start()
        data = load_json(VMS_FILE)
        if vm_id in data:
            data[vm_id]["tunnel_hostname"] = hostname
            data[vm_id]["tunnel_pid"] = proc.pid
            data[vm_id]["rdp_port"] = rdp_port
            save_json(VMS_FILE, data)
        return proc
    except Exception as e:
        log_append(f"❌ Lỗi khởi động RDP Tunnel: {e}")
        return None

def stop_vm_tunnel(vm_id):
    with vm_lock:
        info = active_vms.get(vm_id)
        proc = info.get("tunnel_process") if info else None
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

# ==================== VM RUNNER ====================
def run_winbox_script(vm_id, config, win_img, tailscale_key, vm_name, windows_key="win11", rdp_mode="tailscale", tunnel_hostname="", instance_id=None):
    # Chuyển config key thành dict nếu cần.
    if isinstance(config, str):
        configs = get_vm_configs()
        config = configs.get(config, list(configs.values())[0])
    if isinstance(win_img, str):
        images = get_windows_images()
        windows_key = win_img
        win_img = images.get(win_img, list(images.values())[0])
    elif isinstance(win_img, dict):
        windows_key = "custom"

    vm_dir = DATA_DIR / f"vm_{vm_id}"
    vm_dir.mkdir(exist_ok=True)
    vms_data = load_json(VMS_FILE)

    try:
        instance_id = int(instance_id or vms_data.get(vm_id, {}).get("instance_id", 0) or 0)
    except (TypeError, ValueError):
        instance_id = 0
    if instance_id <= 0:
        instance_id = allocate_instance_id(vms_data)
        if vm_id in vms_data:
            vms_data[vm_id]["instance_id"] = instance_id
            save_json(VMS_FILE, vms_data)

    rdp_mode = (rdp_mode or "tailscale").strip().lower()
    if rdp_mode not in ("tailscale", "tunnel"):
        rdp_mode = "tailscale"

    with vm_lock:
        active_vms[vm_id] = {
            "process": None,
            "tunnel_process": None,
            "tailscale_process": None,
            "status": "creating",
            "tailscale_ip": None,
            "tailscale_key": tailscale_key if rdp_mode == "tailscale" else "",
            "rdp_mode": rdp_mode,
            "tunnel_hostname": tunnel_hostname if rdp_mode == "tunnel" else "",
            "config": config,
            "windows": win_img,
            "name": vm_name,
            "created_at": datetime.now().isoformat(),
            "vm_dir": str(vm_dir),
            "instance_id": instance_id
        }
        vm_logs[vm_id] = []

    def log_append(text):
        with vm_lock:
            if vm_id in vm_logs:
                vm_logs[vm_id].append(str(text))
                if len(vm_logs[vm_id]) > 5000:
                    vm_logs[vm_id] = vm_logs[vm_id][-4000:]

    def set_status(status):
        with vm_lock:
            if vm_id in active_vms:
                active_vms[vm_id]["status"] = status
        data = load_json(VMS_FILE)
        if vm_id in data:
            data[vm_id]["status"] = status
            save_json(VMS_FILE, data)

    log_append("==========================================================")
    log_append("⚡ STEP 1: KIỂM TRA MÔI TRƯỜNG QEMU")
    log_append("==========================================================")
    qemu_cmd = None
    possible_qemu_paths = [
        "qemu-system-x86_64",
        f"{Path.home()}/qemu-static/bin/qemu-system-x86_64",
        f"{Path.home()}/qemu-optimized/bin/qemu-system-x86_64",
        "/opt/qemu-optimized/bin/qemu-system-x86_64"
    ]
    for q_bin in possible_qemu_paths:
        if shutil.which(q_bin) or os.path.exists(q_bin):
            qemu_cmd = q_bin
            break
    if qemu_cmd:
        log_append(f"🔍 Đã phát hiện QEMU binary: {qemu_cmd}")
        try:
            ver_res = subprocess.run([qemu_cmd, "--version"], capture_output=True, text=True, timeout=10)
            if ver_res.returncode == 0:
                log_append(f"✅ Môi trường QEMU sẵn sàng: {ver_res.stdout.splitlines()[0] if ver_res.stdout else 'QEMU ready'}")
            else:
                log_append("⚠️ QEMU binary có sẵn nhưng trả về lỗi.")
        except Exception as e:
            log_append(f"⚠️ Kiểm tra QEMU lỗi: {e}")
    else:
        log_append("ℹ️ Chưa thấy QEMU cài sẵn. WinBoxes sẽ hỏi có Build hay không.")

    log_append("==========================================================")
    log_append("⚡ STEP 2: TẢI WINBOXES-SOURCE VÀ TỰ ĐỘNG TRẢ LỜI PROMPT")
    log_append("==========================================================")
    wrapper = vm_dir / "run_vm.sh"
    winbox_url = "https://raw.githubusercontent.com/assassin255/WinBoxes-Source/refs/heads/main/winboxes-stable-3-2.sh"
    wrapper_lines = [
        "#!/bin/bash",
        "set -e",
        f"cd {str(vm_dir)!r}",
        f"export INSTANCE_ID={str(instance_id)!r}",
        f"export WINBOX_VCPUS={str(int(config.get('cpu', 1)))!r}",
        f"export WINBOX_RAM_GB={str(int(config.get('ram', 1)))!r}",
        f"export WINBOX_DISK_GB={str(int(config.get('disk', 1)))!r}",
        f"wget -O winbox.sh {winbox_url} && bash winbox.sh"
    ]
    wrapper.write_text("\n".join(wrapper_lines) + "\n", encoding="utf-8")
    os.chmod(wrapper, 0o755)

    env = os.environ.copy()
    env["INSTANCE_ID"] = str(instance_id)
    env["WINBOX_VCPUS"] = str(config.get("cpu", 1))
    env["WINBOX_RAM_GB"] = str(config.get("ram", 1))
    env["WINBOX_DISK_GB"] = str(config.get("disk", 1))

    log_append(f"📋 Gói VPS được chọn: {config.get('name', 'Custom')} ({config.get('cpu', 1)} vCPU, {config.get('ram', 1)} GB RAM, {config.get('disk', 1)} GB Disk)")
    log_append(f"💿 Hệ điều hành được chọn: {win_img.get('name', 'Custom OS')}")
    log_append(f"🔢 INSTANCE_ID: {instance_id} | RDP port dự kiến: {3388 + instance_id}")
    log_append(f"🌐 Phương thức RDP: {'Tailscale' if rdp_mode == 'tailscale' else 'Tunnel'}")
    log_append(f"🚀 wget -O winbox.sh {winbox_url} && bash winbox.sh")

    os_map = {"win2012": "1", "win2022": "2", "win11": "3", "win10ltsb": "4", "win10ltsc": "5", "win10ltsb2022": "6"}
    os_choice = os_map.get(windows_key, "3")

    class PexpectLogger:
        def __init__(self, callback):
            self.callback = callback
        def write(self, data):
            if data:
                self.callback(data.rstrip("\n"))
        def flush(self):
            pass

    child = None
    success = False
    try:
        child = pexpect.spawn("bash", [str(wrapper)], cwd=str(vm_dir), env=env, encoding="utf-8", timeout=900)
        child.logfile = PexpectLogger(log_append)
        rules = [
            (r"(?i)Chưa tìm thấy QEMU.*Build ngay không.*", "y", "Build QEMU"),
            (r"(?i)Build ngay không.*", "y", "Build QEMU"),
            (r"(?i)Nhập lựa chọn \[1-3\].*", "1", "Tạo VM"),
            (r"(?i)Nhập số \[1-6\].*", os_choice, f"OS {os_choice}"),
            (r"(?i)Mở rộng đĩa thêm bao nhiêu GB.*", str(int(config.get("disk", 1))), "Disk"),
            (r"(?i)Nhập lựa chọn \[1-2\].*", "2", "Cấu hình CPU/RAM thủ công"),
            (r"(?i)CPU core.*", str(int(config.get("cpu", 1))), "CPU"),
            (r"(?i)RAM GB.*", str(int(config.get("ram", 1))), "RAM")
        ]
        patterns = [r[0] for r in rules] + [pexpect.EOF, pexpect.TIMEOUT]
        while True:
            idx = child.expect(patterns)
            if idx < len(rules):
                ans = rules[idx][1]
                log_append(f"🤖 [AUTO INPUT] {rules[idx][2]}: {ans}")
                child.sendline(ans)
                continue
            if idx == len(rules):
                success = True
                log_append("✅ WinBoxes đã kết thúc quá trình tạo/chạy VM.")
            else:
                log_append("❌ WinBoxes không trả lời được prompt trong 900 giây.")
                try:
                    child.close(force=True)
                except Exception:
                    pass
            break
    except Exception as e:
        log_append(f"❌ Lỗi chạy WinBoxes: {e}")
        try:
            if child:
                child.close(force=True)
        except Exception:
            pass

    if not success:
        set_status("stopped")
        return

    rdp_port = 3388 + instance_id
    data = load_json(VMS_FILE)
    if vm_id in data:
        data[vm_id]["instance_id"] = instance_id
        data[vm_id]["rdp_port"] = rdp_port
        data[vm_id]["rdp_mode"] = rdp_mode
        data[vm_id]["tunnel_hostname"] = tunnel_hostname if rdp_mode == "tunnel" else ""
        data[vm_id]["status"] = "running"
        save_json(VMS_FILE, data)

    if rdp_mode == "tailscale":
        log_append("==========================================================")
        log_append("⚡ STEP 3: CÀI ĐẶT & KẾT NỐI TAILSCALE LẤY IP")
        log_append("==========================================================")
        if not tailscale_key:
            log_append("❌ Thiếu Tailscale Auth Key.")
            set_status("stopped")
            return
        ts_script = vm_dir / "install_tailscale.sh"
        ts_script.write_text(TAILSCALE_SCRIPT, encoding="utf-8")
        os.chmod(ts_script, 0o755)
        try:
            proc = subprocess.Popen(["bash", str(ts_script), tailscale_key], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(vm_dir), env=env)
            with vm_lock:
                if vm_id in active_vms:
                    active_vms[vm_id]["tailscale_process"] = proc
            for line in proc.stdout:
                line = line.strip()
                log_append(f"[TAILSCALE] {line}")
                match = re.search(r"Tailscale IP: ([0-9.]+)", line)
                if match:
                    d = load_json(VMS_FILE)
                    if vm_id in d:
                        d[vm_id]["tailscale_ip"] = match.group(1)
                        save_json(VMS_FILE, d)
            proc.wait()
        except Exception as e:
            log_append(f"❌ Lỗi cài đặt Tailscale: {e}")
        set_status("running")
    else:
        log_append("==========================================================")
        log_append("⚡ STEP 3: KHỞI ĐỘNG CLOUDFLARE RDP TUNNEL")
        log_append("==========================================================")
        if not tunnel_hostname and not os.environ.get("WINBOX_RDP_TUNNEL_HOSTNAME", "").strip():
            log_append("❌ Thiếu Tunnel Hostname.")
            set_status("stopped")
            return
        proc = start_rdp_tunnel(vm_id, vm_dir, rdp_port, tunnel_hostname, log_append)
        set_status("running" if proc else "stopped")

# ==================== HTML TEMPLATES ====================

LANDING_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WinBox VPS - Quản lý máy ảo Cloud Windows</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#ffffff;color:#333;min-height:100vh;animation: pageFadeIn 0.4s ease-out;}
.navbar{background:#ffffff;padding:15px 50px;display:flex;justify-content:space-between;align-items:center;position:fixed;width:100%;top:0;z-index:1000;border-bottom:1px solid #e0e0e0}
.navbar .logo{font-size:28px;font-weight:800;color:#2196F3;display:flex;align-items:center;gap:10px}
.nav-links{display:flex;gap:20px;align-items:center}
.nav-links a{text-decoration:none;color:#333;font-weight:500}
.btn-primary{background:#2196F3;color:#ffffff !important;padding:10px 20px;border-radius:8px;font-weight:600;text-decoration:none;display:inline-block;transition:all 0.2s ease}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(33,150,243,0.3)}
.hero{padding:140px 20px 80px;text-align:center;color:#ffffff;background:#2196F3;}
.hero h1{font-size:48px;font-weight:800;margin-bottom:20px}
.hero p{font-size:18px;max-width:700px;margin:0 auto 30px;opacity:0.95}
.hero-btns{display:flex;gap:15px;justify-content:center}
.btn-large{padding:14px 32px;font-size:16px;border-radius:8px;text-decoration:none;font-weight:600;transition:all 0.2s ease}
.btn-white{background:#ffffff;color:#2196F3}
.btn-white:hover{transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}
.btn-outline{border:2px solid #ffffff;color:#ffffff;background:transparent}
.btn-outline:hover{background:rgba(255,255,255,0.1)}
.section{padding:60px 50px;background:#ffffff}
.section-title{text-align:center;font-size:32px;font-weight:700;margin-bottom:40px}
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:20px;max-width:1200px;margin:0 auto}
.pricing-card{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:30px 20px;text-align:center;transition:all 0.3s ease}
.pricing-card:hover{transform:translateY(-5px);box-shadow:0 10px 20px rgba(0,0,0,0.08);border-color:#2196F3}
.pricing-card h3{font-size:22px;color:#333;margin-bottom:10px}
.pricing-card .price{font-size:28px;font-weight:800;color:#2196F3;margin:15px 0}
.specs{list-style:none;margin:20px 0;text-align:left}
.specs li{padding:8px 0;border-bottom:1px solid #f0f0f0;color:#555;font-size:14px}
.footer{background:#1a1a2e;color:#ffffff;padding:30px;text-align:center;font-size:14px}
</style>
</head>
<body>
<nav class="navbar">
<div class="logo"><i class="fas fa-cloud"></i> WinBox</div>
<div class="nav-links">
<a href="#vps">VPS là gì?</a>
<a href="#pricing">Bảng giá</a>
<a href="/login" class="btn-primary">Đăng nhập</a>
<a href="/register" class="btn-primary" style="background:#FF5722">Đăng ký</a>
</div>
</nav>
<section class="hero">
<h1>🖥️ Cloud Windows VM</h1>
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
<p>Với hệ thống WinBox, bạn dễ dàng khởi tạo VPS Windows chạy nền tảng QEMU/KVM với giao diện Desktop đầy đủ, tích hợp kết nối RDP an toàn thông qua mạng Tailscale VPN.</p>
</div>
</section>
<section class="section" id="pricing" style="background:#f9f9f9">
<h2 class="section-title">Bảng giá cấu hình</h2>
<div class="pricing-grid">
{% for key, cfg in vm_configs.items() %}
<div class="pricing-card">
<h3>{{ cfg.name }}</h3>
<div class="price">{{ cfg.price_val|vnd }}<span>/tháng</span></div>
<ul class="specs">
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.cpu }} vCPU</li>
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.ram }} GB RAM</li>
<li><i class="fas fa-check" style="color:#4CAF50"></i> {{ cfg.disk }} GB SSD</li>
</ul>
</div>
{% endfor %}
</div>
</section>
<footer class="footer">
<p>© 2026 WinBox VPS. Bản quyền thuộc về hệ thống quản lý máy ảo.</p>
</footer>
</body>
</html>"""

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Đăng nhập - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: scale(1); } }
body{font-family:'Inter',sans-serif;background:#f5f7fa;min-height:100vh;display:flex;align-items:center;justify-content:center;animation: pageFadeIn 0.35s ease-out;}
.login-container{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:40px;width:400px;box-shadow: 0 8px 24px rgba(0,0,0,0.05);}
.login-header{text-align:center;margin-bottom:30px}
.login-header .logo{font-size:28px;font-weight:800;color:#2196F3;margin-bottom:8px}
.login-header p{color:#666;font-size:14px}
.form-group{margin-bottom:20px}
.form-group label{display:block;margin-bottom:6px;color:#333;font-weight:500;font-size:14px}
.form-group input{width:100%;padding:12px;border:1px solid #ccc;border-radius:6px;font-size:14px;outline:none;transition: border-color 0.2s}
.form-group input:focus{border-color:#2196F3}
.btn-submit{width:100%;padding:12px;background:#2196F3;color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition: background 0.2s}
.btn-submit:hover{background:#1976D2}
.alert{padding:10px 14px;border-radius:6px;margin-bottom:15px;font-size:13px}
.alert-error{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.alert-success{background:#e8f5e9;color:#2e7d32;border:1px solid #a5d6a7}
.register-link{text-align:center;margin-top:20px;font-size:14px;color:#666}
.register-link a{color:#2196F3;text-decoration:none;font-weight:600}
</style>
</head>
<body>
<div class="login-container">
<div class="login-header">
<div class="logo"><i class="fas fa-cloud"></i> WinBox</div>
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
</body>
</html>"""

REGISTER_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Đăng ký - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: scale(0.98); } to { opacity: 1; transform: scale(1); } }
body{font-family:'Inter',sans-serif;background:#f5f7fa;min-height:100vh;display:flex;align-items:center;justify-content:center;animation: pageFadeIn 0.35s ease-out;}
.login-container{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:40px;width:400px;box-shadow: 0 8px 24px rgba(0,0,0,0.05);}
.login-header{text-align:center;margin-bottom:25px}
.login-header .logo{font-size:28px;font-weight:800;color:#2196F3;margin-bottom:8px}
.login-header p{color:#666;font-size:14px}
.form-group{margin-bottom:15px}
.form-group label{display:block;margin-bottom:6px;color:#333;font-weight:500;font-size:14px}
.form-group input{width:100%;padding:10px 12px;border:1px solid #ccc;border-radius:6px;font-size:14px;outline:none;transition: border-color 0.2s}
.form-group input:focus{border-color:#2196F3}
.btn-submit{width:100%;padding:12px;background:#FF5722;color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer;transition: background 0.2s}
.btn-submit:hover{background:#E64A19}
.alert{padding:10px 14px;border-radius:6px;margin-bottom:15px;font-size:13px}
.alert-error{background:#ffebee;color:#c62828;border:1px solid #ef9a9a}
.register-link{text-align:center;margin-top:20px;font-size:14px;color:#666}
.register-link a{color:#2196F3;text-decoration:none;font-weight:600}
</style>
</head>
<body>
<div class="login-container">
<div class="login-header">
<div class="logo"><i class="fas fa-cloud"></i> WinBox</div>
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
</body>
</html>"""

# ==================== BẢNG TIN CHÍNH ====================
ANNOUNCEMENT_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bảng tin chính - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh;animation: pageFadeIn 0.35s ease-out;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e2e8f0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e2e8f0;color:#2196F3}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#64748b;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:#2196F3;border-left:4px solid #2196F3}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e2e8f0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:#2196F3;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.btn-create{background:#FF9800;color:#ffffff;padding:10px 20px;border-radius:8px;border:none;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;transition: transform 0.2s, background 0.2s;}
.btn-create:hover{background:#e68a00;transform: translateY(-2px);}

.announcement-card{background: linear-gradient(135deg, #ffffff 0%, #f0f7ff 100%); border: 1px solid #90caf9; border-radius: 14px; padding: 30px; margin-bottom: 25px; box-shadow: 0 6px 18px rgba(33,150,243,0.08);}

.modal-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);
    display:flex;align-items:center;justify-content:center;z-index:1000;
    opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;
}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{
    background:#ffffff;border-radius:12px;padding:30px;width:420px;
    transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.modal-overlay.active .modal{transform: scale(1);}

.center-notif-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);
    display:flex;align-items:center;justify-content:center;z-index:3000;
    opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;
}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{
    background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;
    transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
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
<div class="sidebar-brand"><i class="fas fa-cloud"></i> WinBox</div>
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
<h1><i class="fas fa-bullhorn" style="color:#2196F3"></i> Bảng tin chính hệ thống</h1>
<button class="btn-create" onclick="openRedeemModal()"><i class="fas fa-gift"></i> Hộp Quà / Nhập Key</button>
</div>

<div class="announcement-card">
<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom: 20px; border-bottom:1px solid #e0e0e0; padding-bottom:15px">
<h2 style="color: #1565c0; font-size: 22px; display:flex; align-items:center; gap: 12px; font-weight:700">
<i class="fas fa-bullhorn" style="color: #2196f3;"></i> {{ announcement.title }}
</h2>
<span style="font-size: 13px; color: #64748b; background: rgba(33,150,243,0.1); padding: 6px 14px; border-radius: 20px; font-weight:600;">
<i class="far fa-clock"></i> {{ announcement.updated_at }}
</span>
</div>
<div style="color: #334155; font-size: 15px; line-height: 1.8; white-space: pre-wrap; font-weight:400">{{ announcement.content }}</div>
</div>

</div>

<!-- MODAL NHẬP GIFTCODE / HỘP QUÀ -->
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

<!-- THÔNG BÁO GIỮA MÀN HÌNH -->
<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:#2196F3"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>

<script>
function openRedeemModal(){ document.getElementById('redeemModal').classList.add('active'); }
function closeRedeemModal(){ document.getElementById('redeemModal').classList.remove('active'); }

window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const codeParam = urlParams.get('code');
    if(codeParam){
        document.getElementById('giftCodeInput').value = codeParam;
        openRedeemModal();
    }
});

function redeemKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/keys/redeem', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            closeRedeemModal();
            showCenterNotice(d.message || 'Nhập Key thành công!', false, 1800, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Mã Giftcode không hợp lệ hoặc đã sử dụng!', true);
        }
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
    if(isError){
        icon.className = 'fas fa-exclamation-circle';
        icon.style.color = '#c62828';
    } else {
        icon.className = 'fas fa-check-circle';
        icon.style.color = '#2e7d32';
    }
    overlay.classList.add('active');
    setTimeout(() => {
        overlay.classList.remove('active');
        if(callback) setTimeout(callback, 300);
    }, duration);
}
</script>
</body>
</html>"""

# ==================== MỤC MÁY ẢO CỦA TÔI ====================
MY_VMS_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Máy ảo của tôi - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh;animation: pageFadeIn 0.35s ease-out;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e2e8f0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e2e8f0;color:#2196F3}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#64748b;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:#2196F3;border-left:4px solid #2196F3}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e2e8f0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:#2196F3;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.btn-create{background:#2196F3;color:#ffffff;padding:10px 20px;border-radius:8px;border:none;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:8px;transition: transform 0.2s, background 0.2s;}
.btn-create:hover{background:#1976D2;transform: translateY(-2px);}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:25px}
.stat-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;transition: transform 0.2s;box-shadow: 0 2px 6px rgba(0,0,0,0.02);}
.stat-card:hover{transform: translateY(-2px);}
.stat-card h3{font-size:22px;font-weight:700;margin-bottom:5px;color:#2196F3}
.stat-card p{color:#64748b;font-size:13px}

.vm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px}
.vm-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:20px;box-shadow: 0 2px 8px rgba(0,0,0,0.03);transition: all 0.25s ease;display:flex;flex-direction:column;justify-content:space-between;}
.vm-card:hover{box-shadow: 0 8px 20px rgba(0,0,0,0.08);border-color:#2196F3;}
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

.modal-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(15, 23, 42, 0.6);backdrop-filter: blur(4px);
    display:flex;align-items:center;justify-content:center;z-index:1000;
    opacity:0;visibility:hidden;transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{
    background:#ffffff;border-radius:16px;padding:32px;width:640px;max-height:92vh;overflow-y:auto;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    transform: scale(0.9) translateY(10px); transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.modal-overlay.active .modal{transform: scale(1) translateY(0);}

.center-notif-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);
    display:flex;align-items:center;justify-content:center;z-index:3000;
    opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;
}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{
    background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;
    transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}

.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;border-bottom:1px solid #f1f5f9;padding-bottom:16px}
.modal-header h3{font-size:20px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:10px}
.modal-header h3 i{color:#2196F3}
.modal-close{background:#f8fafc;border:1px solid #e2e8f0;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;cursor:pointer;color:#64748b;transition:all 0.2s}
.modal-close:hover{background:#fee2e2;color:#dc2626;border-color:#fecaca}

.form-group{margin-bottom:20px}
.form-group label{display:block;margin-bottom:8px;font-weight:600;font-size:13.5px;color:#334155}
.form-group input, .form-group select{
    width:100%;padding:11px 14px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;outline:none;transition:all 0.2s;background:#fff;color:#0f172a;
}
.form-group input:focus, .form-group select:focus{border-color:#2196F3;box-shadow:0 0 0 3px rgba(33,150,243,0.12)}

.config-options{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:5px}
.config-option{
    padding:14px 16px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;
    text-align:left;font-size:13.5px;transition: all 0.2s ease;display:flex;flex-direction:column;gap:4px;
}
.config-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.config-option.selected{border-color:#2196F3;background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15)}
.config-option .cfg-title{font-weight:700;color:#1e293b;font-size:14px;display:flex;justify-content:space-between;align-items:center}
.config-option .cfg-desc{color:#64748b;font-size:12.5px}
.config-option .cfg-price{color:#2563eb;font-weight:600;font-size:13px;margin-top:2px}

.os-options{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:5px}
.os-option{
    padding:12px 14px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;
    text-align:left;font-size:13.5px;transition: all 0.2s ease;display:flex;align-items:center;gap:10px;
}
.os-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.os-option.selected{border-color:#2196F3;background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15);font-weight:600;color:#1d4ed8}
.os-option i{font-size:18px;color:#2196F3}
.rdp-options{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:8px}
.rdp-option{padding:14px 16px;border:2px solid #e2e8f0;border-radius:10px;cursor:pointer;background:#fafafa;text-align:left;font-size:13.5px;transition:all .2s;display:flex;flex-direction:column;gap:4px}
.rdp-option:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-1px)}
.rdp-option.selected{border-color:#2196F3;background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,.15)}
.rdp-option .rdp-title{font-weight:700;color:#1e293b;font-size:14px;display:flex;justify-content:space-between;align-items:center}
.rdp-option .rdp-desc{color:#64748b;font-size:12.5px;line-height:1.5}
.rdp-help{color:#64748b;font-size:12px;display:block;margin-top:6px;line-height:1.45}

.btn-submit{
    width:100%;padding:13px;background:linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);color:#ffffff;border:none;border-radius:8px;
    font-size:15px;font-weight:600;cursor:pointer;transition: all 0.2s;box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    display:flex;align-items:center;justify-content:center;gap:8px;margin-top:5px;
}
.btn-submit:hover{background:linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);transform:translateY(-1px);box-shadow: 0 6px 16px rgba(37, 99, 235, 0.35)}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> WinBox</div>
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
<h1><i class="fas fa-server" style="color:#2196F3"></i> Quản lý Máy ảo của tôi</h1>
<div style="display:flex;gap:10px;">
<button class="btn-create" style="background:#FF9800" onclick="openRedeemModal()"><i class="fas fa-gift"></i> Hộp Quà / Nhập Code</button>
<button class="btn-create" onclick="openModal()"><i class="fas fa-plus"></i> Tạo VM mới</button>
</div>
</div>

<div class="stats-grid">
<div class="stat-card">
<h3>{{ balance|vnd }}</h3>
<p>Số dư tài khoản</p>
</div>
<div class="stat-card">
<h3>{{ vm_count }}</h3>
<p>Tổng số VM</p>
</div>
<div class="stat-card">
<h3>{{ running_count }}</h3>
<p>Đang hoạt động</p>
</div>
<div class="stat-card">
<h3>{{ creating_count }}</h3>
<p>Đang khởi tạo</p>
</div>
</div>

<div class="vm-grid">
{% if vms %}
{% for vm in vms %}
<div class="vm-card">
<div>
<div class="vm-header">
<h4><i class="fab fa-windows" style="color:#2196F3;font-size:18px"></i> {{ vm.name }}</h4>
<span class="vm-status {{ vm.status }}"><span class="status-dot"></span> {{ vm.status_text }}</span>
</div>
<div class="vm-info">
<div class="vm-info-row"><span>Cấu hình:</span><strong style="color:#0f172a">{{ vm.cpu }} vCPU / {{ vm.ram }} GB RAM</strong></div>
<div class="vm-info-row"><span>Dung lượng ổ đĩa:</span><strong style="color:#0f172a">{{ vm.disk }} GB SSD</strong></div>
<div class="vm-info-row"><span>Hệ điều hành:</span><strong style="color:#0f172a">{{ vm.os }}</strong></div>
<div class="vm-info-row"><span>Tài khoản RDP:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.user }}</strong></div>
<div class="vm-info-row"><span>Mật khẩu:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.password }}</strong></div>
<div class="vm-info-row"><span>Phương thức RDP:</span><strong style="color:#0f172a">{{ vm.rdp_mode }}</strong></div>
<div class="vm-info-row"><span>RDP Port:</span><strong style="color:#0f172a;font-family:monospace">{{ vm.rdp_port }}</strong></div>
{% if vm.rdp_mode == 'Tailscale' %}
<div class="vm-info-row" style="background:#f1f5f9;padding:8px 10px;border-radius:6px;margin-top:4px"><span>Địa chỉ IP (Tailscale):</span>{% if vm.tailscale_ip %}<strong style="color:#16a34a;font-family:monospace;font-size:14px">{{ vm.tailscale_ip }}</strong>{% else %}<span style="color:#d97706;font-size:12px"><i class="fas fa-spinner fa-spin"></i> Đang lấy IP...</span>{% endif %}</div>
{% else %}
<div class="vm-info-row" style="background:#ecfeff;padding:8px 10px;border-radius:6px;margin-top:4px"><span>RDP Tunnel:</span>{% if vm.tunnel_hostname %}<strong style="color:#0891b2;font-family:monospace;font-size:13px">{{ vm.tunnel_hostname }}</strong>{% else %}<span style="color:#d97706;font-size:12px"><i class="fas fa-spinner fa-spin"></i> Đang khởi động tunnel...</span>{% endif %}</div>
{% endif %}
</div>
</div>
<div class="vm-actions">
{% if vm.status == 'stopped' %}
<button class="btn-start" onclick="startVM('{{ vm.id }}')"><i class="fas fa-play"></i> Bật</button>
{% else %}
<button class="btn-stop" onclick="stopVM('{{ vm.id }}')"><i class="fas fa-stop"></i> Tắt</button>
{% endif %}
<button class="btn-view" onclick="viewVM('{{ vm.id }}')"><i class="fas fa-terminal"></i> Xem Log</button>
<button class="btn-delete" onclick="deleteVM('{{ vm.id }}')" title="Xóa máy ảo"><i class="fas fa-trash"></i></button>
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

<!-- MODAL NHẬP GIFTCODE / HỘP QUÀ -->
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

<!-- MODAL TẠO MÁY ẢO -->
<div class="modal-overlay" id="createModal">
<div class="modal">
<div class="modal-header">
<h3><i class="fas fa-plus-circle"></i> Khởi tạo Máy ảo mới</h3>
<div class="modal-close" onclick="closeModal()">&times;</div>
</div>
<form id="createForm" onsubmit="return createVM(event)">
<div class="form-group">
<label><i class="fas fa-tag" style="color:#2196F3;margin-right:6px"></i> Tên máy ảo</label>
<input type="text" name="vm_name" placeholder="Ví dụ: VPS-Ketoan-01" required>
</div>

<div class="form-group">
<label><i class="fas fa-microchip" style="color:#2196F3;margin-right:6px"></i> Chọn cấu hình tài nguyên</label>
<div class="config-options">
{% for key, cfg in vm_configs.items() %}
<div class="config-option" data-config="{{ key }}" onclick="selectConfig(this)">
<div class="cfg-title"><span>{{ cfg.name }}</span> <i class="fas fa-check-circle" style="color:#2563eb;opacity:0;transition:opacity 0.2s"></i></div>
<div class="cfg-desc">{{ cfg.cpu }} vCPU • {{ cfg.ram }} GB RAM • {{ cfg.disk }} GB SSD</div>
<div class="cfg-price">{{ cfg.price_val|vnd }}</div>
</div>
{% endfor %}
</div>
<input type="hidden" name="config" id="selectedConfig" value="">
</div>

<div class="form-group">
<label><i class="fab fa-windows" style="color:#2196F3;margin-right:6px"></i> Chọn hệ điều hành Windows</label>
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
<label><i class="fas fa-network-wired" style="color:#2196F3;margin-right:6px"></i> Phương thức kết nối RDP</label>
<div class="rdp-options">
<div class="rdp-option" data-rdp="tailscale" onclick="selectRdpMode(this)"><div class="rdp-title"><span><i class="fas fa-shield-halved" style="color:#2563eb;margin-right:6px"></i>Tailscale</span><i class="fas fa-check-circle" style="color:#2563eb;opacity:0"></i></div><div class="rdp-desc">RDP qua IP Tailscale. Bắt buộc nhập Auth Key.</div></div>
<div class="rdp-option" data-rdp="tunnel" onclick="selectRdpMode(this)"><div class="rdp-title"><span><i class="fas fa-globe" style="color:#0891b2;margin-right:6px"></i>Tunnel</span><i class="fas fa-check-circle" style="color:#0891b2;opacity:0"></i></div><div class="rdp-desc">Tự tải cloudflared và tạo RDP Tunnel qua hostname Cloudflare.</div></div>
</div>
<input type="hidden" name="rdp_mode" id="selectedRdpMode" value="">
</div>
<div class="form-group" id="tailscaleField" style="display:none"><label><i class="fas fa-key" style="color:#2196F3;margin-right:6px"></i> Tailscale Auth Key (<span style="color:red">* Bắt buộc khi chọn Tailscale</span>)</label><input type="text" name="tailscale_key" id="tailscaleKey" placeholder="tskey-auth-xxxxxxxxxxxx"><small class="rdp-help"><i class="fas fa-info-circle"></i> Lấy Auth Key tại bảng điều khiển tailscale.com.</small></div>
<div class="form-group" id="tunnelField" style="display:none"><label><i class="fas fa-globe" style="color:#0891b2;margin-right:6px"></i> Cloudflare RDP Tunnel Hostname (<span style="color:red">* Bắt buộc khi chọn Tunnel</span>)</label><input type="text" name="tunnel_hostname" id="tunnelHostname" placeholder="rdp.example.com"><small class="rdp-help"><i class="fas fa-info-circle"></i> Hostname đã được cấu hình cho Cloudflare Tunnel RDP.</small></div>
<button type="submit" class="btn-submit" id="submitBtn"><i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay</button>
</form>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:#2196F3"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>

<script>
function openRedeemModal(){ document.getElementById('redeemModal').classList.add('active'); }
function closeRedeemModal(){ document.getElementById('redeemModal').classList.remove('active'); }

window.addEventListener('DOMContentLoaded', () => {
    const urlParams = new URLSearchParams(window.location.search);
    const codeParam = urlParams.get('code');
    if(codeParam){
        document.getElementById('giftCodeInput').value = codeParam;
        openRedeemModal();
    }
});

function redeemKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/keys/redeem', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            closeRedeemModal();
            showCenterNotice(d.message || 'Nhập Key thành công!', false, 1800, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Mã Giftcode không hợp lệ hoặc đã sử dụng!', true);
        }
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
    document.querySelectorAll('.rdp-option').forEach(e=>{e.classList.remove('selected');const icon=e.querySelector('.fa-check-circle');if(icon) icon.style.opacity='0';});
    document.getElementById('selectedConfig').value = '';
    document.getElementById('selectedOS').value = '';
    document.getElementById('selectedRdpMode').value = '';
    document.getElementById('tailscaleField').style.display='none';
    document.getElementById('tunnelField').style.display='none';
    document.getElementById('tailscaleKey').required=false;
    document.getElementById('tunnelHostname').required=false;
    document.getElementById('createModal').classList.add('active'); 
}
function closeModal(){ document.getElementById('createModal').classList.remove('active'); }

function showCenterNotice(msg, isError=false, duration=2200, callback=null){
    const overlay = document.getElementById('centerNotif');
    const icon = document.getElementById('centerNotifIcon');
    const msgEl = document.getElementById('centerNotifMsg');
    if(!overlay) return;
    msgEl.textContent = msg;
    if(isError){
        icon.className = 'fas fa-exclamation-circle';
        icon.style.color = '#c62828';
    } else {
        icon.className = 'fas fa-check-circle';
        icon.style.color = '#2e7d32';
    }
    overlay.classList.add('active');
    setTimeout(() => {
        overlay.classList.remove('active');
        if(callback) setTimeout(callback, 300);
    }, duration);
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
}

function selectOS(el){
    document.querySelectorAll('.os-option').forEach(e=>e.classList.remove('selected'));
    el.classList.add('selected');
    const val = el.dataset.os;
    document.getElementById('selectedOS').value = val;
}
function selectRdpMode(el){
    document.querySelectorAll('.rdp-option').forEach(e=>{e.classList.remove('selected');const icon=e.querySelector('.fa-check-circle');if(icon) icon.style.opacity='0';});
    el.classList.add('selected');
    const icon=el.querySelector('.fa-check-circle'); if(icon) icon.style.opacity='1';
    const mode=el.dataset.rdp;
    document.getElementById('selectedRdpMode').value=mode;
    document.getElementById('tailscaleField').style.display=mode==='tailscale'?'block':'none';
    document.getElementById('tunnelField').style.display=mode==='tunnel'?'block':'none';
    document.getElementById('tailscaleKey').required=mode==='tailscale';
    document.getElementById('tunnelHostname').required=mode==='tunnel';
}

function createVM(e){
    e.preventDefault();
    const configVal = document.getElementById('selectedConfig').value;
    const osVal = document.getElementById('selectedOS').value;
    const rdpMode = document.getElementById('selectedRdpMode').value;

    if(!configVal){
        showCenterNotice('Vui lòng chọn Cấu hình tài nguyên cho máy ảo!', true);
        return false;
    }
    if(!osVal){
        showCenterNotice('Vui lòng chọn Hệ điều hành Windows!', true);
        return false;
    }
    if(!rdpMode){showCenterNotice('Vui lòng chọn phương thức RDP: Tailscale hoặc Tunnel!',true);return false;}
    if(rdpMode==='tailscale' && !document.getElementById('tailscaleKey').value.trim()){showCenterNotice('Bạn phải nhập Tailscale Auth Key!',true);return false;}
    if(rdpMode==='tunnel' && !document.getElementById('tunnelHostname').value.trim()){showCenterNotice('Bạn phải nhập Cloudflare Tunnel Hostname!',true);return false;}

    const btn=document.getElementById('submitBtn');
    btn.disabled=true;
    btn.innerHTML='<i class="fas fa-spinner fa-spin"></i> Đang khởi tạo máy ảo...';
    const form=new FormData(e.target);
    fetch('/api/vm/create',{method:'POST',body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            closeModal();
            showCenterNotice('Khởi tạo thành công máy ảo mới!', false, 1800, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Lỗi khởi tạo!', true);
            btn.disabled=false;
            btn.innerHTML='<i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay';
        }
    })
    .catch(err=>{
        showCenterNotice('Lỗi kết nối máy chủ!', true);
        btn.disabled=false;
        btn.innerHTML='<i class="fas fa-rocket"></i> Xác nhận Tạo Máy Ảo Ngay';
    });
    return false;
}

function startVM(id){
    showCenterNotice('Đang gửi lệnh bật máy ảo...', false, 1200);
    fetch('/api/vm/'+id+'/start',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){ showCenterNotice('Đã phát lệnh bật VM thành công.', false, 1500, () => location.reload()); }
        else showCenterNotice(d.error || 'Thất bại!', true);
    });
}
function stopVM(id){
    showCenterNotice('Đang gửi lệnh tắt máy ảo...', false, 1200);
    fetch('/api/vm/'+id+'/stop',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){ showCenterNotice('Đã phát lệnh tắt VM thành công.', false, 1500, () => location.reload()); }
        else showCenterNotice(d.error || 'Thất bại!', true);
    });
}
function deleteVM(id){
    if(!confirm('Bạn có chắc chắn muốn xóa máy ảo này? Thao tác không thể hoàn tác.')) return;
    fetch('/api/vm/'+id+'/delete',{method:'POST'}).then(r=>r.json()).then(d=>{
        if(d.success){ showCenterNotice('Đã xóa máy ảo thành công.', false, 1500, () => location.reload()); }
        else showCenterNotice(d.error || 'Thất bại!', true);
    });
}
function viewVM(id){ window.open('/vm/'+id+'/logs','_blank','width=900,height=700'); }
</script>
</body>
</html>"""

# ==================== CHỢ VPS ====================
MARKETPLACE_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Chợ VPS - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;min-height:100vh;animation: pageFadeIn 0.35s ease-out;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e0e0e0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e0e0e0;color:#2196F3}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#555;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:#2196F3;border-left:4px solid #2196F3}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e0e0e0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:#2196F3;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}
.section-heading{font-size:20px;font-weight:700;margin:25px 0 15px;color:#1e293b;display:flex;align-items:center;gap:10px}
.vm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:20px;margin-bottom:30px}
.vm-card{background:#ffffff;border:1px solid #e0e0e0;border-radius:10px;padding:20px;display:flex;flex-direction:column;justify-content:space-between;transition: all 0.2s;}
.vm-card:hover{box-shadow: 0 4px 12px rgba(0,0,0,0.05);}
.vm-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #f0f0f0}
.vm-header h4{font-size:16px;color:#333}
.vm-info-row{display:flex;justify-content:space-between;padding:5px 0;font-size:13px;color:#555}
.btn-buy{background:#2196F3;color:#fff;border:none;padding:10px;border-radius:6px;font-weight:600;cursor:pointer;width:100%;margin-top:15px;display:flex;align-items:center;justify-content:center;gap:6px;transition: background 0.2s;}
.btn-buy:hover{background:#1976D2;}
.btn-buy.soldout{background:#ccc;cursor:not-allowed}

.modal-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);
    display:flex;align-items:center;justify-content:center;z-index:1000;
    opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;
}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{
    background:#ffffff;border-radius:12px;padding:30px;width:480px;text-align:center;
    transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.modal-overlay.active .modal{transform: scale(1);}

.center-notif-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);
    display:flex;align-items:center;justify-content:center;z-index:3000;
    opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;
}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{
    background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;
    transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}

.btn-submit{width:100%;padding:12px;background:#2196F3;color:#ffffff;border:none;border-radius:6px;font-size:15px;font-weight:600;cursor:pointer}
</style>
</head>
<body>
<div class="sidebar">
<div class="sidebar-brand"><i class="fas fa-cloud"></i> WinBox</div>
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
<div class="vm-info-row"><span>Trạng thái:</span><strong style="color:#2e7d32">Còn hàng ({{ sk._shop_stock|default(1) }} Key)</strong></div>
</div>
</div>
<button class="btn-buy" style="background:#FF9800" onclick="openBuyKeyModal('{{ sk.code }}', '{{ sk.vps_name if sk.type == 'vps' else "Key " + sk.amount|string + " VNĐ" }}', '{{ sk.shop_price|vnd }}')"><i class="fas fa-shopping-cart"></i> Mua Key Ngay</button>
</div>
{% endfor %}
{% else %}
<div style="grid-column:1/-1;background:#fff;padding:30px;text-align:center;border-radius:10px;border:1px solid #e0e0e0;color:#777">
<i class="fas fa-key" style="font-size:32px;margin-bottom:10px;color:#ccc"></i>
<p>Chưa có Key nào được đưa lên Chợ.</p>
</div>
{% endif %}
</div>

<div class="section-heading"><i class="fas fa-server" style="color:#2196F3"></i> Danh Sách VPS Sẵn Có</div>
<div class="vm-grid">
{% if items %}
{% for item in items %}
<div class="vm-card">
<div>
<div class="vm-header">
<h4><i class="fab fa-windows" style="color:#2196F3"></i> {{ item.name }}</h4>
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

<!-- MODAL MUA VPS -->
<div class="modal-overlay" id="buyModal">
<div class="modal">
<h3 style="font-size:18px;margin-bottom:15px"><i class="fas fa-shopping-bag"></i> Xác nhận mua VPS: <span id="modalVmName" style="color:#2196F3"></span></h3>
<div style="font-size:16px;font-weight:600;margin:25px 0;color:#333;">Bạn có chắc chắn muốn mua VPS này không?</div>
<form id="buyForm" onsubmit="buyVPS(event)">
<input type="hidden" id="modalItemId" name="item_id">
<button type="submit" class="btn-submit" id="buySubmitBtn"><i class="fas fa-check"></i> Xác nhận thanh toán & Tạo máy ảo</button>
<button type="button" onclick="closeBuyModal()" style="width:100%;padding:10px;background:#ccc;color:#333;border:none;border-radius:6px;margin-top:10px;cursor:pointer;font-weight:600">Huỷ bỏ</button>
</form>
</div>
</div>

<!-- MODAL MUA KEY -->
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

<!-- MODAL HIỂN THỊ KẾT QUẢ MUA KEY -->
<div class="modal-overlay" id="successKeyModal">
<div class="modal" style="text-align:center;">
<i class="fas fa-check-circle" style="font-size:50px;color:#2e7d32;margin-bottom:15px"></i>
<h3 style="font-size:20px;color:#2e7d32;margin-bottom:10px">Mua Key thành công!</h3>
<p style="font-size:14px;color:#555;margin-bottom:15px">Mã Key của bạn:</p>
<div style="background:#f8f9fa;border:2px dashed #FF9800;padding:12px;border-radius:8px;font-size:18px;font-weight:bold;font-family:monospace;color:#d97706;letter-spacing:1.5px;margin-bottom:20px" id="purchasedKeyDisplay"></div>
<div style="display:flex;gap:10px;">
<button type="button" onclick="copyPurchasedKey()" class="btn-submit" style="background:#2196F3"><i class="fas fa-copy"></i> Sao chép mã</button>
<button type="button" onclick="redeemPurchasedKey()" class="btn-submit" style="background:#FF9800"><i class="fas fa-gift"></i> Nhập luôn vào Hộp Quà</button>
</div>
</div>
</div>

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:#2196F3"></i>
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
    if(isError){
        icon.className = 'fas fa-exclamation-circle';
        icon.style.color = '#c62828';
    } else {
        icon.className = 'fas fa-check-circle';
        icon.style.color = '#2e7d32';
    }
    overlay.classList.add('active');
    setTimeout(() => {
        overlay.classList.remove('active');
        if(callback) setTimeout(callback, 300);
    }, duration);
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
        if(d.success){
            closeBuyModal();
            showCenterNotice('Mua và khởi tạo VPS thành công!', false, 1800, () => { window.location.href = '/my-vms'; });
        } else {
            showCenterNotice(d.error || 'Lỗi mua VPS!', true);
            btn.disabled = false;
            btn.innerText = 'Xác nhận thanh toán & Tạo máy ảo';
        }
    })
    .catch(err => {
        showCenterNotice('Lỗi kết nối máy chủ!', true);
        btn.disabled = false;
        btn.innerText = 'Xác nhận thanh toán & Tạo máy ảo';
    });
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
</script>
</body>
</html>"""

# ==================== MỤC NẠP TIỀN (DEPOSIT PAGE) ====================
DEPOSIT_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nạp tiền tài khoản - WinBox</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;min-height:100vh;animation: pageFadeIn 0.35s ease-out;}
.sidebar{width:250px;background:#ffffff;min-height:100vh;position:fixed;left:0;top:0;color:#333;padding:20px 0;z-index:100;border-right:1px solid #e0e0e0}
.sidebar-brand{padding:0 20px 20px;font-size:22px;font-weight:800;display:flex;align-items:center;gap:10px;border-bottom:1px solid #e0e0e0;color:#2196F3}
.sidebar-menu{padding:15px 0}
.sidebar-menu a{display:flex;align-items:center;padding:12px 20px;color:#555;text-decoration:none;font-weight:500;gap:10px;transition: all 0.2s}
.sidebar-menu a:hover,.sidebar-menu a.active{background:#f0f7ff;color:#2196F3;border-left:4px solid #2196F3}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:20px;border-top:1px solid #e0e0e0}
.user-info{display:flex;align-items:center;gap:10px}
.user-avatar{width:36px;height:36px;border-radius:50%;background:#2196F3;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700}
.main-content{margin-left:250px;padding:30px}
.top-bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}

.deposit-container{display:grid;grid-template-columns: 1fr 1fr;gap:25px}
@media(max-width:900px){.deposit-container{grid-template-columns:1fr}}

.card{background:#ffffff;border:1px solid #e0e0e0;border-radius:12px;padding:25px;box-shadow:0 4px 12px rgba(0,0,0,0.03)}
.card h3{font-size:18px;font-weight:700;color:#1e293b;margin-bottom:20px;display:flex;align-items:center;gap:10px}

.amounts-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:20px}
.amount-btn{
    padding:16px;border:2px solid #e2e8f0;border-radius:10px;background:#fafafa;cursor:pointer;
    text-align:center;transition:all 0.2s ease;display:flex;flex-direction:column;gap:5px;
}
.amount-btn:hover{border-color:#93c5fd;background:#f0f7ff;transform:translateY(-2px)}
.amount-btn.selected{border-color:#2196F3;background:#eff6ff;box-shadow:0 0 0 2px rgba(33,150,243,0.15)}
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
<div class="sidebar-brand"><i class="fas fa-cloud"></i> WinBox</div>
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
<h1><i class="fas fa-wallet" style="color:#2196F3"></i> Nạp tiền vào tài khoản</h1>
</div>

<div style="background:linear-gradient(135deg, #e0f2fe 0%, #dbeafe 100%);border:1px solid #93c5fd;color:#1e40af;padding:15px 20px;border-radius:10px;margin-bottom:25px;font-weight:600;display:flex;align-items:center;gap:12px">
<i class="fas fa-bolt" style="font-size:24px;color:#2563eb"></i>
<div>
Ưu đãi nạp tiền tự động: <strong>10.000 VNĐ tiền thật = 12.000 VNĐ tiền web</strong> (+20% giá trị). Hệ thống cộng tiền tự động qua web ngay khi chuyển khoản thành công!
</div>
</div>

<div class="deposit-container">
<div class="card">
<h3><i class="fas fa-hand-pointer" style="color:#2196F3"></i> Bước 1: Chọn mệnh giá nạp</h3>
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
<h3><i class="fas fa-qrcode" style="color:#2196F3"></i> Bước 2: Quét mã QR thanh toán</h3>
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

// Tạo QR động cho từng user, trong đó nội dung chuyển khoản luôn là NAP <username>.
// Nhờ vậy SePay có thể xác định chính xác tài khoản cần cộng tiền.
const qrLinks = {
    "10000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=10000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "20000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=20000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "50000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=50000&showinfo=true&holder=TRAN%20THANH%20TRUNG",
    "100000": "https://vietqr.app/img?bank=BIDV&acc=96247JBL40&template=&amount=100000&showinfo=true&holder=TRAN%20THANH%20TRUNG"
};

function buildQrUrl(amount){
    const baseUrl = qrLinks[String(amount)] || qrLinks["10000"];
    // Thêm nội dung riêng của user để SePay xác định đúng tài khoản nhận tiền.
    return baseUrl + "&des=" + encodeURIComponent("NAP " + username);
}

function selectAmount(amount){
    document.querySelectorAll('.amount-btn').forEach(btn => {
        btn.classList.remove('selected');
        if(btn.dataset.amount == amount){
            btn.classList.add('selected');
        }
    });

    const qrImg = document.getElementById('qrImage');
    qrImg.src = buildQrUrl(amount);

    document.getElementById('qrAmountText').innerText = "Số tiền: " + Number(amount).toLocaleString('vi-VN') + " VNĐ";
    document.getElementById('qrSyntaxNote').innerText = "Nội dung: NAP " + username;
}

// Cập nhật QR ngay khi trang nạp tiền mở.
document.addEventListener('DOMContentLoaded', function(){
    const selected = document.querySelector('.amount-btn.selected');
    selectAmount(selected ? selected.dataset.amount : 10000);
});
</script>
</body>
</html>"""

# ==================== TRANG QUẢN TRỊ (ADMIN PAGE) ====================
ADMIN_PAGE = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quản trị hệ thống - WinBox Admin</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
@keyframes pageFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
body{font-family:'Inter',sans-serif;background:#f5f7fa;color:#333;padding:20px;animation: pageFadeIn 0.35s ease-out;}
.container{max-width:1200px;margin:0 auto;background:#fff;padding:30px;border-radius:10px;border:1px solid #e0e0e0;box-shadow:0 4px 6px rgba(0,0,0,0.05)}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px;padding-bottom:15px;border-bottom:1px solid #eee}
h1{font-size:24px;color:#1a237e}
table{width:100%;border-collapse:collapse;margin-bottom:30px;font-size:13px}
th,td{padding:10px 12px;border:1px solid #eee;text-align:left;vertical-align:middle}
th{background:#f9f9f9;font-weight:600;color:#555}
.btn-action{padding:5px 10px;border-radius:4px;border:none;cursor:pointer;font-size:12px;font-weight:600;margin-right:2px;display:inline-flex;align-items:center;gap:4px;transition: opacity 0.2s;}
.btn-action:hover{opacity: 0.85;}
.btn-add{background:#4CAF50;color:#fff}
.btn-edit{background:#2196F3;color:#fff}
.btn-deduct{background:#FF9800;color:#fff}
.btn-role{background:#9C27B0;color:#fff}
.btn-del{background:#F44336;color:#fff}
.form-box{background:#f8f9fa;border:1px solid #e0e0e0;padding:20px;border-radius:8px;margin-bottom:30px}
.form-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:15px;margin-bottom:15px}
.form-group label{display:block;margin-bottom:6px;font-weight:500;font-size:13px}
.form-group input,.form-group select,.form-group textarea{width:100%;padding:9px;border:1px solid #ccc;border-radius:6px;font-size:13px;outline:none}
.badge-admin{background:#ffebee;color:#c62828;padding:2px 6px;border-radius:4px;font-weight:700}
.badge-user{background:#e3f2fd;color:#1565c0;padding:2px 6px;border-radius:4px;font-weight:700}
.section-title{display:flex;justify-content:space-between;align-items:center;font-size:18px;margin-bottom:15px;color:#333}
.btn-plus{background:#2196F3;color:#fff;border:none;padding:6px 14px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:6px}

.modal-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);
    display:flex;align-items:center;justify-content:center;z-index:1000;
    opacity:0;visibility:hidden;transition: opacity 0.3s ease, visibility 0.3s ease;
}
.modal-overlay.active{opacity:1;visibility:visible;}
.modal{
    background:#ffffff;border-radius:12px;padding:25px;width:500px;max-height:90vh;overflow-y:auto;
    transform: scale(0.85); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.modal-overlay.active .modal{transform: scale(1);}

.center-notif-overlay{
    position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.35);
    display:flex;align-items:center;justify-content:center;z-index:3000;
    opacity:0;visibility:hidden;transition: opacity 0.25s ease, visibility 0.25s ease;
}
.center-notif-overlay.active{opacity:1;visibility:visible;}
.center-notif-card{
    background:#ffffff;padding:25px 35px;border-radius:14px;text-align:center;
    box-shadow: 0 10px 30px rgba(0,0,0,0.25); min-width:320px; max-width:450px;
    transform: scale(0.7); transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.center-notif-overlay.active .center-notif-card{transform: scale(1);}

.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}

.config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:15px;margin-bottom:20px}
.config-card{border:1px solid #e0e0e0;border-radius:10px;padding:18px;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.04)}
.config-card h3{font-size:16px;color:#1a237e;margin-bottom:8px;display:flex;justify-content:space-between;gap:8px;align-items:center}
.config-meta{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:12px 0;font-size:13px}
.config-meta div{background:#f7f9fc;padding:8px;border-radius:6px}
.config-price{font-size:20px;font-weight:800;color:#2196F3;margin:10px 0}
.small-note{font-size:12px;color:#777;margin-top:5px;line-height:1.5}
.badge-custom{background:#fff3e0;color:#e65100;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700}
</style>
</head>
<body>
<div class="container">
<div class="header">
<h1><i class="fas fa-user-shield"></i> Trang Quản Trị Hệ Thống (Admin Panel)</h1>
<a href="/dashboard" style="text-decoration:none;color:#2196F3;font-weight:600"><i class="fas fa-arrow-left"></i> Quay lại Dashboard</a>
</div>

<!-- BẢNG TIN CHÍNH -->
<div class="section-title">
<h2><i class="fas fa-bullhorn" style="color:#2196F3"></i> Quản lý Bảng tin chính (Thông báo Admin)</h2>
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
<h2><i class="fas fa-sliders-h" style="color:#673AB7"></i> Quản lý cấu hình VM & Giá bán</h2>
<button class="btn-plus" type="button" onclick="openConfigModal()"><i class="fas fa-plus"></i> Thêm cấu hình</button>
</div>
<div class="form-box">
<div class="small-note" style="margin-bottom:15px"><strong>Thay đổi tại đây sẽ áp dụng ngay cho người dùng.</strong> Giá, vCPU, RAM, SSD và tên gói được dùng trực tiếp khi user bấm <b>Tạo VM mới</b>. Cấu hình chỉ là thông số dịch vụ; máy chủ thực tế vẫn phải có đủ tài nguyên.</div>
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
<div class="config-price">{{ cfg.price_val|vnd }}<span style="font-size:12px;font-weight:500;color:#777"> / tháng</span></div>
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
<div class="form-group"><label>Giá (VNĐ/tháng)</label><input id="configPrice" type="number" name="price_val" min="0" step="1" required></div>
</div>
<div class="small-note">Ví dụ muốn gói 4 vCPU / 8 GB / 100 GB giá 150.000 VNĐ: nhập đúng 4 / 8 / 100 / 150000.</div>
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
<div class="form-group">
<label>Tên VPS</label>
<input type="text" name="vps_name" placeholder="VPS Gift VIP 01" value="VPS Gift Custom">
</div>
<div class="form-group">
<label>Tên OS</label>
<input type="text" name="vps_os" placeholder="Windows 10 LTSB" value="Windows 10 LTSB">
</div>
<div class="form-group">
<label>Địa chỉ IP</label>
<input type="text" name="vps_ip" placeholder="103.x.x.x">
</div>
</div>
<div class="form-row">
<div class="form-group">
<label>User VPS</label>
<input type="text" name="vps_user" placeholder="Administrator" value="Administrator">
</div>
<div class="form-group">
<label>Pass VPS</label>
<input type="text" name="vps_pass" placeholder="Pass123456" value="Pass123456">
</div>
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
<label for="put_on_shop" style="margin:0;font-weight:700;color:#2e7d32;cursor:pointer">Đưa Key này lên Chợ VPS để người dùng mua bằng số dư</label>
</div>
<div class="form-group" id="shop_price_group" style="display:none;">
<label>Giá bán trên Chợ (VNĐ)</label>
<input type="number" name="shop_price" placeholder="Ví dụ: 50000" value="50000">
</div>
<div class="form-group" id="shop_quantity_group" style="display:none;">
<label>Số lượng Key đưa lên Shop</label>
<input type="number" name="quantity" min="1" value="1" placeholder="Ví dụ: 10">
</div>
<div class="form-group">
<label>Số lần 1 User được nhập Key này</label>
<input type="number" name="max_uses_per_user" min="1" value="1" placeholder="Ví dụ: 3">
</div>
</div>

<button type="submit" class="btn-action btn-add" style="padding:10px 25px;font-size:14px;margin-top:10px;"><i class="fas fa-plus"></i> Tạo Key Mới</button>
</form>
</div>

<!-- DANH SÁCH KEYS -->
<div class="section-title">
<h2><i class="fas fa-key" style="color:#2196F3"></i> Danh sách Giftcode / Keys hiện có</h2>
</div>
<table>
<thead>
<tr>
<th>Mã Code</th>
<th>Loại</th>
<th>Giá trị / Cấu hình</th>
<th>Trạng thái Shop</th>
<th>Số lần / User</th>
<th>Trạng thái sử dụng</th>
<th>Hành động</th>
</tr>
</thead>
<tbody>
{% if keys %}
{% for k_code, k in keys.items() %}
<tr>
<td><strong style="font-family:monospace;color:#2196F3">{{ k_code }}</strong></td>
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
<strong style="color:#7c3aed">{{ k.max_uses_per_user|default(1) }} lần</strong>
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
<tr><td colspan="7" style="text-align:center;color:#777">Chưa có Key nào trong hệ thống.</td></tr>
{% endif %}
</tbody>
</table>

<!-- QUẢN LÝ USER -->
<div class="section-title">
<h2><i class="fas fa-users" style="color:#2196F3"></i> Quản lý Tài khoản người dùng</h2>
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
{% if u.username != 'admin' %}
<button class="btn-action btn-role" onclick="toggleRole('{{ uid }}')"><i class="fas fa-user-shield"></i> Đổi Role</button>
<button class="btn-action btn-del" onclick="deleteUser('{{ uid }}')"><i class="fas fa-trash"></i> Xóa</button>
{% endif %}
</td>
</tr>
{% endfor %}
</tbody>
</table>
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
<h3 style="font-size:18px">Đổi mật khẩu người dùng</h3>
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

<div class="center-notif-overlay" id="centerNotif">
<div class="center-notif-card" id="centerNotifCard">
<i id="centerNotifIcon" class="fas fa-info-circle" style="font-size:40px;margin-bottom:12px;color:#2196F3"></i>
<div id="centerNotifMsg" style="font-size:16px;font-weight:600;line-height:1.4"></div>
</div>
</div>

<script>
window.addEventListener('DOMContentLoaded', () => {
    const shopCheckbox = document.getElementById('put_on_shop');
    const priceGroup = document.getElementById('shop_price_group');
    const quantityGroup = document.getElementById('shop_quantity_group');
    if(shopCheckbox){
        shopCheckbox.addEventListener('change', (e) => {
            priceGroup.style.display = e.target.checked ? 'block' : 'none';
            quantityGroup.style.display = e.target.checked ? 'block' : 'none';
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
    if(isError){
        icon.className = 'fas fa-exclamation-circle';
        icon.style.color = '#c62828';
    } else {
        icon.className = 'fas fa-check-circle';
        icon.style.color = '#2e7d32';
    }
    overlay.classList.add('active');
    setTimeout(() => {
        overlay.classList.remove('active');
        if(callback) setTimeout(callback, 300);
    }, duration);
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
    document.getElementById('configPrice').value=cfg.price_val || 0;
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
    if(!confirm('Xóa cấu hình '+key+'? Người dùng sẽ không còn thấy gói này. Các VM đã tạo trước đó không bị xóa.')) return;
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
        if(d.success){
            showCenterNotice('Đã cập nhật Bảng tin chính thành công!', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Lỗi cập nhật!', true);
        }
    });
}

function createKey(e){
    e.preventDefault();
    const form = new FormData(e.target);
    fetch('/api/admin/keys/create', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            showCenterNotice(d.message || 'Đã tạo Key thành công!', false, 1800, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Lỗi tạo Key!', true);
        }
    });
}

function deleteKey(code){
    if(!confirm('Bạn có chắc muốn xóa Key này?')) return;
    const form = new FormData();
    form.append('code', code);
    fetch('/api/admin/keys/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            showCenterNotice('Đã xóa Key thành công.', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Thất bại!', true);
        }
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
        if(d.success){
            closeBalanceModal();
            showCenterNotice('Cập nhật số dư thành công!', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Thất bại!', true);
        }
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
        if(d.success){
            closePasswordModal();
            showCenterNotice('Đổi mật khẩu thành công!', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Thất bại!', true);
        }
    });
}

function toggleRole(uid){
    if(!confirm('Bạn có chắc muốn đổi quyền của tài khoản này?')) return;
    const form = new FormData();
    form.append('user_id', uid);
    fetch('/api/admin/user/role', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            showCenterNotice('Đã đổi quyền thành công.', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Thất bại!', true);
        }
    });
}

function deleteUser(uid){
    if(!confirm('Bạn có chắc muốn xóa tài khoản này?')) return;
    const form = new FormData();
    form.append('user_id', uid);
    fetch('/api/admin/user/delete', {method:'POST', body:form})
    .then(r=>r.json())
    .then(d=>{
        if(d.success){
            showCenterNotice('Đã xóa tài khoản thành công.', false, 1500, () => location.reload());
        } else {
            showCenterNotice(d.error || 'Thất bại!', true);
        }
    });
}
</script>
</body>
</html>"""

# ==================== FLASK ROUTES ====================

@app.route("/")
def index():
    if is_logged_in():
        return redirect("/dashboard")
    return render_template_string(LANDING_PAGE, vm_configs=get_vm_configs())

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    success = request.args.get("success")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        users = load_json(USERS_FILE)
        
        found_user = None
        for uid, user in users.items():
            if user.get("username") == username:
                if user.get("password") == hash_password(password):
                    found_user = user
                    break
        
        if found_user:
            session["user_id"] = found_user["id"]
            return redirect("/dashboard")
        else:
            error = "Tên đăng nhập hoặc mật khẩu không chính xác."
            
    return render_template_string(LOGIN_PAGE, error=error, success=success)

@app.route("/register", methods=["GET", "POST"])
def register():
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
            users = load_json(USERS_FILE)
            exists = any(u.get("username") == username or u.get("email") == email for u in users.values())
            if exists:
                error = "Tên đăng nhập hoặc Email đã tồn tại trong hệ thống."
            else:
                uid = str(uuid.uuid4())
                users[uid] = {
                    "id": uid,
                    "username": username,
                    "email": email,
                    "password": hash_password(password),
                    "role": "user",
                    "balance": 0.0,
                    "created_at": datetime.now().isoformat()
                }
                save_json(USERS_FILE, users)
                return redirect("/login?success=Đăng ký thành công! Vui lòng đăng nhập.")
                
    return render_template_string(REGISTER_PAGE, error=error)

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
        
    anc = get_announcement()
    return render_template_string(
        ANNOUNCEMENT_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        announcement=anc
    )

@app.route("/my-vms")
def my_vms():
    if not is_logged_in():
        return redirect("/login")
    user = get_current_user()
    if not user:
        return redirect("/login")
        
    vms_data = load_json(VMS_FILE)
    user_vms = []
    
    running_count = 0
    creating_count = 0
    
    for vid, vm in vms_data.items():
        if vm.get("user_id") == user["id"]:
            st = vm.get("status", "stopped")
            if st == "running":
                running_count += 1
                status_text = "Đang chạy"
            elif st == "creating":
                creating_count += 1
                status_text = "Đang khởi tạo"
            else:
                status_text = "Đã dừng"
                
            os_name = vm.get("windows", {}).get("name", "Windows Server") if isinstance(vm.get("windows"), dict) else str(vm.get("windows"))
            
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
                "rdp_mode": "Tunnel" if vm.get("rdp_mode", "tailscale") == "tunnel" else "Tailscale",
                "tunnel_hostname": vm.get("tunnel_hostname", ""),
                "rdp_port": vm.get("rdp_port", 3388 + int(vm.get("instance_id", 1) or 1))
            })

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
        windows_images=get_windows_images()
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
    for k_code, k in keys_data.items():
        if k.get("on_shop") and not k.get("used"):
            batch_id = k.get("batch_id", k_code)
            batch_counts[batch_id] = batch_counts.get(batch_id, 0) + 1

    for k_code, k in keys_data.items():
        if k.get("on_shop") and not k.get("used"):
            batch_id = k.get("batch_id", k_code)
            k["_shop_stock"] = batch_counts.get(batch_id, 1)
            shop_keys[k_code] = k

    return render_template_string(
        MARKETPLACE_PAGE,
        username=user["username"],
        balance=user["balance"],
        role=user.get("role", "user"),
        items=market_items.values(),
        shop_keys=shop_keys
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
        role=user.get("role", "user")
    )

@app.route("/admin")
def admin_panel():
    if not is_admin():
        return redirect("/dashboard")
    user = get_current_user()
    users = load_json(USERS_FILE)
    keys = load_json(KEYS_FILE)
    anc = get_announcement()
    
    return render_template_string(
        ADMIN_PAGE,
        username=user["username"],
        balance=user["balance"],
        users=users,
        keys=keys,
        announcement=anc,
        vm_configs=get_vm_configs(),
        os_images=get_windows_images()
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
    rdp_mode = request.form.get("rdp_mode", "").strip().lower()
    tailscale_key = request.form.get("tailscale_key", "").strip()
    tunnel_hostname = request.form.get("tunnel_hostname", "").strip()
    if not vm_name or not config_key or not os_key or rdp_mode not in ("tailscale", "tunnel"):
        return jsonify({"success": False, "error": "Vui lòng điền đầy đủ thông tin cấu hình, OS và chọn phương thức RDP."})
    if rdp_mode == "tailscale" and not tailscale_key:
        return jsonify({"success": False, "error": "Bạn chọn Tailscale nên bắt buộc phải nhập Auth Key."})
    if rdp_mode == "tunnel" and not tunnel_hostname and not os.environ.get("WINBOX_RDP_TUNNEL_HOSTNAME", "").strip():
        return jsonify({"success": False, "error": "Bạn chọn Tunnel nên bắt buộc phải nhập Cloudflare Tunnel Hostname."})
    configs = get_vm_configs()
    if config_key not in configs:
        return jsonify({"success": False, "error": "Cấu hình VPS không hợp lệ."})
    cfg = configs[config_key]
    images = get_windows_images()
    if os_key not in images:
        return jsonify({"success": False, "error": "Hệ điều hành không hợp lệ."})
    win_img = images[os_key]
    price = cfg.get("price_val", 0.0)
    if user["balance"] < price:
        return jsonify({"success": False, "error": f"Số dư tài khoản không đủ ({user['balance']:,.0f} VNĐ). Cần {price:,.0f} VNĐ để tạo gói này."})
    users = load_json(USERS_FILE)
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_json(USERS_FILE, users)
    vid = str(uuid.uuid4())[:8]
    vms_data = load_json(VMS_FILE)
    instance_id = allocate_instance_id(vms_data)
    vms_data[vid] = {
        "id": vid,
        "user_id": user["id"],
        "name": vm_name,
        "config": cfg,
        "windows": win_img,
        "status": "creating",
        "rdp_mode": rdp_mode,
        "tailscale_key": tailscale_key if rdp_mode == "tailscale" else "",
        "tailscale_ip": None,
        "tunnel_hostname": tunnel_hostname if rdp_mode == "tunnel" else "",
        "rdp_port": 3388 + instance_id,
        "instance_id": instance_id,
        "created_at": datetime.now().isoformat()
    }
    save_json(VMS_FILE, vms_data)
    t = threading.Thread(target=run_winbox_script, args=(vid, cfg, win_img, tailscale_key, vm_name, os_key, rdp_mode, tunnel_hostname, instance_id))
    t.daemon = True
    t.start()
    return jsonify({"success": True, "message": "Đang khởi tạo máy ảo..."})

@app.route("/api/vm/<vid>/start", methods=["POST"])
def api_start_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vms_data = load_json(VMS_FILE)
    if vid not in vms_data or vms_data[vid].get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
        
    vm = vms_data[vid]
    rdp_mode = vm.get("rdp_mode", "tailscale")
    tunnel_hostname = vm.get("tunnel_hostname", "")
    instance_id = int(vm.get("instance_id") or allocate_instance_id(vms_data))
    vm["instance_id"] = instance_id
    vm["rdp_port"] = 3388 + instance_id
    save_json(VMS_FILE, vms_data)
    stop_vm_tunnel(vid)
    t = threading.Thread(target=run_winbox_script, args=(vid, vm.get("config"), vm.get("windows"), vm.get("tailscale_key", ""), vm.get("name"), "win11", rdp_mode, tunnel_hostname, instance_id))
    t.daemon = True
    t.start()
    return jsonify({"success": True})

@app.route("/api/vm/<vid>/stop", methods=["POST"])
def api_stop_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vms_data = load_json(VMS_FILE)
    if vid not in vms_data or vms_data[vid].get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
        
    with vm_lock:
        if vid in active_vms and active_vms[vid].get("process"):
            try:
                active_vms[vid]["process"].terminate()
            except Exception:
                pass
        if vid in active_vms and active_vms[vid].get("tailscale_process"):
            try:
                active_vms[vid]["tailscale_process"].terminate()
            except Exception:
                pass
        active_vms[vid]["status"] = "stopped"
    stop_vm_tunnel(vid)
        
    vms_data[vid]["status"] = "stopped"
    save_json(VMS_FILE, vms_data)
    return jsonify({"success": True})

@app.route("/api/vm/<vid>/delete", methods=["POST"])
def api_delete_vm(vid):
    if not is_logged_in():
        return jsonify({"success": False, "error": "Chưa đăng nhập"})
    user = get_current_user()
    vms_data = load_json(VMS_FILE)
    if vid not in vms_data or vms_data[vid].get("user_id") != user["id"]:
        return jsonify({"success": False, "error": "Không tìm thấy máy ảo."})
        
    stop_vm_tunnel(vid)
    with vm_lock:
        if vid in active_vms and active_vms[vid].get("process"):
            try: active_vms[vid]["process"].terminate()
            except Exception: pass
        if vid in active_vms and active_vms[vid].get("tailscale_process"):
            try: active_vms[vid]["tailscale_process"].terminate()
            except Exception: pass
        active_vms.pop(vid, None)
        vm_logs.pop(vid, None)
        
    del vms_data[vid]
    save_json(VMS_FILE, vms_data)
    
    vm_dir = DATA_DIR / f"vm_{vid}"
    if vm_dir.exists():
        shutil.rmtree(vm_dir, ignore_errors=True)
        
    return jsonify({"success": True})

@app.route("/vm/<vid>/logs")
def vm_logs_page(vid):
    if not is_logged_in():
        return "Unauthorized", 401
    user = get_current_user()
    vms_data = load_json(VMS_FILE)
    if vid not in vms_data or vms_data[vid].get("user_id") != user["id"]:
        return "Not found", 404
        
    logs = vm_logs.get(vid, ["Chưa có log hoặc VM chưa khởi chạy."])
    logs_str = "\n".join(logs)
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><title>Log VM - {vid}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
body{{font-family:'Inter',sans-serif;background:#0f172a;color:#38bdf8;padding:20px;margin:0}}
pre{{background:#1e293b;padding:20px;border-radius:8px;overflow-x:auto;font-family:monospace;font-size:13px;line-height:1.5;color:#e2e8f0}}
h2{{color:#fff;font-size:18px;margin-bottom:15px;display:flex;justify-content:space-between;align-items:center}}
.btn-refresh{{background:#2563eb;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px}}
</style>
</head>
<body>
<h2><span>🖥️ Log hệ thống VM: {vid}</span> <button class="btn-refresh" onclick="location.reload()">🔄 Tải lại</button></h2>
<pre>{logs_str}</pre>
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

    uses_by_user = k.get("uses_by_user", {})
    if not isinstance(uses_by_user, dict):
        uses_by_user = {}

    user_key = str(user["id"])
    current_user_uses = int(uses_by_user.get(user_key, 0) or 0)
    max_uses_per_user = int(k.get("max_uses_per_user", 1) or 1)
    if max_uses_per_user < 1:
        max_uses_per_user = 1

    if current_user_uses >= max_uses_per_user:
        return jsonify({
            "success": False,
            "error": f"Bạn đã nhập Key này đủ {max_uses_per_user} lần."
        })

    if k.get("used") and max_uses_per_user <= 1:
        return jsonify({"success": False, "error": "Mã Key này đã được sử dụng trước đó."})

    uses_by_user[user_key] = current_user_uses + 1
    k["uses_by_user"] = uses_by_user
    k["last_used_by"] = user["username"]
    k["last_used_at"] = datetime.now().isoformat()

    if max_uses_per_user == 1:
        k["used"] = True
        k["used_by"] = user["username"]
        k["used_at"] = datetime.now().isoformat()
    else:
        k["used"] = False
        k["used_by"] = None

    save_json(KEYS_FILE, keys)

    users = load_json(USERS_FILE)
    if k["type"] == "money":
        amt = float(k.get("amount", 0))
        if user["id"] in users:
            users[user["id"]]["balance"] += amt
            save_json(USERS_FILE, users)
        return jsonify({
            "success": True,
            "message": f"Nhập Key thành công lần {current_user_uses + 1}/{max_uses_per_user}! Cộng +{amt:,.0f} VNĐ vào tài khoản."
        })
    elif k["type"] == "vps":
        vid = str(uuid.uuid4())[:8]
        vms_data = load_json(VMS_FILE)

        cfg = {"cpu": k.get("vps_cpu", 2), "ram": k.get("vps_ram", 4), "disk": k.get("vps_disk", 50)}
        win_img = {"name": k.get("vps_os", "Windows Server"), "user": k.get("vps_user", "Administrator"), "pass": k.get("vps_pass", "Pass123456")}

        gift_instance_id = allocate_instance_id(vms_data)
        vms_data[vid] = {
            "id": vid,
            "user_id": user["id"],
            "name": k.get("vps_name", "VPS Gift"),
            "config": cfg,
            "windows": win_img,
            "status": "stopped",
            "rdp_mode": "tailscale",
            "tailscale_key": "",
            "tailscale_ip": k.get("vps_ip"),
            "tunnel_hostname": "",
            "instance_id": gift_instance_id,
            "rdp_port": 3388 + gift_instance_id,
            "created_at": datetime.now().isoformat()
        }
        save_json(VMS_FILE, vms_data)
        return jsonify({
            "success": True,
            "message": f"Nhập Key thành công lần {current_user_uses + 1}/{max_uses_per_user}! Đã thêm VPS vào danh sách Máy ảo của bạn."
        })

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
        
    users = load_json(USERS_FILE)
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_json(USERS_FILE, users)
        
    k["on_shop"] = False
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
        
    users = load_json(USERS_FILE)
    if user["id"] in users:
        users[user["id"]]["balance"] -= price
        save_json(USERS_FILE, users)
        
    item["quantity"] -= 1
    if item["quantity"] <= 0:
        item["sold_out_at"] = time.time()
    save_json(MARKETPLACE_FILE, market_data)
    
    vid = str(uuid.uuid4())[:8]
    vms_data = load_json(VMS_FILE)
    
    cfg = {"cpu": item.get("cpu", 2), "ram": item.get("ram", 4), "disk": item.get("disk", 50)}
    win_img = {"name": item.get("os_name", "Windows Server"), "user": item.get("user", "Admin"), "pass": item.get("password", "Tam255Z")}
    
    market_instance_id = allocate_instance_id(vms_data)
    vms_data[vid] = {
        "id": vid,
        "user_id": user["id"],
        "name": item.get("name", "VPS Marketplace"),
        "config": cfg,
        "windows": win_img,
        "status": "stopped",
        "rdp_mode": "tailscale",
        "tailscale_key": "",
        "tailscale_ip": item.get("ip"),
        "tunnel_hostname": "",
        "instance_id": market_instance_id,
        "rdp_port": 3388 + market_instance_id,
        "created_at": datetime.now().isoformat()
    }
    save_json(VMS_FILE, vms_data)
    return jsonify({"success": True})

# ==================== SEPAY WEBHOOK ENDPOINT ====================
# Lock riêng cho webhook để tránh 2 request Sepay đến cùng lúc cộng tiền 2 lần.
SEPAY_LOCK = threading.Lock()

def _find_username_from_sepay(data, users):
    """
    Tìm username từ nội dung giao dịch.

    Ưu tiên: NAP username / WINBOX username.
    Nếu ngân hàng/SePay thay đổi vị trí nội dung, vẫn thử tìm username
    của hệ thống xuất hiện nguyên token trong content/code/description.
    Chỉ tự động nhận khi tìm được đúng 1 user để tránh cộng nhầm tiền.
    """
    content = str(data.get("content", "") or "")
    code = str(data.get("code", "") or "")
    description = str(data.get("description", "") or "")
    search_text = " ".join([content, code, description]).strip()

    # Cách chuẩn: NAP <username> hoặc WINBOX <username>
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

    # Fallback: nếu SePay trả về content có username nhưng không còn chữ NAP/WINBOX.
    # Chỉ nhận khi đúng 1 username khớp để không cộng nhầm cho user khác.
    upper_text = search_text.upper()
    matches = []
    for uid, user in users.items():
        uname = str(user.get("username", "")).strip()
        if not uname or uname.lower() == "admin":
            continue
        # Username có ký tự đặc biệt thì escape để tìm chính xác.
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

        # Sepay webhook payload fields
        transaction_id = str(data.get("id", "") or "").strip()
        transfer_type = str(data.get("transferType", "") or "").strip().lower()
        content = str(data.get("content", "") or data.get("description", "") or "").strip()
        reference_code = str(data.get("referenceCode", "") or "").strip()

        try:
            transfer_amount = float(data.get("transferAmount", 0) or data.get("amount", 0) or 0)
        except (TypeError, ValueError):
            transfer_amount = 0

        # Chỉ xử lý giao dịch tiền vào. Các webhook khác trả 200 để Sepay không retry.
        if transfer_type and transfer_type != "in":
            return jsonify({"success": True, "message": "Ignored non-incoming transaction"})

        if transfer_amount <= 0:
            return jsonify({"success": False, "error": "Invalid amount"}), 400

        # Tỷ giá: 10k tiền thật = 12k tiền web -> Hệ số nhân 1.2
        web_amount = transfer_amount * 1.2

        with SEPAY_LOCK:
            users = load_json(USERS_FILE)
            deposits = load_json(DEPOSITS_FILE, [])
            if not isinstance(deposits, list):
                deposits = []

            # Chống cộng tiền 2 lần khi Sepay gửi lại cùng transaction.
            if transaction_id:
                for old in deposits:
                    if str(old.get("transaction_id", "")).strip() == transaction_id:
                        return jsonify({
                            "success": True,
                            "message": "Transaction already processed"
                        })

            target_uid, matched_username = _find_username_from_sepay(data, users)

            if not target_uid:
                # Không trả 404 nữa. Sepay sẽ coi webhook đã nhận thành công và không retry vô hạn.
                # Giao dịch vẫn được lưu để admin có thể kiểm tra thủ công.
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
                return jsonify({
                    "success": True,
                    "credited": False,
                    "message": "Webhook received but no matching username was found"
                })

            # Cộng tiền vào tài khoản user. Dùng float tương thích cấu trúc users.json hiện tại.
            current_balance = float(users[target_uid].get("balance", 0) or 0)
            users[target_uid]["balance"] = current_balance + web_amount
            save_json(USERS_FILE, users)

            # Lưu lịch sử nạp tiền, gồm transaction_id để chống cộng trùng.
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

            return jsonify({
                "success": True,
                "credited": True,
                "message": f"Credited {web_amount} to {users[target_uid]['username']}"
            })

    except Exception as e:
        print(f"[SEPAY WEBHOOK ERROR] {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== ADMIN API ENDPOINTS ====================

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
        price_val = float(request.form.get("price_val", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "CPU/RAM/SSD/Giá phải là số hợp lệ."})

    if cpu < 1 or ram < 1 or disk < 1 or price_val < 0:
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
        "price_val": price_val,
        "price": f"{price_val:,.0f} VNĐ/tháng"
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
        max_uses_per_user = int(request.form.get("max_uses_per_user", 1))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Giá, số lượng Key và số lần/User phải là số hợp lệ."})

    if not code:
        return jsonify({"success": False, "error": "Vui lòng nhập mã Key."})
    if quantity < 1:
        return jsonify({"success": False, "error": "Số lượng Key phải >= 1."})
    if max_uses_per_user < 1:
        return jsonify({"success": False, "error": "Số lần 1 User nhập Key phải >= 1."})

    # Chỉ tạo nhiều Key khi đưa lên Shop; Giftcode thường vẫn là 1 mã.
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
        "used": False,
        "used_by": None,
        "max_uses_per_user": max_uses_per_user,
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
        return jsonify({
            "success": True,
            "message": f"Đã tạo {quantity} Key và đưa lên Shop. Mỗi User được nhập tối đa {max_uses_per_user} lần/Key."
        })

    return jsonify({
        "success": True,
        "message": f"Đã tạo Key thành công. Mỗi User được nhập tối đa {max_uses_per_user} lần."
    })

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
    
    users = load_json(USERS_FILE)
    if user_id in users:
        if action_type == "add":
            users[user_id]["balance"] += amount
        else:
            users[user_id]["balance"] = max(0.0, users[user_id]["balance"] - amount)
        save_json(USERS_FILE, users)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "User không tồn tại."})

@app.route("/api/admin/user/password", methods=["POST"])
def api_admin_user_password():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    new_password = request.form.get("new_password", "").strip()
    
    users = load_json(USERS_FILE)
    if user_id in users and new_password:
        users[user_id]["password"] = hash_password(new_password)
        save_json(USERS_FILE, users)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Thất bại."})

@app.route("/api/admin/user/role", methods=["POST"])
def api_admin_user_role():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    users = load_json(USERS_FILE)
    if user_id in users:
        current_role = users[user_id].get("role", "user")
        users[user_id]["role"] = "admin" if current_role == "user" else "user"
        save_json(USERS_FILE, users)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Thất bại."})

@app.route("/api/admin/user/delete", methods=["POST"])
def api_admin_user_delete():
    if not is_admin():
        return jsonify({"success": False, "error": "Unauthorized"})
    user_id = request.form.get("user_id", "").strip()
    users = load_json(USERS_FILE)
    if user_id in users and users[user_id].get("username") != "admin":
        del users[user_id]
        save_json(USERS_FILE, users)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Không thể xóa tài khoản Admin chính."})


# ==================== CLOUDFLARE TUNNEL (FREE) ====================
def get_cloudflared_path():
    """Tải cloudflared binary về DATA_DIR nếu chưa có trong PATH."""
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
    """Khởi động cloudflared tunnel và in URL ra console."""
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
                    print(f"🌐  TRUY CẬP WEB QUA TUNNEL: {tunnel_url}")
                    print("="*70 + "\n")
    except Exception as e:
        print(f"[TUNNEL] Lỗi chạy cloudflared: {e}")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    init_default_admin()

    # Tự động dọn VPS hết hàng sau 2 phút, chạy nền mỗi 10 giây.
    cleanup_thread = threading.Thread(target=marketplace_cleanup_worker, daemon=True)
    cleanup_thread.start()

    # Khởi động Cloudflare Tunnel song song (miễn phí, không cần token)
    tunnel_thread = threading.Thread(target=start_cloudflare_tunnel, args=(5000,), daemon=True)
    tunnel_thread.start()

    print("==========================================================")
    print("🚀 WINBOX MANAGER KHỞI ĐỘNG THÀNH CÔNG")
    print("🌐 Truy cập Local: http://127.0.0.1:5000")
    print("⏳ Đang chờ Cloudflare Tunnel khởi động (khoảng 5-10 giây)...")
    print("==========================================================")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
