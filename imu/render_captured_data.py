import csv
import os
import matplotlib.pyplot as plt

# 從你終端機緩衝區中擷取出的靜態有效數據 (排除移動中的數據點)
experiments = [
    {'ref': 0.0,  'imu1_raw': 0.77,  'imu2_raw': -0.50},
    {'ref': 10.0, 'imu1_raw': 9.92,  'imu2_raw': 9.16},
    {'ref': 20.0, 'imu1_raw': 20.51, 'imu2_raw': 19.98},
    {'ref': 30.0, 'imu1_raw': 29.52, 'imu2_raw': 29.27},
    {'ref': 40.0, 'imu1_raw': 39.70, 'imu2_raw': 39.63},
    {'ref': 50.0, 'imu1_raw': 50.95, 'imu2_raw': 50.98},
    {'ref': 60.0, 'imu1_raw': 59.53, 'imu2_raw': 59.84},
    {'ref': 70.0, 'imu1_raw': 69.99, 'imu2_raw': 70.29},
    {'ref': 80.0, 'imu1_raw': 79.43, 'imu2_raw': 79.58},
    {'ref': 90.0, 'imu1_raw': 89.25, 'imu2_raw': 89.39}
]

# 計算 0° 處的安裝偏置 (Offset)
offset1 = 0.77 - 0.0
offset2 = -0.50 - 0.0

print("\n=========================================================================")
# 輸出表格
print("                         Pitch 靜態準確度分析報告                        ")
print("=========================================================================")
print(f"基準校正偏置 (Offset):")
print(f"  [IMU 1] Offset: {offset1:+.3f}° (於參考角 0.0° 處)")
print(f"  [IMU 2] Offset: {offset2:+.3f}° (於參考角 0.0° 處)")
print("-------------------------------------------------------------------------")
print(" 參考角度 | IMU1 量測 | IMU1 校正後 | IMU1 誤差 | IMU2 量測 | IMU2 校正後 | IMU2 誤差 ")
print(" (Ref °)  | (Raw °)   | (Corr °)    | (Err °)   | (Raw °)   | (Corr °)    | (Err °)  ")
print("-------------------------------------------------------------------------")

plot_data = {
    'ref': [],
    'imu1_err_corr': [],
    'imu2_err_corr': []
}

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
        plot_data['imu1_err_corr'].append(imu1_e)
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
