import serial
import time

# 請確認這是你 MacBook 上的轉接頭路徑
PORT = '/dev/cu.usbserial-110' 
# 常見的藍牙鮑率清單
BAUD_RATES = [9600, 19200, 38400, 57600, 115200]

def scan_baud_rate():
    for baud in BAUD_RATES:
        print(f"嘗試鮑率: {baud}...", end="", flush=True)
        try:
            # 開啟序列埠
            ser = serial.Serial(PORT, baud, timeout=0.5)
            
            # 發送測試指令，記得要加 \r\n
            ser.write(b"AT\r\n")
            
            # 讀取回傳
            response = ser.read(10) # 讀取前 10 個位元組
            
            if b"OK" in response:
                print(f"\n成功！找到真實鮑率: {baud}")
                ser.close()
                return baud
            else:
                print(" 無反應")
            
            ser.close()
        except Exception as e:
            print(f" 錯誤: {e}")
            
    print("\n掃描結束，未找到匹配的鮑率。請檢查接線或電源。")
    return None

if __name__ == "__main__":
    scan_baud_rate()