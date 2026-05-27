import json
import glob
import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

print("🔄 數據分析與可視化腳本已啟動 (三點分段校正版)...")

# ====================================================
# 🛠️ 1. 物理校正參數設定 (🌟 你的專屬分段校正 DNA)
# ====================================================
R_FIXED = 10000.0  # 下拉固定電阻 10k 歐姆
V_CC = 3.3         # 系統供電 3.3V

# 👇 這裡的數值已經為你同步成下方陣列中的真實測量極值！
R_0_DEG = 16634.54   # 0度平整電阻 
R_45_DEG = 42380.95  # 45度彎曲電阻 (從你的實驗數據提取)
R_90_DEG = 52264.15  # 90度極限電阻 

# ====================================================
# 📂 2. 實驗資料檔案設定
# ====================================================
CONTINUOUS_FILE = None  # 例如 'standup.json' 或 None

# ====================================================
# 🚀 3. 讀取與處理【連續動態數據】
# ====================================================
target_file = CONTINUOUS_FILE
if target_file is None:
    json_files = glob.glob('sensor_log_*.json') + glob.glob('sensor_gait_data_*.json') + glob.glob('standup.json')
    if json_files:
        target_file = max(json_files, key=os.path.getmtime)

try:
    with open(target_file, 'r', encoding='utf-8') as f:
        data_list = json.load(f)
    print(f"📂 成功載入連續動態數據 ➡️ {target_file}")
except Exception as e:
    print(f"❌ 讀取連續數據失敗: {e}")
    exit()

voltages = [entry['voltage'] for entry in data_list]
timestamps = [entry['time'] for entry in data_list]
time_seconds = []

if timestamps:
    start_time = datetime.strptime(timestamps[0], "%Y-%m-%d %H:%M:%S.%f")
    for t_str in timestamps:
        current_t = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S.%f")
        time_seconds.append((current_t - start_time).total_seconds())

# 🌟 核心物理重新運算：將電壓重新計算為分段線性角度
angles = []
resistors_raw_data = []

for v in voltages:
    v_safe = max(v, 0.01) # 避免電壓為 0 造成數學錯誤
    
    # 步驟 1：電壓反推電阻
    r_sensor = R_FIXED * (V_CC - v_safe) / v_safe
    resistors_raw_data.append(r_sensor)
    
    # 步驟 2：核心安全邊界防護 (防護範圍夾在 0度 到 90度之間)
    r_clipped = max(min(r_sensor, R_90_DEG), R_0_DEG)
    
    # 🌟 步驟 3：三點分段線性插值演算法 (Piecewise Linear Interpolation)
    if r_clipped <= R_45_DEG:
        # ---- 第一段：0度 ~ 45度 區間 ----
        a = (r_clipped - R_0_DEG) * (45.0 - 0.0) / (R_45_DEG - R_0_DEG)
    else:
        # ---- 第二段：45度 ~ 90度 區間 ----
        a = 45.0 + (r_clipped - R_45_DEG) * (90.0 - 45.0) / (R_90_DEG - R_45_DEG)
        
    angles.append(a)

# ====================================================
# 🚀 4. 讀取與處理【5 度步進真實校正數據】(手動輸入版)
# ====================================================
cal_angles = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90]

cal_resistors = [
    16634.54,  # 0度
    17684.87,  # 5度
    19152.31,  # 10度
    24555.92,  # 15度
    27205.99,  # 20度
    31302.22,  # 25度
    34000.0,   # 30度
    35519.41,  # 35度
    38674.28,  # 40度
    42380.95,  # 45度
    42972.35,  # 50度
    44188.52,  # 55度
    43923.85,  # 60度
    45838.98,  # 65度
    47595.28,  # 70度
    48618.42,  # 75度
    49035.71,  # 80度
    50888.89,  # 85度
    52264.15   # 90度
]

has_calibration = True
print("📂 成功載入【手動輸入】的真實量角器校正數據！")

# 防呆檢查：確保角度與電阻資料數量一致
if len(cal_angles) != len(cal_resistors):
    print(f"❌ 警告：角度數量 ({len(cal_angles)}) 與電阻數量 ({len(cal_resistors)}) 不一致！")
    has_calibration = False

# ====================================================
# 🎨 5. 開始畫圖：開啟分析視窗 (圖一與圖二合併雙 Y 軸)
# ====================================================

# --- 【圖表一 & 二合併：角度與電阻隨時間變化圖 (雙 Y 軸)】 ---
fig, ax1 = plt.subplots(figsize=(10, 6), num='1 & 2. Angle and Resistance Over Time')
plt.title('Calculated Angle & Sensor Resistance Over Time', fontsize=13, fontweight='bold')

