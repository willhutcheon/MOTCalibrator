import socket
import threading
import time
import csv
import os
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext
import queue
import subprocess
import sys
import RPi.GPIO as GPIO
import threading

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5132
SEND_PORT = 5131

SESSION_THRESHOLDS = {
    5.0: 5.222,
    10.0: 10.001
}

LOG_DIR = "/media/cal/SURFACE/motcal"
os.makedirs(LOG_DIR, exist_ok=True)

FIRMWARE_DIR = "/media/cal/SURFACE/firmware"
os.makedirs(FIRMWARE_DIR, exist_ok=True)

devices = {}
lock = threading.Lock()

WIDTH, HEIGHT = 480, 320
root = tk.Tk()
root.title("MOT Calibrator")
root.geometry(f"{WIDTH}x{HEIGHT}")
root.configure(bg="black")

OUTPUT_PIN = 24      # BCM numbering
PULSE_TIME = 1       # seconds

GPIO.setmode(GPIO.BCM)
GPIO.setup(OUTPUT_PIN, GPIO.OUT)
GPIO.output(OUTPUT_PIN, GPIO.LOW)

device_count_var = tk.StringVar(value="Devices: 0")

log_box = scrolledtext.ScrolledText(
    root, height=6, bg="black", fg="white", font=("Courier", 9)
)
log_box.pack(fill="x", padx=5, pady=5)

device_frame = tk.Frame(root, bg="black")
device_frame.pack(fill="both", expand=True)

ui_queue = queue.Queue()

def schedule_ui(fn):
    ui_queue.put(fn)

def process_ui_queue():
    while not ui_queue.empty():
        fn = ui_queue.get()
        fn()
    root.after(50, process_ui_queue)

def ui_log(msg):
    log_box.insert(tk.END, msg + "\n")
    log_box.yview(tk.END)

def fw_path(filename):
    """Return the absolute path to a firmware file."""
    return os.path.abspath(os.path.join(FIRMWARE_DIR, filename))

def log_fw_path(filename):
    """Log the absolute firmware path to the GUI log box."""
    full_path = fw_path(filename)
    schedule_ui(lambda: ui_log(f"Firmware file: {full_path}"))
    return full_path
    
def pulse_pin():
    """Threaded function to raise pin for PULSE_TIME seconds."""
    schedule_ui(lambda: ui_log("Raising pin HIGH..."))
    GPIO.output(OUTPUT_PIN, GPIO.HIGH)
    time.sleep(PULSE_TIME)
    GPIO.output(OUTPUT_PIN, GPIO.LOW)
    schedule_ui(lambda: ui_log("Pin LOW (done)"))

def update_device_display():
    for w in device_frame.winfo_children():
        w.destroy()
    with lock:
        for dev in devices.values():
            color = (
                "green" if dev.get("result") == "PASS" else
                "red" if dev.get("result") == "FAIL" else
                "yellow"
            )
            text = f"{dev['device_id']} → {dev.get('result', 'CONNECTED')}"
            if "measured" in dev:
                text += f" ({dev['measured']:.3f}s)"
            tk.Label(
                device_frame,
                text=text,
                fg=color,
                bg="black",
                font=("Arial", 10)
            ).pack(anchor="w")
    device_count_var.set(f"Devices: {len(devices)}")

def extract_device_id(msg):
    if msg.startswith("MOT-") and ":" in msg:
        return msg.split(":")[0]
    return "UNKNOWN"

def create_device_logger(device_id):
    filename = os.path.join(
        LOG_DIR,
        f"{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    f = open(filename, "w", newline="")
    writer = csv.writer(f)
    writer.writerow(["timestamp", "direction", "message"])
    return f, writer

def log(dev, direction, msg):
    ts = datetime.now().isoformat(timespec="milliseconds")
    dev["writer"].writerow([ts, direction, msg])
    dev["file"].flush()

def listen_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_HOST, LISTEN_PORT))
    schedule_ui(lambda: ui_log("Listening for MOT devices..."))
    while True:
        data, addr = sock.recvfrom(1024)
        msg = data.decode().strip()
        ip = addr[0]
        device_id = extract_device_id(msg)
        with lock:
            if ip not in devices:
                file, writer = create_device_logger(device_id)
                devices[ip] = {
                    "device_id": device_id,
                    "ip": ip,
                    "state": "IDLE",
                    "session_start": None,
                    "duration": None,
                    "file": file,
                    "writer": writer
                }
                schedule_ui(update_device_display)
            dev = devices[ip]
        schedule_ui(lambda m=msg, d=device_id: ui_log(f"{d}: {m}"))
        log(dev, "MOT", msg)
        handle_mot_message(ip, msg)

