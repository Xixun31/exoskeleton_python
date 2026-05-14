import serial
import struct
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread

# ================= 設定區 =================
SERIAL_PORT = '/dev/cu.usbserial-10' 
BAUD_RATE = 115200  
HISTORY_SIZE = 100  # 圖表顯示最近 100 筆數據
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
    """背景執行緒：負責處理 Xbus 協定與數據解析"""
    try:
        # 開啟 Serial
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        ser.reset_input_buffer()
        print(f"成功連線至 {SERIAL_PORT}，開始同步數據...")
        
        while True:
            # 1. 尋找 Preamble 0xFA 和 BusID 0xFF
            if ser.read(1) == b'\xFA':
                if ser.read(1) == b'\xFF':
                    mid = ord(ser.read(1))
                    length = ord(ser.read(1))
                    if length == 255:
                        length = struct.unpack('>H', ser.read(2))[0]
                    
                    payload = ser.read(length)
                    ser.read(1) # Checksum
                    
                    if mid == 0x36: # MTData2 封包
                        i = 0
                        while i < len(payload):
                            try:
                                xdi = struct.unpack('>H', payload[i:i+2])[0]
                                size = payload[i+2]
                                content = payload[i+3 : i+3+size]
                                
                                # 歐拉角 (0x2030)
                                if xdi == 0x2030:
                                    r, p, y = struct.unpack('>fff', content)
                                    euler_data['r'].append(r)
                                    euler_data['p'].append(p)
                                    euler_data['y'].append(y)
                                
                                # 加速度 (0x4020)
                                elif xdi == 0x4020:
                                    ax, ay, az = struct.unpack('>fff', content)
                                    accel_data['x'].append(ax)
                                    accel_data['y'].append(ay)
                                    accel_data['z'].append(az)
                                
                                # 角速度 (0x8020)
                                elif xdi == 0x8020:
                                    gx, gy, gz = struct.unpack('>fff', content)
                                    gyro_data['x'].append(gx * 57.2958) # 轉度/秒
                                    gyro_data['y'].append(gy * 57.2958)
                                    gyro_data['z'].append(gz * 57.2958)
                                
                                i += (3 + size)
                            except Exception:
                                break
    except Exception as e:
        print(f"串口錯誤: {e}")

# --- 繪圖設定 ---
fig, (ax_e, ax_a, ax_g) = plt.subplots(3, 1, figsize=(10, 12))
fig.canvas.manager.set_window_title('MTi-2 Real-time Monitor')

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

# 啟動背景執行緒
thread = Thread(target=serial_reader, daemon=True)
thread.start()

# 啟動動畫
ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()