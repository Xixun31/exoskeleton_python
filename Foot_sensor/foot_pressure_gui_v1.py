import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
from collections import deque

import serial
import serial.tools.list_ports
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

BAUDRATE = 115200
MAX_POINTS = 300
G_TO_N = 9.80665 / 1000.0
BASELINE_DURATION = 5.0  # 秒


class FootPressureGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("STM32 足底壓力監測 - 第一版（含靜止平均記錄）")
        self.root.geometry("1100x780")
        self.root.minsize(900, 700)

        self.ser = None
        self.running = False
        self.reader_thread = None
        self.q = queue.Queue()

        self.left_g = 0.0
        self.right_g = 0.0
        self.left_hist = deque(maxlen=MAX_POINTS)
        self.right_hist = deque(maxlen=MAX_POINTS)
        self.total_hist = deque(maxlen=MAX_POINTS)
        self.time_hist = deque(maxlen=MAX_POINTS)

        self.start_time = None
        self.packet_count = 0
        self.bad_count = 0

        # --- 靜止平均記錄用的狀態 ---
        self.baseline_recording = False
        self.baseline_samples = []  # 每筆為 (left_g, right_g)
        self.baseline_start = None

        self.build_gui()
        self.refresh_ports()
        self.root.after(50, self.process_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_gui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="COM Port：").pack(side="left")

        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(
            top, textvariable=self.port_var,
            state="readonly", width=15
        )
        self.port_box.pack(side="left", padx=5)

        ttk.Button(top, text="重新掃描",
                   command=self.refresh_ports).pack(side="left", padx=5)

        self.connect_btn = ttk.Button(
            top, text="連線", command=self.toggle_connection
        )
        self.connect_btn.pack(side="left", padx=5)

        self.status_var = tk.StringVar(value="未連線")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=15)

        self.packet_var = tk.StringVar(value="DATA：0")
        ttk.Label(top, textvariable=self.packet_var).pack(side="right")

        cards = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        cards.pack(fill="x")

        self.left_card = self.make_card(cards, "左腳總量")
        self.left_card.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.right_card = self.make_card(cards, "右腳總量")
        self.right_card.pack(side="left", fill="both", expand=True, padx=5)

        self.total_card = self.make_card(cards, "雙腳總量")
        self.total_card.pack(side="left", fill="both", expand=True, padx=(5, 0))

        # --- 靜止平均記錄區塊 ---
        baseline_box = ttk.LabelFrame(
            self.root, text="靜止平均記錄", padding=8
        )
        baseline_box.pack(fill="x", padx=10, pady=(0, 10))

        self.baseline_btn = ttk.Button(
            baseline_box, text=f"記錄{BASELINE_DURATION:.0f}秒平均",
            command=self.start_baseline_capture
        )
        self.baseline_btn.pack(side="left", padx=(0, 10))

        self.baseline_result_var = tk.StringVar(value="尚未記錄")
        ttk.Label(
            baseline_box, textvariable=self.baseline_result_var,
            font=("Arial", 11)
        ).pack(side="left")

        chart_box = ttk.LabelFrame(
            self.root, text="即時總量曲線", padding=8
        )
        chart_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.fig = Figure(figsize=(8, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Left / Right / Total")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Total (g)")
        self.ax.grid(True, alpha=0.3)

        self.left_line, = self.ax.plot([], [], label="Left")
        self.right_line, = self.ax.plot([], [], label="Right")
        self.total_line, = self.ax.plot([], [], label="Total")
        self.ax.legend()

        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_box)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.info_var = tk.StringVar(value="等待 STM32 DATA...")
        ttk.Label(bottom, textvariable=self.info_var).pack(side="left")

    def make_card(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        frame.g_var = tk.StringVar(value="0 g")
        frame.n_var = tk.StringVar(value="0.00 N")

        ttk.Label(
            frame, textvariable=frame.g_var,
            font=("Arial", 24, "bold")
        ).pack(pady=(5, 2))

        ttk.Label(
            frame, textvariable=frame.n_var,
            font=("Arial", 14)
        ).pack(pady=(0, 5))

        return frame

    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_box["values"] = ports
        if ports:
            if self.port_var.get() not in ports:
                self.port_var.set(ports[0])
        else:
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
            messagebox.showwarning("提示", "請先選擇 STM32 的 COM Port。")
            return

        try:
            self.ser = serial.Serial(
                port=port, baudrate=BAUDRATE, timeout=0.2
            )
        except Exception as e:
            messagebox.showerror("連線失敗", f"無法開啟 {port}\n\n{e}")
            return

        self.running = True
        self.connect_btn.config(text="斷線")
        self.status_var.set(f"已連線：{port}")

        self.left_g = 0.0
        self.right_g = 0.0
        self.left_hist.clear()
        self.right_hist.clear()
        self.total_hist.clear()
        self.time_hist.clear()
        self.start_time = time.time()
        self.packet_count = 0
        self.bad_count = 0

        # 重新連線時，若正在記錄靜止平均，一併取消
        self.baseline_recording = False
        self.baseline_samples = []
        self.baseline_btn.config(state="normal", text=f"記錄{BASELINE_DURATION:.0f}秒平均")

        self.reader_thread = threading.Thread(
            target=self.serial_reader, daemon=True
        )
        self.reader_thread.start()

    def disconnect(self):
        self.running = False
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connect_btn.config(text="連線")
        self.status_var.set("未連線")

        # 斷線時若正在記錄，一併取消
        self.baseline_recording = False
        self.baseline_btn.config(state="normal", text=f"記錄{BASELINE_DURATION:.0f}秒平均")

    def serial_reader(self):
        while self.running and self.ser is not None:
            try:
                raw = self.ser.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="ignore").strip()
                if line:
                    self.q.put(line)
            except Exception as e:
                if self.running:
                    self.q.put("__ERROR__:" + str(e))
                break

    def process_queue(self):
        for _ in range(100):
            try:
                line = self.q.get_nowait()
            except queue.Empty:
                break

            if line.startswith("__ERROR__:"):
                self.info_var.set(line)
                self.root.after(0, self.disconnect)
                break

            self.parse_data(line)

        self.update_gui()
        self.root.after(50, self.process_queue)

    def parse_data(self, line):
        if not line.startswith("DATA,"):
            return

        fields = line.split(",")

        # DATA,Foot,time_ms,P1..P18,Total_g,COP_valid,COP_X,COP_Y
        if len(fields) < 25:
            self.bad_count += 1
            return

        try:
            foot = fields[1].strip().upper()
            total_g = float(fields[21])
            cop_valid = int(float(fields[22]))
            if cop_valid:
                cop_x = float(fields[23])
                cop_y = float(fields[24])
            else:
                cop_x = cop_y = None
        except (ValueError, IndexError):
            self.bad_count += 1
            return

        if foot not in ("L", "R"):
            self.bad_count += 1
            return

        if foot == "L":
            self.left_g = total_g
        else:
            self.right_g = total_g

        self.packet_count += 1

        elapsed = time.time() - self.start_time
        self.time_hist.append(elapsed)
        self.left_hist.append(self.left_g)
        self.right_hist.append(self.right_g)
        self.total_hist.append(self.left_g + self.right_g)

        # --- 若正在記錄靜止平均，把當下的左右腳讀值存起來 ---
        if self.baseline_recording:
            self.baseline_samples.append((self.left_g, self.right_g))

        if cop_valid:
            cop_text = f"COP=({cop_x:.1f}, {cop_y:.1f}) mm"
        else:
            cop_text = "COP invalid"

        self.info_var.set(
            f"目前資料：{foot}腳 | {cop_text}"
        )

    def start_baseline_capture(self):
        if not self.running:
            messagebox.showwarning("提示", "請先連線 STM32 再開始記錄。")
            return
        if self.baseline_recording:
            return  # 記錄中，忽略重複點擊

        self.baseline_recording = True
        self.baseline_samples = []
        self.baseline_start = time.time()
        self.baseline_btn.config(state="disabled")
        self.baseline_result_var.set("記錄中，請保持靜止不動...")
        self.root.after(100, self.update_baseline_progress)

    def update_baseline_progress(self):
        if not self.baseline_recording:
            return

        elapsed = time.time() - self.baseline_start
        if elapsed >= BASELINE_DURATION:
            self.finish_baseline_capture()
            return

        remaining = BASELINE_DURATION - elapsed
        self.baseline_result_var.set(f"記錄中，請保持靜止不動... 剩餘 {remaining:.1f} 秒")
        self.root.after(100, self.update_baseline_progress)

    def finish_baseline_capture(self):
        self.baseline_recording = False
        self.baseline_btn.config(state="normal")

        if self.baseline_samples:
            lefts = [s[0] for s in self.baseline_samples]
            rights = [s[1] for s in self.baseline_samples]
            totals = [l + r for l, r in self.baseline_samples]

            avg_left = sum(lefts) / len(lefts)
            avg_right = sum(rights) / len(rights)
            avg_total = sum(totals) / len(totals)

            self.baseline_result_var.set(
                f"5秒平均 → 左腳：{avg_left:,.0f} g　右腳：{avg_right:,.0f} g　"
                f"總力：{avg_total:,.0f} g　（樣本數：{len(self.baseline_samples)}）"
            )
        else:
            self.baseline_result_var.set("5秒內沒有收到任何有效資料，請確認連線後再試一次")

    def update_gui(self):
        left_n = self.left_g * G_TO_N
        right_n = self.right_g * G_TO_N
        total_g = self.left_g + self.right_g
        total_n = total_g * G_TO_N

        self.left_card.g_var.set(f"{self.left_g:,.0f} g")
        self.left_card.n_var.set(f"{left_n:,.2f} N")

        self.right_card.g_var.set(f"{self.right_g:,.0f} g")
        self.right_card.n_var.set(f"{right_n:,.2f} N")

        self.total_card.g_var.set(f"{total_g:,.0f} g")
        self.total_card.n_var.set(f"{total_n:,.2f} N")

        self.packet_var.set(
            f"DATA：{self.packet_count}   錯誤：{self.bad_count}"
        )

        if self.time_hist:
            x = list(self.time_hist)
            self.left_line.set_data(x, list(self.left_hist))
            self.right_line.set_data(x, list(self.right_hist))
            self.total_line.set_data(x, list(self.total_hist))

            self.ax.relim()
            self.ax.autoscale_view()
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

    app = FootPressureGUI(root)
    root.mainloop()