import serial
import re
import csv
import time
import os
import sys

# ================= 設定區 =================
PORT = '/dev/ttyACM0'  # 串口埠號 (請依實際連接修改，如 /dev/ttyUSB0 或 /dev/ttyACM0)
BAUD = 115200          # 鮑率
CSV_FILE = 'imu_data.csv'
# ==========================================

def print_table(imu1_data, imu2_data):
    # 使用 ANSI escape code 清除螢幕並重置游標位置
    sys.stdout.write("\033[H\033[J")
    sys.stdout.write("====================================================================================\n")
    sys.stdout.write("                          STM32 雙 IMU 即時數據監控器 (UART)                        \n")
    sys.stdout.write("====================================================================================\n")
    sys.stdout.write("+-------+--------------------------+--------------------------+--------------------------+\n")
    sys.stdout.write("| Sensor| 歐拉角 (Roll/Pitch/Yaw)  |      加速度 (X/Y/Z)      |      角速度 (X/Y/Z)      |\n")
    sys.stdout.write("+-------+--------------------------+--------------------------+--------------------------+\n")
    
    def format_row(name, data):
        if data:
            euler_str = f"{data[0]:6.2f}, {data[1]:6.2f}, {data[2]:6.2f}"
            accel_str = f"{data[3]:5.2f}, {data[4]:5.2f}, {data[5]:5.2f}"
            gyro_str  = f"{data[6]:6.2f}, {data[7]:6.2f}, {data[8]:6.2f}"
        else:
            euler_str = "    N/A,     N/A,     N/A"
            accel_str = "  N/A,   N/A,   N/A"
            gyro_str  = "    N/A,     N/A,     N/A"
        return f"| {name:<5} | {euler_str:<24} | {accel_str:<24} | {gyro_str:<24} |\n"

    sys.stdout.write(format_row("IMU 1", imu1_data))
    sys.stdout.write(format_row("IMU 2", imu2_data))
    sys.stdout.write("+-------+--------------------------+--------------------------+--------------------------+\n")
    sys.stdout.write(f"正在將數據儲存至: {os.path.abspath(CSV_FILE)}\n")
    sys.stdout.write("按 Ctrl+C 可結束程式...\n")
    sys.stdout.flush()

def main():
    imu1_latest = None
    imu2_latest = None

    print(f"正在連線至 STM32 ({PORT} @ {BAUD} baud)...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print("連線成功！開始接收資料...")
    except Exception as e:
        print(f"開啟串口錯誤: {e}")
        print("請確認連接的埠號是否正確，且已取得對應讀寫權限 (例如: sudo chmod 666 /dev/ttyACM0)。")
        sys.exit(1)

    # 準備 CSV 檔案
    file_exists = os.path.exists(CSV_FILE)
    try:
        csv_file = open(CSV_FILE, 'a', newline='')
        csv_writer = csv.writer(csv_file)
        if not file_exists:
            csv_writer.writerow([
                'Timestamp',
                'IMU1_Roll', 'IMU1_Pitch', 'IMU1_Yaw',
                'IMU1_AccX', 'IMU1_AccY', 'IMU1_AccZ',
                'IMU1_GyroX', 'IMU1_GyroY', 'IMU1_GyroZ',
                'IMU2_Roll', 'IMU2_Pitch', 'IMU2_Yaw',
                'IMU2_AccX', 'IMU2_AccY', 'IMU2_AccZ',
                'IMU2_GyroX', 'IMU2_GyroY', 'IMU2_GyroZ'
            ])
            csv_file.flush()
    except Exception as e:
        print(f"無法寫入 CSV 檔案: {e}")
        sys.exit(1)

    last_update_time = 0

    try:
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
            except Exception as e:
                print(f"\n讀取串口時出錯: {e}")
                break

            if not line:
                continue

            # 解析資料行
            is_imu1 = line.startswith("IMU1 ->")
            is_imu2 = line.startswith("IMU2 ->")

            if is_imu1 or is_imu2:
                prefix = "IMU1 ->" if is_imu1 else "IMU2 ->"
                content = line[len(prefix):]
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", content)
                
                if len(nums) == 9:
                    try:
                        floats = [float(n) for n in nums]
                        if is_imu1:
                            imu1_latest = floats
                        else:
                            imu2_latest = floats
                    except ValueError:
                        continue

            # 當偵測到分隔線時，表示一輪數據傳輸完成，進行寫檔與更新表格顯示
            if line.startswith("---") and (imu1_latest or imu2_latest):
                current_time = time.time()
                
                # 寫入 CSV
                row = [current_time]
                row.extend(imu1_latest if imu1_latest else [None]*9)
                row.extend(imu2_latest if imu2_latest else [None]*9)
                csv_writer.writerow(row)
                csv_file.flush()

                # 限制畫面更新率（約 20Hz），避免終端機閃爍
                if current_time - last_update_time >= 0.05:
                    print_table(imu1_latest, imu2_latest)
                    last_update_time = current_time

    except KeyboardInterrupt:
        print("\n正在關閉程式並存檔...")
    finally:
        csv_file.close()
        ser.close()
        print("已成功關閉。")

if __name__ == '__main__':
    main()
