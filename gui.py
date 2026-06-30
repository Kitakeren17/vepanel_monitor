import os
import time
import threading
from datetime import datetime
import requests
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import sys
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import re

import json
import requests
import threading

def log_to_sheet(webapp_url, action, payload):
    if not webapp_url or not webapp_url.startswith("http"): return
    def _send():
        try:
            data = {"action": action}
            data.update(payload)
            requests.post(webapp_url, data=data, timeout=10)
        except Exception as e:
            print("Error logging to sheet:", e)
    threading.Thread(target=_send, daemon=True).start()

def save_msg_map(msg_id, log_ids):
    try:
        data = {}
        if os.path.exists("msg_map.json"):
            with open("msg_map.json", "r") as f:
                data = json.load(f)
        data[str(msg_id)] = log_ids
        with open("msg_map.json", "w") as f:
            json.dump(data, f)
    except: pass

def get_msg_map(msg_id):
    try:
        if os.path.exists("msg_map.json"):
            with open("msg_map.json", "r") as f:
                data = json.load(f)
            return data.get(str(msg_id), [])
    except: pass
    return []

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

active_bot = None

def check_user_deposit_on_demand(target_username, url, user, pwd, is_headless):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=is_headless)
            context = browser.new_context()
            page = context.new_page()

            page.goto(url)
            page.fill("input[name='username'], input[type='text'], input[placeholder*='Username']", user)
            page.fill("input[name='password'], input[type='password']", pwd)
            page.click("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign In')")
            
            page.wait_for_load_state("networkidle")
            
            try:
                page.get_by_text("Report", exact=False).first.click(timeout=15000)
                time.sleep(1)
                page.get_by_text("Deposit Report", exact=False).first.click(timeout=15000)
            except Exception:
                return "❌ Gagal menavigasi ke menu 'Deposit Report'. Pastikan menu tersebut ada atau koneksi tidak sedang lambat."
                
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            
            try:
                # 1. Fill Username first
                try:
                    # 1. Cari kotak dengan tulisan Username
                    try:
                        page.get_by_placeholder("Username", exact=False).first.fill(target_username)
                    except:
                        # 2. Cari kotak pencarian lain
                        try:
                            page.locator("label").filter(has_text="Username").locator("xpath=..").locator("input").fill(target_username)
                        except:
                            box = page.get_by_placeholder("Search", exact=False).first
                            box.fill(target_username)
                except:
                    try:
                        box = page.locator("input[type='text']").first
                        box.fill(target_username)
                    except:
                        pass
                
                # 2. Click THIS WEEK button
                try:
                    page.get_by_role("button", name=re.compile(r"this week", re.IGNORECASE)).click(timeout=3000)
                except:
                    try:
                        page.get_by_text(re.compile(r"this week", re.IGNORECASE)).first.click(timeout=3000)
                    except:
                        pass
                
                time.sleep(1)
                
                # 3. Click the red FILTER button
                try:
                    page.get_by_role("button", name=re.compile(r"filter", re.IGNORECASE)).click(timeout=3000)
                except:
                    try:
                        page.get_by_text("FILTER", exact=True).first.click(timeout=3000)
                    except:
                        pass
                
                # Wait for results to load
                page.wait_for_load_state("networkidle")
                time.sleep(4)
                
                # 4. Change pagination to 1000 rows
                try:
                    page.get_by_text("10", exact=True).last.click(timeout=2000)
                    time.sleep(1)
                    page.get_by_text("1000", exact=True).last.click(timeout=2000)
                    time.sleep(3)
                except:
                    pass
            except Exception as e:
                pass
                
            rows = page.locator("tbody tr")
            count = rows.count()
            
            if count == 0:
                browser.close()
                return f"⚠️ Tidak ada data pada tabel Deposit Report."
                
            found_rows = []
            for i in range(count):
                row_text = rows.nth(i).inner_text().strip()
                if not row_text:
                    continue
                if target_username.lower() in row_text.lower():
                    found_rows.append(row_text.replace('\t', ' | '))
                    
            browser.close()
            
            if not found_rows:
                return f"⚠️ Tidak ditemukan riwayat deposit untuk user '<b>{target_username}</b>' di data terbaru."
                
            import html
            result_msg = f"✅ <b>Riwayat Deposit (Maks. 3 Terakhir) untuk {target_username}:</b>\n\n"
            
            for i, row in enumerate(found_rows[:3]):
                safe_text = html.escape(row)
                result_msg += f"{i+1}. <code>{safe_text}</code>\n\n"
            
            return result_msg.strip()
    except Exception as e:
        return f"❌ Terjadi kesalahan sistem: {e}"

