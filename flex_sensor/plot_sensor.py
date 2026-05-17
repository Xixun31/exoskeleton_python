import json
import glob
import os
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

print("🔄 腳本已成功啟動...")

# ====================================================
# 🛠️ 實驗室校正參數與檔案指定設定
# ====================================================
R_FIXED = 10000.0  
V_CC = 3.3         

V_0 = 1.44    
V_90 = 0.90   

# 🌟 【在這裡手動指定你要分析的 JSON 檔名】
# 💡 若設定為 None：會維持自動抓取資料夾內「最新產生的」檔案
# 💡 若要指定舊檔案：請直接改成字串，例如 SPECIFIED_FILE = "sensor_log_2026-05-17.json"
SPECIFIED_FILE = None  # <-- 這裡改成你想分析的檔案名稱，或保持 None 以自動抓取最新檔案 
# ====================================================

# 1. 核心檔案防呆偵測
if SPECIFIED_FILE is not None:
    # 走手動指定模式
    target_file = SPECIFIED_FILE
    if not os.path.exists(target_file):
        print(f"❌ 找不到你指定的 JSON 檔案: '{target_file}'")
        exit()
    print(f"🎯 手動指定模式：正在分析歷史檔案 ➡️ {target_file}")
else:
    # 走原本的自動尋找最新檔案模式
    json_files = glob.glob('sensor_log_*.json') + glob.glob('sensor_log.json')
    if not json_files:
        print("❌ 數據資料夾內找不到任何 JSON 紀錄檔！")
        exit()
    target_file = max(json_files, key=os.path.getmtime)
    print(f"📂 自動偵測模式：成功抓取最新產生的檔案 ➡️ {target_file}")

# 2. 讀取數據
try:
    with open(target_file, 'r', encoding='utf-8') as f:
        data_list = json.load(f)
except Exception as e:
    print(f"❌ 讀取檔案失敗: {e}")
    exit()

if not data_list:
    print("⚠️ 警告：該 JSON 檔案內容為空！")
    exit()

voltages = [entry['voltage'] for entry in data_list]

# 3. 解析 JSON 裡的時間戳記，計算出相對於起點的「真實秒數」
timestamps = [entry['time'] for entry in data_list]
time_seconds = []

if timestamps:
    start_time = datetime.strptime(timestamps[0], "%Y-%m-%d %H:%M:%S.%f")
    for t_str in timestamps:
        current_t = datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S.%f")
        delta_seconds = (current_t - start_time).total_seconds()
        time_seconds.append(delta_seconds)
else:
    time_seconds = list(range(len(voltages)))

# 4. 核心演算法：純 0-90 度映射角度與原始電阻計算
angles = []
resistors_raw_data = []

for v in voltages:
    v_clipped = max(min(v, max(V_0, V_90)), min(V_0, V_90))
    a = (v_clipped - V_0) * (90.0 - 0.0) / (V_90 - V_0)
    angles.append(a)
    r_sensor = R_FIXED * (V_CC - v_clipped) / v_clipped
    resistors_raw_data.append(r_sensor)

samples = list(range(len(voltages)))

# ====================================================
# 🎨 5. 開始畫圖：獨立開啟四個分離視窗
# ====================================================

# --- 【視窗一：角度對真實時間】 ---
plt.figure('Joint Angle Over Time', figsize=(8, 5.5))
plt.plot(time_seconds, angles, color='green', linewidth=2, label='Calculated Angle (0-90° Map)')
plt.title('Calculated Angle Over Time', fontsize=12, fontweight='bold')
plt.xlabel('Time (Seconds s)')  
plt.ylabel('Angle (Degrees °)')
plt.ylim(-5, 100)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()

# --- 【視窗二：電壓對真實時間】 ---
plt.figure('ADC Voltage Over Time', figsize=(8, 5.5))
plt.plot(time_seconds, voltages, color='blue', linewidth=2, label='Raw Voltage')
plt.title('ADC Voltage Over Time (Raw Data)', fontsize=12, fontweight='bold')
plt.axhline(V_0, color='gray', linestyle=':', alpha=0.7, label=f'Flat Baseline ({V_0}V)')
plt.axhline(V_90, color='gray', linestyle=':', alpha=0.7, label=f'90° Baseline ({V_90}V)')
plt.xlabel('Time (Seconds s)')  
plt.ylabel('Voltage (V)')
plt.ylim(0.5, 1.6)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()

# --- 【視窗三：電壓對角度關係】 ---
plt.figure('ADC Voltage vs. Bending Angle', figsize=(8, 5.5))
plt.scatter(angles, voltages, color='green', s=6, alpha=0.3, label='Raw Data Points')
plt.plot([0.0, 90.0], [V_0, V_90], color='red', linestyle='-', marker='o', linewidth=2, label='0-90° Linear Trend Line')
plt.title('ADC Voltage vs. Bending Angle', fontsize=12, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('ADC Voltage (V)')
plt.xlim(-5, 100)
plt.ylim(0.5, 1.6)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()

# --- 【視窗四：電阻對角度關係】 ---
plt.figure('Sensor Resistance vs. Bending Angle', figsize=(8, 5.5))
plt.scatter(angles, resistors_raw_data, color='orange', s=6, alpha=0.4, label='Raw Resistance Data')
z = np.polyfit(angles, resistors_raw_data, 2)
p = np.poly1d(z)
plt.plot(sorted(angles), p(sorted(angles)), color='darkorange', linestyle='--', linewidth=1.5, label='Actual Curved Trend')
plt.title('Sensor Resistance vs. Bending Angle', fontsize=12, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('Resistance (Ohms Ω)')
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()

print(f"📊 檔案【{target_file}】分析完成，圖形視窗已成功彈出！")
plt.show()