# 🟢 繪製左側 Y 軸：分段線性修正後的角度
color1 = 'green'
ax1.set_xlabel('Time (Seconds s)')
ax1.set_ylabel('Angle (Degrees °)', color=color1)
line1 = ax1.plot(time_seconds, angles, color=color1, linewidth=2, label='Piecewise Corrected Angle')
ax1.tick_params(axis='y', labelcolor=color1)
ax1.set_ylim(-5, 100)
ax1.grid(True, linestyle='--', alpha=0.6)

# 🟠 建立共用 X 軸的右側 Y 軸：電阻變化
ax2 = ax1.twinx()  
color2 = 'orange'
ax2.set_ylabel('Resistance (Ohms Ω)', color=color2)
line2 = ax2.plot(time_seconds, resistors_raw_data, color=color2, linewidth=2, label='Real-time Resistance')
ax2.tick_params(axis='y', labelcolor=color2)

# 自動計算極值並保留 10% 裕度
if resistors_raw_data:
    r_min = min(resistors_raw_data)
    r_max = max(resistors_raw_data)
    r_margin = (r_max - r_min) * 0.10
    ax2.set_ylim(r_min - r_margin, r_max + r_margin)  

# 加入電阻參考線
line3 = ax2.axhline(R_0_DEG, color='gray', linestyle=':', alpha=0.7, label=f'0° Baseline ({R_0_DEG}Ω)')
line4 = ax2.axhline(R_45_DEG, color='lightgray', linestyle='--', alpha=0.7, label=f'45° Pivot ({R_45_DEG}Ω)')
line5 = ax2.axhline(R_90_DEG, color='gray', linestyle=':', alpha=0.7, label=f'90° Baseline ({R_90_DEG}Ω)')

# 合併兩個 Y 軸的圖例 (Legend)
lines_1, labels_1 = ax1.get_legend_handles_labels()
lines_2, labels_2 = ax2.get_legend_handles_labels()
ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left', bbox_to_anchor=(0.02, 0.98))

# --- 【圖表三：每 5 度電阻對角度 (分段理論折線 vs 實際量測曲線)】 ---
plt.figure('3. Resistance vs. Bending Angle (Calibration)', figsize=(9, 6))

X_pivots = [0, 45, 90]
Y_pivots = [R_0_DEG, R_45_DEG, R_90_DEG]
plt.plot(X_pivots, Y_pivots, color='blue', linestyle='--', linewidth=2, label='3-Point Piecewise Model')
plt.scatter(X_pivots, Y_pivots, color='blue', marker='o', s=60, zorder=4, label='Calibration Pivots')

if has_calibration:
    plt.plot(cal_angles, cal_resistors, color='red', linestyle='-', linewidth=2, alpha=0.8, label='Actual Empirical Trend')
    plt.scatter(cal_angles, cal_resistors, color='red', marker='X', s=80, edgecolor='black', zorder=5, label='Measured 5° Step Points')

plt.title('Calibration: Piecewise Linear Model vs. Empirical Data', fontsize=13, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('Resistance (Ohms Ω)')
plt.xlim(-5, 95)
plt.xticks(np.arange(0, 95, 5)) 
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper left')

# --- 【圖表四：電壓對角度 (分壓電路的非線性物理展現)】 ---
plt.figure('4. Voltage vs. Bending Angle', figsize=(8, 5.5))

V_0_DEG_theoretical = (R_FIXED * V_CC) / (R_0_DEG + R_FIXED)
V_45_DEG_theoretical = (R_FIXED * V_CC) / (R_45_DEG + R_FIXED)
V_90_DEG_theoretical = (R_FIXED * V_CC) / (R_90_DEG + R_FIXED)

Y_voltages_pivots = [V_0_DEG_theoretical, V_45_DEG_theoretical, V_90_DEG_theoretical]

plt.plot(X_pivots, Y_voltages_pivots, color='purple', linestyle='--', linewidth=2, label='3-Point Theoretical Voltage Model')
plt.scatter(X_pivots, Y_voltages_pivots, color='purple', marker='o', s=60, zorder=4, label='Voltage Pivots')

if has_calibration:
    cal_voltages_measured = [
        1.239, 1.192, 1.132, 0.955, 0.887, 0.799, 0.75, 0.725, 0.678, 
        0.63, 0.623, 0.609, 0.612, 0.591, 0.573, 0.563, 0.559, 0.542, 0.541   
    ]
    plt.plot(cal_angles, cal_voltages_measured, color='red', linestyle='-', linewidth=2, alpha=0.8, label='Actual Empirical Voltage Trend')
    plt.scatter(cal_angles, cal_voltages_measured, color='red', marker='X', s=80, edgecolor='black', zorder=5, label='Measured 5° Step Points')

plt.title('System Response: ADC Voltage vs. Bending Angle', fontsize=13, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('Voltage (V)')
plt.xlim(-5, 95)
plt.xticks(np.arange(0, 95, 5))
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

print(f"📊 視覺化完成，圖一與圖二已成功疊加為雙 Y 軸圖表！")
plt.show()