import serial
import time

COM_PORT = 'COM9' # 請確認你的 COM Port 號碼
BAUD_RATE = 115200 # 請確認這裡跟 STM32 的設定一致

try:
    ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
    print("✅ 開始攔截原始封包...")
    
    while True:
        if ser.in_waiting > 0:
            raw_data = ser.read(ser.in_waiting)
            hex_str = ' '.join([f'{b:02X}' for b in raw_data])
            print(f"收到數據: {hex_str}")
        time.sleep(0.05)
except Exception as e:
    print(e)