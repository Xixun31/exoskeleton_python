import serial
import collections
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.animation as animation
import matplotlib.path as mpath
from scipy.interpolate import griddata
from threading import Thread

# ================= 設定區 =================
COM_PORT = 'COM8'
BAUD_RATE = 115200
VMAX = 30000       # 熱度圖單點壓力值上限
GRID_RES = 25      # 馬賽克解析度

HISTORY_SIZE = 150 # 曲線圖 X 軸歷史長度
Y_MAX_INIT = 30000 # 曲線圖初始 Y 軸高度

# 🎯 硬體傳來的資料陣列 0~17，剛好對應你的這張圖：
# [9, 3, 10, 4, 15, 11, 5, 16, 12, 6, 17, 13, 7, 1, 18, 14, 8, 2]
# 所以我們直接抓對應的 Index：
HEEL_IDX = [8, 2]              # 腳跟 (Label 9, 3) 
FORE_IDX = [12, 6, 13, 7]      # 前腳掌 (Label 12, 6, 13, 7)
# ==========================================

# 建立畫布網格
grid_x, grid_y = np.mgrid[-10:110:complex(0, GRID_RES), -10:110:complex(0, GRID_RES)]

# 📍 回歸你最滿意的腳底座標矩陣 (完美對齊上面的 18 個陣列位置)
x_L = np.array([82, 82, 60, 60, 70, 75, 66, 68, 40, 40, 50, 50, 48, 52, 30, 25, 30, 38])
y_L = np.array([74, 88, 7, 22, 40, 59, 75, 94, 7, 22, 40, 57, 73, 90, 40, 55, 70, 84])
x_R = 100 - x_L
y_R = y_L

# ✂️ 回歸完美鞋墊遮罩 (Polygon Mask)，切掉多餘的方塊邊角
left_foot_outline = np.array([
    [35, 0], [65, 0], [65, 22], [75, 40], [80, 59], [87, 74], [88, 92], 
    [70, 100], [52, 96], [33, 90], [25, 72], [18, 55], [25, 40], [35, 22]
])
path_L = mpath.Path(left_foot_outline)
right_foot_outline = left_foot_outline.copy()
right_foot_outline[:, 0] = 100 - left_foot_outline[:, 0]
path_R = mpath.Path(right_foot_outline)

# 將畫布點拿去判定 (在輪廓內為 True，外為 False)
points_flat = np.c_[grid_x.ravel(), grid_y.ravel()]
mask_L = path_L.contains_points(points_flat).reshape(grid_x.shape)
mask_R = path_R.contains_points(points_flat).reshape(grid_x.shape)

# 零延遲全域變數：只儲存最新一筆的 18 個壓力點數據
raw_z_L = np.zeros(18)
raw_z_R = np.zeros(18)

# 這些變數必須在程式啟動時就存在
heatmap_L = np.zeros((GRID_RES, GRID_RES))
heatmap_R = np.zeros((GRID_RES, GRID_RES))

# 資料儲存：單腳獨立曲線圖
x_data = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
heel_L_hist = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
fore_L_hist = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
heel_R_hist = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
fore_R_hist = collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)

frame_counter = 0
start_time = None

# 新增用來暫存最新數值的變數
curr_heel_L, curr_fore_L = 0, 0
curr_heel_R, curr_fore_R = 0, 0

def calculate_checksum(data_bytes):
    return sum(data_bytes) & 0xFF

def parse_foot_data(frame):
    if len(frame) != 39 or frame[0] != 0xAA: return None
    if calculate_checksum(frame[:38]) != frame[38]: return None
    foot_id = frame[1]
    foot_side = "左腳" if foot_id == 0x01 else "右腳" if foot_id == 0x02 else None
    if not foot_side: return None
    points = [(frame[2 + i*2] << 8) | frame[3 + i*2] for i in range(18)]
    return {"side": foot_side, "points": points}

def serial_reader():
    # 記得加上新變數
    global raw_z_L, raw_z_R, frame_counter, start_time, heatmap_L, heatmap_R
    global curr_heel_L, curr_fore_L, curr_heel_R, curr_fore_R
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print("✅ 成功連線，開始繪製零延遲完美輪廓儀表板...")
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
                            z = np.array(result["points"])
                            
                            if result["side"] == "左腳":
                                grid_z = griddata((x_L, y_L), z, (grid_x, grid_y), method='linear', fill_value=np.nan)
                                new_heatmap = np.where(mask_L, np.clip(grid_z, 0, VMAX), np.nan)
                                heatmap_L = new_heatmap
                                raw_z_L = z
                                
                                # 更新左腳最新狀態
                                curr_heel_L = sum(z[i] for i in HEEL_IDX)
                                curr_fore_L = sum(z[i] for i in FORE_IDX)
                            else:
                                grid_z = griddata((x_R, y_R), z, (grid_x, grid_y), method='linear', fill_value=np.nan)
                                heatmap_R = np.where(mask_R, np.clip(grid_z, 0, VMAX), np.nan)
                                raw_z_R = z
                                
                                # 更新右腳最新狀態
                                curr_heel_R = sum(z[i] for i in HEEL_IDX)
                                curr_fore_R = sum(z[i] for i in FORE_IDX)
                            
                            # 🚀 關鍵修正：不管更新哪一腳，歷史陣列都要「同時」推進！
                            heel_L_hist.append(curr_heel_L)
                            fore_L_hist.append(curr_fore_L)
                            heel_R_hist.append(curr_heel_R)
                            fore_R_hist.append(curr_fore_R)
                            
                            frame_counter += 1
                            if start_time is None:
                                start_time = time.monotonic()
                            elapsed_s = time.monotonic() - start_time
                            x_data.append(elapsed_s)
                                
                        buffer = buffer[start_idx+39:]
                    else:
                        buffer = buffer[start_idx:]
                        break
    except Exception as e:
        print(f"❌ 串口錯誤: {e}")

