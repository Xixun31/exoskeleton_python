import pandas as pd
import json
import matplotlib.pyplot as plt
import numpy as np  # 新增 numpy 用於訊號內插與對齊

# ================= 設定區 =================
SOFTWARE_FILE = 'software_data.csv' 
PYTHON_FILE = 'gait_data_output.json'
TARGET_INTERVAL_SEC = 0.02  # 目標重取樣頻率：每 0.02 秒一筆 (50Hz)
# ==========================================

def main():
    print("讀取並進行訊號處理 (去突波、平滑化、重取樣)...")

    # ---------------------------------------------------------
    # 1. 處理原廠軟體數據
    # ---------------------------------------------------------
    try:
        df_software = pd.read_csv(SOFTWARE_FILE)
        
        all_cols = [f'L{i}' for i in range(1, 19)] + [f'R{i}' for i in range(1, 19)]
        software_combined_total = df_software[all_cols].sum(axis=1).tolist()
        
        df_software['Time'] = pd.to_datetime(df_software['Time'])
        software_time = (df_software['Time'] - df_software['Time'].iloc[0]).dt.total_seconds().tolist()
        
        # 🛠️ 訊號處理：移動平均平滑化 (Smoothing)
        # 用前後 10 筆數據平均，消除鋸齒毛邊
        sw_series = pd.Series(software_combined_total)
        sw_smooth = sw_series.rolling(window=10, min_periods=1, center=True).mean().tolist()
        
    except Exception as e:
        print(f"❌ 讀取軟體檔案失敗: {e}")
        return

    # ---------------------------------------------------------
    # 2. 處理你的 Python 數據
    # ---------------------------------------------------------
    try:
        with open(PYTHON_FILE, 'r', encoding='utf-8') as f:
            python_data = json.load(f)
            
        python_combined_raw = []
        python_time = []
        first_ts = None
        curr_l = 0
        curr_r = 0
        
        for entry in python_data:
            if first_ts is None:
                first_ts = entry["timestamp_ms"]
            
            points_sum = sum(entry["pressure_points_g"])
            if entry["side"] == "左腳":
                curr_l = points_sum
            elif entry["side"] == "右腳":
                curr_r = points_sum
                
            python_combined_raw.append(curr_l + curr_r)
            python_time.append((entry["timestamp_ms"] - first_ts) / 1000.0)
            
        # 🛠️ 訊號處理：中位數濾波去突波 (Despiking)
        # 專門消除那種只有 1~2 個點的異常極端值 (例如飆到 70000 的雜訊)
        py_series = pd.Series(python_combined_raw)
        py_clean = py_series.rolling(window=5, min_periods=1, center=True).median().tolist()
        
    except Exception as e:
        print(f"❌ 讀取 JSON 檔案失敗: {e}")
        return

    # ---------------------------------------------------------
    # 3. 統一頻率對齊 (Resampling / Interpolation)
    # ---------------------------------------------------------
    # 找出兩者之中較短的結束時間，作為圖表的終點
    max_time = min(software_time[-1], python_time[-1])
    
    # 創造一個完美的 50Hz 時間軸 (0, 0.02, 0.04, 0.06...)
    common_time = np.arange(0, max_time, TARGET_INTERVAL_SEC)
    
    # 將兩組經過處理的數據，強制內插對齊到這個完美的共同時間軸上
    software_aligned = np.interp(common_time, software_time, sw_smooth)
    python_aligned = np.interp(common_time, python_time, py_clean)

    # ---------------------------------------------------------
    # 4. 繪圖比對
    # ---------------------------------------------------------
    plt.figure('Data Validation (Processed & Aligned)', figsize=(12, 6))
    
    plt.plot(common_time, software_aligned, label='Software (Smoothed 50Hz)', 
             color='gray', linestyle='--', linewidth=2)
             
    plt.plot(common_time, python_aligned, label='Python (Despiked 50Hz)', 
             color='purple', alpha=0.8, linewidth=2.5)

    plt.title('Validation: Processed & Frequency-Aligned Combined Force', fontsize=14, fontweight='bold')
    plt.xlabel('Absolute Time (Seconds)', fontsize=12)
    plt.ylabel('Total Combined Force (Raw Data)', fontsize=12)
    
    plt.grid(True, linestyle=':', alpha=0.8)
    plt.legend(loc='upper right', fontsize=12)
    
    plt.tight_layout()
    plt.show()

if __name__ == '__main__':
    main()