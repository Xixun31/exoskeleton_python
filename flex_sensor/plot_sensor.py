import json
import glob
import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

print("🔄 數據分析與可視化腳本已啟動 (動態與靜態基準分離版)...")

# ====================================================
# 🛠️ 1. 物理校正參數設定
# ====================================================
R_FIXED = 10000.0  # 下拉固定電阻 10k 歐姆
V_CC = 3.3         # 系統供電 3.3V

R_0_DEG = 16634.54   # 0度平整電阻 
R_45_DEG = 42380.95  # 45度彎曲電阻 

# 🌟 將 90 度的電阻拆分為「靜態畫圖用」與「動態計算用」
R_90_DEG_STATIC = 52264.15   # 用於圖表三、四的理論折線基準 (量角器真實極限)
R_90_DEG_DYNAMIC = 65000.0   # 用於圖表一的角度計算基準 (考量肌肉形變的寬容值)

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

# 🌟 核心物理重新運算
angles = []
resistors_raw_data = []

for v in voltages:
    v_safe = max(v, 0.01) # 避免電壓為 0 造成數學錯誤
    
    # 步驟 1：電壓反推電阻
    r_sensor = R_FIXED * (V_CC - v_safe) / v_safe
    resistors_raw_data.append(r_sensor)
    
    # 步驟 2：使用動態基準 (R_90_DEG_DYNAMIC = 65000) 來計算角度
    if r_sensor <= R_45_DEG:
        # ---- 第一段：0度 ~ 45度 區間 ----
        a = (r_sensor - R_0_DEG) * (45.0 - 0.0) / (R_45_DEG - R_0_DEG)
    else:
        # ---- 第二段：45度 ~ 90度 區間 (🌟 這裡改用 65000 作為 90 度基準) ----
        a = 45.0 + (r_sensor - R_45_DEG) * (90.0 - 45.0) / (R_90_DEG_DYNAMIC - R_45_DEG)
        
    angles.append(a)

# ====================================================
# 🚀 4. 讀取與處理【5 度步進真實校正數據】
# ====================================================
cal_angles = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90]

cal_resistors = [
    16634.54, 17684.87, 19152.31, 24555.92, 27205.99, 31302.22, 34000.0, 35519.41, 
    38674.28, 42380.95, 42972.35, 44188.52, 43923.85, 45838.98, 47595.28, 48618.42, 
    49035.71, 50888.89, 52264.15
]

has_calibration = True
if len(cal_angles) != len(cal_resistors):
    has_calibration = False

# ====================================================
# 🎨 5. 開始畫圖：拆分為四個獨立視窗
# ====================================================

# --- 【圖表一：角度隨時間變化圖】 ---
plt.figure('1. Angle Over Time', figsize=(10, 5))
plt.title('Calculated Angle Over Time', fontsize=13, fontweight='bold')
plt.plot(time_seconds, angles, color='green', linewidth=2, label='Dynamic Angle (Unclipped)')
plt.xlabel('Time (Seconds s)')
plt.ylabel('Angle (Degrees °)')
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

# --- 【圖表二：電阻隨時間變化圖】 ---
plt.figure('2. Resistance Over Time', figsize=(10, 5))
plt.title('Sensor Resistance Over Time', fontsize=13, fontweight='bold')
plt.plot(time_seconds, resistors_raw_data, color='orange', linewidth=2, label='Real-time Resistance')
plt.xlabel('Time (Seconds s)')
plt.ylabel('Resistance (Ohms Ω)')
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

# --- 【圖表三：每 5 度電阻對角度 (分段理論 vs 實際量測)】 ---
plt.figure('3. Resistance vs. Bending Angle', figsize=(9, 6))
X_pivots = [0, 45, 90]
# 🌟 這裡使用靜態的 52264.15 來畫藍色理論折線，保持實驗一致性
Y_pivots = [R_0_DEG, R_45_DEG, R_90_DEG_STATIC]
plt.plot(X_pivots, Y_pivots, color='blue', linestyle='--', linewidth=2, label='3-Point Piecewise Model (Static)')
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

# --- 【圖表四：電壓對角度】 ---
plt.figure('4. Voltage vs. Bending Angle', figsize=(8, 5.5))
V_0_DEG_theoretical = (R_FIXED * V_CC) / (R_0_DEG + R_FIXED)
V_45_DEG_theoretical = (R_FIXED * V_CC) / (R_45_DEG + R_FIXED)
# 🌟 這裡也使用靜態的 52264.15 來計算紫色的理論電壓折線
V_90_DEG_theoretical = (R_FIXED * V_CC) / (R_90_DEG_STATIC + R_FIXED)
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

print(f"📊 視覺化完成！已將動態與靜態基準分離！")
plt.show()