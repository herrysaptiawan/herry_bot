import asyncio
import os
import socket
from telegram.ext import ApplicationBuilder

# Ambil TOKEN dan CHAT_ID dari environment variables
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

# Pastikan TOKEN dan CHAT_ID tersedia
if not TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN and CHAT_ID must be set in environment variables")

# Inisialisasi aplikasi Telegram
application = ApplicationBuilder().token(TOKEN).build()

# Variabel untuk menyimpan status terakhir
last_status = None

async def check_connection():
    """
    Mengecek koneksi internet dengan mencoba koneksi socket ke 8.8.8.8 port 53.
    Menggunakan retry 2x sebelum dianggap DOWN.
    """
    for attempt in range(2):
        try:
            # Buat socket dan coba koneksi dengan timeout 3 detik
            sock = socket.create_connection(('8.8.8.8', 53), timeout=3)
            sock.close()
            return True  # Koneksi berhasil
        except (socket.timeout, socket.error):
            if attempt == 0:
                await asyncio.sleep(1)  # Tunggu sebentar sebelum retry
                continue
            return False  # Kedua percobaan gagal

async def send_message(text):
    """
    Mengirim pesan ke chat Telegram.
    """
    try:
        await application.bot.send_message(chat_id=CHAT_ID, text=text)
        print(f"Pesan dikirim: {text}")
    except Exception as e:
        print(f"Gagal mengirim pesan: {e}")

async def monitor_internet():
    """
    Loop utama untuk monitoring koneksi internet.
    Mengecek setiap 30 detik, kirim notifikasi hanya saat status berubah.
    """
    global last_status
    while True:
        try:
            is_connected = await check_connection()
            current_status = 'UP' if is_connected else 'DOWN'

            # Cek jika status berubah
            if current_status != last_status:
                if current_status == 'DOWN':
                    await send_message("🚨 INTERNET DOWN!")
                elif current_status == 'UP' and last_status == 'DOWN':
                    await send_message("✅ INTERNET KEMBALI NORMAL")

                # Update status terakhir
                last_status = current_status

            # Print log ke console
            print(f"Status koneksi: {current_status}")

        except Exception as e:
            print(f"Error dalam monitoring: {e}")

        # Tunggu 30 detik sebelum loop berikutnya
        await asyncio.sleep(30)

async def main():
    """
    Fungsi utama untuk menjalankan bot.
    """
    print("Bot monitoring internet dimulai...")
    await monitor_internet()

if __name__ == "__main__":
    asyncio.run(main())