import serial
import re
import time
import glob
import os
import sys
import statistics
import csv
import math
import matplotlib.pyplot as plt

# ================= 設定區 =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
SAMPLE_TIME = 2.0  # 每個角度採樣 2 秒
ENCODER_RESOLUTION = 4096.0  # 12-bit
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

def circular_mean_raw(raw_vals, resolution=ENCODER_RESOLUTION):
    """計算原始編碼器數值的圓心均值，避免 0/resolution 交界處的平均誤差"""
    if not raw_vals:
        return 0.0
    x = 0.0
    y = 0.0
    for r in raw_vals:
        angle_rad = (r / resolution) * 2.0 * math.pi
        x += math.cos(angle_rad)
        y += math.sin(angle_rad)
    mean_rad = math.atan2(y, x)
    mean_val = ((mean_rad / (2.0 * math.pi)) * resolution) % resolution
    if abs(mean_val - resolution) < 1e-4:
        mean_val = 0.0
    return mean_val

def circular_stdev(angles_deg, mean_deg):
    """將角度投影到 [mean - 180, mean + 180) 範圍，再計算標準差"""
    if len(angles_deg) < 2:
        return 0.0
    diffs = []
    for a in angles_deg:
        # 計算相對於 mean_deg 的偏差，範圍 [-180, 180)
        diff = (a - mean_deg + 180) % 360 - 180
        diffs.append(diff)
    return statistics.stdev(diffs)

def angular_difference(a, b):
    """計算兩個角度的最短偏差 (a - b)，結果在 [-180, 180) 區間"""
    return (a - b + 180) % 360 - 180

def collect_encoder_samples(ser, sample_duration):
    """讀取串口數據，收集指定時間內的 Encoder 樣本 (raw_val, degree)"""
    raw_vals = []
    degree_vals = []
    
    start_time = time.time()
    # 清空輸入緩衝區，確保讀取的是最新數據
    ser.reset_input_buffer()
    
    while time.time() - start_time < sample_duration:
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
                raw_vals.append(raw_val)
                degree_vals.append(degree_val)
            except ValueError:
                continue
                
    return raw_vals, degree_vals

