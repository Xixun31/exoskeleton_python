import csv
import math
import statistics
import os
import sys

CSV_FILE = 'imu_data.csv'

def analyze_data(file_path):
    if not os.path.exists(file_path):
        print(f"找不到數據檔案: {os.path.abspath(file_path)}")
        print("請先執行 python3 stm32_dual_imu_table.py 收集一些靜態數據。")
        return

    # 讀取 CSV 數據
    data_columns = {
        'IMU1_Roll': [], 'IMU1_Pitch': [], 'IMU1_Yaw': [],
        'IMU1_AccX': [], 'IMU1_AccY': [], 'IMU1_AccZ': [],
        'IMU1_GyroX': [], 'IMU1_GyroY': [], 'IMU1_GyroZ': [],
        'IMU2_Roll': [], 'IMU2_Pitch': [], 'IMU2_Yaw': [],
        'IMU2_AccX': [], 'IMU2_AccY': [], 'IMU2_AccZ': [],
        'IMU2_GyroX': [], 'IMU2_GyroY': [], 'IMU2_GyroZ': []
    }

    headers = []
    row_count = 0

    with open(file_path, 'r') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            print("數據檔案為空。")
            return

        for row in reader:
            if not row:
                continue
            row_count += 1
            # 填入數據，忽略 None 或空值
            for key in data_columns.keys():
                if key in headers:
                    idx = headers.index(key)
                    if idx < len(row) and row[idx].strip() and row[idx].strip() != 'None':
                        try:
                            data_columns[key].append(float(row[idx]))
                        except ValueError:
                            pass

    if row_count < 10:
        print(f"數據量不足 (目前僅 {row_count} 筆)，請收集至少 100 筆 (約 5 秒) 靜態數據再進行分析。")
        return

    print("====================================================================================")
    print(f"                          雙 IMU 靜態誤差分析報告 (樣本數: {row_count} 筆)                     ")
    print("====================================================================================")
    print("說明：")
    print("1. 均值 (Mean / Bias)：在完全靜止下，陀螺儀應為 0，水平放置時 Acc X/Y 應為 0，Acc Z 應為 9.81 m/s²。")
    print("2. 標準差 (Std Dev / Noise)：代表高頻噪聲大小，數值越小表示信號越純淨、雜訊越低。")
    print("3. 峰對峰值 (Peak-to-Peak)：最大值與最小值的差，代表噪聲的最大波動範圍。")
    print("------------------------------------------------------------------------------------")

    def print_imu_report(name, imu_prefix):
        print(f"\n>>> 【 {name} 靜態性能指標 】")
        print("+------------------+------------------+------------------+------------------+")
        print("| 數據項目         | 均值 (Bias)      | 標準差 (Noise)   | 峰對峰值 (P-P)   |")
        print("+------------------+------------------+------------------+------------------+")
        
        metrics = [
            ('Roll  (deg)', f'{imu_prefix}_Roll'),
            ('Pitch (deg)', f'{imu_prefix}_Pitch'),
            ('Yaw   (deg)', f'{imu_prefix}_Yaw'),
            ('Acc X (m/s²)', f'{imu_prefix}_AccX'),
            ('Acc Y (m/s²)', f'{imu_prefix}_AccY'),
            ('Acc Z (m/s²)', f'{imu_prefix}_AccZ'),
            ('Gyro X(deg/s)', f'{imu_prefix}_GyroX'),
            ('Gyro Y(deg/s)', f'{imu_prefix}_GyroY'),
            ('Gyro Z(deg/s)', f'{imu_prefix}_GyroZ'),
        ]

        for label, col in metrics:
            vals = data_columns[col]
            if len(vals) >= 2:
                mean_val = statistics.mean(vals)
                std_val = statistics.stdev(vals)
                p2p_val = max(vals) - min(vals)
                print(f"| {label:<16} | {mean_val:>16.4f} | {std_val:>16.4f} | {p2p_val:>16.4f} |")
            else:
                print(f"| {label:<16} | {'N/A':>16} | {'N/A':>16} | {'N/A':>16} |")
        print("+------------------+------------------+------------------+------------------+")

    print_imu_report("IMU 1 (接腳 PA9/PA10)", "IMU1")
    print_imu_report("IMU 2 (接腳 PC10/PC11)", "IMU2")

if __name__ == '__main__':
    # 可以由命令列指定檔案路徑，否則預設為 imu_data.csv
    file_path = sys.argv[1] if len(sys.argv) > 1 else CSV_FILE
    analyze_data(file_path)
