import serial
import re
import csv
import time
import glob
import os
import sys
import math
import statistics
import matplotlib.pyplot as plt

# ================= 設定區 =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
CSV_FILE = 'dynamic_encoder_data.csv'
# ==========================================

def circular_mean(angles_deg):
    """計算角度的圓心均值，避免 0/360 度交界處的平均誤差"""
    if not angles_deg:
        return 0.0
    x = 0.0
    y = 0.0
    for a in angles_deg:
        rad = math.radians(a)
        x += math.cos(rad)
        y += math.sin(rad)
    mean_rad = math.atan2(y, x)
    mean_deg = math.degrees(mean_rad) % 360.0
    if abs(mean_deg - 360.0) < 1e-4:
        mean_deg = 0.0
    return mean_deg

def angular_difference(a, b):
    """計算兩個角度的最短偏差 (a - b)，結果在 [-180, 180) 區間"""
    return (a - b + 180) % 360 - 180

def main():
    print(f"正在連線至 Encoder MCU ({PORT} @ {BAUD} baud)...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        ser.reset_input_buffer()
        print("連線成功！")
    except Exception as e:
        print(f"開啟串口錯誤: {e}")
        print("可用串口列表:")
        available_ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
        for p in available_ports:
            print(f" - {p}")
        sys.exit(1)

    print("\n=========================================================================")
    print("                     Encoder 動態範圍誤差測試與分析工具                   ")
    print("=========================================================================")
    print("說明：")
    print("1. 程式啟動後會連續錄製編碼器的角度與角速度。")
    print("2. 您可以快速旋轉編碼器（例如快速轉 90 度三次、180 度三次），每次轉完請靜止 1~2 秒。")
    print("3. 結束時按 [Ctrl+C] 停止，程式會自動識別出每次的旋轉區間，計算誤差並繪製軌跡。")
    print("=========================================================================\n")

    input("👉 準備好後請按 [Enter] 開始錄製...")

    # 建立 CSV 檔案
    try:
        csvfile = open(CSV_FILE, 'w', newline='')
        writer = csv.writer(csvfile)
        writer.writerow(['Timestamp', 'Relative_Time', 'Raw_Value', 'Angle', 'Velocity'])
        csvfile.flush()
    except Exception as e:
        print(f"無法建立 CSV 檔案: {e}")
        ser.close()
        sys.exit(1)

    start_time = time.time()
    time_series = []
    raw_series = []
    angle_series = []
    velocity_series = []

    # 用於顯示的計時器與暫存器
    last_print_time = 0

    print("\n🔴 正在錄製中... 請開始進行旋轉測試。按 [Ctrl+C] 可停止並分析。\n")

    try:
        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
            except Exception as e:
                print(f"\n讀取串口時出錯: {e}")
                break

            if not line:
                continue

            parts = line.split(',')
            if len(parts) == 2:
                try:
                    raw_val = int(parts[0].strip())
                    degree_val = float(parts[1].strip())
                except ValueError:
                    continue

                current_time = time.time()
                elapsed = current_time - start_time

                # 計算角速度 (使用相鄰樣本，若有 4 個樣本以上則使用 3 階差分平滑噪聲)
                velocity = 0.0
                if len(time_series) >= 3:
                    dt = elapsed - time_series[-3]
                    if dt > 0:
                        d_theta = angular_difference(degree_val, angle_series[-3])
                        velocity = d_theta / dt
                elif len(time_series) >= 1:
                    dt = elapsed - time_series[-1]
                    if dt > 0:
                        d_theta = angular_difference(degree_val, angle_series[-1])
                        velocity = d_theta / dt

                time_series.append(elapsed)
                raw_series.append(raw_val)
                angle_series.append(degree_val)
                velocity_series.append(velocity)

                # 寫入 CSV
                writer.writerow([current_time, f"{elapsed:.4f}", raw_val, f"{degree_val:.2f}", f"{velocity:.2f}"])
                
                # 每 10 筆資料 flush 一次，提高效率
                if len(time_series) % 10 == 0:
                    csvfile.flush()

                # 限制終端機輸出頻率為 5Hz
                if elapsed - last_print_time >= 0.2:
                    sys.stdout.write(f"\r[錄製中 | 時間: {elapsed:5.1f}s] Raw: {raw_val:4d} | 角度: {degree_val:6.2f}° | 角速度: {velocity:+7.1f}°/s")
                    sys.stdout.flush()
                    last_print_time = elapsed

    except KeyboardInterrupt:
        print("\n\n停止錄製，正在關閉串口...")
    finally:
        csvfile.close()
        ser.close()

    if not time_series:
        print("未錄製到任何數據。")
        return

    print("=========================================================================")
    print(f"數據已成功儲存至: {os.path.abspath(CSV_FILE)} (共 {len(time_series)} 筆數據)")
    print("=========================================================================\n")

    # ================= 旋轉動作辨識與誤差分析 =================
    print("正在分析旋轉區間...")
    VEL_THRESHOLD = 25.0  # 判定處於運動狀態的角速度閥值 (deg/s)
    STATIC_WINDOW = 8     # 判定進入靜態所需的連續低速樣本數 (約 400ms)
    
    state = "static"      # 目前狀態: "static" 或 "moving"
    movements = []
    curr_movement_sum = 0.0
    segment_start_idx = 0
    start_time_segment = 0
    start_angle = 0
    
    i = 1
    n = len(time_series)
    while i < n:
        is_moving_now = abs(velocity_series[i]) > VEL_THRESHOLD
        
        if state == "static":
            if is_moving_now:
                # 由靜止進入運動狀態
                start_window = angle_series[max(0, i-5):i]
                start_angle = circular_mean(start_window)
                start_time_segment = time_series[i]
                state = "moving"
                # 包括從靜止到開始運動的第一步
                curr_movement_sum = angular_difference(angle_series[i], angle_series[i-1])
                segment_start_idx = i
                
        elif state == "moving":
            # 累加旋轉位移量
            step = angular_difference(angle_series[i], angle_series[i-1])
            curr_movement_sum += step
            
            if not is_moving_now:
                # 檢查接下來的 samples 是否都處於靜止狀態，確保不是單點噪聲
                is_really_static = True
                for j in range(i, min(n, i + STATIC_WINDOW)):
                    if abs(velocity_series[j]) > VEL_THRESHOLD:
                        is_really_static = False
                        break
                        
                if is_really_static:
                    # 包含減速到完全靜止期間的所有微小步進
                    for j in range(i, min(n, i + STATIC_WINDOW)):
                        step = angular_difference(angle_series[j], angle_series[j-1])
                        curr_movement_sum += step
                        
                    # 判定動作結束，進入靜止狀態
                    end_time_segment = time_series[min(n-1, i + STATIC_WINDOW - 1)]
                    end_window = angle_series[i:min(n, i + STATIC_WINDOW)]
                    end_angle = circular_mean(end_window)
                    
                    # 忽略小於 10 度的微小震動
                    if abs(curr_movement_sum) > 10.0:
                        movements.append({
                            'start_time': start_time_segment,
                            'end_time': end_time_segment,
                            'start_angle': start_angle,
                            'end_angle': end_angle,
                            'accumulated_change': curr_movement_sum
                        })
                    state = "static"
                    i += STATIC_WINDOW - 1
                    continue
        i += 1

    # 輸出動作分析報告
    print("\n=========================================================================")
    print("                      動態旋轉區間分析報告                              ")
    print("=========================================================================")
    if not movements:
        print("未偵測到明顯的旋轉動作。")
    else:
        print(" 序號 | 開始時間 | 結束時間 | 起始角度 | 結束角度 | 實際變化量 | 預期角度 | 誤差")
        print("-------------------------------------------------------------------------")
        for idx, m in enumerate(movements):
            change = m['accumulated_change']
            abs_change = abs(change)
            
            # 自動判定是 90, 180, 270 還是 360 度旋轉
            expected = None
            if abs(abs_change - 90.0) < 20.0:
                expected = 90.0 * (1.0 if change > 0 else -1.0)
            elif abs(abs_change - 180.0) < 30.0:
                expected = 180.0 * (1.0 if change > 0 else -1.0)
            elif abs(abs_change - 270.0) < 40.0:
                expected = 270.0 * (1.0 if change > 0 else -1.0)
            elif abs(abs_change - 360.0) < 45.0:
                expected = 360.0 * (1.0 if change > 0 else -1.0)
                
            if expected is not None:
                err = abs_change - abs(expected)
                err_str = f"{err:+.2f}°"
                exp_str = f"{expected:+.0f}°"
            else:
                err_str = "N/A"
                exp_str = "未知"
                
            print(f"  #{idx+1:<2} |  {m['start_time']:5.1f}s |  {m['end_time']:5.1f}s |  {m['start_angle']:6.1f}° |  {m['end_angle']:6.1f}° |   {change:+7.2f}° |   {exp_str:<6} | {err_str}")
        print("-------------------------------------------------------------------------")
    print("=========================================================================\n")

    # ================= 繪製動態軌跡圖 =================
    print("正在繪製動態軌跡圖...")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # 子圖 1: 角度與角速度隨時間變化
    color = 'tab:blue'
    ax1.set_title('Dynamic Encoder Position & Velocity Over Time', fontsize=14)
    ax1.set_ylabel('Encoder Angle (Degrees)', color=color, fontsize=12)
    ax1.plot(time_series, angle_series, color=color, label='Encoder Angle', linewidth=1.5)
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.set_ylim(-10, 370)
    ax1.grid(True, linestyle=':')

    # 重疊繪製角速度
    ax1_vel = ax1.twinx()
    color_vel = 'tab:red'
    ax1_vel.set_ylabel('Angular Velocity (deg/s)', color=color_vel, fontsize=12)
    ax1_vel.plot(time_series, velocity_series, color=color_vel, alpha=0.5, linestyle='--', label='Velocity', linewidth=1.0)
    ax1_vel.tick_params(axis='y', labelcolor=color_vel)
    
    # 標記偵測到的旋轉區間
    for idx, m in enumerate(movements):
        ax1.axvspan(m['start_time'], m['end_time'], color='green', alpha=0.15)
        # 在區間上方加上標示
        mid_time = (m['start_time'] + m['end_time']) / 2.0
        ax1.text(mid_time, 340, f"#{idx+1}\n{m['accumulated_change']:+.1f}°", 
                 horizontalalignment='center', color='darkgreen', weight='bold', fontsize=9)

    # 子圖 2: 原始編碼器數值 (Counts)
    ax2.plot(time_series, raw_series, 'tab:orange', label='Raw Encoder Value (Counts)', linewidth=1.5)
    ax2.set_title('Raw 12-bit Encoder Counts Over Time', fontsize=12)
    ax2.set_xlabel('Time (seconds)', fontsize=12)
    ax2.set_ylabel('Counts (0-4095)', fontsize=12)
    ax2.set_ylim(-100, 4200)
    ax2.grid(True, linestyle=':')
    ax2.legend(loc='upper right')

    plt.tight_layout()
    
    # 儲存圖檔
    plot_filename = 'dynamic_encoder_plot.png'
    plt.savefig(plot_filename, dpi=150)
    print(f"圖表已成功儲存至: {os.path.abspath(plot_filename)}")

    print("正在開啟即時軌跡圖...")
    plt.show()

if __name__ == '__main__':
    main()
