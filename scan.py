#!/usr/bin/env python3
import os
import subprocess
import time
import select
import requests
import re
import signal
import glob
import threading
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    import pytz
from telegram.ext import Application, CommandHandler
from telegram import Update

# Biểu thức chính quy để xóa mã màu ANSI
ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
def strip_ansi_codes(s):
    """Xóa mã màu ANSI khỏi chuỗi."""
    return ANSI_ESCAPE.sub('', s)

# Cấu hình Bot Telegram
TELEGRAM_BOT_TOKEN = "8193476800:AAG3Of7sCCpn9WEwdfBGfjRhxPoVn9tpTfc"
TELEGRAM_CHAT_ID = "6081972689"
OWNER_ID = "6081972689"  # ID Telegram của owner

# Danh sách chat IDs
CHAT_IDS = [TELEGRAM_CHAT_ID]

# Danh sách cổng cho quét Việt Nam
VN_PORTS = (
    list(range(1001, 1010)) +
    list(range(10001, 10010))
)
US_PORT = 3128  # Cổng cố định cho quét nước ngoài
SCAN_DURATION = 160  # Thời gian quét mỗi cổng (giây)
OUTPUT_FILE = "output.txt"  # Tệp đầu ra tạm thời
RUNNING = False  # Trạng thái quét

def clear_file(filename):
    """Xóa nội dung tệp để đảm bảo không còn dữ liệu cũ."""
    with open(filename, "w") as f:
        f.truncate(0)

def run_scan(port, is_vn=True):
    """Thực hiện quét cổng bằng zmap và prox.
    Xóa OUTPUT_FILE trước khi quét.
    Theo dõi đầu ra thời gian thực, dừng nếu phát hiện 3 dòng '0 open http threads' liên tiếp.
    Trả về True nếu dừng sớm."""
    clear_file(OUTPUT_FILE)
    print(f"[THÔNG BÁO] Bắt đầu quét cổng {port} ({'VN' if is_vn else 'US'})...")
    input_file = "vt.txt" if is_vn else "all.txt"
    if not os.path.exists(input_file):
        print(f"[LỖI] Tệp {input_file} không tồn tại!")
        return False
    if os.path.getsize(input_file) == 0:
        print(f"[LỖI] Tệp {input_file} rỗng!")
        return False
    if is_vn:
        command = f"zmap -p {port} -w {input_file} --rate=1000000000 --cooldown-time=10 | ./zmap -p {port}"
    else:
        command = f"zmap -p {port} -w {input_file} --rate=1000000000 --cooldown-time=10 --probe-module=tcp_synscan --max-sendto-failures=100000 | ./zmap -p {port}"
    # print(f"[DEBUG] Chạy lệnh: {command}")  # Xóa hoặc comment dòng này
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
    )
    start_time = time.time()
    early_stop = False
    consecutive_zero_http = 0

    while True:
        if process.poll() is not None:
            break
        ready, _, _ = select.select([process.stdout], [], [], 1.0)
        if ready:
            line = process.stdout.readline()
            if line:
                clean_line = strip_ansi_codes(line).strip()
                # print(f"[DEBUG] Đầu ra: {clean_line}")  # Xóa hoặc comment dòng này
                if "with 0 open http threads" in clean_line.lower():  # Cho VN
                    consecutive_zero_http += 1
                elif not is_vn and "no results" in clean_line.lower():  # Cho US
                    consecutive_zero_http += 1
                else:
                    consecutive_zero_http = 0
                if consecutive_zero_http >= 3:
                    print("[THÔNG BÁO] Phát hiện 3 dòng không có kết quả liên tiếp. Dừng quét...")
                    process.kill()
                    early_stop = True
                    break
        if time.time() - start_time > SCAN_DURATION:
            print(f"[THÔNG BÁO] Hết thời gian ({SCAN_DURATION}s), dừng quét cổng {port}.")
            process.kill()
            break

    try:
        process.communicate(timeout=5)
    except Exception as e:
        print(f"[LỖI] Lỗi khi giao tiếp với tiến trình: {e}")
    print(f"[THÔNG BÁO] Hoàn tất quét cổng {port}.")
    time.sleep(2)
    return early_stop

