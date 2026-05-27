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
# 🎨 5. 開始畫圖：開啟三個獨立分析視窗
# ====================================================

# --- 【圖表一：分段線性修正後的角度對時間圖】 ---
plt.figure('1. Joint Angle Over Time', figsize=(8, 5.5))
plt.plot(time_seconds, angles, color='green', linewidth=2, label='Piecewise Corrected Angle')
plt.title('Calculated Angle Over Time (3-Point Piecewise Mapped)', fontsize=12, fontweight='bold')
plt.xlabel('Time (Seconds s)')  
plt.ylabel('Angle (Degrees °)')
plt.ylim(-5, 100)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

# --- 【圖表二：電阻隨時間變化圖】 ---
plt.figure('2. Sensor Resistance Over Time', figsize=(8, 5.5))
plt.plot(time_seconds, resistors_raw_data, color='orange', linewidth=2, label='Real-time Resistance')
plt.title('Sensor Resistance Over Time', fontsize=12, fontweight='bold')
plt.axhline(R_0_DEG, color='gray', linestyle=':', alpha=0.7, label=f'0° Baseline ({R_0_DEG}Ω)')
plt.axhline(R_45_DEG, color='lightgray', linestyle='--', alpha=0.7, label=f'45° Pivot ({R_45_DEG}Ω)')
plt.axhline(R_90_DEG, color='gray', linestyle=':', alpha=0.7, label=f'90° Baseline ({R_90_DEG}Ω)')
plt.xlabel('Time (Seconds s)')  
plt.ylabel('Resistance (Ohms Ω)')

# 自動計算極值並保留 10% 裕度
r_min = min(resistors_raw_data)
r_max = max(resistors_raw_data)
r_margin = (r_max - r_min) * 0.10
plt.ylim(r_min - r_margin, r_max + r_margin)  

plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

# --- 【圖表三：每 5 度電阻對角度 (分段理論折線 vs 實際量測曲線)】 ---
plt.figure('3. Resistance vs. Bending Angle (Calibration)', figsize=(9, 6))

# 1. 背景散佈點
#plt.scatter(angles, resistors_raw_data, color='gray', s=5, alpha=0.15, label='Continuous Motion Data')

# 2. 🌟 畫出新的「3點分段線性理論折線」(藍色)
X_pivots = [0, 45, 90]
Y_pivots = [R_0_DEG, R_45_DEG, R_90_DEG]
plt.plot(X_pivots, Y_pivots, color='blue', linestyle='--', linewidth=2, label='3-Point Piecewise Model')
plt.scatter(X_pivots, Y_pivots, color='blue', marker='o', s=60, zorder=4, label='Calibration Pivots')

# 3. 真實量測點
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


print(f"📊 分段校正視覺化完成，三個分析視窗已成功彈出！")
# --- 【圖表四：電壓對角度 (分壓電路的非線性物理展現)】 ---
plt.figure('4. Voltage vs. Bending Angle', figsize=(8, 5.5))

# 1. 背景散佈點 (連續動態測試數據)
#plt.scatter(angles, voltages, color='gray', s=5, alpha=0.3, label='Continuous Motion Data')

# 2. 理論分段模型 (紫色的三點折線)
# 這裡保留理論值，用來跟你的真實量測值做完美的對比！
V_0_DEG_theoretical = (R_FIXED * V_CC) / (R_0_DEG + R_FIXED)
V_45_DEG_theoretical = (R_FIXED * V_CC) / (R_45_DEG + R_FIXED)
V_90_DEG_theoretical = (R_FIXED * V_CC) / (R_90_DEG + R_FIXED)

X_pivots = [0, 45, 90]
Y_voltages_pivots = [V_0_DEG_theoretical, V_45_DEG_theoretical, V_90_DEG_theoretical]

plt.plot(X_pivots, Y_voltages_pivots, color='purple', linestyle='--', linewidth=2, label='3-Point Theoretical Voltage Model')
plt.scatter(X_pivots, Y_voltages_pivots, color='purple', marker='o', s=60, zorder=4, label='Voltage Pivots')

# 3. 🌟 真實每 5 度量測的電壓數據 (直接貼上你的 Excel 數據)
if has_calibration:
    # 👇 請把你在 Excel 裡量到的 19 個電壓值，依照 0度 到 90度的順序填入這裡：
    cal_voltages_measured = [
        1.239,  # 0度 (範例數字，請替換成你的 Excel 數據)
        1.192,  # 5度
        1.132,  # 10度
        0.955,  # 15度
        0.887,  # 20度
        0.799,  # 25度
        0.75,  # 30度
        0.725,  # 35度
        0.678,  # 40度
        0.63,  # 45度
        0.623,  # 50度
        0.609,  # 55度
        0.612,  # 60度
        0.591,  # 65度
        0.573,  # 70度
        0.563,  # 75度
        0.559,  # 80度
        0.542,  # 85度
        0.541   # 90度
    ]
    
    # 畫出你的真實 Excel 電壓紅線
    plt.plot(cal_angles, cal_voltages_measured, color='red', linestyle='-', linewidth=2, alpha=0.8, label='Actual Empirical Voltage Trend')
    plt.scatter(cal_angles, cal_voltages_measured, color='red', marker='X', s=80, edgecolor='black', zorder=5, label='Measured 5° Step Points')

plt.title('System Response: ADC Voltage vs. Bending Angle', fontsize=13, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('Voltage (V)')
plt.xlim(-5, 95)
plt.xticks(np.arange(0, 95, 5))
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

print(f"📊 第四張圖表 (含直接輸入的 Excel 真實電壓曲線) 已加入分析列！")
plt.show()