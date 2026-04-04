import asyncio
import os
import socket
from telegram.ext import ApplicationBuilder

# Ambil TOKEN dan CHAT_ID dari environment variables
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

if not TOKEN or not CHAT_ID:
    raise ValueError("TELEGRAM_TOKEN and CHAT_ID harus di-set di environment variables")

# Variabel untuk menyimpan status terakhir
last_status = None

async def check_connection():
    for attempt in range(2):
        try:
            sock = socket.create_connection(('8.8.8.8', 53), timeout=3)
            sock.close()
            return True
        except (socket.timeout, socket.error):
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            return False

async def send_message(bot, text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
        print(f"Pesan dikirim: {text}")
    except Exception as e:
        print(f"Gagal mengirim pesan: {e}")

async def monitor_internet(bot):
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

            print(f"Status koneksi: {current_status}")

        except Exception as e:
            print(f"Error dalam monitoring: {e}")

        await asyncio.sleep(30)

async def main():
    print("Bot monitoring internet dimulai...")
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Jalankan monitoring sebagai task background
    asyncio.create_task(monitor_internet(application.bot))

    # Jalankan polling untuk Telegram (agar bot aktif)
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
