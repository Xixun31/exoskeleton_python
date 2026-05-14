import serial
import re
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread

# ================= 設定區 =================
PORT = '/dev/cu.usbmodem103'  # 請確認你的埠號是否還是 103
BAUD = 115200
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

def serial_reader():
    """背景執行緒：負責讀取 STM32 傳來的純文字並萃取數字"""
    try:
        # 開啟 Serial
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print(f"成功連線至 STM32 ({PORT})，開始解析並繪圖...")
        
        while True:
            # 讀取一行純文字
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            
            # 使用正規表達式，自動抓出字串中所有的數字 (包含正負號與小數點)
            # 例如從 "R: 12.34 P:-5.6" 中抓出 ['12.34', '-5.6']
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", line)
            
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
                    
                    # 可以在背景印出最新抓到的 Roll 角度，確認解析正常
                    # print(f"最新 Roll 角度: {float(nums[0])}") 
                    
                except ValueError:
                    pass
    except Exception as e:
        print(f"串口錯誤: {e}")

# --- 繪圖設定 (介面與之前一模一樣) ---
fig, (ax_e, ax_a, ax_g) = plt.subplots(3, 1, figsize=(10, 12))
fig.canvas.manager.set_window_title('STM32 IMU Real-time Monitor')

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

# 啟動背景執行緒讀取資料
thread = Thread(target=serial_reader, daemon=True)
thread.start()

# 啟動動畫 (每 50 毫秒更新一次)
ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()