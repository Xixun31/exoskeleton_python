import serial
import json
import re
import time
from datetime import datetime
import platform

# 1. 設定串口參數 (根據你 ls 到的結果)
#SERIAL_PORT = '/dev/cu.usbmodem1103' 
current_os = platform.system()

if current_os == "Windows":
    SERIAL_PORT = 'COM5' 
elif current_os == "Darwin": # Mac 系統
    SERIAL_PORT = '/dev/cu.usbmodem1103'
else:
    SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200  # 必須與 STM32 的 MX_USART2_UART_Init 一致
#JSON_FILE = 'sensor_log.json'
# 利用 datetime 自動抓取現在時間，產生像 sensor_log_20260517_1306.json 這樣的檔名
current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
JSON_FILE = f'sensor_log_{current_time}.json'


# 校正極值設定 (90度端點插值)
V_0 = 1.44
V_90 = 0.90

def parse_and_save():
    try:
        # 開啟串口
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"正在監控 {SERIAL_PORT}...")
        
        data_list = []

        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                
                print(f"收到原始資料: {line}")

                # 2. 使用 Regex 抓取數字
                match = re.search(r"ADC:\s*(\d+)\s*\|\s*Voltage:\s*([\d\.]*)\s*V", line)
                
                if match:
                    adc_raw = int(match.group(1))
                    v_str = match.group(2)
                    voltage = float(v_str) if v_str else 0.0

                    # 🌟 即時進行 90 度端點電壓轉角度運算
                    v_clipped = max(min(voltage, V_0), V_90)
                    angle = (v_clipped - V_0) * (90.0 - 0.0) / (V_90 - V_0)

                    # 3. 建立 JSON 資料項目 (新增 angle 欄位)
                    entry = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "adc_raw": adc_raw,
                        "voltage": voltage,
                        "angle": round(angle, 2) # 四捨五入到小數點後兩位
                    }
                    
                    data_list.append(entry)
                    
                    with open(JSON_FILE, 'w', encoding='utf-8') as f:
                        json.dump(data_list, f, indent=4)
                        
                    print(f"已轉換為 JSON: {entry}")

    except KeyboardInterrupt:
        print("\n使用者停止監控。資料已儲存。")
    except Exception as e:
        print(f"錯誤: {e}")
    finally:
        if 'ser' in locals():
            ser.close()

if __name__ == "__main__":
    parse_and_save()