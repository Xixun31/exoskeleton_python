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
MAX_POINTS = 2000
G_TO_N = 9.80665 / 1000.0
COUNTDOWN_SECONDS = 3.0  # 開始正式紀錄前倒數 3 秒

# 測試時間拉長：原本到 60 秒，現在延伸到 180 秒，中間的檢查點也加密
RECORD_TARGETS = (5.0, 10.0, 20.0, 30.0, 60.0, 90.0, 120.0, 180.0)
BASELINE_DURATION = max(RECORD_TARGETS)


class FootPressureGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"STM32 足底壓力監測 - {BASELINE_DURATION:.0f} 秒定點紀錄")
        self.root.geometry("1150x820")
        self.root.minsize(950, 740)

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
        self.baseline_countdown = False
        self.baseline_start = None
        self.baseline_countdown_end = None
        self.baseline_duration = BASELINE_DURATION
        self.record_targets = list(RECORD_TARGETS)
        self.record_results = []  # (target_s, actual_s, left_g, right_g, total_g)
        self.next_record_index = 0

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

        # --- 定點紀錄區塊 ---
        baseline_box = ttk.LabelFrame(
            self.root, text=f"{BASELINE_DURATION:.0f} 秒定點紀錄（漂移測試）", padding=8
        )
        baseline_box.pack(fill="x", padx=10, pady=(0, 10))

        self.baseline_btn = ttk.Button(
            baseline_box, text=f"開始 {BASELINE_DURATION:.0f} 秒紀錄",
            command=self.start_baseline_capture
        )
        self.baseline_btn.pack(side="left", padx=(0, 10))

        self.countdown_var = tk.StringVar(value="")
        ttk.Label(
            baseline_box, textvariable=self.countdown_var,
            font=("Arial", 13, "bold")
        ).pack(side="left", padx=(0, 10))

        self.baseline_result_var = tk.StringVar(value="尚未開始紀錄")
        ttk.Label(
            baseline_box, textvariable=self.baseline_result_var,
            font=("Arial", 11)
        ).pack(side="left")

        # 固定時間點的紀錄表，欄位加上「增量」跟「每秒漲幅」方便判斷何時打平
        record_table_box = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        record_table_box.pack(fill="x")

        columns = ("target", "actual", "left", "right", "total", "delta", "rate")
        self.record_tree = ttk.Treeview(
            record_table_box,
            columns=columns,
            show="headings",
            height=len(self.record_targets)
        )
        headings = {
            "target": "目標時間",
            "actual": "實際紀錄時間",
            "left": "左腳 (g)",
            "right": "右腳 (g)",
            "total": "雙腳總量 (g)",
            "delta": "與上次比增量 (g)",
            "rate": "每秒漲幅 (g/s)",
        }
        widths = {
            "target": 90,
            "actual": 110,
            "left": 110,
            "right": 110,
            "total": 130,
            "delta": 140,
            "rate": 120,
        }
        for col in columns:
            self.record_tree.heading(col, text=headings[col])
            self.record_tree.column(col, width=widths[col], anchor="center")
        self.record_tree.pack(fill="x")

        for target in self.record_targets:
            self.record_tree.insert(
                "", "end", iid=f"target_{int(target)}",
                values=(f"{target:g} 秒", "-", "-", "-", "-", "-", "-")
            )

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

        # 重新連線時，若正在倒數/紀錄，一併取消
        self.baseline_recording = False
        self.baseline_countdown = False
        self.record_results = []
        self.next_record_index = 0
        self.baseline_btn.config(state="normal", text=f"開始 {BASELINE_DURATION:.0f} 秒紀錄")
        self.countdown_var.set("")
        self.reset_record_table()

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

        # 斷線時若正在倒數/紀錄，一併取消
        self.baseline_recording = False
        self.baseline_countdown = False
        self.baseline_btn.config(state="normal", text=f"開始 {BASELINE_DURATION:.0f} 秒紀錄")
        self.countdown_var.set("")

    def reset_record_table(self):
        for target in self.record_targets:
            item_id = f"target_{int(target)}"
            if self.record_tree.exists(item_id):
                self.record_tree.item(
                    item_id,
                    values=(f"{target:g} 秒", "-", "-", "-", "-", "-", "-")
                )

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

        # 注意：定點紀錄不在這裡直接抓資料。
        # 由 update_baseline_progress() 在目標秒數到達時抓取當下最新值，
        # 這樣每個時間點只會紀錄一次。

        if cop_valid:
            cop_text = f"COP=({cop_x:.1f}, {cop_y:.1f}) mm"
        else:
            cop_text = "COP invalid"

        self.info_var.set(
            f"目前資料：{foot}腳 | {cop_text}"
        )

    def start_baseline_capture(self):
        if not self.running:
            messagebox.showwarning("提示", "請先連線 STM32 再開始紀錄。")
            return

        if self.baseline_recording or self.baseline_countdown:
            return

        # 每次開始前清空上一輪
        self.record_results = []
        self.next_record_index = 0
        self.reset_record_table()

        # 先倒數 3 秒；倒數時間不算進正式的測試時長
        self.baseline_countdown = True
        self.baseline_recording = False
        self.baseline_countdown_end = time.time() + COUNTDOWN_SECONDS

        self.baseline_btn.config(state="disabled")
        self.baseline_result_var.set("倒數中，請把砝碼放到指定位置並保持不動...")
        self.countdown_var.set(f"{COUNTDOWN_SECONDS:.0f}")

        self.root.after(50, self.update_baseline_progress)

    def update_baseline_progress(self):
        if not (self.baseline_countdown or self.baseline_recording):
            return

        now = time.time()

        # ---------- 倒數階段 ----------
        if self.baseline_countdown:
            remaining = self.baseline_countdown_end - now

            if remaining <= 0:
                self.baseline_countdown = False
                self.baseline_recording = True
                self.baseline_start = time.time()
                self.next_record_index = 0
                self.record_results = []

                self.countdown_var.set("開始")
                targets_str = "、".join(f"{t:g}" for t in self.record_targets)
                self.baseline_result_var.set(
                    f"開始 {BASELINE_DURATION:.0f} 秒紀錄：將在 {targets_str} 秒各記錄一次當下數值"
                )
                self.root.after(20, self.update_baseline_progress)
                return

            # 顯示 3、2、1
            countdown_number = int(remaining) + 1
            self.countdown_var.set(str(countdown_number))
            self.baseline_result_var.set(
                "倒數中，請把砝碼放到指定位置並保持不動..."
            )
            self.root.after(50, self.update_baseline_progress)
            return

        # ---------- 正式定點紀錄 ----------
        elapsed = now - self.baseline_start

        # 到達目標秒數時，直接抓取當下 GUI 最新的左右腳值，
        # 並計算跟上一個檢查點相比的增量、換算成每秒漲幅。
        while self.next_record_index < len(self.record_targets):
            target = self.record_targets[self.next_record_index]
            if elapsed < target:
                break

            left_g = self.left_g
            right_g = self.right_g
            total_g = left_g + right_g
            actual_elapsed = elapsed

            if self.record_results:
                prev_target, prev_actual, _, _, prev_total = self.record_results[-1]
                delta = total_g - prev_total
                dt = actual_elapsed - prev_actual
                rate = delta / dt if dt > 0 else 0.0
                delta_str = f"{delta:+,.0f}"
                rate_str = f"{rate:+.2f}"
            else:
                delta_str = "-"
                rate_str = "-"

            self.record_results.append(
                (target, actual_elapsed, left_g, right_g, total_g)
            )

            item_id = f"target_{int(target)}"
            self.record_tree.item(
                item_id,
                values=(
                    f"{target:g} 秒",
                    f"{actual_elapsed:.2f} 秒",
                    f"{left_g:,.0f}",
                    f"{right_g:,.0f}",
                    f"{total_g:,.0f}",
                    delta_str,
                    rate_str,
                )
            )

            self.next_record_index += 1

        # 所有時間點全部記錄完成後結束
        if self.next_record_index >= len(self.record_targets):
            self.finish_baseline_capture()
            return

        next_target = self.record_targets[self.next_record_index]
        remaining_to_target = max(0.0, next_target - elapsed)
        remaining_total = max(0.0, self.baseline_duration - elapsed)

        self.countdown_var.set(f"剩餘 {remaining_total:.1f} 秒")
        self.baseline_result_var.set(
            f"已完成 {len(self.record_results)}/{len(self.record_targets)} 筆，"
            f"下一筆：{next_target:g} 秒（還有 {remaining_to_target:.2f} 秒）"
        )
        self.root.after(20, self.update_baseline_progress)

    def finish_baseline_capture(self):
        self.baseline_recording = False
        self.baseline_countdown = False
        self.baseline_btn.config(state="normal", text=f"開始 {BASELINE_DURATION:.0f} 秒紀錄")
        self.countdown_var.set("完成")

        if self.record_results:
            summary = "；".join(
                f"{target:g}s: L={left_g:,.0f}g / R={right_g:,.0f}g / Total={total_g:,.0f}g"
                for target, actual_t, left_g, right_g, total_g in self.record_results
            )
            self.baseline_result_var.set(summary)

            # 額外提示最後一段的每秒漲幅，方便判斷是否已經打平
            if len(self.record_results) >= 2:
                prev = self.record_results[-2]
                last = self.record_results[-1]
                dt = last[1] - prev[1]
                drate = (last[4] - prev[4]) / dt if dt > 0 else 0.0
                tail_hint = f"（最後一段每秒漲幅：{drate:+.2f} g/s，越接近 0 代表越穩定）"
            else:
                tail_hint = ""

            self.info_var.set("定點紀錄完成：" + summary + tail_hint)
        else:
            self.baseline_result_var.set("沒有成功記錄到任何時間點")

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