import serial
import threading
import time

# --- 設定 TTL 轉接器的 Serial Port ---
COM_PORT = '/dev/cu.usbserial-10'  # ⚠️ 記得確保這裡是你 TTL 的正確路徑
BAUD_RATE = 115200                   # 配合你前面說已經調好的 115200

def read_from_port(ser):
    """這是一個背景執行緒，專門負責緊盯著接收區，有資料就馬上印出來"""
    while True:
        try:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                try:
                    text = data.decode('utf-8')
                    print(text, end='', flush=True)
                except UnicodeDecodeError:
                    print(f"\n[收到亂碼 Hex]: {data.hex()}")
        except Exception as e:
            break
        time.sleep(0.01)

def main():
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
        print(f"✅ 成功連接到 {COM_PORT} (Baud Rate: {BAUD_RATE})")
        print("==================================================")
        print("💻 TTL 實體線終端機已啟動！(已自動附加 \\r\\n)")
        print("🔧 測試指令：輸入 'AT' 並按下 Enter")
        print("🚪 輸入 'exit' 退出程式。")
        print("==================================================\n")

        rx_thread = threading.Thread(target=read_from_port, args=(ser,), daemon=True)
        rx_thread.start()

        while True:
            msg = input()
            
            if msg.lower() == 'exit':
                break
                
            if msg:
                # 這裡就是關鍵：自動幫所有發送的字串補上 \r\n
                data_to_send = msg + "\r\n"
                ser.write(data_to_send.encode('utf-8'))
                
    except serial.SerialException as e:
        print(f"\n❌ 無法開啟 Serial Port: {COM_PORT}")
        print("請檢查：1. 線插好了嗎？ 2. Port 名字對嗎？ 3. 有沒有其他程式佔用了？")
        
    except KeyboardInterrupt:
        print("\n程式被使用者中斷 (Ctrl+C)")
        
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("\n🔌 TTL 連線已安全關閉。")

if __name__ == '__main__':
    main()