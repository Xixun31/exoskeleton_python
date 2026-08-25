import serial
import time
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread

# ================= 設定區 =================
COM_PORT = 'COM6'
BAUD_RATE = 115200
HISTORY_SIZE = 150  # 稍微拉長顯示範圍，讓波形更好看
Y_MAX = 75000       # 鎖死 Y 軸天花板，避免畫面垂直跳動
# ==========================================

# 新增：絕對時間軸 x_data
x_data = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
left_total = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
right_total = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)

# 用來同步左右腳最新狀態的變數
current_L = 0
current_R = 0
start_time = None
x_data = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE) 

def calculate_checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def parse_foot_data(frame):
    if len(frame) != 39 or frame[0] != 0xAA:
        return None
    if calculate_checksum(frame[:38]) != frame[38]:
        return None

    foot_id = frame[1]
    foot_side = "左腳" if foot_id == 0x01 else "右腳" if foot_id == 0x02 else None
    if not foot_side:
        return None

    points = [(frame[2 + i*2] << 8) | frame[3 + i*2] for i in range(18)]
    return {"side": foot_side, "points": points}

def serial_reader():
    global current_L, current_R, start_time
    
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"✅ 成功連線，開始穩定繪製圖表...")
        buffer = bytearray()

        while True:
            if ser.in_waiting > 0:
                buffer.extend(ser.read(ser.in_waiting))
#
                ## 👇 【關鍵新增】：把藍牙模組囉嗦的提示字串直接刪掉！
                #noise = b'ATT_HANDLE_VALUE_NOTI\r\n'
                #if noise in buffer:
                #    buffer = bytearray(buffer.replace(noise, b''))
                ## 👆 ==========================================
                while b'\xaa' in buffer:
                    start_idx = buffer.index(0xAA)
                    
                    if len(buffer) - start_idx >= 39:
                        frame = buffer[start_idx : start_idx+39]
                        result = parse_foot_data(frame)
                        
                        if result:
                            total_f = sum(result["points"])
                            
                            # 更新最新受力狀態
                            if result["side"] == "左腳":
                                current_L = total_f
                            else:
                                current_R = total_f
                            
                            # 紀錄時間
                            if start_time is None:
                                start_time = time.monotonic()

                            elapsed_time = time.monotonic() - start_time
                            x_data.append(elapsed_time)  # 存入的是秒數
                            left_total.append(current_L)
                            right_total.append(current_R)
                                
                        buffer = buffer[start_idx+39:]
                    else:
                        buffer = buffer[start_idx:]
                        break
    except Exception as e:
        print(f"❌ 串口錯誤: {e}")

# ================= 繪圖設定 =================
fig, ax = plt.subplots(figsize=(10, 6))
fig.canvas.manager.set_window_title('即時雙腳總壓力監控 (穩定版)')

def animate(frame):
    ax.clear()
    
    # 複製出列表以供繪圖
    l_x = list(x_data)
    l_left = list(left_total)
    l_right = list(right_total)
    
    if not l_x:
        return
        
    combined_list = [l + r for l, r in zip(l_left, l_right)]
    
    ax.plot(l_x, l_left, label='Left Foot', color='blue', linewidth=2)
    ax.plot(l_x, l_right, label='Right Foot', color='red', linewidth=2)
    ax.plot(l_x, combined_list, label='Combined Force', color='purple', linewidth=3, linestyle='--')
    
    ax.set_title('Real-time Plantar Force (Stable View)', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel('Force (Raw Data)', fontsize=12)
    # 修改 X 軸名稱
    ax.set_xlabel('Time (s)', fontsize=12)
    # 讓 X 軸顯示為時間視窗 (例如總是顯示過去 10 秒的數據)
    current_time = x_data[-1]
    if current_time > 10:
        ax.set_xlim([current_time - 10, current_time + 1])
    else:
        ax.set_xlim([0, 11])
    
    # 1. 鎖死 Y 軸：解決垂直跳動
    ax.set_ylim([0, Y_MAX])
    
    # 2. 攝影機平移 X 軸：讓過去的數據留在原地，畫面平順向右滑動
    ax.set_xlim([l_x[0], l_x[-1] + 5])
    
    left_latest = l_left[-1]
    right_latest = l_right[-1]
    ax.text(
        0.02, 0.98,
        f'Current L: {left_latest}\nCurrent R: {right_latest}\nCombined: {left_latest + right_latest}',
        transform=ax.transAxes,
        va='top', ha='left',
        fontsize=10,
        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8)
    )
    
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.6)

thread = Thread(target=serial_reader, daemon=True)
thread.start()

ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()