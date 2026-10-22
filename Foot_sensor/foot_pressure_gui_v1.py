import time
import threading
import queue
from collections import deque

import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# 6 Hz Butterworth low-pass (requires scipy)
from scipy.signal import butter, sosfilt, sosfilt_zi

# ================= 可調整設定 =================
BAUD_RATE = 115200
FRAME_LENGTH = 39
HISTORY_SIZE = 600
DEFAULT_ALPHA = 0.10
DEFAULT_KALMAN_Q = 100.0
DEFAULT_KALMAN_R = 1000.0
DEFAULT_SAMPLE_RATE_HZ = 50.0       # 左、右腳各自的更新頻率
DEFAULT_TOTAL_SAMPLE_RATE_HZ = 100.0 # 左右腳交錯封包時，雙腳總和約每秒更新 100 次
DEFAULT_LOWPASS_CUTOFF_HZ = 6.0
DEFAULT_Y_MAX = 75000
# ==============================================

def calculate_checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def parse_foot_data(frame):
    """依照舊版 realtime_foot_sensor.py 的 AA + 39 bytes 封包格式解析。"""
    if len(frame) != FRAME_LENGTH or frame[0] != 0xAA:
        return None
    if calculate_checksum(frame[:38]) != frame[38]:
        return None
    foot_id = frame[1]
    if foot_id == 0x01:
        side = "L"
    elif foot_id == 0x02:
        side = "R"
    else:
        return None
    points = [(frame[2 + i * 2] << 8) | frame[3 + i * 2] for i in range(18)]
    return {"side": side, "points": points, "total": sum(points)}

class KalmanFilter1D:
    """一維、近似常數狀態的 Kalman filter。Q 越大越跟得上變化；R 越大越平滑。"""
    def __init__(self, q=DEFAULT_KALMAN_Q, r=DEFAULT_KALMAN_R, initial_p=1000.0):
        self.q = float(q)
        self.r = float(r)
        self.initial_p = float(initial_p)
        self.reset()

    def reset(self):
        self.p = self.initial_p
        self.x = None

    def set_parameters(self, q, r):
        self.q = float(q)
        self.r = float(r)
        self.reset()

    def update(self, measurement):
        z = float(measurement)
        if self.x is None:
            self.x = z
            return self.x
        self.p = self.p + self.q
        k = self.p / (self.p + self.r)
        self.x = self.x + k * (z - self.x)
        self.p = (1.0 - k) * self.p
        return self.x


class ButterworthLowPass1D:
    """即時二階 Butterworth 低通；逐筆更新，保留濾波器內部狀態。"""
    def __init__(self, cutoff_hz=DEFAULT_LOWPASS_CUTOFF_HZ,
                 sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ, order=2):
        self.cutoff_hz = float(cutoff_hz)
        self.sample_rate_hz = float(sample_rate_hz)
        self.order = int(order)
        if not 0 < self.cutoff_hz < self.sample_rate_hz / 2:
            raise ValueError("截止頻率必須介於 0 與 Nyquist 頻率（取樣率的一半）之間")
        self.sos = butter(self.order, self.cutoff_hz, btype="low",
                          fs=self.sample_rate_hz, output="sos")
        self.reset()

    def reset(self):
        self.zi = sosfilt_zi(self.sos) * 0.0
        self.initialized = False

    def update(self, measurement):
        value = float(measurement)
        if not self.initialized:
            self.zi = sosfilt_zi(self.sos) * value
            self.initialized = True
        output, self.zi = sosfilt(self.sos, [value], zi=self.zi)
        return float(output[0])


class LiveFilterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("足底感測器即時波型比較（Raw / EMA / Kalman / 6 Hz Low-pass）")
        self.root.geometry("1150x800")
        self.root.minsize(900, 650)

        self.ser = None
        self.running = False
        self.reader_thread = None
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.buffer = bytearray()
        self.start_time = None
        self.last_L = 0.0
        self.last_R = 0.0
        self.filtered = {"L": None, "R": None, "Total": None}
        self.kalman = {key: KalmanFilter1D() for key in ("L", "R", "Total")}
        self.kalman_filtered = {"L": None, "R": None, "Total": None}
        self.lowpass = {
            "L": ButterworthLowPass1D(sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ),
            "R": ButterworthLowPass1D(sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ),
            "Total": ButterworthLowPass1D(sample_rate_hz=DEFAULT_TOTAL_SAMPLE_RATE_HZ),
        }
        self.lowpass_filtered = {"L": None, "R": None, "Total": None}
        self.data = {
            "time": deque(maxlen=HISTORY_SIZE),
            "L_raw": deque(maxlen=HISTORY_SIZE),
            "R_raw": deque(maxlen=HISTORY_SIZE),
            "Total_raw": deque(maxlen=HISTORY_SIZE),
            "L_filt": deque(maxlen=HISTORY_SIZE),
            "R_filt": deque(maxlen=HISTORY_SIZE),
            "Total_filt": deque(maxlen=HISTORY_SIZE),
            "L_kalman": deque(maxlen=HISTORY_SIZE),
            "R_kalman": deque(maxlen=HISTORY_SIZE),
            "Total_kalman": deque(maxlen=HISTORY_SIZE),
            "L_lowpass": deque(maxlen=HISTORY_SIZE),
            "R_lowpass": deque(maxlen=HISTORY_SIZE),
            "Total_lowpass": deque(maxlen=HISTORY_SIZE),
        }
        self.valid_frames = 0
        self.bad_frames = 0
        self.non_frame_bytes = 0

        self._build_ui()
        self.refresh_ports()
        self.root.after(50, self.process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="COM Port：").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, state="readonly", width=12)
        self.port_box.pack(side="left", padx=5)
        ttk.Button(top, text="重新掃描", command=self.refresh_ports).pack(side="left", padx=4)
        self.connect_btn = ttk.Button(top, text="連線", command=self.toggle_connection)
        self.connect_btn.pack(side="left", padx=4)
        self.status_var = tk.StringVar(value="未連線")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=12)

        ttk.Label(top, text="顯示訊號：").pack(side="left", padx=(16, 2))
        self.signal_var = tk.StringVar(value="雙腳總和")
        self.signal_box = ttk.Combobox(top, textvariable=self.signal_var, state="readonly",
                                       values=["左腳", "右腳", "雙腳總和"], width=10)
        self.signal_box.pack(side="left")
        self.signal_box.bind("<<ComboboxSelected>>", lambda _e: self.update_plot())

        ttk.Label(top, text="EMA α：").pack(side="left", padx=(14, 2))
        self.alpha_var = tk.DoubleVar(value=DEFAULT_ALPHA)
        self.alpha_scale = ttk.Scale(top, from_=0.01, to=1.0, variable=self.alpha_var,
                                     command=lambda _v: self.alpha_label_var.set(f"{self.alpha_var.get():.2f}"))
        self.alpha_scale.pack(side="left", fill="x", expand=True, padx=4)
        self.alpha_label_var = tk.StringVar(value=f"{DEFAULT_ALPHA:.2f}")
        ttk.Label(top, textvariable=self.alpha_label_var, width=5).pack(side="left")

        ttk.Label(top, text="Kalman Q：").pack(side="left", padx=(12, 2))
        self.kalman_q_var = tk.StringVar(value=str(DEFAULT_KALMAN_Q))
        ttk.Entry(top, textvariable=self.kalman_q_var, width=7).pack(side="left")
        ttk.Label(top, text="R：").pack(side="left", padx=(5, 2))
        self.kalman_r_var = tk.StringVar(value=str(DEFAULT_KALMAN_R))
        ttk.Entry(top, textvariable=self.kalman_r_var, width=7).pack(side="left")
        ttk.Button(top, text="套用 Q/R", command=self.apply_kalman_parameters).pack(side="left", padx=5)

        stats = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        stats.pack(fill="x")
        self.raw_value_var = tk.StringVar(value="Raw：—")
        self.filtered_value_var = tk.StringVar(value="Filtered：—")
        self.packet_var = tk.StringVar(value="有效封包：0｜錯誤封包：0")
        ttk.Label(stats, textvariable=self.raw_value_var, font=("Arial", 12, "bold")).pack(side="left", padx=(0, 20))
        ttk.Label(stats, textvariable=self.filtered_value_var, font=("Arial", 12, "bold")).pack(side="left", padx=(0, 20))
        ttk.Label(stats, textvariable=self.packet_var).pack(side="right")

        chart_box = ttk.LabelFrame(self.root, text="即時波型：原始訊號與濾波訊號", padding=8)
        chart_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.fig = Figure(figsize=(9, 5.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Raw sensor total (uncalibrated)")
        self.ax.set_title("Waiting for valid AA packets...")
        self.ax.grid(True, linestyle="--", alpha=0.35)
        self.raw_line, = self.ax.plot([], [], label="Raw", linewidth=0.8)
        self.filtered_line, = self.ax.plot([], [], label="EMA filtered", linewidth=0.8)
        self.kalman_line, = self.ax.plot([], [], label="Kalman filtered", linewidth=0.8)
        self.lowpass_line, = self.ax.plot([], [], label="Butterworth low-pass 6 Hz", linewidth=0.8)
        self.ax.legend(loc="upper right")
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_box)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        # 各波型獨立顯示/隱藏控制
        visibility_box = ttk.Frame(chart_box, padding=(4, 6, 4, 0))
        visibility_box.pack(fill="x")
        self.show_raw_var = tk.BooleanVar(value=True)
        self.show_ema_var = tk.BooleanVar(value=True)
        self.show_kalman_var = tk.BooleanVar(value=True)
        self.show_lowpass_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(
            visibility_box, text="顯示 Raw", variable=self.show_raw_var,
            command=self.update_visibility
        ).pack(side="left", padx=(4, 12))
        ttk.Checkbutton(
            visibility_box, text="顯示 EMA", variable=self.show_ema_var,
            command=self.update_visibility
        ).pack(side="left", padx=12)
        ttk.Checkbutton(
            visibility_box, text="顯示 Kalman", variable=self.show_kalman_var,
            command=self.update_visibility
        ).pack(side="left", padx=12)
        ttk.Checkbutton(
            visibility_box, text="顯示 6 Hz 低通", variable=self.show_lowpass_var,
            command=self.update_visibility
        ).pack(side="left", padx=12)

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.info_var = tk.StringVar(value="請選擇 COM Port 並連線。封包格式：AA 開頭、39 bytes、checksum。Q/R 是 Kalman 參數；低通為二階 Butterworth、截止頻率 6 Hz；左右腳各 50 Hz、雙腳總和約 100 Hz。")
        ttk.Label(bottom, textvariable=self.info_var).pack(side="left")

    def update_visibility(self):
        """依勾選狀態獨立顯示/隱藏波型；資料仍持續接收與濾波。"""
        self.raw_line.set_visible(self.show_raw_var.get())
        self.filtered_line.set_visible(self.show_ema_var.get())
        self.kalman_line.set_visible(self.show_kalman_var.get())
        self.lowpass_line.set_visible(self.show_lowpass_var.get())
        self.canvas.draw_idle()

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])
        elif not ports:
            self.port_var.set("")
            self.status_var.set("找不到 COM Port")

    def toggle_connection(self):
        if self.running:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("提示", "請先選擇藍牙接收器的 COM Port。")
            return
        try:
            self.ser = serial.Serial(port, BAUD_RATE, timeout=0.1)
        except Exception as exc:
            messagebox.showerror("連線失敗", f"無法開啟 {port}\\n\\n{exc}")
            return

        self.running = True
        self.buffer.clear()
        self.start_time = None
        self.last_L = self.last_R = 0.0
        self.filtered = {"L": None, "R": None, "Total": None}
        self.kalman_filtered = {"L": None, "R": None, "Total": None}
        self.lowpass_filtered = {"L": None, "R": None, "Total": None}
        for filt in self.lowpass.values():
            filt.reset()
        for filt in self.kalman.values():
            filt.reset()
        for values in self.data.values():
            values.clear()
        self.valid_frames = self.bad_frames = self.non_frame_bytes = 0
        self.connect_btn.config(text="斷線")
        self.status_var.set(f"已連線：{port}，等待有效封包…")
        self.reader_thread = threading.Thread(target=self.serial_reader, daemon=True)
        self.reader_thread.start()

    def disconnect(self):
        self.running = False
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.connect_btn.config(text="連線")
        self.status_var.set("未連線")

    def serial_reader(self):
        while self.running and self.ser is not None:
            try:
                chunk = self.ser.read(max(1, self.ser.in_waiting))
                if chunk:
                    self.q.put(("bytes", chunk))
            except Exception as exc:
                if self.running:
                    self.q.put(("error", str(exc)))
                break

    def process_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "error":
                    self.info_var.set("序列埠錯誤：" + payload)
                    self.disconnect()
                    break
                self.buffer.extend(payload)
                self._parse_buffer()
        except queue.Empty:
            pass
        self.update_plot()
        self.root.after(50, self.process_queue)

    def _parse_buffer(self):
        while True:
            try:
                start_idx = self.buffer.index(0xAA)
            except ValueError:
                self.non_frame_bytes += len(self.buffer)
                self.buffer.clear()
                return

            if start_idx:
                self.non_frame_bytes += start_idx
                del self.buffer[:start_idx]
            if len(self.buffer) < FRAME_LENGTH:
                return

            frame = bytes(self.buffer[:FRAME_LENGTH])
            result = parse_foot_data(frame)
            if result is None:
                self.bad_frames += 1
                # 往後移一個 byte，重新尋找可能的 AA 起點，避免錯位後丟失封包
                del self.buffer[0]
                continue

            del self.buffer[:FRAME_LENGTH]
            self.valid_frames += 1
            if self.start_time is None:
                self.start_time = time.monotonic()
            elapsed = time.monotonic() - self.start_time

            side = result["side"]
            # STM32 左右腳交錯傳送：每個腳別只在自己的封包到達時更新自己的濾波器。
            if side == "L":
                self.last_L = float(result["total"])
            else:
                self.last_R = float(result["total"])

            raw_values = {"L": self.last_L, "R": self.last_R, "Total": self.last_L + self.last_R}
            alpha = float(self.alpha_var.get())

            # 單腳資料各自約 50 Hz：只更新這次真正收到封包的那隻腳。
            side_raw = raw_values[side]
            old = self.filtered[side]
            self.filtered[side] = side_raw if old is None else alpha * side_raw + (1.0 - alpha) * old
            self.kalman_filtered[side] = self.kalman[side].update(side_raw)
            self.lowpass_filtered[side] = self.lowpass[side].update(side_raw)

            # 雙腳總和每收到一個交錯封包就更新一次，名目更新率約 100 Hz。
            total_raw = raw_values["Total"]
            old_total = self.filtered["Total"]
            self.filtered["Total"] = total_raw if old_total is None else alpha * total_raw + (1.0 - alpha) * old_total
            self.kalman_filtered["Total"] = self.kalman["Total"].update(total_raw)
            self.lowpass_filtered["Total"] = self.lowpass["Total"].update(total_raw)

            # 感測器總值不應為負；只對顯示/終端輸出做下限限制，保留內部原始濾波狀態。
            total_lowpass_display = max(0.0, self.lowpass_filtered["Total"])
            print(f"LP6Hz Total: {total_lowpass_display:.1f}", flush=True)

            # 每收到一個有效腳別封包就記錄當下左右腳最新狀態。
            # LP6Hz 曲線顯示時將不合理的負總值限制為 0，但濾波器內部狀態不做截斷。
            with self.lock:
                self.data["time"].append(elapsed)
                for key, raw in raw_values.items():
                    self.data[f"{key}_raw"].append(raw)
                    self.data[f"{key}_filt"].append(self.filtered[key])
                    self.data[f"{key}_kalman"].append(self.kalman_filtered[key])
                    lowpass_display = max(0.0, self.lowpass_filtered[key]) if self.lowpass_filtered[key] is not None else 0.0
                    self.data[f"{key}_lowpass"].append(lowpass_display)

    def apply_kalman_parameters(self):
        try:
            q = float(self.kalman_q_var.get())
            r = float(self.kalman_r_var.get())
            if q <= 0 or r <= 0:
                raise ValueError("Q 和 R 必須大於 0")
        except ValueError:
            messagebox.showwarning("參數錯誤", "Q 和 R 請輸入大於 0 的數字。")
            return
        for filt in self.kalman.values():
            filt.set_parameters(q, r)
        self.kalman_filtered = {"L": None, "R": None, "Total": None}
        # 清除 Kalman 歷史，避免把不同參數的曲線接在一起
        for key in ("L", "R", "Total"):
            self.data[f"{key}_kalman"].clear()
        self.info_var.set(f"已套用 Kalman 參數：Q={q:g}, R={r:g}；Kalman 曲線已重置。")

    def update_plot(self):
        signal_map = {"左腳": "L", "右腳": "R", "雙腳總和": "Total"}
        key = signal_map.get(self.signal_var.get(), "Total")
        with self.lock:
            xs = list(self.data["time"])
            raw = list(self.data[f"{key}_raw"])
            filt = list(self.data[f"{key}_filt"])
            kalman = list(self.data[f"{key}_kalman"])
            lowpass = list(self.data[f"{key}_lowpass"])
        self.packet_var.set(f"有效封包：{self.valid_frames}｜checksum/格式錯誤：{self.bad_frames}｜非封包位元組：{self.non_frame_bytes}")
        if not xs:
            self.ax.set_title("等待有效 AA 封包…（請確認封包長度、腳別 ID 與 checksum）")
            self.canvas.draw_idle()
            return
        self.raw_line.set_data(xs, raw)
        self.filtered_line.set_data(xs, filt)
        # 套用 Q/R 後 Kalman 歷史可能被清空；此時用最近時間點對齊顯示。
        k_count = min(len(xs), len(kalman))
        k_xs = xs[-k_count:] if k_count else []
        self.kalman_line.set_data(k_xs, kalman[-k_count:] if k_count else [])
        lp_count = min(len(xs), len(lowpass))
        lp_xs = xs[-lp_count:] if lp_count else []
        self.lowpass_line.set_data(lp_xs, lowpass[-lp_count:] if lp_count else [])
        self.ax.set_title(
            f"{self.signal_var.get()}：Raw / EMA(α={self.alpha_var.get():.2f}) / "
            f"Kalman(Q={self.kalman_q_var.get()}, R={self.kalman_r_var.get()}) / 6 Hz Low-pass"
        )
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Raw sensor total (uncalibrated)")
        latest = xs[-1]
        self.ax.set_xlim(max(0, latest - 10), max(10, latest + 0.2))
        all_y = raw + filt + kalman + lowpass
        if all_y:
            ymin, ymax = min(all_y), max(all_y)
            pad = max(100, (ymax - ymin) * 0.15)
            self.ax.set_ylim(max(0, ymin - pad), ymax + pad if ymax > 0 else 1000)
        self.ax.grid(True, linestyle="--", alpha=0.35)
        self.raw_value_var.set(f"Raw：{raw[-1]:,.0f}")
        k_latest = kalman[-1] if kalman else float("nan")
        lp_latest = lowpass[-1] if lowpass else float("nan")
        self.filtered_value_var.set(f"EMA：{filt[-1]:,.1f}｜Kalman：{k_latest:,.1f}｜LP6Hz：{lp_latest:,.1f}")
        self.status_var.set(f"已連線：{self.port_var.get()}｜已解析 {self.valid_frames} 個封包")
        self.canvas.draw_idle()

    def close(self):
        self.disconnect()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    app = LiveFilterGUI(root)
    root.mainloop()
