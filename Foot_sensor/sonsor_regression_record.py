import tkinter as tk
from tkinter import ttk, messagebox
import serial
import time
import numpy as np
import threading

# ================= 配置區 =================
COM_PORT = "COM6"      # 確保是你的官方藍牙接收器 Port
BAUD_RATE = 115200
# ==========================================

class DataCollectorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("足底感測器 迴歸分析數據採集工具 (完美 Excel 版)")
        self.root.geometry("800x450") # 加寬視窗

        self.ser = None
        self.is_connected = False
        
        # 採集狀態
        self.is_collecting = False
        self.collected_left = []
        self.collected_right = []

        self.setup_gui()
        self.connect_serial()

    def setup_gui(self):
        # 狀態顯示
        self.lbl_status = ttk.Label(self.root, text="狀態: 未連線", font=("Arial", 14))
        self.lbl_status.pack(pady=5)

        # 真實重量輸入區
        weight_frame = ttk.Frame(self.root)
        weight_frame.pack(pady=5)
        ttk.Label(weight_frame, text="請輸入目前踩踏的真實重量 (kg): ", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
        self.entry_weight = ttk.Entry(weight_frame, width=10, font=("Arial", 12))
        self.entry_weight.pack(side=tk.LEFT)
        self.entry_weight.insert(0, "0") # 預設值

        # 倒數計時顯示
        self.lbl_countdown = ttk.Label(self.root, text="", font=("Arial", 18, "bold"), foreground="red")
        self.lbl_countdown.pack(pady=5)

        # 採集按鈕
        self.btn_collect = ttk.Button(self.root, text="開始採集 (倒數3秒)", command=self.start_collection)
        self.btn_collect.pack(pady=5, ipadx=20, ipady=10)

        ttk.Label(self.root, text="採集結果 (Tab分隔，請全選複製並直接貼上 Excel):").pack(anchor="w", padx=20)

        # 結果文字方塊與捲軸區 (關閉自動換行，加入 X, Y 捲軸)
        text_frame = ttk.Frame(self.root)
        text_frame.pack(padx=20, pady=5, fill=tk.BOTH, expand=True)
        
        x_scroll = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        y_scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.txt_result = tk.Text(text_frame, wrap=tk.NONE, xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.txt_result.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        x_scroll.config(command=self.txt_result.xview)
        y_scroll.config(command=self.txt_result.yview)
        
        # 動態生成表頭 (Weight, L1~L18, R1~R18)
        cols = ["TrueWeight"] + [f"L{i}" for i in range(1, 19)] + [f"R{i}" for i in range(1, 19)]
        header = "\t".join(cols) + "\n"
        self.txt_result.insert(tk.END, header)

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
                            
                            if result and self.is_collecting:
                                if result["side"] == "L":
                                    self.collected_left.append(result["points"])
                                elif result["side"] == "R":
                                    self.collected_right.append(result["points"])
                                    
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
            
        weight_input = self.entry_weight.get().strip()
        if not weight_input:
            messagebox.showwarning("警告", "請先輸入當前的真實重量！")
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
            
            # 收集 1 秒鐘的資料
            self.root.after(1000, self.finish_capture)

    def finish_capture(self):
        self.is_collecting = False
        
        if not self.collected_left or not self.collected_right:
            self.lbl_countdown.config(text="錯誤：未收到完整的左右腳數據！", foreground="red")
            self.btn_collect.config(state="normal")
            return
            
        # 取得使用者輸入的真實重量
        true_weight = self.entry_weight.get().strip()
            
        # 計算平均值
        avg_left = np.mean(self.collected_left, axis=0)
        avg_right = np.mean(self.collected_right, axis=0)
        
        # 轉換為字串 (小數點 1 位)
        left_str = "\t".join([f"{val:.1f}" for val in avg_left])
        right_str = "\t".join([f"{val:.1f}" for val in avg_right])
        
        # 組合輸出列: TrueWeight \t L1~L18 \t R1~R18
        output_row = f"{true_weight}\t{left_str}\t{right_str}\n"
        
        self.txt_result.insert(tk.END, output_row)
        self.txt_result.see(tk.END)
        
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