def start_telegram_listener(token, url, vep_user, vep_pwd, is_headless, webapp_url):
    global active_bot
    if active_bot:
        active_bot.stop_polling()
    
    if not token:
        return
        
    bot = telebot.TeleBot(token)
    active_bot = bot
    
    
    @bot.callback_query_handler(func=lambda call: call.data == "mark_checked")
    def handle_check(call):
        user_name = call.from_user.first_name
        if call.from_user.last_name:
            user_name += f" {call.from_user.last_name}"
            
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton(f"✅ Divalidasi oleh: {user_name}", callback_data="already_checked")
        markup.add(btn)
        
        try:
            bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id, text="Berhasil divalidasi!")
            
            # Update sheets
            log_ids = get_msg_map(call.message.message_id)
            for lid in log_ids:
                log_to_sheet(webapp_url, "update", {"id": lid, "validator": user_name})
        except Exception as e:
            print(f"Error editing message: {e}")

            
    @bot.callback_query_handler(func=lambda call: call.data == "already_checked")
    def handle_already_checked(call):
        bot.answer_callback_query(call.id, text="Data ini sudah divalidasi!")
    @bot.message_handler(commands=['cekdepo'])
    def handle_cekdepo(message):
        text = message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Format salah.\nGunakan: <code>/cekdepo username_player</code>", parse_mode="HTML")
            return
            
        target_username = parts[1]
        bot.reply_to(message, f"🔍 Sedang memproses pengecekan deposit untuk user: <b>{target_username}</b>...\n<i>Mohon tunggu sekitar 15 detik...</i>", parse_mode="HTML")
        
        try:
            result = check_user_deposit_on_demand(target_username, url, vep_user, vep_pwd, is_headless)
            bot.reply_to(message, result, parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ Terjadi kesalahan: {e}")
            
    def poll():
        try:
            bot.polling(none_stop=True)
        except:
            pass
            
    threading.Thread(target=poll, daemon=True).start()

if getattr(sys, 'frozen', False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.environ['LOCALAPPDATA'], 'ms-playwright')

load_dotenv()

def send_telegram_message(token, chat_id, message, is_report=False, topic_id=None, log_func=None):
    bot = telebot.TeleBot(token)
    try:
        kwargs = {}
        if topic_id and str(topic_id).strip():
            kwargs['message_thread_id'] = int(str(topic_id).strip())
            
        if is_report:
            markup = InlineKeyboardMarkup()
            btn = InlineKeyboardButton("⏳ Belum Dicek (Klik untuk Validasi)", callback_data="mark_checked")
            markup.add(btn)
            bot.send_message(chat_id, message, parse_mode="HTML", reply_markup=markup, **kwargs)
        else:
            bot.send_message(chat_id, message, parse_mode="HTML", **kwargs)
    except Exception as e:
        err = f"❌ GAGAL MENGIRIM KE TELEGRAM: {e}"
        print(err)
        if log_func:
            log_func(err)

def run_scraping_cycle(url, user, pwd, token, chat_id, topic_rp, topic_ek, log_func, is_headless, webapp_url):
    def log(msg):
        log_func(msg + "\n")
        
    log("Memulai sesi Playwright...")
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=is_headless, channel="chrome")
            except Exception:
                try:
                    browser = p.chromium.launch(headless=is_headless, channel="msedge")
                except Exception as e:
                    log(f"Gagal membuka Chrome/Edge. Pastikan Google Chrome terinstal. Error: {e}")
                    raise
            context = browser.new_context()
            page = context.new_page()

            log(f"Membuka {url}...")
            page.goto(url)

            log("Melakukan login...")
            page.fill("input[name='username'], input[type='text'], input[placeholder*='Username']", user)
            page.fill("input[name='password'], input[type='password']", pwd)
            page.click("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign In')")
            
            page.wait_for_load_state("networkidle")
            log("Login berhasil! Menavigasi ke Activity Log...")

            # --- NAVIGASI ---
            try:
                page.get_by_text("Activity Log", exact=False).first.click()
                time.sleep(1)
                page.get_by_text("Operator Activity Log", exact=False).first.click()
            except Exception:
                log("Gagal menavigasi via teks, Anda bisa klik manual jika perlu. Tunggu 3 detik...")
                time.sleep(3)
            
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            log("Memuat seluruh tabel aktivitas...")
            try:
                try:
                    page.get_by_text(re.compile(r"filter", re.IGNORECASE)).first.click(timeout=3000)
                    log("> Berhasil menekan tombol FILTER (menampilkan semua data)")
                except Exception as ex:
                    log(f"> Gagal menekan tombol FILTER otomatis.")
                
                time.sleep(3) 
                
                # Ubah pagination menjadi 1000
                try:
                    log("> Mengubah tampilan tabel menjadi 1000 baris...")
                    page.get_by_text("10", exact=True).last.click(timeout=3000)
                    time.sleep(1)
                    page.get_by_text("1000", exact=True).last.click(timeout=3000)
                    time.sleep(4)
                    log("> Berhasil mengubah ke 1000 baris!")
                except Exception as ep:
                    log("> Info: Gagal ubah ke 1000 baris otomatis.")
                
            except Exception as e:
                log(f"Info: Jeda 5 detik...")
                time.sleep(5)
            
            log("Membaca tabel log...")
            rows = page.locator("tbody tr")
            count = rows.count()
            
            log(f"Ditemukan {count} baris data pada tabel.")
            
            reports_rp = []
            reports_ek = []
            today_str = datetime.now().strftime("%d %b %Y") 
            if today_str.startswith("0"):
                today_str = today_str[1:]
                
            log(f"Menyaring {count} baris data hari ini ('{today_str}') untuk mencari:")
            log("- Reset Password\n- Update player data: Contact")
            
            if count > 0:
                cells_0 = rows.nth(0).locator("td")
                if cells_0.count() >= 3:
                    dbg_time = cells_0.nth(0).inner_text().strip()
                    dbg_act = cells_0.nth(2).inner_text().strip()
                    log(f"-> DEBUG BARIS 1: Waktu='{dbg_time}', Activity='{dbg_act}'")
            
            # Memuat riwayat data yang sudah dikirim
            import json
            sent_logs_file = "sent_logs.json"
            sent_logs = []
            if os.path.exists(sent_logs_file):
                try:
                    with open(sent_logs_file, 'r') as f:
                        sent_logs = json.load(f)
                except:
                    pass

            for i in range(count):
                row = rows.nth(i)
                cells = row.locator("td")
                
                if cells.count() >= 6:
                    time_text = cells.nth(0).inner_text().strip()
                    operator = cells.nth(1).inner_text().strip()
                    activity = cells.nth(2).inner_text().strip()
                    player = cells.nth(3).inner_text().strip()
                    ip_addr = cells.nth(5).inner_text().strip()
                    
                    if today_str in time_text:
                        log_id = f"{time_text}_{operator}_{player}_{activity}"
                        if log_id not in sent_logs:
                            report_item = (
                                f"⏰ <b>Waktu:</b> {time_text}\n"
                                f"👤 <b>Operator:</b> {operator}\n"
                                f"🎯 <b>Player:</b> {player}\n"
                                f"🌐 <b>IP:</b> {ip_addr}"
                            )
                            # Cek kategori aktivitas
                            activity_lower = activity.lower()
                            if "reset password" in activity_lower:
                                reports_rp.append((report_item, log_id))
                                sent_logs.append(log_id)
                                log_to_sheet(webapp_url, "create", {"id": log_id, "waktu": time_text, "tipe": "Reset Password", "operator": operator, "player": player})
                            elif ("update player data" in activity_lower and "contact" in activity_lower) or "edit kontak" in activity_lower:
                                reports_ek.append((report_item, log_id))
                                sent_logs.append(log_id)
                                log_to_sheet(webapp_url, "create", {"id": log_id, "waktu": time_text, "tipe": "Edit Kontak", "operator": operator, "player": player})
            
            log(f"\nSelesai menyaring! Hasil yang didapat:")
            log(f"• Reset Password: {len(reports_rp)} data baru")
            log(f"• Edit Kontak: {len(reports_ek)} data baru\n")
            
            if reports_rp:
                log(f"Ditemukan {len(reports_rp)} data Reset Password BARU.")
                header = f"<b>🚨 LAPORAN RESET PASSWORD ({today_str})</b>\n\n"
                full_message = header + "\n\n---\n\n".join([r[0] for r in reports_rp])
                msg_id = send_telegram_message(token, chat_id, full_message, is_report=True, topic_id=topic_rp, log_func=log)
                if msg_id: save_msg_map(msg_id, [r[1] for r in reports_rp])
                
            if reports_ek:
                log(f"Ditemukan {len(reports_ek)} data Edit Kontak BARU.")
                header = f"<b>📝 LAPORAN EDIT KONTAK ({today_str})</b>\n\n"
                full_message = header + "\n\n---\n\n".join([r[0] for r in reports_ek])
                msg_id = send_telegram_message(token, chat_id, full_message, is_report=True, topic_id=topic_ek, log_func=log)
                if msg_id: save_msg_map(msg_id, [r[1] for r in reports_ek])

            if reports_rp or reports_ek:
                log("Semua laporan aktivitas berhasil terkirim ke Telegram (dengan tombol validasi)!")
                # Simpan riwayat data yang sudah dikirim (maksimal 8000 data terakhir agar tidak berat)
                try:
                    with open(sent_logs_file, 'w') as f:
                        json.dump(sent_logs[-8000:], f)
                except:
                    pass
            else:
                log("Tidak ada aktivitas BARU. Mengirim info rutin...")
                no_data_msg = f"ℹ️ <b>LAPORAN RUTIN ({datetime.now().strftime('%H:%M')})</b>\n\nPengecekan selesai. Saat ini <b>TIDAK ADA</b> aktivitas Reset Password / Edit Kontak baru."
                send_telegram_message(token, chat_id, no_data_msg, topic_id=topic_rp, log_func=log)
                
            log("Sesi selesai, menutup browser...\n")
            time.sleep(2)
            browser.close()
    except Exception as e:
        log(f"Terjadi kesalahan: {e}\n")

