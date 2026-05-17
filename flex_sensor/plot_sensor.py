import json
import glob
import os
import numpy as np
import matplotlib.pyplot as plt

print("🔄 腳本已成功啟動，正在自動搜尋最新數據...")

# ====================================================
# 🛠️ 實驗室校正參數設定 (全面回歸 0 到 90 度純粹端點線性映射)
# ====================================================
R_FIXED = 10000.0  # 分壓電路固定電阻 (10k 歐姆)
V_CC = 3.3         # STM32 供電電壓

V_0 = 1.44    # 平放 0 度電壓
V_90 = 0.70   # 彎曲 90 度電壓 (💡 註：未來若改為 0.9，直接在此處修改即可)
# ====================================================

# 1. 自動尋找最新產生的 JSON 檔案
json_files = glob.glob('sensor_log_*.json') + glob.glob('sensor_log.json')
if not json_files:
    print("❌ 找不到數據紀錄檔！請確認終端機路徑是否正確。")
    exit()
latest_file = max(json_files, key=os.path.getmtime)
print(f"📂 成功偵測到最新檔案: {latest_file}")

try:
    with open(latest_file, 'r', encoding='utf-8') as f:
        data_list = json.load(f)
except Exception as e:
    print(f"❌ 讀取檔案失敗: {e}")
    exit()

if not data_list:
    print("⚠️ 警告：JSON 檔案內容為空，請先執行 flex_sensor.py 錄製數據！")
    exit()

voltages = [entry['voltage'] for entry in data_list]

# 2. 核心演算法：純 0-90 度映射角度與原始電阻計算
angles = []
resistors_raw_data = []

for v in voltages:
    # 動態相容 V_90 為 0.7 或 0.9 的安全夾擠防呆
    v_clipped = max(min(v, max(V_0, V_90)), min(V_0, V_90))
    
    # 直接由 0 到 90 度的線性端點公式求出最原始的角度
    a = (v_clipped - V_0) * (90.0 - 0.0) / (V_90 - V_0)
    angles.append(a)

    # 直接反推原始真實電阻 (未經過任何插值扭曲)
    r_sensor = R_FIXED * (V_CC - v_clipped) / v_clipped
    resistors_raw_data.append(r_sensor)

samples = list(range(len(voltages)))

# ====================================================
# 🎨 3. 開始畫圖：獨立開啟四個分離視窗 (題號數字已完全移除)
# ====================================================

# --- 【視窗一：角度對時間】 ---
plt.figure('Joint Angle Over Time', figsize=(8, 5.5))
plt.plot(samples, angles, color='green', linewidth=2, label='Calculated Angle (0-90° Map)')
plt.title('Calculated Angle Over Time', fontsize=12, fontweight='bold')
plt.xlabel('Sample Points')
plt.ylabel('Angle (Degrees °)')
plt.ylim(-5, 100)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()


# --- 【視窗二：電壓對時間】 ---
plt.figure('ADC Voltage Over Time', figsize=(8, 5.5))
plt.plot(samples, voltages, color='blue', linewidth=2, label='Raw Voltage')
plt.title('ADC Voltage Over Time (Raw Data)', fontsize=12, fontweight='bold')
plt.axhline(V_0, color='gray', linestyle=':', alpha=0.7, label=f'Flat Baseline ({V_0}V)')
plt.axhline(V_90, color='gray', linestyle=':', alpha=0.7, label=f'90° Baseline ({V_90}V)')
plt.xlabel('Sample Points')
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


# --- 【視窗四：電阻對角度關係 (🌟 純粹原始物理特徵版本)】 ---
plt.figure('Sensor Resistance vs. Bending Angle', figsize=(8, 5.5))
# 畫出原始電阻對上最原始映射角度的散佈點
plt.scatter(angles, resistors_raw_data, color='orange', s=6, alpha=0.4, label='Raw Resistance Data')
# 利用曲線擬合描繪出這群原始點天然的非線性弧線趨勢
z = np.polyfit(angles, resistors_raw_data, 2)
p = np.poly1d(z)
plt.plot(sorted(angles), p(sorted(angles)), color='darkorange', linestyle='--', linewidth=1.5, label='Actual Curved Trend')

plt.title('Sensor Resistance vs. Bending Angle', fontsize=12, fontweight='bold')
plt.xlabel('Angle (Degrees °)')
plt.ylabel('Resistance (Ohms Ω)')
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend()

# ====================================================
# 4. 觸發顯示
# ====================================================
print("📊 四個最純粹的原始數據分析視窗已全部順利彈出！")
plt.show()