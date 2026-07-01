# exoskeleton_python

專案內容為與 STM32 與藍牙感測器進行通訊的 Python 腳本，包含 IMU、壓力感測、藍牙連線與 UART 讀寫相關功能。現已依感測器與功能進行模組化分類。

## 專案結構

### 📂 [encoder/](file:///home/xixun/project/python/encoder/) - 編碼器測試與分析工具
- [encoder.py](file:///home/xixun/project/python/encoder/encoder.py)：即時編碼器角度讀取與 Matplotlib 動態波形繪圖程式。
- [encoder_calibration_helper.py](file:///home/xixun/project/python/encoder/encoder_calibration_helper.py)：互動式編碼器靜態角度多點校正與分析工具，支援**自動方向反轉判定**與**自訂零點校正基準**，可輸出報告與誤差分布圖。
- [record_dynamic_encoder.py](file:///home/xixun/project/python/encoder/record_dynamic_encoder.py)：連續記錄編碼器動態旋轉（如 90 度/180 度）動作的工具，自動分割旋轉區間、估算角速度並計算動態範圍誤差。
- [generate_chart_from_data.py](file:///home/xixun/project/python/encoder/generate_chart_from_data.py)：由特定量測數據重新計算並繪製校正誤差曲線的輔助腳本。

### 📂 [imu/](file:///home/xixun/project/python/imu/) - 慣性感測器測試與分析工具
- [imu.py](file:///home/xixun/project/python/imu/imu.py)：單一 IMU 感測器資料讀取與解析。
- [imu_spi.py](file:///home/xixun/project/python/imu/imu_spi.py)、[imu2spi.py](file:///home/xixun/project/python/imu/imu2spi.py)：IMU SPI 介面通訊測試程式。
- [stm32_imu_uart.py](file:///home/xixun/project/python/imu/stm32_imu_uart.py)：自 STM32 讀取單一 IMU 的 UART 資料並進行即時繪圖。
- [stm32_dual_imu_table.py](file:///home/xixun/project/python/imu/stm32_dual_imu_table.py)：讀取雙 UART IMU 並在終端機輸出即時表格，同時將數據記錄到 `imu_data.csv`。
- [stm32_dual_imu_chart.py](file:///home/xixun/project/python/imu/stm32_dual_imu_chart.py)：即時顯示雙 IMU 的歐拉角、加速度與角速度對比曲線。
- [analyze_static_error.py](file:///home/xixun/project/python/imu/analyze_static_error.py)：統計分析靜態 IMU 數據，生成 Bias、噪聲標準差與 P-P 波動報告。
- [pitch_calibration_helper.py](file:///home/xixun/project/python/imu/pitch_calibration_helper.py)：互動式 Pitch 靜態角度多點校正工具，自動扣除安裝偏置，生成校正 CSV 並繪製誤差分布圖。
- [record_dynamic_pitch.py](file:///home/xixun/project/python/imu/record_dynamic_pitch.py)：連續記錄來回擺動時的 Pitch 數據，並繪製兩顆 IMU 動態角度與同步差值曲線。
- [render_captured_data.py](file:///home/xixun/project/python/imu/render_captured_data.py)：用以從中斷緩衝區中手動重建校正報告與繪圖的備用工具。

### 📂 [bluetooth/](file:///home/xixun/project/python/bluetooth/) - 藍牙與 BLE 通訊工具
- [Bluetooth.py](file:///home/xixun/project/python/bluetooth/Bluetooth.py)：藍牙裝置掃描與連線管理。
- [findbluetooth.py](file:///home/xixun/project/python/bluetooth/findbluetooth.py)：搜尋附近的藍牙設備。
- [readble.py](file:///home/xixun/project/python/bluetooth/readble.py)：自藍牙/BLE 裝置讀取感測器資料。
- [writetoble.py](file:///home/xixun/project/python/bluetooth/writetoble.py)：向藍牙/BLE 裝置發送寫入控制指令。

### 📂 [utils/](file:///home/xixun/project/python/utils/) - 通用與輔用工具
- [genppt.py](file:///home/xixun/project/python/utils/genppt.py)、[html2pptx.py](file:///home/xixun/project/python/utils/html2pptx.py)：簡報自動生成與 HTML 轉換工具。
- [encoder_imu.html](file:///home/xixun/project/python/utils/encoder_imu.html)：編碼器與 IMU 動態展示網頁。
- [buad.py](file:///home/xixun/project/python/utils/buad.py)：串口通訊鮑率設定與計算輔助工具。
- [read_stm32.py](file:///home/xixun/project/python/utils/read_stm32.py)：從 STM32 裝置讀取 UART 資料。

### 📂 其他感測器目錄
- [Foot_sensor/](file:///home/xixun/project/python/Foot_sensor/)：足底壓力感測器相關腳本。
- [flex_sensor/](file:///home/xixun/project/python/flex_sensor/)：軟性彎曲感測器資料讀取與解析。

## 安裝與執行

1. 建議使用虛擬環境：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. 安裝依賴套件（若有需要）：
   ```bash
   pip install pyserial matplotlib
   ```
3. 進入對應資料夾執行腳本，例如執行編碼器動態測試：
   ```bash
   cd encoder
   python3 record_dynamic_encoder.py
   ```

## 注意事項

- 執行任何通訊腳本前，請確認硬體裝置（如 STM32、USB 串口、藍牙）已正確連接並正常運作。
- 大部分測試工具在執行結束後（如按下 `Ctrl+C` 或 `q` 退出時）均會自動在該腳本所在目錄生成對應的 `.csv` 數據報告與 `.png` 分析曲線圖。
