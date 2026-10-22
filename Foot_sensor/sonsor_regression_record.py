import tkinter as tk
from tkinter import ttk, messagebox
import serial
import time
import numpy as np
import threading
from scipy.signal import butter, sosfilt, sosfilt_zi

# ================= 配置區 =================
COM_PORT = "COM6"      # 確保是你的官方藍牙接收器 Port
BAUD_RATE = 115200

# 6 Hz 二階 Butterworth 低通濾波設定
FILTER_CUTOFF_HZ = 6.0
FOOT_SAMPLE_RATE_HZ = 50.0  # 左腳、右腳各自約 50 Hz
CAPTURE_SECONDS = 3         # 姿勢穩定後，連續採集 3 秒
# ==========================================

class DataCollectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("足底感測器數據採集工具（6 Hz 低通濾波）")
        self.root.geometry("800x450") # 加寬視窗

        self.ser = None
        self.is_connected = False
        
        # 採集狀態
        self.is_collecting = False
        self.collected_left = []
        self.collected_right = []

        # 每隻腳的 18 個感測點各自使用同一組 6 Hz 低通濾波器。
        # 濾波器狀態在連續串流中保留，不會每次按下採集就重設。
        self.filter_sos = butter(
            2,
            FILTER_CUTOFF_HZ,
            btype="lowpass",
            fs=FOOT_SAMPLE_RATE_HZ,
            output="sos"
        )
        self.filter_zi = {"L": [None] * 18, "R": [None] * 18}

        self.setup_gui()
        self.connect_serial()

    def setup_gui(self):
        # 狀態顯示
        self.lbl_status = ttk.Label(self.root, text="狀態: 未連線", font=("Arial", 14))
        self.lbl_status.pack(pady=5)

        # 倒數計時顯示
        self.lbl_countdown = ttk.Label(self.root, text="", font=("Arial", 18, "bold"), foreground="red")
        self.lbl_countdown.pack(pady=5)

        # 採集按鈕
        self.btn_collect = ttk.Button(
            self.root,
            text="開始採集（倒數 3 秒＋記錄 3 秒平均）",
            command=self.start_collection
        )
        self.btn_collect.pack(pady=5, ipadx=20, ipady=10)

        ttk.Label(self.root, text="採集結果 (Tab分隔，請全選複製並直接貼上 Excel):").pack(anchor="w", padx=20)

        # 結果文字方塊與捲軸區 (關閉自動換行，加入 X, Y 捲軸)
        text_frame = ttk.Frame(self.root)
        text_frame.pack(padx=20, pady=5, fill=tk.BOTH, expand=True)
        
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.txt_result = tk.Text(
            text_frame,
            wrap=tk.NONE,
            xscrollcommand=x_scroll.set,
            yscrollcommand=y_scroll.set,
            state=tk.DISABLED  # 使用者不能直接修改或刪除標題與紀錄
        )
        self.txt_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        x_scroll.config(command=self.txt_result.xview)
        y_scroll.config(command=self.txt_result.yview)
        
        # 固定表頭 (L1~L18, R1~R18)，並鎖定文字框避免手動刪改
        cols = [f"L{i}" for i in range(1, 19)] + [f"R{i}" for i in range(1, 19)]
        header = "\t".join(cols) + "\n"
        self.txt_result.config(state=tk.NORMAL)
        self.txt_result.insert(tk.END, header)
        self.txt_result.config(state=tk.DISABLED)

    def calculate_checksum(self, data_bytes):
        return sum(data_bytes) & 0xFF

    def parse_foot_data(self, frame):
        # 檢查封包長度、開頭與 Checksum
        if len(frame) != 39 or frame[0] != 0xAA:
            return None
        if self.calculate_checksum(frame[:38]) != frame[38]:
            return None

        # 判斷左右腳
        foot_id = frame[1]
        if foot_id == 0x01:
            foot_side = "L"
        elif foot_id == 0x02:
            foot_side = "R"
        else:
            return None

        # 解析 18 點的 16-bit 數據
        points = [(frame[2 + i*2] << 8) | frame[3 + i*2] for i in range(18)]
        return {"side": foot_side, "points": points}

    def filter_foot_points(self, side, points):
        """對單腳 18 個感測點逐點套用連續式 6 Hz 低通濾波。"""
        filtered_points = []

        for i, raw_value in enumerate(points):
            zi = self.filter_zi[side][i]

            # 第一次收到該感測點資料時，以目前讀值初始化，減少起始突波。
            if zi is None:
                zi = sosfilt_zi(self.filter_sos) * float(raw_value)

            filtered, zi = sosfilt(
                self.filter_sos,
                [float(raw_value)],
                zi=zi
            )
            self.filter_zi[side][i] = zi
            filtered_points.append(float(filtered[0]))

        return filtered_points

    def connect_serial(self):
        try:
            self.ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
            self.is_connected = True
            self.lbl_status.config(text=f"狀態: 已連線至 {COM_PORT}")
            
            # 啟動背景接收 Thread
            threading.Thread(target=self.serial_reader_thread, daemon=True).start()
        except Exception as e:
            messagebox.showerror("連線錯誤", f"無法開啟 {COM_PORT}\n{e}")

    def serial_reader_thread(self):
        buffer = bytearray()
        while self.is_connected:
            if self.ser.in_waiting > 0:
                try:
                    buffer.extend(self.ser.read(self.ser.in_waiting))
                    
                    while b'\xaa' in buffer:
                        start_idx = buffer.index(0xAA)
                        
                        if len(buffer) - start_idx >= 39:
                            frame = buffer[start_idx : start_idx+39]
                            result = self.parse_foot_data(frame)
                            
                            if result:
                                side = result["side"]
                                # 無論目前是否在採集，都持續更新濾波器狀態。
                                filtered_points = self.filter_foot_points(
                                    side, result["points"]
                                )

                                if self.is_collecting:
                                    if side == "L":
                                        self.collected_left.append(filtered_points)
                                    elif side == "R":
                                        self.collected_right.append(filtered_points)
                                    
                            buffer = buffer[start_idx+39:]
                        else:
                            buffer = buffer[start_idx:]
                            break
                except Exception as e:
                    pass
            time.sleep(0.01)

    def start_collection(self):
        if not self.is_connected:
            messagebox.showwarning("警告", "請先確認藍牙已連線！")
            return
            
        self.btn_collect.config(state="disabled")
        self.countdown(3)

    def countdown(self, count):
        if count > 0:
            self.lbl_countdown.config(text=f"請保持姿態穩定... {count}")
            self.root.after(1000, self.countdown, count - 1)
        else:
            self.lbl_countdown.config(text="資料擷取中...")
            self.root.update()
            
            self.collected_left = []
            self.collected_right = []
            self.is_collecting = True
            
            # 收集連續 3 秒的濾波後資料，再計算各感測點平均值
            self.root.after(CAPTURE_SECONDS * 1000, self.finish_capture)

    def finish_capture(self):
        self.is_collecting = False
        
        if not self.collected_left or not self.collected_right:
            self.lbl_countdown.config(text="錯誤：未收到完整的左右腳數據！", foreground="red")
            self.btn_collect.config(state="normal")
            return
            
        # 計算 3 秒採集區間內，濾波後各感測點的平均值
        avg_left = np.mean(self.collected_left, axis=0)
        avg_right = np.mean(self.collected_right, axis=0)
        
        # 轉換為字串 (小數點 1 位)
        left_str = "\t".join([f"{val:.1f}" for val in avg_left])
        right_str = "\t".join([f"{val:.1f}" for val in avg_right])
        
        # 只輸出感測器數據：L1~L18、R1~R18，不包含 TrueWeight
        output_row = f"{left_str}\t{right_str}\n"
        
        # 暫時開啟文字框供程式追加資料，完成後重新鎖定
        self.txt_result.config(state=tk.NORMAL)
        self.txt_result.insert(tk.END, output_row)
        self.txt_result.see(tk.END)
        self.txt_result.config(state=tk.DISABLED)
        
        self.lbl_countdown.config(text="擷取完成！", foreground="green")
        self.btn_collect.config(state="normal")

    def on_closing(self):
        self.is_connected = False
        if self.ser:
            self.ser.close()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = DataCollectorGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()