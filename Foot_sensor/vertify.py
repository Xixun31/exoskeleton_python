import pandas as pd
import json
import matplotlib.pyplot as plt

# ================= 設定區 =================
# 替換成你原廠軟體導出的檔案名稱 (支援 .csv 或用 pd.read_excel 讀 .xlsx)
SOFTWARE_FILE = 'software_data.csv' 
PYTHON_FILE = 'gait_data_output.json'
# ==========================================

def main():
    print("讀取並整合雙方數據中...")

    # ---------------------------------------------------------
    # 1. 處理原廠軟體數據 (Software Data)
    # ---------------------------------------------------------
    try:
        df_software = pd.read_csv(SOFTWARE_FILE)
        
        # 自動產生 L1 到 L18 的欄位名稱列表
        l_cols = [f'L{i}' for i in range(1, 19)]
        
        # 將 L1~L18 的數值橫向加總，得到軟體版的「左腳總受力」
        software_left_total = df_software[l_cols].sum(axis=1).tolist()
        print(f"✅ 成功讀取軟體數據：共 {len(software_left_total)} 筆左腳資料")
        
    except Exception as e:
        print(f"❌ 讀取軟體檔案失敗，請檢查檔名或欄位名稱: {e}")
        return

    # ---------------------------------------------------------
    # 2. 處理你的 Python 數據 (Python Data)
    # ---------------------------------------------------------
    try:
        with open(PYTHON_FILE, 'r', encoding='utf-8') as f:
            python_data = json.load(f)
            
        python_left_total = []
        for entry in python_data:
            if entry["side"] == "左腳":
                python_left_total.append(sum(entry["pressure_points_g"]))
                
        print(f"✅ 成功讀取 Python 數據：共 {len(python_left_total)} 筆左腳資料")
        
    except Exception as e:
        print(f"❌ 讀取 JSON 檔案失敗: {e}")
        return

    # ---------------------------------------------------------
    # 3. 繪圖比對 (Plotting)
    # ---------------------------------------------------------
    plt.figure('Data Validation', figsize=(12, 6))
    
    # 畫出軟體數據 (用灰色虛線當底)
    plt.plot(software_left_total, label='Software (Left Total)', 
             color='gray', linestyle='--', linewidth=2)
             
    # 畫出 Python 數據 (用半透明藍色疊加)
    plt.plot(python_left_total, label='Python (Left Total)', 
             color='blue', alpha=0.7, linewidth=2)

    plt.title('Validation: Software Export vs. Python Parsing', fontsize=14, fontweight='bold')
    plt.xlabel('Data Frames (Index)', fontsize=12)
    plt.ylabel('Total Force Sum', fontsize=12)
    
    # 加入格線與圖例
    plt.grid(True, linestyle=':', alpha=0.8)
    plt.legend(loc='upper right', fontsize=12)
    
    plt.tight_layout()
    plt.show()

if __name__ == '__main__':
    main()