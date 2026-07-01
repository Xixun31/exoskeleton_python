import serial
import re
import csv
import time
import glob
import os
import sys
import matplotlib.pyplot as plt

# ================= 設定區 =================
ports = glob.glob('/dev/ttyACM*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
CSV_FILE = 'dynamic_pitch_data.csv'
# ==========================================

def main():
    print(f"正在連線至 STM32 ({PORT} @ {BAUD} baud)...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print("連線成功！")
    except Exception as e:
        print(f"開啟串口錯誤: {e}")
        sys.exit(1)

    print("\n=========================================================================")
    print("                      雙 IMU 動態 Pitch 數據錄製工具                     ")
    print("=========================================================================")
    print("說明：")
    print("1. 請將兩個 IMU 固定於斜板上。")
    print("2. 程式啟動後會開始錄製 Pitch 隨時間變化的數據。")
    print("3. 你可以開始在 0 到 90 度之間來回移動斜板數次。")
    print("4. 結束後，按 Ctrl+C 停止錄製。程式會存檔並自動繪製動態軌跡對比圖。")
    print("=========================================================================\n")

    input("👉 準備好後請按 [Enter] 開始錄製...")

    # 建立或覆蓋 CSV 檔案
    try:
        csvfile = open(CSV_FILE, 'w', newline='')
        writer = csv.writer(csvfile)
        writer.writerow(['Timestamp', 'Relative_Time', 'IMU1_Pitch', 'IMU2_Pitch', 'Difference'])
        csvfile.flush()
    except Exception as e:
        print(f"無法建立 CSV 檔案: {e}")
        ser.close()
        sys.exit(1)

    start_time = time.time()
    imu1_latest = None
    imu2_latest = None
    
    # 用於在終端機顯示的更新時間限制
    last_print_time = 0
    
    # 快取記憶體中繪圖用的數據
    time_series = []
    imu1_series = []
    imu2_series = []
    diff_series = []

    print("\n🔴 正在錄製中... 請開始來回移動斜板。按 Ctrl+C 可停止並繪圖。\n")

    try:
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
            except Exception as e:
                print(f"\n讀取串口時出錯: {e}")
                break

            if not line:
                continue

            is_imu1 = line.startswith("IMU1 ->")
            is_imu2 = line.startswith("IMU2 ->")

            if is_imu1 or is_imu2:
                prefix = "IMU1 ->" if is_imu1 else "IMU2 ->"
                content = line[len(prefix):]
                nums = re.findall(r"[-+]?\d*\.\d+|\d+", content)
                
                if len(nums) == 9:
                    try:
                        pitch_val = float(nums[1]) # Index 1 是 Pitch
                        if is_imu1:
                            imu1_latest = pitch_val
                        else:
                            imu2_latest = pitch_val
                    except ValueError:
                        continue

            # 當偵測到數據輸出輪詢結束時（分隔線）寫入資料點
            if line.startswith("---") and imu1_latest is not None and imu2_latest is not None:
                current_time = time.time()
                elapsed = current_time - start_time
                diff = imu1_latest - imu2_latest

                # 寫入 CSV
                writer.writerow([current_time, elapsed, imu1_latest, imu2_latest, diff])
                csvfile.flush()

                # 快取到記憶體供後續繪圖
                time_series.append(elapsed)
                imu1_series.append(imu1_latest)
                imu2_series.append(imu2_latest)
                diff_series.append(diff)

                # 限制終端機輸出頻率為 5Hz，避免洗屏過快
                if elapsed - last_print_time >= 0.2:
                    sys.stdout.write(f"\r[錄製中 | 時間: {elapsed:5.1f}s] IMU1 Pitch: {imu1_latest:6.2f}° | IMU2 Pitch: {imu2_latest:6.2f}° | 差異: {diff:+6.2f}°")
                    sys.stdout.flush()
                    last_print_time = elapsed

    except KeyboardInterrupt:
        print("\n\n停止錄製，正在關閉串口...")
    finally:
        csvfile.close()
        ser.close()

    if not time_series:
        print("未錄製到任何數據點。")
        return

    print("=========================================================================")
    print(f"數據已成功儲存至: {os.path.abspath(CSV_FILE)} (共 {len(time_series)} 筆數據)")
    print("=========================================================================\n")

    # 繪製動態對比圖
    print("正在繪製動態軌跡對比圖...")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # 子圖 1: 兩個 IMU 的 Pitch 動態變化軌跡
    ax1.plot(time_series, imu1_series, 'r-', label='IMU 1 (PA9/PA10)', linewidth=1.5)
    ax1.plot(time_series, imu2_series, 'b--', label='IMU 2 (PC10/PC11)', linewidth=1.5)
    ax1.set_title('Dynamic Pitch Tracking Comparison', fontsize=12)
    ax1.set_ylabel('Pitch Angle (deg)', fontsize=10)
    ax1.grid(True, linestyle=':')
    ax1.legend(loc='upper right')

    # 子圖 2: 兩個 IMU 之間的差值 (IMU1 - IMU2)
    ax2.plot(time_series, diff_series, 'g-', label='Difference (IMU1 - IMU2)', linewidth=1.2)
    ax2.axhline(0, color='red', linestyle='--', linewidth=0.8, alpha=0.7)
    ax2.set_title('Dynamic Angle Difference Over Time', fontsize=12)
    ax2.set_xlabel('Time (seconds)', fontsize=10)
    ax2.set_ylabel('Angle Difference (deg)', fontsize=10)
    ax2.grid(True, linestyle=':')
    ax2.legend(loc='upper right')

    # 儲存圖表圖片
    plot_image_path = 'dynamic_pitch_plot.png'
    plt.tight_layout()
    plt.savefig(plot_image_path, dpi=150)
    print(f"圖表圖片已存檔至: {os.path.abspath(plot_image_path)}")

    # 顯示圖表
    print("正在開啟即時軌跡圖...")
    plt.show()

if __name__ == '__main__':
    main()