class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"🤖 vePanel Monitor Pro {CURRENT_VERSION}")
        self.root.geometry("680x880")
        self.root.configure(bg="#f4f5f7")
        
        self.is_monitoring = False
        
        title_font = ("Segoe UI", 16, "bold")
        label_font = ("Segoe UI", 10, "bold")
        entry_font = ("Segoe UI", 10)
        btn_font = ("Segoe UI", 10, "bold")
        
        header = tk.Label(root, text="vePanel Auto Monitor", font=title_font, bg="#f4f5f7", fg="#2c3e50")
        header.pack(pady=(15, 2))
        
        desc = tk.Label(root, text="Sistem Pemantauan Otomatis & Notifikasi Telegram", font=("Segoe UI", 9), bg="#f4f5f7", fg="#7f8c8d")
        desc.pack(pady=(0, 15))

        # Frame input
        frame = tk.Frame(root, padx=20, pady=20, bg="#ffffff", highlightbackground="#dcdde1", highlightthickness=1)
        frame.pack(fill="x", padx=20)

        def create_input(row, text, var, is_password=False):
            tk.Label(frame, text=text, font=label_font, bg="#ffffff", fg="#34495e").grid(row=row, column=0, sticky="w", pady=8)
            entry = tk.Entry(frame, textvariable=var, font=entry_font, width=50, relief="solid", bd=1)
            if is_password:
                entry.config(show="•")
            entry.grid(row=row, column=1, pady=8, padx=10)
            return entry

        self.url_var = tk.StringVar(value=os.getenv("VEPANEL_URL", "https://ag77b.vepanel.club/"))
        create_input(0, "🌐 URL vePanel:", self.url_var)

        self.user_var = tk.StringVar(value=os.getenv("VEPANEL_USERNAME", ""))
        create_input(1, "👤 Username:", self.user_var)

        self.pwd_var = tk.StringVar(value=os.getenv("VEPANEL_PASSWORD", ""))
        create_input(2, "🔑 Password:", self.pwd_var, is_password=True)

        self.webapp_var = tk.StringVar(value=os.getenv("WEBAPP_URL", ""))
        create_input(3, "📌 URL Google Sheets Web App (Opsional):", self.webapp_var)

        self.token_var = tk.StringVar(value=os.getenv("TELEGRAM_BOT_TOKEN", ""))
        create_input(4, "🤖 Bot Token:", self.token_var)

        self.chat_var = tk.StringVar(value=os.getenv("TELEGRAM_CHAT_ID", ""))
        create_input(5, "💬 Chat ID:", self.chat_var)
        
        self.topic_rp_var = tk.StringVar(value=os.getenv("TOPIC_RP", ""))
        create_input(6, "📌 Topic Reset Password (Kosong=Main):", self.topic_rp_var)

        self.topic_ek_var = tk.StringVar(value=os.getenv("TOPIC_EK", "2"))
        create_input(7, "📌 Topic Edit Kontak:", self.topic_ek_var)

        # Options frame
        opt_frame = tk.Frame(root, padx=20, pady=10, bg="#f4f5f7")
        opt_frame.pack(fill="x", padx=10)
        
        self.headless_var = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(opt_frame, text="Sembunyikan Browser (Mode Headless - Hemat RAM)", variable=self.headless_var, font=label_font, bg="#f4f5f7", activebackground="#f4f5f7", cursor="hand2")
        chk.pack(anchor="w", padx=5)

        # Buttons frame
        btn_frame = tk.Frame(root, bg="#f4f5f7")
        btn_frame.pack(pady=10)

        def create_btn(parent, text, color, command, width=20):
            return tk.Button(parent, text=text, command=command, bg=color, fg="white", font=btn_font, width=width, relief="flat", cursor="hand2", pady=5)

        self.btn_test = create_btn(btn_frame, "▶ Test Run (1x)", "#3498db", self.run_test, 18)
        self.btn_test.pack(side="left", padx=8)
        
        self.btn_start = create_btn(btn_frame, "⚡ Mulai Auto (30 Menit)", "#2ecc71", self.start_monitoring, 22)
        self.btn_start.pack(side="left", padx=8)
        
        self.btn_stop = create_btn(btn_frame, "⏹ Berhenti", "#95a5a6", self.stop_monitoring, 15)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_stop.pack(side="left", padx=8)

        log_label = tk.Label(root, text="📋 Log Aktivitas Sistem:", font=label_font, bg="#f4f5f7", fg="#2c3e50")
        log_label.pack(anchor="w", padx=20, pady=(10, 0))
        
        self.log_area = scrolledtext.ScrolledText(root, width=80, height=14, font=("Consolas", 9), bg="#2d3436", fg="#dfe6e9", relief="flat")
        self.log_area.pack(padx=20, pady=(5, 15))

    def log(self, msg):
        self.log_area.insert(tk.END, msg)
        self.log_area.see(tk.END)

    def run_test(self):
        if not self.user_var.get() or not self.pwd_var.get():
            messagebox.showwarning("Peringatan", "Username dan Password tidak boleh kosong!")
            return
            
        self.btn_test.config(state=tk.DISABLED, bg="#bdc3c7")
        self.btn_start.config(state=tk.DISABLED, bg="#bdc3c7")
        self.log("=== MEMULAI TEST RUN ===\n")
        start_telegram_listener(
            self.token_var.get(), self.url_var.get(), self.user_var.get(), 
            self.pwd_var.get(), self.headless_var.get(), self.webapp_var.get()
        )
        
        def task():
            run_scraping_cycle(
                self.url_var.get(), self.user_var.get(), self.pwd_var.get(),
                self.token_var.get(), self.chat_var.get(), 
                self.topic_rp_var.get(), self.topic_ek_var.get(), 
                self.log, self.headless_var.get(), self.webapp_var.get()
            )
            self.btn_test.config(state=tk.NORMAL, bg="#3498db")
            self.btn_start.config(state=tk.NORMAL, bg="#2ecc71")
            self.log("=== TEST RUN SELESAI ===\n")
            
        threading.Thread(target=task, daemon=True).start()
        
    def start_monitoring(self):
        if not self.user_var.get() or not self.pwd_var.get():
            messagebox.showwarning("Peringatan", "Username dan Password tidak boleh kosong!")
            return
            
        self.is_monitoring = True
        self.btn_test.config(state=tk.DISABLED, bg="#bdc3c7")
        self.btn_start.config(state=tk.DISABLED, bg="#bdc3c7")
        self.btn_stop.config(state=tk.NORMAL, bg="#e74c3c")
        self.log("=== MEMULAI PEMANTAUAN OTOMATIS (30 MENIT) ===\n")
        start_telegram_listener(
            self.token_var.get(), self.url_var.get(), self.user_var.get(), 
            self.pwd_var.get(), self.headless_var.get(), self.webapp_var.get()
        )
        
        def loop_task():
            while self.is_monitoring:
                run_scraping_cycle(
                    self.url_var.get(), self.user_var.get(), self.pwd_var.get(),
                    self.token_var.get(), self.chat_var.get(), 
                    self.topic_rp_var.get(), self.topic_ek_var.get(), 
                    self.log, self.headless_var.get(), self.webapp_var.get()
                )
                if not self.is_monitoring:
                    break
                
                self.log(f"[{datetime.now().strftime('%H:%M:%S')}] Pengecekan selesai. Menunggu 30 menit...\n")
                
                # Sleep interruptible for 30 minutes
                for _ in range(30 * 60):
                    if not self.is_monitoring:
                        break
                    time.sleep(1)
                    
            self.log("=== PEMANTAUAN OTOMATIS BERHENTI ===\n")
            self.btn_test.config(state=tk.NORMAL, bg="#3498db")
            self.btn_start.config(state=tk.NORMAL, bg="#2ecc71")
            self.btn_stop.config(state=tk.DISABLED, bg="#95a5a6")

        threading.Thread(target=loop_task, daemon=True).start()
        
    def stop_monitoring(self):
        self.log("Menghentikan pemantauan... (akan berhenti setelah proses/waktu tunggu saat ini selesai)\n")
        self.is_monitoring = False
        self.btn_stop.config(state=tk.DISABLED, bg="#95a5a6")

