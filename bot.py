import asyncio
import os
import socket
from telegram.ext import ApplicationBuilder

# Ambil TOKEN dan CHAT_ID dari environment variables
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN and CHAT_ID harus di-set di environment variables")

# Variabel global untuk menyimpan status terakhir
last_status = None

async def check_connection():
    """
    Mengecek koneksi internet ke 8.8.8.8 port 53.
    Retry 2x sebelum dianggap DOWN.
    """
    for attempt in range(2):
        try:
            sock = socket.create_connection(('8.8.8.8', 53), timeout=3)
            sock.close()
            return True
        except (socket.timeout, socket.error):
            if attempt == 0:
                await asyncio.sleep(1)  # Tunggu sebentar sebelum retry
                continue
            return False

async def send_message(bot, text):
    """
    Kirim pesan ke Telegram.
    """
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
        print(f"[INFO] Pesan dikirim: {text}")
    except Exception as e:
        print(f"[ERROR] Gagal kirim pesan: {e}")

async def monitor_internet(bot):
    """
    Loop utama monitoring internet.
    Kirim notifikasi hanya jika status berubah.
    """
    global last_status
    while True:
        try:
            is_connected = await check_connection()
            current_status = 'UP' if is_connected else 'DOWN'

            if current_status != last_status:
                if current_status == 'DOWN':
                    await send_message(bot, "🚨 INTERNET DOWN!")
                elif current_status == 'UP' and last_status == 'DOWN':
                    await send_message(bot, "✅ INTERNET KEMBALI NORMAL")

                last_status = current_status

            print(f"[LOG] Status koneksi: {current_status}")

        except Exception as e:
            print(f"[ERROR] Monitoring gagal: {e}")

        await asyncio.sleep(30)  # Delay 30 detik sebelum cek berikutnya

async def main():
    """
    Fungsi utama: buat aplikasi, jalankan polling + monitoring.
    """
    print("[INFO] Bot monitoring internet dimulai...")
    application = ApplicationBuilder().token(TOKEN).build()

    # Jalankan monitoring sebagai background task
    asyncio.create_task(monitor_internet(application.bot))

    # Jalankan polling agar bot bisa aktif di Telegram
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
