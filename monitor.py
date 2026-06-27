import os
import time
from datetime import datetime
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv()

VEPANEL_URL = os.getenv("VEPANEL_URL")
VEPANEL_USERNAME = os.getenv("VEPANEL_USERNAME")
VEPANEL_PASSWORD = os.getenv("VEPANEL_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    response = requests.post(url, json=payload)
    return response.json()

def run_monitor():
    print("Memulai pemantauan vePanel...")
    with sync_playwright() as p:
        # Gunakan headless=False untuk proses pengujian pertama agar kita bisa melihat interaksi bot
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            print(f"Membuka {VEPANEL_URL}...")
            page.goto(VEPANEL_URL)

            # --- PROSES LOGIN ---
            print("Melakukan login...")
            # Menunggu elemen input username (Asumsi selector name="username")
            # Jika selector berbeda, kita perlu ubah ini nanti berdasarkan hasil inspect elemen
            page.fill("input[name='username'], input[type='text'], input[placeholder*='Username']", VEPANEL_USERNAME)
            page.fill("input[name='password'], input[type='password']", VEPANEL_PASSWORD)
            
            # Mencari tombol login dan klik
            page.click("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign In')")
            
            # Tunggu halaman selesai dimuat setelah login (Asumsi ada elemen dashboard)
            page.wait_for_load_state("networkidle")
            print("Login berhasil! Menavigasi ke Activity Log...")

            # --- NAVIGASI ---
            # Klik Activity Log
            page.click("text='Activity Log'")
            # Klik Operator Activity Log
            page.click("text='Operator Activity Log'")
            
            page.wait_for_load_state("networkidle")
            time.sleep(2) # Jeda ekstra agar tabel termuat

            # --- FILTERING ---
            print("Mencari filter Activity...")
            # Membuka dropdown atau input filter activity
            # Ini asumsional: Mencari select yang ada kata activity atau mencari dropdown
            # Kita coba pendekatan ini: jika ada dropdown khusus atau input
            # Karena belum tahu persis HTML-nya, kita buat yang paling umum
            
            # Mungkin seperti ini (jika dropdown):
            # page.select_option("select[name='activity']", "Reset Password")
            
            # Atau jika itu custom dropdown, kita klik labelnya lalu klik opsinya
            # Mari kita coba klik text dropdown activity
            # page.click("text='Activity'") # mungkin ini nama kolom atau filter
            # Kita anggap ada input atau dropdown
            try:
                page.click("div.filter-activity, button:has-text('Activity')") 
                page.click("text='Reset Password'")
            except Exception as e:
                print(f"Gagal melakukan klik filter otomatis, mencoba cara lain: {e}")
                
            # Kita beri jeda agar pengguna bisa filter manual saat testing, ATAU script menunggu tabel refresh
            time.sleep(3)
            
            # --- EKSTRAK DATA ---
            print("Membaca tabel log...")
            # Kita cari baris di tabel (tr di dalam tbody)
            rows = page.locator("tbody tr")
            count = rows.count()
            
            print(f"Ditemukan {count} baris data.")
            
            reports = []
            today_str = datetime.now().strftime("%d %b %Y") # Format tanggal spt: 27 Jun 2026
            
            for i in range(count):
                row = rows.nth(i)
                cells = row.locator("td")
                
                if cells.count() >= 6:
                    # Berdasarkan gambar:
                    # 0: Activity Time (e.g. 27 Jun 2026, 01:50:34)
                    # 1: Operator (e.g. andreas77id_bo)
                    # 2: Activity (e.g. Reset Password)
                    # 3: Impacted Player (e.g. playjp22)
                    # 4: Impacted Operator
                    # 5: IP Address (e.g. 154.16.17.147)
                    
                    time_text = cells.nth(0).inner_text().strip()
                    operator = cells.nth(1).inner_text().strip()
                    activity = cells.nth(2).inner_text().strip()
                    player = cells.nth(3).inner_text().strip()
                    ip_addr = cells.nth(5).inner_text().strip()
                    
                    # Filter hanya untuk hari ini dan aktivitas Reset Password
                    # (Meski sudah difilter di web, kita pastikan lagi)
                    if "Reset Password" in activity and today_str in time_text:
                        report_item = (
                            f"⏰ <b>Waktu:</b> {time_text}\n"
                            f"👤 <b>Operator:</b> {operator}\n"
                            f"🎯 <b>Player:</b> {player}\n"
                            f"🌐 <b>IP:</b> {ip_addr}"
                        )
                        reports.append(report_item)
            
            # --- KIRIM TELEGRAM ---
            if reports:
                print(f"Ditemukan {len(reports)} data reset password hari ini. Mengirim ke Telegram...")
                
                header = f"<b>🚨 LAPORAN RESET PASSWORD ({today_str})</b>\n\n"
                body = "\n\n---\n\n".join(reports)
                
                full_message = header + body
                send_telegram_message(full_message)
                print("Pesan terkirim ke Telegram!")
            else:
                print("Tidak ada aktivitas Reset Password untuk hari ini.")
                
        except Exception as e:
            print(f"Terjadi kesalahan saat menjalankan bot: {e}")
            page.screenshot(path="error_screenshot.png")
            print("Screenshot error tersimpan sebagai error_screenshot.png")
            
        finally:
            print("Menutup browser...")
            browser.close()

if __name__ == "__main__":
    # Cek kredensial
    if not all([VEPANEL_URL, VEPANEL_USERNAME, VEPANEL_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("Harap isi semua konfigurasi di file .env terlebih dahulu.")
    else:
        run_monitor()
