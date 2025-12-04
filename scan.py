#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import os
import shutil
import json
import signal
from datetime import datetime
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


BOT_TOKEN = "8193476800:AAG3Of7sCCpn9WEwdfBGfjRhxPoVn9tpTfc"
CMD = "zmap -p 3128 -w ngoai.txt | ./zmap -p 3128"

OUTPUT_FILE = "output.txt"
FINAL_FILE = "proxy.txt"
GROUP_FILE = "groups.json"

ADMINS = ["6081972689", "6926655784"]

is_running = False
current_process = None  
scan_status_info = None  
SCAN_REPEAT = 2  

def is_admin(user_id):
    return str(user_id) in ADMINS



def load_groups():
    if not os.path.exists(GROUP_FILE):
        with open(GROUP_FILE, "w") as f:
            json.dump([], f)
    with open(GROUP_FILE, "r") as f:
        return json.load(f)


def save_groups(groups):
    with open(GROUP_FILE, "w") as f:
        json.dump(groups, f)



def is_scan_complete(line):
    """Check if scan completed"""
    line_lower = line.lower()
    return "zmap: completed" in line_lower or "zmap completed" in line_lower


def parse_scan_status(line):
    # Example: Imported [101049] IPs Checked [100968] IPs (Success: 20, StatusCodeErr: 2, ProxyErr: 100946, Timeout: 5) with 80 open http threads
    #          1:03 20% (4m14s left); send: 6553373 101 Kp/s (104 Kp/s avg); recv: 101549 1.49 Kp/s (1.60 Kp/s avg); drops: 0 p/s (0 p/s avg); hitrate: 1.55%
    import re
    percent = None
    time_left = None
    checked = None
    success = None

    # Find percent and time left
    m = re.search(r'(\d+)% \(([\d\w:]+) left\)', line)
    if m:
        percent = m.group(1)
        time_left = m.group(2)

    # Find checked IPs and success
    m2 = re.search(r'Checked \[(\d+)\] IPs.*Success: (\d+)', line)
    if m2:
        checked = m2.group(1)
        success = m2.group(2)

    return percent, time_left, checked, success

def run_scan_blocking():
    global current_process, scan_status_info
    
    current_process = subprocess.Popen(
        CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True,
        text=True,
        bufsize=1,
        preexec_fn=os.setsid
    )

    scan_completed = False

    scan_status_info = None
    try:
        for line in iter(current_process.stdout.readline, ''):
            if not line:
                break
            
            line = line.strip()
            if line:
                print(line)
                # Update scan status info if line matches
                if "Checked" in line and "Success:" in line:
                    scan_status_info = line
                elif "%" in line and "left" in line:
                    scan_status_info = line

                if is_scan_complete(line):
                    print("[TRIGGER] Scan completed!")
                    scan_completed = True
                    # Kill process group
                    try:
                        os.killpg(os.getpgid(current_process.pid), signal.SIGTERM)
                    except:
                        pass
                    break
    
    except Exception as e:
        print(f"[ERROR] Scan error: {e}")
    
    finally:
        try:
            current_process.terminate()
            current_process.wait(timeout=3)
        except:
            try:
                current_process.kill()
                current_process.wait()
            except:
                pass
        current_process = None
    
    return scan_completed


def rename_output():
    if os.path.exists(OUTPUT_FILE):
        if os.path.exists(FINAL_FILE):
            backup = f"{FINAL_FILE}.backup"
            shutil.move(FINAL_FILE, backup)
        shutil.move(OUTPUT_FILE, FINAL_FILE)
        print("[INFO] Renamed output.txt -> proxy.txt")
        return True
    else:
        print("[WARN] output.txt not found!")
        return False



