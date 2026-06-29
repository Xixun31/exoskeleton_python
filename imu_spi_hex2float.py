from pyparsing import line
import serial
import re
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread
import struct
import glob

import platform

# ================= 設定區 =================
current_os = platform.system()
if current_os == "Windows":
    PORT = 'COM7'                # Windows 的 COM 埠
elif current_os == "Darwin":
    PORT = '/dev/cu.usbmodem1103' # macOS (MacBook) 的 USB 埠
else:
    # Linux 系統 (若你用 STM32 開發板直連，通常是 ttyACM0；若是 TTL 轉接板則是 ttyUSB0)
    PORT = '/dev/ttyACM0'

BAUD = 115200                 # 鮑率
HISTORY_SIZE = 100            # 圖表顯示最近 100 筆數據
# ==========================================

# 數據容器 (使用 deque 自動維持固定長度)
euler_data = {'r': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'p': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

accel_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

gyro_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
             'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
             'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}
'''
這裡是原始imu_spi.py的程式碼
def serial_reader():
    """背景執行緒：負責讀取 STM32 傳來的純文字並萃取數字"""
    try:
        # 開啟 Serial
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print(f"成功連線至 STM32 SPI IMU ({PORT})，開始解析並繪圖...")
        
        while True:
            # 讀取一行純文字
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            
            # 使用正規表達式，自動抓出字串中所有的數字 (包含正負號與小數點)
            # 例如從 "R: 12.34 P:-5.6" 中抓出 ['12.34', '-5.6']
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", line)
            # 【新增這行來除錯】看看 Python 到底抓到了幾個數字？內容是什麼？
            #print(f"收到文字: {line} | 抓到的數字: {nums} | 數量: {len(nums)}")
            # 我們預期 STM32 會傳來 9 個數字 (Euler 3 + Accel 3 + Gyro 3)
            if len(nums) == 9:
                try:
                    # 1. 歐拉角
                    euler_data['r'].append(float(nums[0]))
                    euler_data['p'].append(float(nums[1]))
                    euler_data['y'].append(float(nums[2]))
                    
                    # 2. 加速度
                    accel_data['x'].append(float(nums[3]))
                    accel_data['y'].append(float(nums[4]))
                    accel_data['z'].append(float(nums[5]))
                    
                    # 3. 角速度
                    gyro_data['x'].append(float(nums[6]))
                    gyro_data['y'].append(float(nums[7]))
                    gyro_data['z'].append(float(nums[8]))
                    
                except ValueError:
                    pass
    except Exception as e:
        print(f"串口錯誤: {e}")
到這裡結束
'''
# ======================= 讀取 Hex 並轉換為 Float =======================
def serial_reader():
    """背景執行緒：負責讀取 STM32 傳來的 Hex 整數並還原為浮點數"""
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print(f"成功連線至 STM32，開始接收 Hex 格式資料...")
        
        while True:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            # 假設 STM32 印出: R:12345678 P:87654321 Y:11223344 ...
            # 我們這裡用簡單的方式只抓出 9 個 16 進位字串
            # 如果你的格式是 R:12345678 P:...，我們用 findall 抓數字
            hex_nums = re.findall(r"[:\s]([0-9A-Fa-f]{8})", line)
            
            if len(hex_nums) == 9:
                try:
                    # 定義一個函數來轉換 Hex String -> Float
                    def hex_to_float(h):
                        # 將 hex string 轉為 bytes，再轉回 float
                        return struct.unpack('f', struct.pack('I', int(h, 16)))[0]

                    # 1. 歐拉角
                    euler_data['r'].append(hex_to_float(hex_nums[0]))
                    euler_data['p'].append(hex_to_float(hex_nums[1]))
                    euler_data['y'].append(hex_to_float(hex_nums[2]))
                    
                    # 2. 加速度
                    accel_data['x'].append(hex_to_float(hex_nums[3]))
                    accel_data['y'].append(hex_to_float(hex_nums[4]))
                    accel_data['z'].append(hex_to_float(hex_nums[5]))
                    
                    # 3. 角速度
                    gyro_data['x'].append(hex_to_float(hex_nums[6]))
                    gyro_data['y'].append(hex_to_float(hex_nums[7]))
                    gyro_data['z'].append(hex_to_float(hex_nums[8]))
                    
                except Exception as e:
                    print(f"解析錯誤: {e}")
                    
    except Exception as e:
        print(f"串口錯誤: {e}")
# --- 繪圖設定 ---
fig, (ax_e, ax_a, ax_g) = plt.subplots(3, 1, figsize=(10, 12))
fig.canvas.manager.set_window_title('STM32 IMU Real-time Monitor (SPI Mode)')

def animate(frame):
    # 1. 繪製歐拉角
    ax_e.clear()
    ax_e.plot(list(euler_data['r']), label='Roll (X)', color='r')
    ax_e.plot(list(euler_data['p']), label='Pitch (Y)', color='g')
    ax_e.plot(list(euler_data['y']), label='Yaw (Z)', color='b')
    ax_e.set_title('Orientation (Euler Angles) [deg]')
    ax_e.set_ylim([-180, 180])
    ax_e.legend(loc='upper right')
    ax_e.grid(True)

    # 2. 繪製加速度
    ax_a.clear()
    ax_a.plot(list(accel_data['x']), label='Acc X', color='r')
    ax_a.plot(list(accel_data['y']), label='Acc Y', color='g')
    ax_a.plot(list(accel_data['z']), label='Acc Z', color='b')
    ax_a.set_title('Acceleration [m/s²]')
    ax_a.legend(loc='upper right')
    ax_a.grid(True)

    # 3. 繪製角速度
    ax_g.clear()
    ax_g.plot(list(gyro_data['x']), label='Gyro X', color='r')
    ax_g.plot(list(gyro_data['y']), label='Gyro Y', color='g')
    ax_g.plot(list(gyro_data['z']), label='Gyro Z', color='b')
    ax_g.set_title('Rate of Turn [deg/s]')
    ax_g.legend(loc='upper right')
    ax_g.grid(True)

    # 取得最新的 Roll/Pitch
    r_now = euler_data['r'][-1]
    p_now = euler_data['p'][-1]
    
    # 在圖表上顯示文字
    ax_e.text(0.02, 0.95, f'Roll: {r_now:.2f} | Pitch: {p_now:.2f}', 
              transform=ax_e.transAxes, color='black', fontsize=12,
              bbox=dict(facecolor='white', alpha=0.5))

# 啟動背景執行緒讀取資料
thread = Thread(target=serial_reader, daemon=True)
thread.start()

# 啟動動畫 (每 50 毫秒更新一次)
ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()