def handle_mot_message(ip, msg):
    with lock:
        dev = devices[ip]
    if msg.endswith("PRESS_START_SESSION_ACK"):
        dev["session_start"] = time.monotonic()
        dev["state"] = "RUNNING"
        send_udp(ip, "PRESS_1")
        threading.Thread(target=delayed_stop, args=(ip,), daemon=True).start()
    elif msg.endswith("PRESS_STOP_SESSION_ACK"):
        if dev["session_start"]:
            elapsed = time.monotonic() - dev["session_start"]
            dev["measured"] = elapsed
            threshold = SESSION_THRESHOLDS[dev["duration"]]
            dev["result"] = "PASS" if elapsed <= threshold else "FAIL"
            log(dev, "PI", f"MEASURED_DURATION={elapsed:.6f}")
            dev["session_start"] = None
            dev["state"] = "IDLE"
            schedule_ui(update_device_display)

def send_udp(ip, message):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode(), (ip, SEND_PORT))
    with lock:
        dev = devices[ip]
    log(dev, "PI", message)
    schedule_ui(lambda: ui_log(f"Sent → {dev['device_id']}: {message}"))

def delayed_stop(ip):
    with lock:
        duration = devices[ip]["duration"]
    time.sleep(duration)
    send_udp(ip, "PRESS_STOP_SESSION")

def calibrate_all(duration):
    with lock:
        for dev in devices.values():
            dev["duration"] = duration
            dev["result"] = None
            dev.pop("measured", None)
    schedule_ui(update_device_display)
    schedule_ui(lambda: ui_log(f"Starting {duration}s calibration"))
    for ip in list(devices.keys()):
        send_udp(ip, "PRESS_START_SESSION")

def update_flash_button_state():
    files = os.listdir(FIRMWARE_DIR)
    has_files = any(f.endswith(".bin") for f in files)
    if has_files:
        flash_btn.config(state=tk.NORMAL)
    else:
        flash_btn.config(state=tk.DISABLED)
    # Schedule the next check in 2 seconds
    root.after(2000, update_flash_button_state)

def flash_device():
    def run_flash():
        cmd = [
            "/home/cal/esp-env/bin/python",
            "-m", "esptool",
            "--chip", "esp32s3",
            "--port", "/dev/ttyACM0",
            "--baud", "921600",
            "--before", "default-reset",
            "--after", "hard-reset",
            "write-flash",
            "--compress",
            "--flash-mode", "keep",
            "--flash-freq", "keep",
            "--flash-size", "keep",
            "0x0", fw_path("mot-firmware.ino.bootloader.bin"),
            "0x8000", fw_path("mot-firmware.ino.partitions.bin"),
            "0xe000", fw_path("boot_app0.bin"),
            "0x10000", fw_path("mot-1.0.1.bin"),
        ]
        schedule_ui(lambda: ui_log("=== FLASH STARTED ==="))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in proc.stdout:
                schedule_ui(lambda l=line.rstrip(): ui_log(l))
            rc = proc.wait()
            schedule_ui(lambda: ui_log(
                "=== FLASH SUCCESS ===" if rc == 0 else "=== FLASH FAILED ==="
            ))
        except Exception as e:
            schedule_ui(lambda: ui_log(f"FLASH ERROR: {e}"))
    threading.Thread(target=run_flash, daemon=True).start()

tk.Label(
    root, text="MOT CALIBRATOR",
    fg="white", bg="black",
    font=("Arial", 18, "bold")
).pack(pady=5)

tk.Label(
    root, textvariable=device_count_var,
    fg="white", bg="black",
    font=("Arial", 10)
).pack()

tk.Button(
    root, text="5 SECOND CALIBRATION",
    font=("Arial", 14),
    command=lambda: calibrate_all(5.0),
    width=25
).pack(pady=3)

tk.Button(
    root, text="10 SECOND CALIBRATION",
    font=("Arial", 14),
    command=lambda: calibrate_all(10.0),
    width=25
).pack(pady=3)

tk.Button(
    root,
    text=f"RAISE PIN FOR {PULSE_TIME} SECOND",
    font=("Arial", 14),
    command=lambda: threading.Thread(target=pulse_pin, daemon=True).start(),
    width=25
).pack(pady=3)

flash_btn = tk.Button(
    root, text="FLASH DEVICE",
    font=("Arial", 14),
    command=flash_device,
    width=25
)
flash_btn.pack(pady=3)

threading.Thread(target=listen_udp, daemon=True).start()
root.after(50, process_ui_queue)

update_flash_button_state()

root.mainloop()
