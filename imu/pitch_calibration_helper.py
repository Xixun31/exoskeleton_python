import serial
import re
import time
import glob
import os
import sys
import statistics
import csv
import matplotlib.pyplot as plt

# ================= 設定區 =================
ports = glob.glob('/dev/ttyACM*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
SAMPLE_TIME = 2.0  # 每個角度採樣 2 秒
# ==========================================

def collect_pitch_samples(ser, sample_duration):
    """讀取串口數據，收集指定時間內的 Pitch 樣本"""
    imu1_pitches = []
    imu2_pitches = []
    
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
            
        is_imu1 = line.startswith("IMU1 ->")
        is_imu2 = line.startswith("IMU2 ->")
        
        if is_imu1 or is_imu2:
            prefix = "IMU1 ->" if is_imu1 else "IMU2 ->"
            content = line[len(prefix):]
            nums = re.findall(r"[-+]?\d*\.\d+|\d+", content)
            
            if len(nums) == 9:
                try:
                    pitch_val = float(nums[1])  # Index 1 是 Pitch
                    if is_imu1:
                        imu1_pitches.append(pitch_val)
                    else:
                        imu2_pitches.append(pitch_val)
                except ValueError:
                    continue
                    
    return imu1_pitches, imu2_pitches

def main():
    print(f"正在連線至 STM32 ({PORT} @ {BAUD} baud)...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        print("連線成功！")
    except Exception as e:
        print(f"開啟串口錯誤: {e}")
        sys.exit(1)

    print("\n=========================================================================")
    print("                    雙 IMU Pitch 靜態準確度測試與校正工具                ")
    print("=========================================================================")
    print("測試步驟：")
    print("1. 將斜板調整到指定角度（建議以數位角度計/傾角儀作為標準參考值）。")
    print("2. 在程式中輸入該「標準角度（度）」，程式會自動收集 2 秒的靜態 Pitch 數據並計算均值。")
    print("3. 重複上述步驟測量多個不同的角度點（例如 0, 5, 10, 15, 20... 度）。")
    print("4. 輸入 'q' 結束測試，程式將自動生成準確度分析表格，並繪製誤差曲線圖。")
    print("=========================================================================\n")

    experiments = []

    try:
        while True:
            user_input = input("👉 請調整斜板，並輸入當前目標標準角度 (度)，或輸入 'q' 結束測試: ").strip()
            if user_input.lower() == 'q':
                break
                
            try:
                ref_angle = float(user_input)
            except ValueError:
                print("輸入格式錯誤，請輸入數字或 'q'。")
                continue
                
            print(f"正在採樣 {SAMPLE_TIME} 秒，請保持斜板完全靜止...")
            imu1_samples, imu2_samples = collect_pitch_samples(ser, SAMPLE_TIME)
            
            if not imu1_samples or not imu2_samples:
                print("⚠️ 未收集到足夠數據，請檢查硬體接線與編譯燒錄狀態。")
                continue
                
            imu1_mean = statistics.mean(imu1_samples)
            imu1_std = statistics.stdev(imu1_samples) if len(imu1_samples) >= 2 else 0
            
            imu2_mean = statistics.mean(imu2_samples)
            imu2_std = statistics.stdev(imu2_samples) if len(imu2_samples) >= 2 else 0
            
            print(f"✅ 採樣完成！")
            print(f"   [IMU 1] 樣本數: {len(imu1_samples)} 筆 | Pitch 均值: {imu1_mean:6.2f}° | 標準差: {imu1_std:5.3f}°")
            print(f"   [IMU 2] 樣本數: {len(imu2_samples)} 筆 | Pitch 均值: {imu2_mean:6.2f}° | 標準差: {imu2_std:5.3f}°\n")
            
            experiments.append({
                'ref': ref_angle,
                'imu1_raw': imu1_mean,
                'imu2_raw': imu2_mean
            })
            
    except KeyboardInterrupt:
        print("\n測試被使用者中斷。")

    if not experiments:
        print("未收集任何測試數據，程式結束。")
        ser.close()
        return

    # 排序測試點（依據參考角度由小到大）
    experiments.sort(key=lambda x: x['ref'])

    # 尋找 0 度（或最接近 0 度）的數據點作為安裝偏差（Installation Offset）校正基準
    zero_point = None
    for exp in experiments:
        if exp['ref'] == 0:
            zero_point = exp
            break
    if not zero_point:
        # 若沒有測 0 度，則以參考角絕對值最小的點作為 offset 基準
        zero_point = min(experiments, key=lambda x: abs(x['ref']))

    offset1 = zero_point['imu1_raw'] - zero_point['ref']
    offset2 = zero_point['imu2_raw'] - zero_point['ref']

    print("\n=========================================================================")
    print("                         Pitch 靜態準確度分析報告                        ")
    print("=========================================================================")
    print(f"基準校正偏置 (Offset):")
    print(f"  [IMU 1] Offset: {offset1:+.3f}° (於參考角 {zero_point['ref']}° 處)")
    print(f"  [IMU 2] Offset: {offset2:+.3f}° (於參考角 {zero_point['ref']}° 處)")
    print("-------------------------------------------------------------------------")
    print(" 參考角度 | IMU1 量測 | IMU1 校正後 | IMU1 誤差 | IMU2 量測 | IMU2 校正後 | IMU2 誤差 ")
    print(" (Ref °)  | (Raw °)   | (Corr °)    | (Err °)   | (Raw °)   | (Corr °)    | (Err °)  ")
    print("-------------------------------------------------------------------------")

    plot_data = {
        'ref': [],
        'imu1_err_raw': [], 'imu1_err_corr': [],
        'imu2_err_raw': [], 'imu2_err_corr': []
    }

    # 寫入 CSV 報告
    csv_filename = "pitch_accuracy_report.csv"
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Ref_Angle', 'IMU1_Raw', 'IMU1_Corrected', 'IMU1_Error', 'IMU2_Raw', 'IMU2_Corrected', 'IMU2_Error'])
        
        for exp in experiments:
            ref = exp['ref']
            
            imu1_c = exp['imu1_raw'] - offset1
            imu1_e = imu1_c - ref
            
            imu2_c = exp['imu2_raw'] - offset2
            imu2_e = imu2_c - ref
            
            print(f" {ref:8.2f} | {exp['imu1_raw']:9.2f} | {imu1_c:11.2f} | {imu1_e:+9.2f} | {exp['imu2_raw']:9.2f} | {imu2_c:11.2f} | {imu2_e:+9.2f} ")
            writer.writerow([ref, exp['imu1_raw'], imu1_c, imu1_e, exp['imu2_raw'], imu2_c, imu2_e])
            
            plot_data['ref'].append(ref)
            plot_data['imu1_err_raw'].append(exp['imu1_raw'] - ref)
            plot_data['imu1_err_corr'].append(imu1_e)
            plot_data['imu2_err_raw'].append(exp['imu2_raw'] - ref)
            plot_data['imu2_err_corr'].append(imu2_e)

    print("-------------------------------------------------------------------------")
    print(f"報告已成功儲存至: {os.path.abspath(csv_filename)}")
    print("=========================================================================\n")

    # 繪製誤差圖表
    plt.figure(figsize=(10, 6))
    plt.plot(plot_data['ref'], plot_data['imu1_err_corr'], 'ro-', label='IMU 1 (Corrected Error)')
    plt.plot(plot_data['ref'], plot_data['imu2_err_corr'], 'bs--', label='IMU 2 (Corrected Error)')
    plt.axhline(0, color='gray', linestyle=':', label='Ideal (Zero Error)')
    plt.title('Pitch Static Accuracy Analysis (Offset Calibrated)')
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
