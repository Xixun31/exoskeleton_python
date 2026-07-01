import csv
import math
import statistics
import os
import matplotlib.pyplot as plt

# ================= 您的量測數據 =================
# (參考角, 原始數值, 量測角度)
raw_data = [
    (0.00, 2654.6, 233.31),
    (15.00, 2477.3, 217.74),
    (30.00, 2329.3, 204.73),
    (45.00, 2144.6, 188.50),
    (45.00, 2142.2, 188.28),
    (60.00, 1994.4, 175.29),
    (75.00, 1826.0, 160.49),
    (90.00, 1634.3, 143.64),
    (105.00, 1476.2, 129.75),
    (120.00, 1310.8, 115.21),
    (135.00, 1148.3, 100.93),
    (150.00, 949.6, 83.46),
    (165.00, 753.0, 66.18),
    (165.00, 797.9, 70.13),
    (180.00, 625.4, 54.97),
    (195.00, 462.7, 40.66),
    (210.00, 299.0, 26.28),
    (225.00, 118.3, 10.40),
    (240.00, 4063.3, 357.12),
    (255.00, 3881.6, 341.15),
    (270.00, 3698.9, 325.10),
    (285.00, 3568.1, 313.60),
    (300.00, 3355.5, 294.92),
    (300.00, 3381.3, 297.19),
    (315.00, 3231.7, 284.04),
    (330.00, 3088.2, 271.42),
    (345.00, 2882.8, 253.37),
    (360.00, 2715.7, 238.68),
]
# ===============================================

ENCODER_RESOLUTION = 4096.0

def angular_difference(a, b):
    """計算兩個角度的最短偏差 (a - b)，結果在 [-180, 180) 區間"""
    return (a - b + 180) % 360 - 180

def main():
    # 啟用方向反轉修正 (因為量測值與參考值呈反比變化)
    invert_direction = True
    print("已啟用方向反轉修正 (Direction Inversion)。")

    # 選擇 Ref 0.00 (第一筆) 作為零點校正基準
    zero_point_ref = 0.0
    zero_point_measured = 233.31
    
    # 計算基準點處理後(反向)的量測角度
    zero_meas_proc = (360.0 - zero_point_measured) % 360.0
    
    # 計算 offset (Measured_proc - Reference)
    offset = angular_difference(zero_meas_proc, zero_point_ref)

    print("\n=========================================================================")
    print("                         Encoder 靜態準確度分析報告                       ")
    print("=========================================================================")
    print(f"基準校正偏置 (Offset): {offset:+.3f}° (於參考角 {zero_point_ref}° 處)")
    print(f"方向反向修正: 啟用 (已修正)")
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
    csv_filename = "encoder_accuracy_report_real.csv"
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Ref_Angle', 'Raw_Value_Mean', 'Measured_Angle_Raw', 'Corrected_Angle', 'Raw_Error', 'Corrected_Error'])
        
        for ref, raw, deg in raw_data:
            # 處理方向反轉後的對應數值與角度
            raw_proc = (ENCODER_RESOLUTION - raw) % ENCODER_RESOLUTION if invert_direction else raw
            deg_proc = (360.0 - deg) % 360.0 if invert_direction else deg
            
            # 未校正誤差 (相對於原始量測值)
            raw_err = angular_difference(deg, ref)
            
            # 校正後角度與誤差
            corr_deg = (deg_proc - offset) % 360.0
            if abs(corr_deg - 360.0) < 1e-4:
                corr_deg = 0.0
            corr_err = angular_difference(corr_deg, ref)
            
            print(f" {ref:8.2f} | {raw:8.1f} | {deg:8.2f} | {corr_deg:10.2f} | {raw_err:+10.2f} | {corr_err:+10.2f} ")
            writer.writerow([ref, f"{raw:.2f}", f"{deg:.2f}", f"{corr_deg:.2f}", f"{raw_err:.2f}", f"{corr_err:.2f}"])
            
            plot_data['ref'].append(ref)
            plot_data['err_raw'].append(raw_err)
            plot_data['err_corr'].append(corr_err)

    print("-------------------------------------------------------------------------")
    print(f"報告已成功儲存至: {os.path.abspath(csv_filename)}")
    print("=========================================================================\n")

    # 繪製誤差圖表
    plt.figure(figsize=(10, 6))
    plt.plot(plot_data['ref'], plot_data['err_raw'], 'bo--', label='Raw Error (Uncalibrated)')
    plt.plot(plot_data['ref'], plot_data['err_corr'], 'rs-', label='Corrected Error (Offset + Direction Calibrated)')
    plt.axhline(0, color='gray', linestyle=':', label='Ideal (Zero Error)')
    plt.title('Encoder Static Accuracy Analysis (Real Collected Data)')
    plt.xlabel('Reference Angle (deg)')
    plt.ylabel('Measurement Error (deg)')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    
    # 儲存圖檔
    plot_filename = "encoder_accuracy_plot_real.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"誤差分析圖表已儲存至: {os.path.abspath(plot_filename)}")
    
    print("正在開啟誤差分析曲線圖視窗...")
    plt.show()

if __name__ == '__main__':
    main()