CURRENT_VERSION = "v1.3.18"

def check_for_updates():
    if not getattr(sys, 'frozen', False):
        return # Hanya update versi EXE
    try:
        response = requests.get("https://api.github.com/repos/Kitakeren17/vepanel_monitor/releases/latest", timeout=5)
        if response.status_code == 200:
            data = response.json()
            latest_version = data.get("tag_name", "")
            if latest_version and latest_version != CURRENT_VERSION:
                if messagebox.askyesno("Update Tersedia", f"Versi baru {latest_version} tersedia! (Versi saat ini: {CURRENT_VERSION}).\n\nApakah Anda ingin memperbarui secara otomatis sekarang?"):
                    download_url = None
                    for asset in data.get("assets", []):
                        if asset["name"].endswith(".exe"):
                            download_url = asset["browser_download_url"]
                            break
                    if download_url:
                        perform_update(download_url)
    except Exception as e:
        print(f"Gagal mengecek update: {e}")

def perform_update(download_url):
    try:
        import urllib.request
        import subprocess
        
        # Buat pop-up downloading...
        progress = tk.Toplevel()
        progress.title("Memperbarui...")
        progress.geometry("300x100")
        tk.Label(progress, text="Sedang mengunduh versi terbaru...\nMohon tunggu beberapa detik.", pady=20).pack()
        progress.update()
        
        new_exe = "update_temp.exe"
        urllib.request.urlretrieve(download_url, new_exe)
        progress.destroy()
        
        current_exe = sys.executable
        bat_script = f"""@echo off
echo Sedang mengupdate aplikasi...
taskkill /F /PID {os.getpid()} > NUL 2>&1
:loop
del "{current_exe}" > NUL 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak > NUL
    goto loop
)
ren "{new_exe}" "{os.path.basename(current_exe)}"
start "" "{os.path.basename(current_exe)}"
del "%~f0"
"""
        with open("updater.bat", "w") as f:
            f.write(bat_script)
            
        subprocess.Popen("updater.bat", shell=True)
        sys.exit(0)
    except Exception as e:
        messagebox.showerror("Error Update", f"Gagal memperbarui aplikasi:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    
    # Hide window momentarily to check updates
    root.withdraw()
    check_for_updates()
    root.deiconify()
    
    app = App(root)
    root.mainloop()