def process_results(port, is_vn=True):
    """Xử lý kết quả sau khi quét cổng."""
    if not os.path.exists(OUTPUT_FILE):
        print(f"[CẢNH BÁO] Tệp {OUTPUT_FILE} không tồn tại!")
        return []
    with open(OUTPUT_FILE, "r") as f:
        content = f.read().strip()
    proxies = content.splitlines() if content else []
    count = len(proxies)
    print(f"[THÔNG BÁO] Hoàn tất quét cổng {port}, tìm thấy {count} proxy.")
    return proxies

def send_file_to_telegram(filename, caption):
    """Gửi tệp tới tất cả chat IDs qua API sendDocument."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in CHAT_IDS:
        try:
            with open(filename, "rb") as f:
                files_data = {"document": f}
                data = {"chat_id": chat_id, "caption": caption}
                response = requests.post(url, files=files_data, data=data)
            if response.status_code == 200:
                print(f"[THÔNG BÁO] Đã gửi {filename} tới chat ID {chat_id}!")
            else:
                print(f"[LỖI] Không thể gửi tệp {filename} tới chat ID {chat_id}: {response.status_code}")
        except Exception as e:
            print(f"[LỖI] Lỗi khi gửi tệp {filename} tới chat ID {chat_id}: {e}")
    try:
        os.remove(filename)
        print(f"[THÔNG BÁO] Đã xóa {filename}.")
    except Exception as e:
        print(f"[LỖI] Không thể xóa {filename}: {e}")

def periodic_cleanup():
    """Dọn dẹp các tệp tạm thời cứ mỗi 5 phút."""
    while True:
        time.sleep(300)
        files = glob.glob("port_*.txt") + glob.glob("count_*.txt")
        for f in files:
            try:
                os.remove(f)
                print(f"[THÔNG BÁO] Dọn dẹp: Đã xóa {f}.")
            except Exception as e:
                print(f"[LỖI] Không thể xóa {f}: {e}")
        trash_dirs = glob.glob("trash_*")
        for d in trash_dirs:
            try:
                os.rmdir(d)
                print(f"[THÔNG BÁO] Dọn dẹp: Đã xóa thư mục {d}.")
            except Exception as e:
                print(f"[LỖI] Không thể xóa thư mục {d}: {e}")

def signal_handler(signum, frame):
    """Xử lý tín hiệu dừng chương trình."""
    global RUNNING
    print("\n[THÔNG BÁO] Dừng quét...")
    RUNNING = False
    subprocess.run(['pkill', '-f', 'zmap'], check=False)
    subprocess.run(['pkill', '-f', 'prox'], check=False)
    os._exit(0)

async def start_scan(update: Update, context):
    """Xử lý lệnh /on."""
    if str(update.message.from_user.id) != OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    global RUNNING
    if RUNNING:
        await update.message.reply_text("[THÔNG BÁO] Quét đang chạy!")
        return
    RUNNING = True
    await update.message.reply_text("[THÔNG BÁO] Bắt đầu quét liên tục...")
    threading.Thread(target=scan_loop, daemon=True).start()

async def stop_scan(update: Update, context):
    """Xử lý lệnh /off."""
    if str(update.message.from_user.id) != OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    global RUNNING
    if not RUNNING:
        await update.message.reply_text("[THÔNG BÁO] Quét không chạy!")
        return
    RUNNING = False
    subprocess.run(['pkill', '-f', 'zmap'], check=False)
    subprocess.run(['pkill', '-f', 'prox'], check=False)
    await update.message.reply_text("[THÔNG BÁO] Đã dừng quét.")

async def add_group(update: Update, context):
    """Xử lý lệnh /group."""
    if str(update.message.from_user.id) != OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Vui lòng cung cấp chat ID. Ví dụ: /group -1001234567890")
        return
    chat_id = context.args[0]
    if chat_id in CHAT_IDS:
        await update.message.reply_text(f"Chat ID {chat_id} đã tồn tại trong danh sách.")
    else:
        CHAT_IDS.append(chat_id)
        await update.message.reply_text(f"Đã thêm chat ID {chat_id} vào danh sách.")

async def remove_group(update: Update, context):
    """Xử lý lệnh /rm."""
    if str(update.message.from_user.id) != OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Vui lòng cung cấp chỉ số của chat ID để xóa. Ví dụ: /rm 1")
        return
    try:
        index = int(context.args[0]) - 1
        if 0 <= index < len(CHAT_IDS):
            removed = CHAT_IDS.pop(index)
            await update.message.reply_text(f"Đã xóa chat ID {removed} khỏi danh sách.")
        else:
            await update.message.reply_text("Chỉ số không hợp lệ.")
    except ValueError:
        await update.message.reply_text("Chỉ số phải là một số nguyên.")

async def show_groups(update: Update, context):
    """Xử lý lệnh /showgroup."""
    if str(update.message.from_user.id) != OWNER_ID:
        await update.message.reply_text("Bạn không có quyền sử dụng lệnh này.")
        return
    if not CHAT_IDS:
        await update.message.reply_text("Danh sách chat IDs trống.")
    else:
        message = "Danh sách chat IDs:\n"
        for i, chat_id in enumerate(CHAT_IDS, 1):
            message += f"{i}. {chat_id}\n"
        await update.message.reply_text(message)

def scan_loop():
    """Vòng lặp quét liên tục."""
    global RUNNING
    scan_round = 1
    while RUNNING:
        print(f"\n[THÔNG BÁO] Vòng quét {scan_round}")
        vn_proxies = []
        for i, port in enumerate(VN_PORTS, 1):
            if not RUNNING:
                break
            print(f"[THÔNG BÁO] Quét cổng VN {port} ({i}/{len(VN_PORTS)})")
            early_stop = run_scan(port, is_vn=True)
            proxies = process_results(port, is_vn=True)
            vn_proxies.extend(proxies)
            if early_stop:
                print(f"[THÔNG BÁO] Dừng sớm cổng {port}.")
            time.sleep(5)
        if RUNNING and vn_proxies:
            count = len(vn_proxies)
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            vn_filename = f"count_{count}_VN_{now}.txt"
            with open(vn_filename, "w") as f:
                f.write("\n".join(vn_proxies))
            caption = f"❄️scan proxy port: {', '.join(map(str, VN_PORTS))}\n❄️code: nminh"
            send_file_to_telegram(vn_filename, caption)
            vn_proxies = []
            time.sleep(10)
        
        if RUNNING:
            print(f"[THÔNG BÁO] Quét cổng US {US_PORT}")
            early_stop = run_scan(US_PORT, is_vn=False)
            us_proxies = process_results(US_PORT, is_vn=False)
            if us_proxies:
                count = len(us_proxies)
                now = datetime.now().strftime("%Y%m%d_%H%M%S")
                us_filename = f"count_{count}_US_{now}.txt"
                with open(us_filename, "w") as f:
                    f.write("\n".join(us_proxies))
                caption = f"❄️scan proxy port: {US_PORT}\n❄️code: nminh"
                send_file_to_telegram(us_filename, caption)
            else:
                print("[THÔNG BÁO] Không tìm thấy proxy cho US.")
            if early_stop:
                print(f"[THÔNG BÁO] Dừng sớm cổng {US_PORT}.")
        
        if RUNNING:
            print(f"[THÔNG BÁO] Hoàn tất vòng {scan_round}. Chờ 5 phút...")
            scan_round += 1
            time.sleep(300)

def main():
    """Khởi động bot và xử lý lệnh."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTSTP, signal_handler)
    
    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("on", start_scan))
    app.add_handler(CommandHandler("off", stop_scan))
    app.add_handler(CommandHandler("group", add_group))
    app.add_handler(CommandHandler("rm", remove_group))
    app.add_handler(CommandHandler("showgroup", show_groups))
    
    print("[THÔNG BÁO] Bot đã sẵn sàng. Dùng /on để bắt đầu, /off để dừng.")
    app.run_polling()

if __name__ == "__main__":
    main()
