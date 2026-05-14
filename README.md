# exoskeleton_python

專案內容為與 STM32 與藍牙感測器進行通訊的 Python 腳本，包含 IMU、壓力感測、藍牙連線與 UART 讀寫相關功能。

## 專案結構

- `Bluetooth.py`：藍牙裝置掃描與連線管理。
- `findbluetooth.py`：搜尋附近的藍牙設備工具。
- `readble.py`：從藍牙裝置讀取資料。
- `writetoble.py`：向藍牙設備寫入資料。
- `read_stm32.py`：從 STM32 裝置讀取 UART 資料。
- `stm32_imu_uart.py`：處理來自 STM32 的 IMU UART 資料。
- `imu.py`：IMU 感測器資料處理程式。
- `flex_sensor.py`：軟性彎曲感測器資料讀取與解析。
- `encoder.py`：編碼器資料處理與讀取。
- `buad.py`：可能與串列通訊鮑率設定相關的輔助程式。
- `sensor_log.json`：感測器資料範例/記錄檔。

## 安裝與執行

1. 建議使用虛擬環境：
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. 安裝依賴套件（若有需要）：
   ```bash
   pip install pyserial pybluez
   ```
3. 執行腳本，例如：
   ```bash
   python readble.py
   ```

> 注意：實際所需套件與硬體裝置視專案環境而定，請依硬體連線方式與現有程式碼補充相應依賴。

## 注意事項

- 此專案主要用於與 STM32 及藍牙感測器進行資料交換，執行前請確認裝置已正確連線。
- 若有串列埠連線問題，可先檢查系統上的可用序列埠或藍牙配對狀態。
- 若要進一步使用，建議將程式碼拆分成可重用模組並補上參數化設定。
