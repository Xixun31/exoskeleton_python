import serial
import json
import re
import time
from datetime import datetime
import platform

# ====================================================
# 🛠️ 1. 系統與通訊參數設定
# ====================================================
current_os = platform.system()
if current_os == "Windows":
    SERIAL_PORT = 'COM10'  # 請根據你的實際情況修改 COM 埠號
elif current_os == "Darwin":
    SERIAL_PORT = '/dev/cu.usbmodem1103'
else:
    SERIAL_PORT = '/dev/ttyUSB0'

BAUD_RATE = 115200  

current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
JSON_FILE = f'sensor_gait_data_{current_time}.json'

# ====================================================
# 🔬 2. 硬體物理與校正參數 (🌟 三點分段校正 DNA)
# ====================================================
V_CC = 3.3         
R_FIXED = 10000.0  

# 👇 填入你實際測量到的三個核心電阻極值
R_0_DEG = 15000.0     # 0度平整電阻
R_45_DEG = 40000.0    # 45度彎曲電阻 (🚨 請填入你量角器實測 45 度的真實數字！)
R_90_DEG = 50000.0   # 90度極限電阻 (你先前實測的黃金數據)

def parse_and_save():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"🚀 【感測器物理特徵擷取系統 (三點分段校正版)】已啟動！")
        print(f"正在監控 {SERIAL_PORT}...\n")
        
        data_list = []

        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                
                # 1. 解析 STM32 傳來的 ADC 與電壓
                match = re.search(r"ADC:\s*(\d+)\s*\|\s*Voltage:\s*([\d\.]*)\s*V", line)
                
                if match:
                    adc_raw = int(match.group(1))
                    v_str = match.group(2)
                    voltage = float(v_str) if v_str else 0.0

                    # 🌟 物理轉換第一步：電壓反推原始電阻
                    if voltage > 0.01:
                        resistance = R_FIXED * (V_CC - voltage) / voltage
                    else:
                        resistance = 0.0

                    # 🛡️ 核心安全邊界防護：將電阻鎖死在 0度 到 90度的範圍內
                    r_clipped = max(min(resistance, R_90_DEG), R_0_DEG)

                    # 🌟 物理轉換第二步：分段線性插值演算法 (Piecewise Linear Interpolation)
                    if r_clipped <= R_45_DEG:
                        # ---- 第一段：0度 ~ 45度 區間 ----
                        angle = (r_clipped - R_0_DEG) * (45.0 - 0.0) / (R_45_DEG - R_0_DEG)
                    else:
                        # ---- 第二段：45度 ~ 90度 區間 ----
                        angle = 45.0 + (r_clipped - R_45_DEG) * (90.0 - 45.0) / (R_90_DEG - R_45_DEG)

                    # 2. 將包含絕對角度的資料封裝存入 JSON
                    entry = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "adc_raw": adc_raw,
                        "voltage": voltage,
                        "resistance_ohms": round(resistance, 2),
                        "angle": round(angle, 2) # 這裡存入的已經是最精準的分段校正角度！
                    }
                    
                    data_list.append(entry)
                    
                    with open(JSON_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data_list, f, indent=4)
                        
                    # 3. 終端機即時顯示
                    print(f"⚡ 電壓: {voltage:.2f} V  |  🎯 電阻: {resistance:7.2f} Ω  |  📐 角度: {angle:5.2f}°")

    except KeyboardInterrupt:
        print("\n🛑 錄製結束。完美分段線性修正的步態特徵資料已儲存至 JSON。")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
    finally:
        if 'ser' in locals():
            ser.close()

if __name__ == "__main__":
    parse_and_save()