import serial
import re
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread

import glob

# ================= 設定區 =================
# 自動偵測 /dev/ttyACM*，若無則使用預設 /dev/ttyACM0
ports = glob.glob('/dev/ttyACM*')
PORT = ports[0] if ports else '/dev/ttyACM0'         # STM32 序列埠路徑
BAUD = 115200                 # 鮑率
HISTORY_SIZE = 100            # 圖表顯示最近 100 筆數據
# ==========================================

# 數據容器 - IMU 1 (實線)
euler1_data = {'r': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'p': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

accel1_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

gyro1_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

# 數據容器 - IMU 2 (虛線)
euler2_data = {'r': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'p': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

accel2_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
               'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}

gyro2_data = {'x': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'y': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
              'z': collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)}


def serial_reader():
    """背景執行緒：負責讀取 STM32 傳來的純文字並萃取 18 個數值"""
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print(f"成功連線至 STM32 Dual IMU ({PORT})，開始解析並繪圖...")
        
        while True:
            # 讀取一行純文字
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                continue
            
            # 只提取冒號 (:) 後面的數字，避免將 R1, P1, R2, P2 中的 '1' 和 '2' 誤判為數值
            nums = re.findall(r":\s*([-+]?\d*\.\d+|[-+]?\d+)", line)
            
            # 我們預期雙 IMU 會傳來 18 個數字 (IMU1 的 9 個 + IMU2 的 9 個)
            if len(nums) == 18:
                try:
                    # ---- IMU 1 資料 ----
                    euler1_data['r'].append(float(nums[0]))
                    euler1_data['p'].append(float(nums[1]))
                    euler1_data['y'].append(float(nums[2]))
                    
                    accel1_data['x'].append(float(nums[3]))
                    accel1_data['y'].append(float(nums[4]))
                    accel1_data['z'].append(float(nums[5]))
                    
                    gyro1_data['x'].append(float(nums[6]))
                    gyro1_data['y'].append(float(nums[7]))
                    gyro1_data['z'].append(float(nums[8]))
                    
                    # ---- IMU 2 資料 ----
                    euler2_data['r'].append(float(nums[9]))
                    euler2_data['p'].append(float(nums[10]))
                    euler2_data['y'].append(float(nums[11]))
                    
                    accel2_data['x'].append(float(nums[12]))
                    accel2_data['y'].append(float(nums[13]))
                    accel2_data['z'].append(float(nums[14]))
                    
                    gyro2_data['x'].append(float(nums[15]))
                    gyro2_data['y'].append(float(nums[16]))
                    gyro2_data['z'].append(float(nums[17]))
                    
                except ValueError:
                    pass
    except Exception as e:
        print(f"串口錯誤: {e}")


# --- 繪圖設定 ---
fig, (ax_e, ax_a, ax_g) = plt.subplots(3, 1, figsize=(10, 12))
fig.canvas.manager.set_window_title('STM32 Dual IMU Real-time Monitor')

def animate(frame):
    # 1. 繪製歐拉角 (Roll, Pitch, Yaw)
    ax_e.clear()
    # IMU 1 (實線)
    ax_e.plot(list(euler1_data['r']), label='IMU1 Roll', color='r', linestyle='-')
    ax_e.plot(list(euler1_data['p']), label='IMU1 Pitch', color='g', linestyle='-')
    ax_e.plot(list(euler1_data['y']), label='IMU1 Yaw', color='b', linestyle='-')
    # IMU 2 (虛線)
    ax_e.plot(list(euler2_data['r']), label='IMU2 Roll', color='r', linestyle='--')
    ax_e.plot(list(euler2_data['p']), label='IMU2 Pitch', color='g', linestyle='--')
    ax_e.plot(list(euler2_data['y']), label='IMU2 Yaw', color='b', linestyle='--')
    
    ax_e.set_title('Orientation (Euler Angles) [deg]')
    ax_e.set_ylim([-180, 180])
    ax_e.legend(loc='upper right', ncol=2)
    ax_e.grid(True)

    # 2. 繪製加速度 (Acc X, Y, Z)
    ax_a.clear()
    # IMU 1 (實線)
    ax_a.plot(list(accel1_data['x']), label='IMU1 Acc X', color='r', linestyle='-')
    ax_a.plot(list(accel1_data['y']), label='IMU1 Acc Y', color='g', linestyle='-')
    ax_a.plot(list(accel1_data['z']), label='IMU1 Acc Z', color='b', linestyle='-')
    # IMU 2 (虛線)
    ax_a.plot(list(accel2_data['x']), label='IMU2 Acc X', color='r', linestyle='--')
    ax_a.plot(list(accel2_data['y']), label='IMU2 Acc Y', color='g', linestyle='--')
    ax_a.plot(list(accel2_data['z']), label='IMU2 Acc Z', color='b', linestyle='--')
    
    ax_a.set_title('Acceleration [m/s²]')
    ax_a.legend(loc='upper right', ncol=2)
    ax_a.grid(True)

    # 3. 繪製角速度 (Gyro X, Y, Z)
    ax_g.clear()
    # IMU 1 (實線)
    ax_g.plot(list(gyro1_data['x']), label='IMU1 Gyro X', color='r', linestyle='-')
    ax_g.plot(list(gyro1_data['y']), label='IMU1 Gyro Y', color='g', linestyle='-')
    ax_g.plot(list(gyro1_data['z']), label='IMU1 Gyro Z', color='b', linestyle='-')
    # IMU 2 (虛線)
    ax_g.plot(list(gyro2_data['x']), label='IMU2 Gyro X', color='r', linestyle='--')
    ax_g.plot(list(gyro2_data['y']), label='IMU2 Gyro Y', color='g', linestyle='--')
    ax_g.plot(list(gyro2_data['z']), label='IMU2 Gyro Z', color='b', linestyle='--')
    
    ax_g.set_title('Rate of Turn [deg/s]')
    ax_g.legend(loc='upper right', ncol=2)
    ax_g.grid(True)


# 啟動背景讀取執行緒
thread = Thread(target=serial_reader, daemon=True)
thread.start()

# 啟動動畫更新 (50ms 間隔)
ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()
