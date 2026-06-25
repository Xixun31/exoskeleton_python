import serial
import glob

# ⚠️ 自動偵測 /dev/ttyACM*，若無則使用預設 /dev/ttyACM0
ports = glob.glob('/dev/ttyACM*')
COM_PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD_RATE = 115200

def main():
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE)
        print(f"✅ 成功連線至 STM32 ({COM_PORT})")
        print("========================================")
        print("👉 現在請按下板子上的【黑色 Reset 按鈕】！")
        print("========================================\n")

        while True:
            if ser.in_waiting:
                # 讀取 STM32 的 printf 輸出
                msg = ser.readline().decode('utf-8', errors='replace').strip()
                if msg:
                    print(f"[STM32]: {msg}")

    except serial.SerialException:
        print(f"❌ 無法連線至 {COM_PORT}，請確認板子已插上 USB。")
    except KeyboardInterrupt:
        print("\n程式結束。")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == '__main__':
    main()