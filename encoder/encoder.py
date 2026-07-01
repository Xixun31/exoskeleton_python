import serial
import time
import collections
import glob
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# --- 設定 Serial Port ---
# 自動偵測 /dev/ttyACM* (Linux) 或使用預設值
ports = glob.glob('/dev/ttyACM*')
COM_PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD_RATE = 115200

# --- 設定圖表參數 ---
MAX_POINTS = 100  # 畫面上最多顯示最新的 100 筆資料
# 使用 deque 來建立一個固定長度的佇列，新資料進來時，舊資料會自動被擠出去
y_data = collections.deque([0] * MAX_POINTS, maxlen=MAX_POINTS)
x_data = list(range(MAX_POINTS))

def main():
    try:
        # 開啟 Serial Port，timeout 設短一點避免卡死
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"成功連接到 {COM_PORT}，Baud Rate: {BAUD_RATE}")
        print("開始接收資料並繪圖... (直接關閉圖表視窗即可結束程式)\n")
        
        # --- 初始化 Matplotlib 圖表 ---
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.set_title('Real-time Encoder Angle', fontsize=14)
        ax.set_xlabel('Time (frames)', fontsize=12)
        ax.set_ylabel('Angle (Degrees)', fontsize=12)
        ax.set_ylim(0, 360)  # 編碼器角度固定在 0~360 度
        ax.grid(True, linestyle='--', alpha=0.6) # 加上網格方便觀看
        
        # 建立一條初始的線
        line_plot, = ax.plot(x_data, y_data, '-b', linewidth=2) 
        
        # --- 定義圖表更新邏輯 ---
        def update_plot(frame):
            # 每次更新時，把緩衝區內「所有」累積的資料都讀完，避免圖表嚴重延遲
            while ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='replace').strip()
                
                if line:
                    data_str = line.split(',')
                    if len(data_str) == 2:
                        try:
                            raw_val = int(data_str[0].strip())
                            angle_deg = float(data_str[1].strip())
                            
                            # 將最新算出的角度加入佇列中
                            y_data.append(angle_deg)
                            print(f"讀取成功 | 原始數值: {raw_val}, 角度: {angle_deg:.2f}°")
                            
                        except ValueError:
                            pass # 忽略剛開機的系統訊息或亂碼
                            
            # 把更新後的資料重新設定給線條
            line_plot.set_ydata(y_data)
            return line_plot,

        # --- 設定動畫 (每 50 毫秒觸發一次 update_plot) ---
        ani = animation.FuncAnimation(
            fig, update_plot, interval=50, blit=True, cache_frame_data=False
        )
        
        # 顯示圖表 (程式會在這裡進入迴圈，直到你把彈出的圖表視窗打叉關閉)
        plt.tight_layout()
        plt.show()
        
    except serial.SerialException as e:
        print(f"\n[錯誤] 無法開啟 Serial Port: {COM_PORT}")
        print(f"詳細錯誤: {e}")
        print("請檢查板子是否連接，或 Port 名稱是否正確。")
        
    except KeyboardInterrupt:
        print("\n程式被使用者中斷 (Ctrl+C)")
        
    finally:
        # 確保視窗關閉或程式結束時，安全釋放 Serial Port
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial Port 已安全關閉。")

if __name__ == '__main__':
    main()