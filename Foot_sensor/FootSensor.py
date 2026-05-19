import serial
import time
import json  # 1. 引入 json 模組

# 設定串口參數
COM_PORT = 'COM8'
BAUD_RATE = 115200

def calculate_checksum(data_bytes):
    """計算校驗和：前 38 bytes 累加取低 8 位"""
    return sum(data_bytes) & 0xFF

def parse_foot_data(frame):
    """解析 39 Bytes 的數據幀"""
    if len(frame) != 39 or frame[0] != 0xAA:
        return None

    # 驗證 Checksum (B39)
    expected_checksum = calculate_checksum(frame[:38])
    if expected_checksum != frame[38]:
        return None

    # 判斷左右腳 (B2)
    foot_id = frame[1]
    if foot_id == 0x01:
        foot_side = "左腳"
    elif foot_id == 0x02:
        foot_side = "右腳"
    else:
        return None

    # 解析 18 點壓力數據 (B3 ~ B38)
    points = []
    for i in range(18):
        high_byte = frame[2 + i*2]
        low_byte = frame[3 + i*2]
        pressure_value = (high_byte << 8) | low_byte 
        points.append(pressure_value)

    parsed_data = {
        "timestamp_ms": int(time.time() * 1000),
        "side": foot_side,
        "pressure_points_g": points
    }
    
    return parsed_data

def main():
    # 2. 準備一個大清單，用來裝所有的步態數據
    all_gait_data = []
    
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"✅ 已成功連接至 {COM_PORT}，等待數據中...")
        print("🏃‍♂️ 開始測試！(隨時可以在終端機按下 Ctrl + C 來結束並存檔)\n")

        buffer = bytearray()

        while True:
            if ser.in_waiting > 0:
                buffer.extend(ser.read(ser.in_waiting))
                
                while b'\xaa' in buffer:
                    start_idx = buffer.index(0xAA)
                    
                    if len(buffer) - start_idx >= 39:
                        frame = buffer[start_idx : start_idx+39]
                        result = parse_foot_data(frame)
                        
                        if result:
                            # 印出簡化的提示，讓你知道程式還在跑，但不會洗畫面
                            side_color = "🔵" if result["side"] == "左腳" else "🔴"
                            print(f"[{result['timestamp_ms']}] {side_color} 收到 {result['side']} 數據...", end="\r")
                            
                            # 把這筆數據裝進大清單裡面
                            all_gait_data.append(result)
                        
                        buffer = buffer[start_idx+39:]
                    else:
                        buffer = buffer[start_idx:]
                        break

    except serial.SerialException as e:
        print(f"❌ 串口連接錯誤: {e}")
    except KeyboardInterrupt:
        # 當你按下 Ctrl+C 時，會跳到這裡
        print("\n\n🛑 測量已手動終止。準備開始存檔...")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("🔌 串口已關閉。")
            
        # 3. 核心存檔邏輯：將清單轉換成 JSON 檔案
        if len(all_gait_data) > 0:
            filename = "gait_data_output.json" # 你可以隨時修改這個檔名
            
            # 使用 utf-8 編碼開啟檔案，準備寫入
            with open(filename, "w", encoding="utf-8") as f:
                # indent=4 會幫你自動排版、換行，ensure_ascii=False 確保中文正常顯示
                json.dump(all_gait_data, f, indent=4, ensure_ascii=False)
                
            print(f"🎉 太棒了！一共 {len(all_gait_data)} 筆數據已成功儲存到「{filename}」！")
        else:
            print("⚠️ 沒有收集到任何數據，因此未建立檔案。")

if __name__ == '__main__':
    main()