# ================= 繪圖版面設定 =================
plt.rcParams['font.family'] = 'Arial'
plt.rcParams['axes.unicode_minus'] = False 

fig = plt.figure(figsize=(14, 9))
fig.canvas.manager.set_window_title('步態分析儀表板 (完美輪廓 & 核心波形版)')

gs = gridspec.GridSpec(2, 2, height_ratios=[2, 1], hspace=0.3, wspace=0.2)

# --- 上半部：雙腳熱度圖 ---
ax_heat_L = fig.add_subplot(gs[0, 0])
ax_heat_R = fig.add_subplot(gs[0, 1])

cmap = plt.get_cmap('jet').copy()
cmap.set_bad(color='white')

ax_heat_L.set_title('Left Foot Heatmap', fontsize=14, fontweight='bold')
ax_heat_R.set_title('Right Foot Heatmap', fontsize=14, fontweight='bold')
ax_heat_L.axis('off')
ax_heat_R.axis('off')

# 預設放置全空的矩陣
im_left = ax_heat_L.imshow(np.zeros((GRID_RES, GRID_RES)), cmap=cmap, vmin=0, vmax=VMAX, origin='lower', extent=[-10, 110, -10, 110], interpolation='nearest')
im_right = ax_heat_R.imshow(np.zeros((GRID_RES, GRID_RES)), cmap=cmap, vmin=0, vmax=VMAX, origin='lower', extent=[-10, 110, -10, 110], interpolation='nearest')
fig.colorbar(im_right, ax=[ax_heat_L, ax_heat_R], fraction=0.03, pad=0.05, label='Force')

# --- 下半部：左右腳獨立曲線圖 ---
ax_line_L = fig.add_subplot(gs[1, 0])
ax_line_R = fig.add_subplot(gs[1, 1])

for ax, title in zip([ax_line_L, ax_line_R], ['Left Foot: Heel Strike vs. Forefoot Loading', 'Right Foot: Heel Strike vs. Forefoot Loading']):
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_ylabel('Core Sensor Sum', fontsize=10)
    ax.set_xlabel('Time (s)', fontsize=10)
    ax.set_ylim(0, Y_MAX_INIT)
    ax.grid(True, linestyle='--', alpha=0.6)

line_heel_L, = ax_line_L.plot([], [], label='Heel (Contact: 3, 9)', color='navy', linestyle='-', linewidth=2)
line_fore_L, = ax_line_L.plot([], [], label='Forefoot (Propulsion: 6, 7, 12, 13)', color='darkorange', linestyle='--', linewidth=2)
line_heel_R, = ax_line_R.plot([], [], label='Heel (Contact: 3, 9)', color='navy', linestyle='-', linewidth=2)
line_fore_R, = ax_line_R.plot([], [], label='Forefoot (Propulsion: 6, 7, 12, 13)', color='darkorange', linestyle='--', linewidth=2)

ax_line_L.legend(loc='upper left', fontsize=9)
ax_line_R.legend(loc='upper left', fontsize=9)

def animate(frame):
    global heatmap_L, heatmap_R  # 務必加上此行，否則讀不到更新後的資料
    
    # 確保繪製的是轉置後的矩陣，並確保資料已非初始的 zeros
    im_left.set_data(heatmap_L.T)
    im_right.set_data(heatmap_R.T)
    
    # 3. 更新曲線圖資料 (使用固定的 10 秒視窗)
    l_x = list(x_data)
    if len(l_x) > 0:
        current_time = l_x[-1]  # 取得最新時間點
        window = 10
        l_h_L, l_f_L = list(heel_L_hist), list(fore_L_hist)
        l_h_R, l_f_R = list(heel_R_hist), list(fore_R_hist)
        
        line_heel_L.set_data(l_x, l_h_L)
        line_fore_L.set_data(l_x, l_f_L)
        line_heel_R.set_data(l_x, l_h_R)
        line_fore_R.set_data(l_x, l_f_R)
        
        # 設置一個動態視窗：若時間小於 10 秒，顯示 0-10；若大於 10 秒，顯示 (current-10) 到 current
        x_min = max(0, current_time - 10)
        x_max = max(10, current_time + 1)

        ax_line_L.set_xlim(x_min, x_max)
        ax_line_R.set_xlim(x_min, x_max)
        #max_L = max(max(l_h_L), max(l_f_L))
        #if max_L > ax_line_L.get_ylim()[1] * 0.9: ax_line_L.set_ylim(0, max_L * 1.2)
        #    
        #max_R = max(max(l_h_R), max(l_f_R))
        #if max_R > ax_line_R.get_ylim()[1] * 0.9: ax_line_R.set_ylim(0, max_R * 1.2)
            
    return [im_left, im_right, line_heel_L, line_fore_L, line_heel_R, line_fore_R]

thread = Thread(target=serial_reader, daemon=True)
thread.start()

ani = animation.FuncAnimation(fig, animate, interval=50, blit=False, cache_frame_data=False)

plt.show()