def main():
    print(f"正在連線至 Encoder MCU ({PORT} @ {BAUD} baud)...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        print("連線成功！")
    except Exception as e:
        print(f"開啟串口錯誤: {e}")
        print("可用串口列表:")
        available_ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
        for p in available_ports:
            print(f" - {p}")
        sys.exit(1)

    print("\n=========================================================================")
    print("                     Encoder 靜態準確度測試與分析工具                    ")
    print("=========================================================================")
    print("測試步驟：")
    print("1. 將編碼器調整到指定角度（建議以精密分度盤、光學平台或已知刻度為標準參考值）。")
    print("2. 在程式中輸入該「標準角度（度）」，程式會自動收集 2 秒的靜態數據並計算均值與標準差。")
    print("3. 重複上述步驟測量多個不同的角度點（例如 0, 30, 60, 90... 330 度）。")
    print("4. 輸入 'q' 結束測試，程式將自動生成準確度分析表格，並繪製誤差曲線圖。")
    print("=========================================================================\n")

    experiments = []

    try:
        while True:
            user_input = input("👉 請調整編碼器位置，並輸入當前目標標準角度 (度)，或輸入 'q' 結束測試: ").strip()
            if user_input.lower() == 'q':
                break
                
            try:
                ref_angle = float(user_input) % 360.0
            except ValueError:
                print("輸入格式錯誤，請輸入數字或 'q'。")
                continue
                
            print(f"正在採樣 {SAMPLE_TIME} 秒，請保持編碼器完全靜態...")
            raw_samples, degree_samples = collect_encoder_samples(ser, SAMPLE_TIME)
            
            if not degree_samples:
                print("⚠️ 未收集到足夠數據，請檢查硬體接線與 SPI 通訊狀態。")
                continue
                
            # 使用 circular mean 處理角度平均
            mean_deg = circular_mean(degree_samples)
            std_deg = circular_stdev(degree_samples, mean_deg)
            mean_raw = circular_mean_raw(raw_samples)
            
            print(f"✅ 採樣完成！")
            print(f"   樣本數: {len(degree_samples)} 筆 | Raw 均值: {mean_raw:6.1f} | 角度均值: {mean_deg:6.2f}° | 標準差: {std_deg:5.3f}°\n")
            
            experiments.append({
                'ref': ref_angle,
                'raw_mean': mean_raw,
                'deg_mean': mean_deg
            })
            
    except KeyboardInterrupt:
        print("\n測試被使用者中斷。")

    if not experiments:
        print("未收集任何測試數據，程式結束。")
        ser.close()
        return

    # 排序測試點（依據參考角度由小到大）
    experiments.sort(key=lambda x: x['ref'])

    # 偵測旋轉方向是否相反
    opposite_count = 0
    same_count = 0
    for i in range(len(experiments) - 1):
        d_ref = angular_difference(experiments[i+1]['ref'], experiments[i]['ref'])
        d_meas = angular_difference(experiments[i+1]['deg_mean'], experiments[i]['deg_mean'])
        # 忽略變化量小於 1 度的噪聲或重複量測點
        if abs(d_ref) > 1.0 and abs(d_meas) > 1.0:
            if (d_ref > 0 and d_meas < 0) or (d_ref < 0 and d_meas > 0):
                opposite_count += 1
            else:
                same_count += 1
                
    auto_invert = opposite_count > same_count
    
    dir_prompt = f"\n👉 是否啟用方向反轉修正？偵測結果建議: {'是 (Y)' if auto_invert else '否 (N)'} (輸入 y/n/auto，直接按 Enter 預設為 auto): "
    dir_choice = input(dir_prompt).strip().lower()
    
    if dir_choice == 'y':
        invert_direction = True
    elif dir_choice == 'n':
        invert_direction = False
    else:
        invert_direction = auto_invert
        
    print(f"已{'啟用' if invert_direction else '停用'}方向反轉修正。")

    # 讓使用者選擇以哪個量測點作為校正基準
    print("\n可用於校正的參考角度點：")
    for idx, exp in enumerate(experiments):
        # 根據是否反向來顯示量測均值
        display_deg = (360.0 - exp['deg_mean']) % 360.0 if invert_direction else exp['deg_mean']
        print(f" [{idx}] 參考角: {exp['ref']:6.2f}° | 量測均值: {display_deg:6.2f}°")
    
    # 預設基準點：最接近 0 度的點
    default_zero_point = None
    for exp in experiments:
        if exp['ref'] == 0:
            default_zero_point = exp
            break
    if not default_zero_point:
        default_zero_point = min(experiments, key=lambda x: abs(x['ref']))
        
    choice_prompt = f"\n👉 請選擇哪一個參考角度作為零點校正基準 (直接按 Enter 預設為 {default_zero_point['ref']}°): "
    user_choice = input(choice_prompt).strip()
    
    zero_point = None
    if user_choice == "":
        zero_point = default_zero_point
    else:
        # 嘗試解析為 index 或數值
        try:
            # 優先嘗試當成索引
            idx_choice = int(user_choice)
            if 0 <= idx_choice < len(experiments):
                zero_point = experiments[idx_choice]
        except ValueError:
            pass
            
        if not zero_point:
            # 嘗試當成角度值，尋找最接近的角度點
            try:
                angle_choice = float(user_choice)
                zero_point = min(experiments, key=lambda x: abs(angular_difference(x['ref'], angle_choice)))
            except ValueError:
                print("輸入格式無法識別，將採用預設基準點。")
                zero_point = default_zero_point

    print(f"\n已選擇 {zero_point['ref']}° 作為校正零點基準。")

    # 計算基準點處理後的量測角度
    zero_meas = (360.0 - zero_point['deg_mean']) % 360.0 if invert_direction else zero_point['deg_mean']
    # 計算 offset (Measured - Reference)
    offset = angular_difference(zero_meas, zero_point['ref'])

    print("\n=========================================================================")
    print("                         Encoder 靜態準確度分析報告                       ")
    print("=========================================================================")
    print(f"基準校正偏置 (Offset): {offset:+.3f}° (於參考角 {zero_point['ref']}° 處)")
    print(f"方向反轉修正: {'啟用 (已修正)' if invert_direction else '未啟用'}")
    print("-------------------------------------------------------------------------")
    print(" 參考角度 | 原始數值 | 量測角度 | 校正後角度 | 未校正誤差 | 校正後誤差 ")
    print(" (Ref °)  | (Raw)    | (Raw °)  | (Corr °)   | (Raw Err°) | (Corr Err°)")
    print("-------------------------------------------------------------------------")

    plot_data = {
        'ref': [],
        'err_raw': [],
        'err_corr': []
    }

    # 寫入 CSV 報告
    csv_filename = "encoder_accuracy_report.csv"
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Ref_Angle', 'Raw_Value_Mean', 'Measured_Angle_Raw', 'Corrected_Angle', 'Raw_Error', 'Corrected_Error'])
        
        for exp in experiments:
            ref = exp['ref']
            
            # 若啟用方向反轉，將原始數值與角度也做對應反向處理
            raw_mean = (ENCODER_RESOLUTION - exp['raw_mean']) % ENCODER_RESOLUTION if invert_direction else exp['raw_mean']
            deg_mean = (360.0 - exp['deg_mean']) % 360.0 if invert_direction else exp['deg_mean']
            
            # 未校正誤差 (相對於未反轉的原始量測值)
            raw_err = angular_difference(exp['deg_mean'], ref)
            
            # 校正後角度與誤差
            corr_deg = (deg_mean - offset) % 360.0
            if abs(corr_deg - 360.0) < 1e-4:
                corr_deg = 0.0
            corr_err = angular_difference(corr_deg, ref)
            
            print(f" {ref:8.2f} | {raw_mean:8.1f} | {deg_mean:8.2f} | {corr_deg:10.2f} | {raw_err:+10.2f} | {corr_err:+10.2f} ")
            writer.writerow([ref, f"{raw_mean:.2f}", f"{deg_mean:.2f}", f"{corr_deg:.2f}", f"{raw_err:.2f}", f"{corr_err:.2f}"])
            
            plot_data['ref'].append(ref)
            plot_data['err_raw'].append(raw_err)
            plot_data['err_corr'].append(corr_err)

    print("-------------------------------------------------------------------------")
    print(f"報告已成功儲存至: {os.path.abspath(csv_filename)}")
    print("=========================================================================\n")

    # 繪製誤差圖表
    plt.figure(figsize=(10, 6))
    plt.plot(plot_data['ref'], plot_data['err_raw'], 'bo--', label='Raw Error (Uncalibrated)')
    plt.plot(plot_data['ref'], plot_data['err_corr'], 'rs-', label='Corrected Error (Offset Calibrated)')
    plt.axhline(0, color='gray', linestyle=':', label='Ideal (Zero Error)')
    plt.title('Encoder Static Accuracy Analysis')
    plt.xlabel('Reference Angle (deg)')
    plt.ylabel('Measurement Error (deg)')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    print("正在開啟誤差分析曲線圖...")
    plt.show()

    ser.close()

if __name__ == '__main__':
    main()