def merge_outputs(files, merged_file):
    lines = set()
    for fname in files:
        if os.path.exists(fname):
            with open(fname, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.add(line)
    with open(merged_file, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')
    print(f"[INFO] Merged {files} into {merged_file}")

async def send_file_to_all(context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] send_file_to_all() called")
    
    if not os.path.exists(FINAL_FILE):
        print(f"[WARN] {FINAL_FILE} not found, skip sending")
        return

    print(f"[DEBUG] {FINAL_FILE} exists")
    
    groups = load_groups()
    print(f"[DEBUG] Loaded {len(groups)} groups: {groups}")
    
    if len(groups) == 0:
        print("[WARN] No groups registered. Use /group <chat_id> to add groups")
        return

    # Count proxies
    try:
        with open(FINAL_FILE, 'r', encoding='utf-8') as f:
            total = sum(1 for _ in f)
    except Exception as e:
        print(f"[ERROR] Cannot read file: {e}")
        total = 0

    print(f"[DEBUG] Found {total} proxies")

    stats = {
        "total": total,
        "port": 3128,
        "type": "HTTP",
        "anonymity": "MIX",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    caption = (
        f"Total Proxy: {stats['total']}\n"
        f"Proxy Type: {stats['type']}\n"
        f"Anonymity: {stats['anonymity']}\n"
        f"Time: {stats['time']}\n"
        f"Port: {stats['port']}\n"
        f"Bot Proxy Scanner\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("INFO", url="https://telegra.ph/Admin-12-04-13")]
    ])

    success_count = 0
    for chat_id in groups:
        print(f"[DEBUG] Attempting to send to {chat_id}")
        try:
            with open(FINAL_FILE, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=caption,
                    reply_markup=keyboard,
                    filename="proxy.txt"
                )
            success_count += 1
            print(f"[OK] Sent to {chat_id}")
        except Exception as e:
            print(f"[ERROR] Failed to send to {chat_id}: {type(e).__name__}: {e}")
    
    print(f"[INFO] Sent file to {success_count}/{len(groups)} groups")



async def scan_loop(app):
    global is_running
    while True:
        if not is_running:
            await asyncio.sleep(2)
            continue

        print(f"\n[SYSTEM] Starting scan cycle ({SCAN_REPEAT} scans)...")

        loop = asyncio.get_event_loop()
        output_files = []
        for i in range(1, SCAN_REPEAT + 1):
            scan_completed = await loop.run_in_executor(None, run_scan_blocking)
            fname = f"output{i}.txt"
            if scan_completed:
                if os.path.exists(OUTPUT_FILE):
                    shutil.move(OUTPUT_FILE, fname)
                    output_files.append(fname)
                print(f"[SYSTEM] Scan {i} done, waiting 2s before next scan...")
                await asyncio.sleep(2)
            else:
                print(f"[WARN] Scan {i} ended without completion signal")
                await asyncio.sleep(5)
                break  # N?u scan l?i th? d?ng chu k?

        if output_files:
            print("[SYSTEM] Merging results and sending file...")
            await asyncio.sleep(1)
            merge_outputs(output_files, FINAL_FILE)
            await send_file_to_all(app)
            # Xóa file t?m
            for fname in output_files:
                if os.path.exists(fname):
                    os.remove(fname)

        print("[SYSTEM] Waiting 3s before next scan cycle...\n")
        await asyncio.sleep(3)


async def post_init(app):
    asyncio.create_task(scan_loop(app))


async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    global is_running
    if is_running:
        return await update.message.reply_text("Scan is already RUNNING. Please /off or /stop before starting again.")
    is_running = True
    await update.message.reply_text("Started continuous scanning!")


async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    global is_running, current_process
    is_running = False
    
    if current_process:
        try:
            os.killpg(os.getpgid(current_process.pid), signal.SIGTERM)
        except:
            pass
    
    await update.message.reply_text("Scan stopped.")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    global is_running, current_process
    is_running = False
    
    if current_process:
        try:
            os.killpg(os.getpgid(current_process.pid), signal.SIGTERM)
        except:
            pass
    
    await update.message.reply_text("Stopped scanning! Sending last file...")
    
    if os.path.exists(OUTPUT_FILE):
        rename_output()
    
    await send_file_to_all(context)


async def cmd_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    if len(context.args) == 0:
        return await update.message.reply_text("Usage: /group <chat_id>")

    groups = load_groups()
    chat = context.args[0]

    if chat not in groups:
        groups.append(chat)
        save_groups(groups)
        await update.message.reply_text(f"Added chat: {chat}")
    else:
        await update.message.reply_text(f"Chat {chat} already exists")


async def cmd_rm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    if len(context.args) == 0:
        return await update.message.reply_text("Usage: /rm <index>")

    groups = load_groups()
    
    try:
        idx = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("Index must be a number!")

    if 0 <= idx < len(groups):
        removed = groups.pop(idx)
        save_groups(groups)
        await update.message.reply_text(f"Removed: {removed}")
    else:
        await update.message.reply_text(f"Index out of range! (0-{len(groups)-1})")


async def cmd_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")

    groups = load_groups()
    
    if len(groups) == 0:
        return await update.message.reply_text("No groups registered yet.")
    
    text = "Registered Groups\n\n" + "\n".join([f"{i}. {g}" for i, g in enumerate(groups)])
    await update.message.reply_text(text)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("? You cannot use this command.")
    
    status = "RUNNING" if is_running else "STOPPED"
    groups_count = len(load_groups())
    file_exists = "Yes" if os.path.exists(FINAL_FILE) else "No"

    text = (
        f"Bot Status\n"
        f"Status: {status}\n"
        f"Groups: {groups_count}\n"
        f"Proxy file exists: {file_exists}\n\n"
    )
    global scan_status_info
    if scan_status_info:
        percent, time_left, checked, success = parse_scan_status(scan_status_info)
        text += "\nScan Progress:\n"
        text += f"{scan_status_info}\n"
        if percent:
            text += f"Percent: {percent}%\n"
        if time_left:
            text += f"Time left: {time_left}\n"
        if checked:
            text += f"Checked IPs: {checked}\n"
        if success:
            text += f"Success: {success}\n"

    await update.message.reply_text(text)


async def cmd_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("You cannot use this command.")
    
    await update.message.reply_text("Attempting to send file...")
    await send_file_to_all(context)
    await update.message.reply_text("Send command executed. Check console for details.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Proxy Scanner Bot Commands\n\n"
        "Scan Control:\n"
        "/off - Stop scanning\n"
        "/on - Start continuous scanning\n"
        "/stop - Stop scan and send current file\n"
        "/status - Show bot status\n"
        "/send - Manually send proxy file\n\n"
        "Group Management\n"
        "/group <chat_id> - Add chat to send files\n"
        "/rm <index> - Remove chat by index\n"
        "/showgroup - List all registered chats\n\n"
        "/help - Show this help"
        "/start - Alias for /help"
    )
    await update.message.reply_text(help_text)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("on", cmd_on))
    app.add_handler(CommandHandler("off", cmd_off))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("send", cmd_send))
    app.add_handler(CommandHandler("group", cmd_group))
    app.add_handler(CommandHandler("rm", cmd_rm))
    app.add_handler(CommandHandler("showgroup", cmd_show))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))

    print("[BOT] Starting...")
    print(f"[BOT] Admin: {ADMINS}")
    print(f"[BOT] Command: {CMD}")
    app.run_polling()


if __name__ == "__main__":
    main()
