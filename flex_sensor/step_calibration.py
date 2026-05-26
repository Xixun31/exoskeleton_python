import serial
import json
import re
import time
from datetime import datetime
import platform

# ====================================================
# 🛠️ 1. 系統設定
# ====================================================
current_os = platform.system()
if current_os == "Windows":
    SERIAL_PORT = 'COM10'  # 請根據你的實際情況修改 COM 埠號
elif current_os == "Darwin":
    SERIAL_PORT = '/dev/cu.usbmodem1103'
else:
    SERIAL_PORT = '/dev/ttyUSB0'

BAUD_RATE = 115200  
JSON_FILE = f'calibration_table_{datetime.now().strftime("%Y%m%d_%H%M")}.json'

V_CC = 3.3         
R_FIXED = 10000.0  

def run_step_calibration():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print("==================================================")
        print("🚀 【感測器 5 度步進校正系統 (Multi-point Calibration)】")
        print("==================================================\n")
        
        results = []
        # 產生 0, 5, 10, ..., 90 的目標角度清單
        target_angles = list(range(0, 95, 5))

        for target_angle in target_angles:
            # 1. 互動式提示：等待使用者折好角度
            input(f"📐 請將感測器精準彎曲至 【 {target_angle} 度 】，保持穩定後按下 [Enter] 鍵記錄...")
            print(f"   🔄 正在擷取 {target_angle} 度的數據 (自動進行 10 次採樣平均)...\n")

            samples = []
            ser.reset_input_buffer() # 清除舊的緩衝區數據，確保抓到的是按下 Enter 後的最即時資料

            # 2. 連續抓取 10 筆有效數據
            while len(samples) < 10:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('utf-8').strip()
                    match = re.search(r"Voltage:\s*([\d\.]*)\s*V", line)
                    if match:
                        v = float(match.group(1))
                        if v > 0.01:
                            r = R_FIXED * (V_CC - v) / v
                            samples.append({"voltage": v, "resistance": r})
            
            # 3. 數學運算：計算這 10 筆資料的平均值 (消除手抖雜訊)
            avg_v = sum(s["voltage"] for s in samples) / 10.0
            avg_r = sum(s["resistance"] for s in samples) / 10.0

            print(f"   ✅ {target_angle} 度紀錄完成！ ➡️  平均電壓: {avg_v:.3f} V | 平均電阻: {avg_r:.2f} Ω")
            print("-" * 50)

            # 將結果存入記憶體
            results.append({
                "angle_degree": target_angle,
                "avg_voltage_v": round(avg_v, 3),
                "avg_resistance_ohms": round(avg_r, 2)
            })

        # 4. 全部錄製完畢，存成漂亮的 JSON 查表檔
        with open(JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)
            
        print(f"\n🎉 完美！所有步進數據已採集完畢！")
        print(f"💾 查表資料已儲存至: {JSON_FILE}")

    except KeyboardInterrupt:
        print("\n🛑 實驗強制中斷。")
    except Exception as e:
        print(f"❌ 發生錯誤: {e}")
    finally:
        if 'ser' in locals():
            ser.close()

if __name__ == "__main__":
    run_step_calibration()