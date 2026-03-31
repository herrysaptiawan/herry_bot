# ================= IMPORT =================
import subprocess      # menjalankan command sistem (ping)
import re              # parsing output text (regex)
import time            # delay / sleep
import requests        # HTTP request (Telegram API)
import matplotlib
matplotlib.use('Agg')  # mode tanpa GUI (penting untuk server/VPS)
import matplotlib.pyplot as plt  # plotting grafik
from collections import deque    # struktur data buffer (FIFO, efisien)
from datetime import datetime, timedelta
from threading import Thread     # untuk multi-threading (listener & auto report)
import sys
import os
import json

# ================= LAST LOSS OFFLINE-SAFE =================
# File untuk menyimpan downtime terakhir (biar tidak hilang saat restart)
STATUS_FILE = "last_loss.json"

# Variabel global untuk menyimpan waktu downtime
down_start = None   # waktu mulai down
down_end = None     # waktu selesai down

def save_last_loss():
    """Simpan waktu downtime terakhir ke file JSON"""
    global down_start, down_end
    data = {
        # simpan dalam format string supaya bisa diserialisasi JSON
        "down_start": down_start.strftime("%Y-%m-%d %H:%M:%S") if down_start else None,
        "down_end": down_end.strftime("%Y-%m-%d %H:%M:%S") if down_end else None
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_last_loss():
    """Load downtime terakhir dari file (dipakai saat bot restart)"""
    global down_start, down_end
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r") as f:
            data = json.load(f)

            # convert string → datetime object
            down_start = datetime.strptime(data["down_start"], "%Y-%m-%d %H:%M:%S") if data.get("down_start") else None
            down_end = datetime.strptime(data["down_end"], "%Y-%m-%d %H:%M:%S") if data.get("down_end") else None
    else:
        # kalau belum ada file, reset
        down_start = down_end = None

# ================= CONFIG REPORT =================
REPORT_INTERVAL = 1440  # default interval auto-report (menit)

# (duplikat import datetime, sebenarnya tidak perlu, tapi tidak masalah)
from datetime import datetime, timedelta

def filter_last_10_minutes(ping_data, time_data):
    """Ambil data ping dalam 10 menit terakhir"""
    cutoff = datetime.now() - timedelta(minutes=10)

    # filter ping berdasarkan waktu
    filtered_pings = [ping for ping, t in zip(ping_data, time_data) if t >= cutoff]
    return filtered_pings


# ================= HISTORY DOWNTIME =================
# File untuk menyimpan history downtime per hari
HISTORY_FILE = "downtime_history.json"

def load_history():
    """Load history downtime dari file"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}  # jika belum ada data

def save_history(history):
    """Simpan history downtime ke file"""
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def cleanup_history(days=30):
    """Hapus history yang lebih lama dari X hari"""
    history = load_history()
    cutoff = datetime.now() - timedelta(days=days)

    new_history = {}

    for date_str, entries in history.items():
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            continue

        if date_obj >= cutoff:
            new_history[date_str] = entries

    save_history(new_history)

# ================= CONFIG UTAMA =================
TARGET = "8.8.8.8"  # target ping (Google DNS, biasanya stabil)

# ===== TELEGRAM BOT UTAMA =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ===== TELEGRAM BOT KEDUA (AUTO REPORT) =====
SECOND_BOT_TOKEN = os.environ.get("SECOND_BOT_TOKEN")

# ================= CHAT ID DINAMIS =================
CHAT_ID = None
CHAT_FILE = "chat_ids.json"

# ===== CEK BOT TOKEN =====
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN belum di-set di Environment Variables")

# ===== LIMIT & THRESHOLD =====
MAX_POINTS = 3600          # max data disimpan (±1 jam jika 1 detik per ping)
LOSS_THRESHOLD = 3         # jumlah loss berturut-turut dianggap DOWN
PING_SPIKE_THRESHOLD = 100 # batas ping tinggi (ms)

# ================= DATA =================
# deque dipakai karena:
# - otomatis buang data lama jika penuh
# - lebih efisien daripada list biasa
ping_data = deque(maxlen=MAX_POINTS)  # menyimpan nilai ping
time_data = deque(maxlen=MAX_POINTS)  # menyimpan timestamp

# statistik total
total_ping = 0     # total akumulasi ping
total_count = 0    # jumlah ping berhasil
total_loss = 0     # jumlah loss

# global statistik
global_min = float('inf')  # ping minimum sepanjang runtime
global_max = 0             # ping maksimum sepanjang runtime

last_reset_date = None

# status koneksi
started = False    # flag: sudah mulai menerima ping valid
loss_counter = 0   # hitung loss berturut-turut
is_down = False    # status koneksi saat ini (down/up)

# ================= TELEGRAM =================
def send_telegram(message, image_path=None, parse_mode=None):
    try:
        if not CHAT_ID:
            return

        if image_path and os.path.exists(image_path):
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

            with open(image_path, "rb") as img:
                requests.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "caption": message,
                        "parse_mode": parse_mode
                    },
                    files={"photo": img}
                )
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

            requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": message,
                    "parse_mode": parse_mode
                }
            )

    except Exception as e:
        print(f"Error sending telegram: {e}")

def send_telegram_second(message, image_path=None, parse_mode=None):
    try:
        if not CHAT_ID:
            return

        if image_path and os.path.exists(image_path):
            url = f"https://api.telegram.org/bot{SECOND_BOT_TOKEN}/sendPhoto"

            with open(image_path, "rb") as img:
                requests.post(
                    url,
                    data={
                        "chat_id": CHAT_ID,
                        "caption": message,
                        "parse_mode": parse_mode
                    },
                    files={"photo": img}
                )
        else:
            url = f"https://api.telegram.org/bot{SECOND_BOT_TOKEN}/sendMessage"

            requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "text": message,
                    "parse_mode": parse_mode
                }
            )

    except Exception as e:
        print(f"Error sending telegram (second): {e}")

# ================= STATUS =================
def get_status(avg, loss, is_down):
    """Menentukan status koneksi berdasarkan ping & loss"""
    if is_down:
        return "🔴 DOWN"
    elif loss >= 3:
        return "🟠 UNSTABLE"
    elif avg > 80:
        return "🟡 HIGH LATENCY"
    else:
        return "🟢 STABLE"

def get_global_stats():
    """Hitung statistik global (sepanjang runtime)"""
    if total_count > 0:
        avg = total_ping / total_count
        loss = (total_loss / total_count) * 100
    else:
        avg = loss = 0
    return avg, loss

# ================= UTILITY =================
def format_duration(duration_minutes):
    """Format durasi menit → hari/jam/menit (untuk display)"""
    days = duration_minutes // 1440
    remainder = duration_minutes % 1440
    hours = remainder // 60
    minutes = remainder % 60

    parts = []
    if days > 0:
        parts.append(f"{days} Hari")
    if hours > 0:
        parts.append(f"{hours} Jam")
    if minutes > 0:
        parts.append(f"{minutes} Menit")

    return " ".join(parts) if parts else "0 Menit"

def format_durasi(total_seconds):
    """Format detik → jam/menit/detik (untuk downtime)"""
    jam, sisa = divmod(total_seconds, 3600)
    menit, detik = divmod(sisa, 60)
    parts = []
    if jam > 0:
        parts.append(f"{jam}j")
    if menit > 0:
        parts.append(f"{menit}m")
    if detik > 0 or not parts:
        parts.append(f"{detik}s")
    return " ".join(parts)

def format_tanggal_indonesia(dt):
    """Format tanggal ke bahasa Indonesia"""
    bulan = ["Januari","Februari","Maret","April","Mei","Juni",
             "Juli","Agustus","September","Oktober","November","Desember"]
    return f"{dt.day} {bulan[dt.month-1]} {dt.year}"

# ================= INTERVAL HELPER =================
def format_interval_output(minutes_total):
    """Format menit total → string friendly, misal '1d 2h 5m'"""
    parts = []

    days, rem = divmod(minutes_total, 1440)  # 1440 menit = 1 hari
    hours, rem = divmod(rem, 60)
    mins = rem

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0:
        parts.append(f"{mins}m")

    return " ".join(parts) if parts else "0m"

# ================= HELPERS INTERVAL =================
import re

def parse_interval_to_minutes(text):
    """Parse string seperti 2h10m, 1d5h30m menjadi total menit"""
    text = text.lower().replace(" ", "")
    total = 0
    match = re.findall(r'(\d+)([dhms])', text)
    if not match:
        # asumsi input angka saja → menit
        if text.isdigit():
            total += int(text)
        else:
            return 0
    for value, unit in match:
        value = int(value)
        if unit == "d":
            total += value * 1440
        elif unit == "h":
            total += value * 60
        elif unit == "m":
            total += value
        elif unit == "s":
            total += value / 60  # detik → menit
    return int(total)


def format_interval_output(total_minutes):
    """Ubah menit → string H M S D, misal 2h 10m"""
    days = total_minutes // 1440
    remainder = total_minutes % 1440
    hours = remainder // 60
    minutes = remainder % 60
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    return " ".join(parts)

# ================= GRAPH =================
def create_graph(duration_minutes=10):
    """Membuat grafik ping + highlight loss + statistik"""

    # Jika belum ada data → tidak bisa buat grafik
    if not time_data:
        return None

    # Pastikan folder output ada
    os.makedirs("graphs", exist_ok=True)
    file = "graphs/graph.png"

    # Ambil waktu akhir & awal (dibulatkan ke detik)
    end_time = time_data[-1].replace(microsecond=0)
    start_time = end_time - timedelta(minutes=duration_minutes)

    # ================= TIMELINE PER DETIK =================
    # Membuat list waktu per detik selama durasi
    total_seconds = duration_minutes * 60
    full_times = [start_time + timedelta(seconds=i) for i in range(total_seconds + 1)]

    # Mapping waktu → ping
    # replace microsecond supaya match dengan full_times
    ping_dict = {t.replace(microsecond=0): p for t, p in zip(time_data, ping_data)}

    # Ambil ping sesuai timeline (kalau tidak ada → None)
    filtered_pings = [ping_dict.get(t, None) for t in full_times]

    # ================= DETEKSI LOSS AREA =================
    # Cari index pertama yang valid (bukan None)
    first_valid_index = next((i for i, p in enumerate(filtered_pings) if p is not None), None)

    loss_mask = []      # True jika masuk kondisi loss panjang
    loss_streak = 0     # hitung loss berturut-turut

    for i, p in enumerate(filtered_pings):
        # sebelum ada data valid → abaikan
        if first_valid_index is None or i < first_valid_index:
            loss_mask.append(False)
            continue

        # jika None → loss
        if p is None:
            loss_streak += 1
        else:
            loss_streak = 0

        # tandai loss jika sudah melebihi threshold
        loss_mask.append(loss_streak >= LOSS_THRESHOLD)

    # ================= SMOOTHING DATA =================
    # Isi nilai None dengan nilai terakhir (biar grafik nyambung)
    plot_data = []
    last = None

    for i, p in enumerate(filtered_pings):
        if first_valid_index is None or i < first_valid_index:
            plot_data.append(None)
            continue

        if p is None:
            plot_data.append(last)  # pakai nilai sebelumnya
        else:
            plot_data.append(p)
            last = p

    # ================= PLOT GRAFIK =================
    plt.figure(figsize=(16,4))
    ax = plt.gca()

    # garis utama ping
    plt.plot(plot_data, linewidth=1, color="blue")

    # ================= HIGHLIGHT AREA LOSS =================
    # warnai area merah saat koneksi dianggap down
    in_loss = False

    for i, is_loss in enumerate(loss_mask):
        if is_loss and not in_loss:
            in_loss = True
            start_idx = i  # mulai area merah

        elif not is_loss and in_loss:
            in_loss = False
            plt.axvspan(start_idx, i, color='red', alpha=0.3)

    # jika loss sampai akhir grafik
    if in_loss:
        plt.axvspan(start_idx, len(loss_mask)-1, color='red', alpha=0.3)

    # ================= AUTO SCALE Y =================
    valid_plot = [p for p in plot_data if p is not None]
    if valid_plot:
        plt.ylim(0, max(valid_plot)*1.2)  # kasih margin 20%

        # ================= AUTO X TICK =================
        # menentukan interval label waktu di sumbu X
        if duration_minutes <= 10:
            step = 60            # tiap 1 menit
        elif duration_minutes <= 30:
            step = 300           # tiap 5 menit
        elif duration_minutes <= 60:
            step = 600           # tiap 10 menit
        elif duration_minutes <= 120:
            step = 1200          # tiap 20 menit
        elif duration_minutes <= 1440:  # ≤ 1 hari
            step = 10800         # tiap 3 jam
        else:
            step = 10800         # default (3 jam)

    # posisi tick
    x_ticks = list(range(0, len(full_times), step))

    # pastikan titik terakhir selalu tampil
    if (len(full_times)-1) not in x_ticks:
        x_ticks.append(len(full_times)-1)

    # label waktu (HH:MM)
    x_labels = [full_times[i].strftime("%H:%M") for i in x_ticks]
    plt.xticks(x_ticks, x_labels, rotation=45)

    plt.ylabel("Latency (ms)")

    # ================= HEADER ATAS =================

    # kiri atas → target ping
    ax.text(
        0.01, 1.05,
        f"Target: {TARGET}",
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment='bottom',
        horizontalalignment='left'
    )

    # ================= DURASI =================
    duration_seconds = int((end_time - start_time).total_seconds())

    days = duration_seconds // 86400
    hours = (duration_seconds % 86400) // 3600
    minutes = (duration_seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days} hari")
    if hours > 0:
        parts.append(f"{hours} jam")
    if minutes > 0:
        parts.append(f"{minutes} menit")

    dur_text = " ".join(parts) if parts else "0 menit"

    # kanan atas → durasi + range waktu
    ax.text(
        0.99, 1.05,
        f"Durasi: {dur_text} ({start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})",
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment='bottom',
        horizontalalignment='right'
    )

    # ================= STATISTIK =================
    # hitung statistik dari data valid
    valid_values = [p for p in plot_data if p is not None]

    avg_ping = sum(valid_values)/len(valid_values) if valid_values else 0
    min_ping = min(valid_values, default=0)
    max_ping = max(valid_values, default=0)

    # jitter = rata-rata perubahan antar ping
    if len(valid_values) >= 2:
        diffs = [abs(valid_values[i] - valid_values[i-1]) for i in range(1, len(valid_values))]
        jitter = sum(diffs) / len(diffs)
    else:
        jitter = 0

    # persentase loss
    loss_percent = (sum(loss_mask)/len(loss_mask)*100) if loss_mask else 0

    stat_text = f"Avg: {avg_ping:.1f} ms | Min: {min_ping} ms | Max: {max_ping} ms | Jitter: {jitter:.1f} ms | Loss: {loss_percent:.1f}%"

    # tengah atas → statistik
    ax.text(
        0.5, 1.05,
        stat_text,
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment='bottom',
        horizontalalignment='center'
    )

    # ================= TANGGAL =================
    tanggal = format_tanggal_indonesia(end_time)

    ax.text(
        0.99, 1.12,
        f"{tanggal}",
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment='bottom',
        horizontalalignment='right'
    )

    # ================= FINAL RENDER =================
    plt.subplots_adjust(bottom=0.10)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(file, dpi=150)
    plt.close()

    # return data untuk dipakai di bagian lain (telegram, dll)
    return file, start_time, end_time, plot_data, loss_mask

# ================= TELEGRAM LISTENER =================
def telegram_listener():
    """Listener untuk menerima command dari Telegram (long polling)"""

    offset = None  # dipakai untuk tracking update terakhir (biar tidak double baca)

    global PING_SPIKE_THRESHOLD  # supaya bisa diubah realtime via command

    while True:
        try:
            # ================= GET UPDATE =================
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

            # jika sudah pernah ambil data → pakai offset
            if offset:
                url += f"?offset={offset}"

            # request ke Telegram API
            resp = requests.get(url, timeout=10).json()

            # ================= LOOP MESSAGE =================
            for r in resp.get("result", []):
                offset = r["update_id"] + 1  # update offset

                msg = r.get("message", {})
                chat_id = msg.get("chat", {}).get("id")

                # auto simpan chat_id
                if chat_id:
                    if chat_id:
                        global CHAT_ID
                        CHAT_ID = chat_id

                text = msg.get("text", "").lower()

                # ================= /STATUS =================
                if text == "/status":
                    # ambil data 10 menit terakhir
                    last_10_pings = filter_last_10_minutes(ping_data, time_data)

                    sent_10 = len(last_10_pings)
                    received_10 = len([p for p in last_10_pings if p is not None])
                    lost_10 = len([p for p in last_10_pings if p is None])

                    # hitung loss %
                    loss_10 = (lost_10 / sent_10 * 100) if sent_10 > 0 else 0

                    # hitung average ping
                    valid_pings = [p for p in last_10_pings if p is not None]
                    avg_10 = sum(valid_pings)/len(valid_pings) if valid_pings else 0

                    # tentukan status
                    status = get_status(avg_10, loss_10, is_down)

                    # kirim ke Telegram
                    send_telegram(
                        f"📊 STATUS INTERNET (10 MENIT TERAKHIR)\n\n"
                        f"Sent = {sent_10}\n"
                        f"Received = {received_10}\n"
                        f"Ping Avg: {avg_10:.1f} ms\n"
                        f"Lost = {lost_10}\n"
                        f"Loss: {loss_10:.1f}%\n\n"
                        f"Status: {status}"
                    )

                # ================= /LASTLOSS =================
                elif text == "/lastloss":
                    load_last_loss()  # load dari file

                    if down_start:
                        # jika masih down → hitung sampai sekarang
                        if is_down:
                            duration = datetime.now() - down_start
                            status_text = "⚠️ Masih DOWN"
                        else:
                            duration = down_end - down_start
                            status_text = "✅ Kembali UP"

                        menit, detik = divmod(int(duration.total_seconds()), 60)

                        # format tanggal Indonesia
                        tanggal_text = format_tanggal_indonesia(down_start)

                        start_time_text = down_start.strftime('%H:%M:%S')

                        # jika belum ada end → masih down
                        if down_end:
                            end_time_text = down_end.strftime('%H:%M:%S')
                        else:
                            end_time_text = "Masih DOWN"

                        send_telegram(
                            f"📉 LAST LOSS\n\n"
                            f"━━━ {tanggal_text} ━━━\n"
                            f"Start: {start_time_text}\n"
                            f"End: {end_time_text}\n"
                            f"Durasi: {menit}m {detik}s\n\n"
                            f"Status: {status_text}"
                        )
                    else:
                        send_telegram("Belum pernah mengalami downtime.")

                # ================= /SETLOSS =================
                elif text.startswith("/setloss"):
                    parts = text.split()

                    if len(parts) == 2:
                        try:
                            new_loss_threshold = int(parts[1])

                            # validasi minimal 1
                            if new_loss_threshold < 1:
                                raise ValueError("Minimal 1")

                            global LOSS_THRESHOLD
                            LOSS_THRESHOLD = new_loss_threshold

                            send_telegram(
                                f"✅ LOSS threshold diubah menjadi {LOSS_THRESHOLD} ping hilang berturut-turut"
                            )

                        except ValueError:
                            send_telegram("❌ Nilai harus angka ≥ 1!\nFormat: /setloss <jumlah>")
                    else:
                        send_telegram("❌ Gunakan format: /setloss <jumlah>\n"
                            "Contoh:\n"
                            "- /setloss 3"
                        )

                # ================= /GETLOSS =================
                elif text == "/getloss":
                    send_telegram(
                        f"📌 LOSS threshold saat ini: {LOSS_THRESHOLD} ping hilang berturut-turut dianggap DOWN\n\n"
                        f"Gunakan /setloss <jumlah> untuk mengubahnya"
                    )

                # ================= /SETTHRESHOLD =================
                elif text.startswith("/setthreshold"):
                    parts = text.split()

                    if len(parts) == 2:
                        try:
                            PING_SPIKE_THRESHOLD = int(parts[1])

                            send_telegram(
                                f"✅ Ping spike threshold diubah menjadi {PING_SPIKE_THRESHOLD} ms"
                            )
                        except ValueError:
                            send_telegram("❌ Nilai threshold harus angka!")
                    else:
                        send_telegram("❌ Gunakan format: /setthreshold <nilai>\n"
                            "Contoh:\n"
                            "- /setthreshold 100"
                        )

                # ================= /GETTHRESHOLD =================
                elif text == "/getthreshold":
                    send_telegram(
                        f"📌 Ping spike threshold saat ini: {PING_SPIKE_THRESHOLD} ms\n\n"
                        f"Gunakan /settrhreshold <nilai> untuk mengubahnya"
                    )

                # ================= /HISTORY =================
                elif text.startswith("/history"):
                    parts = text.split()

                    # jika ada parameter tanggal
                    if len(parts) == 2:
                        raw_date = parts[1]

                        try:
                            # format: DDMMYY
                            parsed_date = datetime.strptime(raw_date, "%d%m%y")
                        except ValueError:
                            send_telegram("❌ Format harus DDMMYY\nContoh: /history 290326")
                            continue
                    else:
                        # default: hari ini
                        parsed_date = datetime.now()

                    day_key = parsed_date.strftime("%Y-%m-%d")
                    display_date = format_tanggal_indonesia(parsed_date)

                    history = load_history()

                    if day_key in history and history[day_key]:
                        msg = f"📅 Downtime History - {display_date}\n\n"

                        for i, entry in enumerate(history[day_key], 1):
                            start_str = entry.get("start")
                            end_str = entry.get("end") or "Masih DOWN"

                            # hitung durasi jika sudah selesai
                            if end_str != "Masih DOWN":
                                start_dt = datetime.strptime(f"{day_key} {start_str}", "%Y-%m-%d %H:%M:%S")
                                end_dt = datetime.strptime(f"{day_key} {end_str}", "%Y-%m-%d %H:%M:%S")
                                durasi_sec = int((end_dt - start_dt).total_seconds())
                                durasi_text = format_durasi(durasi_sec)
                            else:
                                durasi_text = "Masih DOWN"

                            msg += f"{i}️⃣ Start: {start_str} - End: {end_str} | Durasi: {durasi_text}\n"

                        # jika tidak pakai parameter → hari ini
                        if len(parts) == 1:
                            msg += "\nGunakan /history DDMMYY untuk melihat history sebelumnya"

                        send_telegram(msg)

                    else:
                        # tidak ada downtime
                        if len(parts) == 1:
                            # hari ini → tambahkan catatan
                            send_telegram(
                                f"Tidak ada downtime tercatat pada {display_date}\n\n"
                                "Gunakan /history DDMMYY untuk melihat history sebelumnya"
                            )
                        else:
                            # tanggal tertentu → cukup tulis kosong
                            send_telegram(f"Tidak ada downtime tercatat pada {display_date}")

                # ================= /SETREPORT =================
                elif text.startswith("/setreport"):
                    parts = text.split()
                    if len(parts) == 2:
                        try:
                            new_interval = parse_interval_to_minutes(parts[1])
                            if new_interval < 1:
                                raise ValueError("Minimal 1 menit")
                            global REPORT_INTERVAL
                            REPORT_INTERVAL = new_interval

                            interval_str = format_interval_output(REPORT_INTERVAL)
                            send_telegram(
                                f"✅ Auto-report interval diubah menjadi {interval_str} ({REPORT_INTERVAL} menit)"
                            )
                        except ValueError:
                            send_telegram(
                                "❌ Format salah atau nilai < 1 menit\n"
                                "Gunakan format /setreport <interval>, misal:\n"
                                "- /setreport 15   → 15 menit\n"
                                "- /setreport 2h10m → 2 jam 10 menit"
                            )
                    else:
                        send_telegram("❌ Gunakan format /setreport <interval>\n"
                            "Contoh:\n"
                            "- /setreport 10\n"
                            "- /setreport 1h30m"
                        )

                # ================= /GETREPORT =================
                elif text == "/getreport":
                    interval_str = format_interval_output(REPORT_INTERVAL)
                    send_telegram(
                        f"📌 Interval auto-report saat ini: {interval_str} ({REPORT_INTERVAL} menit)\n\n"
                        f"Gunakan /setreport <interval> untuk mengubahnya"
                    )

                # ================= /GRAPH =================
                elif text.startswith("/graph"):
                    parts = text.split()
                    duration = 10  # default 10 menit

                    if len(parts) == 2:
                        try:
                            # parse string seperti 1d2h30m → total menit
                            duration = parse_interval_to_minutes(parts[1])
                        except ValueError:
                            send_telegram("❌ Format salah, gunakan /graph <interval>\nContoh: /graph 1h30m")
                            continue

                    # buat grafik
                    result = create_graph(duration_minutes=duration)

                    if result:
                        graph, start_time, end_time, plot_data, loss_mask = result

                        # hitung statistik
                        cutoff = datetime.now() - timedelta(minutes=duration)
                        filtered_pings = [p for p, t in zip(ping_data, time_data) if t >= cutoff]

                        sent = len(filtered_pings)
                        received = len([p for p in filtered_pings if p is not None])
                        lost = sent - received
                        loss_percent = (lost / sent * 100) if sent > 0 else 0

                        valid_pings = [p for p in filtered_pings if p is not None]

                        avg_ping = sum(valid_pings)/len(valid_pings) if valid_pings else 0
                        min_ping = min(valid_pings) if valid_pings else 0
                        max_ping = max(valid_pings) if valid_pings else 0

                        caption = (
                            f"📊 PING GRAPH ({start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})\n"
                            f"Stats Last {format_duration(duration)}\n\n"
                            f"━━━━━━━━━━ {format_duration(duration)} ━━━━━━━━━━\n"
                            f"Packets: Sent = {sent}, Received = {received}, Lost = {lost} ({loss_percent:.1f}% loss)\n\n"
                            f"Ping:\n  Avg = {avg_ping:.1f} ms | Min = {min_ping} ms | Max = {max_ping} ms\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"Gunakan /graph <waktu> untuk mengubah rentan waktu\n"
                            f"Contoh:\n"
                            f"- /graph 10\n"
                            f"- /graph 1h30m"
                        )

                        send_telegram(caption, graph)

                    else:
                        send_telegram("⏳ Data belum cukup")

                # ================= DEFAULT MENU =================
                else:
                    # kirim help menu jika command tidak dikenali
                    send_telegram(
                        "🤖 *DAFTAR COMMAND BOT MONITORING INTERNET*\n\n"

                        "*STATUS & RIWAYAT*\n"
                        "/status - Cek kondisi 10 menit terakhir\n"
                        "/lastloss - Downtime terakhir\n"
                        "/graph - Grafik ping 10 menit terakhir\n"
                        "/history - Riwayat downtime hari ini\n\n"

                        "*THRESHOLD & LOSS*\n"
                        "/setthreshold <nilai> - Atur batas ping\n"
                        "/getthreshold - Cek batas ping\n"
                        "/setloss <jumlah> - Atur jumlah loss\n"
                        "/getloss - Cek setting loss\n\n"

                        "*LAPORAN OTOMATIS*\n"
                        "/setreport <interval> - Atur interval laporan\n"
                        "/getreport - Cek interval laporan",
                        parse_mode="Markdown"
                    )

        except Exception as e:
            print(f"Telegram listener error: {e}")
            time.sleep(5)

# Jalankan listener di thread terpisah (non-blocking)
Thread(target=telegram_listener, daemon=True).start()

# ================= AUTO REPORT =================

last_report_time = None  # timestamp terakhir kirim report (anti spam)
first_report_sent = False  # flag supaya report pertama langsung kirim (tidak nunggu menit bulat)

def auto_report():
    """Thread untuk kirim laporan otomatis tiap X menit"""

    global last_report_time, first_report_sent

    while True:
        try:
            # kalau belum ada data ping → tunggu
            if not time_data:
                time.sleep(1)
                continue

            interval = REPORT_INTERVAL  # interval report (menit)

            now = datetime.now()

            # waktu dibulatkan ke menit (00 detik)
            end_time = now.replace(second=0, microsecond=0)

            # hitung waktu mulai interval
            start_interval = end_time - timedelta(minutes=interval)

            # ================= REPORT PERTAMA (INSTAN) =================
            if not first_report_sent:
                first_report_sent = True
                last_report_time = now

                # ambil data sesuai interval
                interval_pings = [(p, t) for p, t in zip(ping_data, time_data) if t >= start_interval]

                pings = [p for p, t in interval_pings if p is not None]
                lost = len([p for p, t in interval_pings if p is None])
                sent = len(interval_pings)
                received = sent - lost

                # hitung statistik
                loss_percent = (lost / sent * 100) if sent > 0 else 0
                avg_ping = sum(pings)/len(pings) if pings else 0
                min_ping = min(pings) if pings else 0
                max_ping = max(pings) if pings else 0

                # generate grafik
                result = create_graph(duration_minutes=interval)
                graph_path = result[0] if result else None

                # caption report instan
                caption = (
                    f"⏱ AUTO REPORT {format_duration(interval)} (instan)\n"
                    f"({start_interval.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})\n"
                    f"Packets: Sent = {sent}, Received = {received}, Lost = {lost} ({loss_percent:.1f}% loss)\n"
                    f"Ping: Avg = {avg_ping:.1f} ms | Min = {min_ping} ms | Max = {max_ping} ms"
                )

                # kirim ke bot kedua
                send_telegram_second(caption, graph_path)

                continue  # langsung loop lagi tanpa nunggu

            # ================= REPORT NORMAL =================

            interval_pings = [(p, t) for p, t in zip(ping_data, time_data) if t >= start_interval]

            pings = [p for p, t in interval_pings if p is not None]
            lost = len([p for p, t in interval_pings if p is None])
            sent = len(interval_pings)
            received = sent - lost

            # statistik interval
            loss_percent = (lost / sent * 100) if sent > 0 else 0
            avg_ping = sum(pings)/len(pings) if pings else 0
            min_ping = min(pings) if pings else 0
            max_ping = max(pings) if pings else 0

            # ================= GLOBAL STAT =================
            total_sent = total_count + total_loss
            total_received = total_count
            total_lost = total_loss
            total_loss_percent = (total_lost / total_sent * 100) if total_sent > 0 else 0

            g_avg, _ = get_global_stats()
            g_min = global_min if global_min != float('inf') else 0
            g_max = global_max

            # status koneksi
            status = get_status(avg_ping, loss_percent, is_down)

            # warning jika data masih sedikit (<10 menit)
            kurang_10menit = (now - time_data[0]).total_seconds() < 600
            kurang_text = "⚠️ Data kurang dari 10 menit, statistik mungkin belum stabil" if kurang_10menit else ""

            # generate grafik
            result = create_graph(duration_minutes=interval)
            graph_path = result[0] if result else None

            # caption lengkap
            caption = (
                f"⏱ AUTO REPORT {format_duration(interval)}\n"
                f"({start_interval.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})\n\n"
                f"━━━━━━━━━━ {format_duration(interval)} ━━━━━━━━━━\n"
                f"Packets: Sent = {sent}, Received = {received}, Lost = {lost} ({loss_percent:.1f}% loss)\n\n"
                f"Ping:\n  Avg = {avg_ping:.1f} ms | Min = {min_ping} ms | Max = {max_ping} ms\n"
                f"{kurang_text}\n\n"
                f"━━━━━━━━━━ TOTAL ━━━━━━━━━━\n"
                f"Packets: Sent = {total_sent}, Received = {total_received}, Lost = {total_lost} ({total_loss_percent:.1f}% loss)\n\n"
                f"Ping:\n  Avg = {g_avg:.1f} ms | Min = {g_min} ms | Max = {g_max}\n\n"
                f"{status}"
            )

            # ================= TRIGGER BERDASARKAN WAKTU =================
            # hanya kirim saat menit kelipatan interval (misal tiap 10 menit → 00,10,20,...)
            if now.minute % interval == 0 and now.second < 2:

                # anti spam (minimal jarak 60 detik)
                if last_report_time is None or (now - last_report_time).total_seconds() >= 60:
                    send_telegram_second(caption, graph_path)
                    last_report_time = now

        except Exception as e:
            print(f"Auto report error: {e}")

        finally:
            # loop tiap 1 detik (biar presisi trigger menit)
            time.sleep(1)


# jalankan auto report di background thread
Thread(target=auto_report, daemon=True).start()


# ================= PING PROCESS =================

# jalankan command ping terus menerus
process = subprocess.Popen(
    ["ping", "-t", TARGET],  # -t = infinite ping (Windows)
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    encoding="utf-8",
    errors="ignore",
    bufsize=1
)

try:
    while True:
        # baca output ping per baris
        line = process.stdout.readline()

        if not line:
            continue

        print(line.strip())  # tampilkan ke console
        sys.stdout.flush()

        # regex ambil nilai ping (time=XX ms)
        match = re.search(r'time[=<]\s*(\d+)', line)

        now = datetime.now().replace(microsecond=0)

        # ================= RESET HARIAN =================
        current_date = now.date()

        if now.hour == 0 and now.minute == 5:
            if last_reset_date != current_date:
                total_ping = 0
                total_count = 0
                total_loss = 0
                global_min = float('inf')
                global_max = 0

                last_reset_date = current_date

                send_telegram("🔄 Statistik harian telah di-reset (00:05)")


        # ================= JIKA PING BERHASIL =================
        if match:
            ping = int(match.group(1))

            # update global min/max
            if ping < global_min:
                global_min = ping
            if ping > global_max:
                global_max = ping

            # simpan data ping
            ping_data.append(ping)
            total_ping += ping
            total_count += 1

            # ================= DETEKSI SPIKE =================
            if ping > PING_SPIKE_THRESHOLD:
                send_telegram(f"⚠️ Ping Tinggi: {ping} ms")

            # ================= JIKA SEBELUMNYA DOWN =================
            if is_down:
                is_down = False
                down_end = now

                save_last_loss()

                # update history
                history = load_history()
                today = down_start.strftime("%Y-%m-%d")

                if today in history and history[today]:
                    history[today][-1]["end"] = down_end.strftime("%H:%M:%S")

                save_history(history)
                cleanup_history(30)

                # hitung durasi downtime
                durasi = int((down_end - down_start).total_seconds())
                menit = durasi // 60
                detik = durasi % 60

                # kirim notifikasi recovery + grafik
                graph = create_graph()

                send_telegram(
                    f"⚠️ Internet Kembali Normal!\n\n"
                    f"Down: {down_start.strftime('%H:%M:%S')}\n"
                    f"Up: {down_end.strftime('%H:%M:%S')}\n"
                    f"Durasi: {menit}m {detik}s",
                    graph[0] if graph else None
                )

            # reset loss counter
            loss_counter = 0
            started = True

        # ================= JIKA PING GAGAL =================
        else:
            if started:
                ping_data.append(None)  # None = packet loss
                loss_counter += 1
                total_loss += 1

            # ================= DETEKSI DOWN =================
            if loss_counter >= LOSS_THRESHOLD and not is_down:
                is_down = True
                down_start = now

                save_last_loss()

                # simpan ke history
                history = load_history()
                today = now.strftime("%Y-%m-%d")

                if today not in history or not isinstance(history[today], list):
                    history[today] = []

                history[today].append({
                    "start": down_start.strftime("%H:%M:%S"),
                    "end": None
                })

                save_history(history)
                cleanup_history(30)

        # simpan timestamp
        time_data.append(now)

# ================= HANDLE CTRL+C =================
except KeyboardInterrupt:
    print("\nMonitoring dihentikan oleh user.")
    process.terminate()
    sys.exit(0)