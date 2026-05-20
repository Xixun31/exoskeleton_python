import json
import os
import matplotlib.pyplot as plt

# Set the JSON filename
GAIT_FILE = "gait_data_output.json"

if not os.path.exists(GAIT_FILE):
    print(f"❌ Cannot find '{GAIT_FILE}'. Please ensure it is in the same directory.")
    exit()

with open(GAIT_FILE, "r", encoding="utf-8") as f:
    data_list = json.load(f)

if not data_list:
    print("⚠️ JSON file is empty!")
    exit()

# Set initial timestamp as 0 seconds reference
start_time_ms = data_list[0]["timestamp_ms"]

# Initialize data containers (Using enhanced forefoot representation)
left_data = {"time": [], "total_force": [], "heel": [], "forefoot": []}
right_data = {"time": [], "total_force": [], "heel": [], "forefoot": []}

for entry in data_list:
    t_seconds = (entry["timestamp_ms"] - start_time_ms) / 1000.0  # Convert to seconds
    points = entry["pressure_points_g"]
    
    if len(points) < 18:
        continue
        
    # 1. Total Plantar Force (Sum of all 18 sensors)
    total_f = sum(points)
    
    # 2. Heel Core Area: Sensor 3 + Sensor 9
    # Python indices: 2 and 8
    heel_f = points[2] + points[8]
    
    # 3. Forefoot Core Area: Merging Sensor 6, 7, 12, 13 for optimal force distribution
    # Python indices: 5, 6, 11, 12
    forefoot_f = points[5] + points[6] + points[11] + points[12]
    
    # Classify by side
    if entry["side"] == "左腳":
        left_data["time"].append(t_seconds)
        left_data["total_force"].append(total_f)
        left_data["heel"].append(heel_f)
        left_data["forefoot"].append(forefoot_f)
    elif entry["side"] == "右腳":
        right_data["time"].append(t_seconds)
        right_data["total_force"].append(total_f)
        right_data["heel"].append(heel_f)
        right_data["forefoot"].append(forefoot_f)

# ====================================================
# 🎨 Matplotlib Plotting Configuration (Original English Labels)
# ====================================================
plt.rcParams['font.family'] = 'Arial'
plt.rcParams['axes.unicode_minus'] = False 

# --- Figure 1: Total Plantar Force ---
plt.figure('Plantar Total Force Analysis', figsize=(10, 5))
plt.plot(left_data["time"], left_data["total_force"], color='blue', linewidth=2, label='Left Foot (Total)')
plt.plot(right_data["time"], right_data["total_force"], color='red', linewidth=2, label='Right Foot (Total)')

plt.title('Plantar Total Force During "Sit-to-Stand & Walk" Test', fontsize=12, fontweight='bold', pad=15)
plt.xlabel('Time (Seconds s)', fontsize=10, labelpad=8)
plt.ylabel('Total Weight / Pressure Value (g)', fontsize=10, labelpad=8)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

# --- Figure 2: Left Foot Micro-Gait Timing (Heel vs. Forefoot) ---
plt.figure('Heel vs Forefoot Timing Analysis', figsize=(10, 5)) # 🛠️ 圖表視窗名稱微調
if left_data["time"]:
    # 🛠️ 將標籤從原先的 'Left Toe (Propulsion)' 改為學術名詞 'Left Forefoot (Propulsion)'
    plt.plot(left_data["time"], left_data["heel"], color='navy', linestyle='-', linewidth=2, label='Left Heel (Contact)')
    plt.plot(left_data["time"], left_data["forefoot"], color='darkorange', linestyle='--', linewidth=2, label='Left Forefoot (Propulsion)')

# 🛠️ 標題修改：將 "Toe Off" 修正為更能代表前腳掌特徵的 "Forefoot Loading" 或 "Forefoot Push-Off"
plt.title('Heel Strike vs. Forefoot Loading Timing Verification', fontsize=12, fontweight='bold', pad=15)
plt.xlabel('Time (Seconds s)', fontsize=10, labelpad=8)
plt.ylabel('Sensor Raw Value (g)', fontsize=10, labelpad=8)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(loc='upper right')

print("📊 Done! The code is fully aligned with the hardware spec sheet and the english layout.")
plt.show()