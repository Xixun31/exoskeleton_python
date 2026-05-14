import serial
import json
import re
import time
from datetime import datetime

# 1. 設定串口參數 (根據你 ls 到的結果)
SERIAL_PORT = '/dev/cu.usbmodem1103' 
BAUD_RATE = 115200  # 必須與 STM32 的 MX_USART2_UART_Init 一致
JSON_FILE = 'sensor_log.json'

def parse_and_save():
    try:
        # 開啟串口
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"正在監控 {SERIAL_PORT}...")
        
        data_list = []

        while True:
            if ser.in_waiting > 0:
                # 讀取一行並解碼
                line = ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                
                print(f"收到原始資料: {line}")

                # 2. 使用 Regex 抓取數字 (ADC 和 Voltage)
                # 格式: ADC: 1234 | Voltage: 1.23 V
                match = re.search(r"ADC:\s*(\d+)\s*\|\s*Voltage:\s*([\d\.]*)\s*V", line)
                
                if match:
                    adc_raw = int(match.group(1))
                    # 如果電壓抓不到數字，就給它 0.0
                    v_str = match.group(2)
                    voltage = float(v_str) if v_str else 0.0

                    # 3. 建立 JSON 資料項目
                    entry = {
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                        "adc_raw": adc_raw,
                        "voltage": voltage
                    }
                    
                    data_list.append(entry)
                    
                    # 4. 存成 JSON 檔 (存為一個 List)
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