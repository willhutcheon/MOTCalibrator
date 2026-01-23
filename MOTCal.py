import socket
import threading
import time
import csv
import os
from datetime import datetime
import tkinter as tk
import queue
import subprocess
import RPi.GPIO as GPIO
import re
from packaging.version import Version

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 5132
SEND_PORT = 5131

SESSION_THRESHOLDS = {
    5.0: 5.222,
    10.0: 10.001
}

LOG_DIR = "/media/cal/SURFACE/motcal"
FIRMWARE_DIR = "/media/cal/SURFACE/firmware"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FIRMWARE_DIR, exist_ok=True)

OUTPUT_PIN = 16
PULSE_TIME = 1

GPIO.setmode(GPIO.BCM)
GPIO.setup(OUTPUT_PIN, GPIO.OUT)
GPIO.output(OUTPUT_PIN, GPIO.LOW)

root = tk.Tk()
root.title("MOT Calibrator")
root.attributes("-fullscreen", True)
root.configure(bg="black", cursor="none")

def exit_app():
    GPIO.cleanup()
    subprocess.call(
        ["sudo", "systemctl", "stop", "mot-calibrator.service"]
    )
    root.destroy()

root.bind("<Escape>", lambda e: exit_app())

exit_btn = tk.Button(
    root,
    text="✕",
    font=("Arial", 18, "bold"),
    fg="white",
    bg="red",
    command=exit_app,
    bd=0,
    width=3,
    height=1
)
exit_btn.place(relx=1.0, rely=0.0, anchor="ne", x=-5, y=5)

devices = {}
lock = threading.Lock()
ui_queue = queue.Queue()
device_count_var = tk.StringVar(value="Devices: 0")
flash_status_var = tk.StringVar(value="FLASH: IDLE")

def schedule_ui(fn):
    ui_queue.put(fn)

def process_ui_queue():
    while not ui_queue.empty():
        ui_queue.get()()
    root.after(50, process_ui_queue)

def set_flash_status(state):
    flash_status_var.set(f"FLASH: {state}")
    flash_status_label.config(
        fg=(
            "green" if state == "SUCCESS" else
            "red" if state == "FAILED" else
            "yellow"
        )
    )

DEVICE_LIST_HEIGHT = 80
device_container = tk.Frame(root, bg="black", height=DEVICE_LIST_HEIGHT)
device_container.pack(fill="both", expand=True, padx=5, pady=5)
device_container.pack_propagate(False)
device_canvas = tk.Canvas(device_container, bg="black", highlightthickness=0)
device_canvas.pack(side="left", fill="both", expand=True)
device_scrollbar = tk.Scrollbar(device_container, orient="vertical", command=device_canvas.yview)
device_scrollbar.pack(side="right", fill="y")
device_canvas.configure(yscrollcommand=device_scrollbar.set)
device_frame = tk.Frame(device_canvas, bg="black")
device_canvas.create_window((0, 0), window=device_frame, anchor="nw")

def on_device_frame_configure(event):
    device_canvas.configure(scrollregion=device_canvas.bbox("all"))

device_frame.bind("<Configure>", on_device_frame_configure)

def _on_mousewheel(event):
    device_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

device_canvas.bind_all("<MouseWheel>", _on_mousewheel)

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
                font=("Arial", 10),
                anchor="w"
            ).pack(fill="x", padx=5)
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
        log(dev, "MOT", msg)
        handle_mot_message(ip, msg)

def handle_mot_message(ip, msg):
    with lock:
        dev = devices[ip]
    if msg.endswith("PRESS_START_SESSION_ACK"):
        dev["session_start"] = time.monotonic()
        send_udp(ip, "PRESS_1")
        threading.Thread(target=delayed_stop, args=(ip,), daemon=True).start()
    elif msg.endswith("PRESS_STOP_SESSION_ACK"):
        if dev["session_start"]:
            elapsed = time.monotonic() - dev["session_start"]
            dev["measured"] = elapsed
            threshold = SESSION_THRESHOLDS[dev["duration"]]
            dev["result"] = "PASS" if elapsed <= threshold else "FAIL"
            dev["session_start"] = None
            schedule_ui(update_device_display)

def send_udp(ip, message):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(message.encode(), (ip, SEND_PORT))
    with lock:
        dev = devices[ip]
    log(dev, "PI", message)

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
    for ip in list(devices.keys()):
        send_udp(ip, "PRESS_START_SESSION")

def find_latest_firmware():
    pattern = re.compile(r"^mot-1\.0\.\d+\.bin$")
    candidates = []
    for fname in os.listdir(FIRMWARE_DIR):
        if pattern.match(fname):
            version_str = fname.replace("mot-", "").replace(".bin", "")
            candidates.append((Version(version_str), fname))
    if not candidates:
        raise FileNotFoundError("No firmware found")
    candidates.sort(key=lambda x: x[0])
    return os.path.join(FIRMWARE_DIR, candidates[-1][1])


def flash_device():
    def run_flash():
        try:
            set_flash_status("IN PROGRESS")
            fw = find_latest_firmware()
            cmd = [
                "/home/cal/esp-env/bin/python", "-m", "esptool",
                "--chip", "esp32s3",
                "--port", "/dev/ttyACM0",
                "--baud", "921600",
                "write-flash",
                "0x0", os.path.join(FIRMWARE_DIR, "mot-firmware.ino.bootloader.bin"),
                "0x8000", os.path.join(FIRMWARE_DIR, "mot-firmware.ino.partitions.bin"),
                "0xe000", os.path.join(FIRMWARE_DIR, "boot_app0.bin"),
                "0x10000", fw,
            ]
            rc = subprocess.call(cmd)
            set_flash_status("SUCCESS" if rc == 0 else "FAILED")
        except Exception as e:
            print("Flash error:", e)
            set_flash_status("FAILED")
    threading.Thread(target=run_flash, daemon=True).start()

tk.Label(root, textvariable=device_count_var, fg="white", bg="black").pack()
flash_status_label = tk.Label(root, textvariable=flash_status_var, fg="yellow", bg="black", font=("Arial", 12, "bold"))
flash_status_label.pack(pady=2)
tk.Button(root, text="5 SECOND CALIBRATION", font=("Arial", 14), width=25, command=lambda: calibrate_all(5.0)).pack(pady=3)
tk.Button(root, text=f"RAISE PIN FOR {PULSE_TIME} SECOND", font=("Arial", 14), width=25, command=lambda: threading.Thread(target=lambda: (GPIO.output(OUTPUT_PIN, GPIO.HIGH), time.sleep(PULSE_TIME), GPIO.output(OUTPUT_PIN, GPIO.LOW)), daemon=True).start()).pack(pady=3)
flash_btn = tk.Button(root, text="FLASH DEVICE", font=("Arial", 14), width=25, command=flash_device)
flash_btn.pack(pady=3)
threading.Thread(target=listen_udp, daemon=True).start()
root.after(50, process_ui_queue)
root.mainloop()
