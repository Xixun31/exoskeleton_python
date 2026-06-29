import serial
import time
import collections
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from threading import Thread

# ================= 設定區 =================
COM_PORT = 'COM8'
BAUD_RATE = 115200
HISTORY_SIZE = 100  # 圖表顯示最近 100 筆數據
# ==========================================

# 建立雙腳的即時數據容器 (只需保留 total)
left_total = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
right_total = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)

def calculate_checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def parse_foot_data(frame):
    """解析 39 Bytes 的數據幀"""
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
    """背景執行緒：負責讀取與解析串口數據"""
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"✅ 成功連線至 {COM_PORT}，開始即時繪製總受力圖...")
        buffer = bytearray()

        while True:
            if ser.in_waiting > 0:
                buffer.extend(ser.read(ser.in_waiting))
                
                while b'\xaa' in buffer:
                    start_idx = buffer.index(0xAA)
                    
                    if len(buffer) - start_idx >= 39:
                        frame = buffer[start_idx : start_idx+39]
                        result = parse_foot_data(frame)
                        
                        if result:
                            # 只要計算 18 個點的總和
                            total_f = sum(result["points"])
                            
                            # 存入對應的佇列中
                            if result["side"] == "左腳":
                                left_total.append(total_f)
                            else:
                                right_total.append(total_f)
                                
                        buffer = buffer[start_idx+39:]
                    else:
                        buffer = buffer[start_idx:]
                        break
    except Exception as e:
        print(f"❌ 串口錯誤: {e}")

# ================= 繪圖設定 =================
fig, ax = plt.subplots(figsize=(10, 6))
fig.canvas.manager.set_window_title('即時雙腳總壓力監控 (Total Plantar Force)')

def animate(frame):
    ax.clear()
    
    # 將左右腳的總和畫在同一張圖上，方便對比重心轉移
    ax.plot(list(left_total), label='Left Foot (Total)', color='blue', linewidth=2.5)
    ax.plot(list(right_total), label='Right Foot (Total)', color='red', linewidth=2.5)
    
    ax.set_title('Real-time Plantar Total Force', fontsize=14, fontweight='bold', pad=15)
    ax.set_ylabel('Force (g)', fontsize=12)
    ax.set_xlabel('Time (Frames)', fontsize=12)
    
    # 動態調整 Y 軸上限，並確保最低高度至少為 100
    max_val = max(max(left_total), max(right_total), 100)
    ax.set_ylim([0, max_val * 1.1])
    
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.6)

# 啟動背景執行緒讀取資料
thread = Thread(target=serial_reader, daemon=True)
thread.start()

# 啟動動畫 (每 50 毫秒更新一次)
ani = animation.FuncAnimation(fig, animate, interval=50, cache_frame_data=False)

plt.tight_layout()
plt.show()