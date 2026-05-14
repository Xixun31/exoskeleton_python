import asyncio
from bleak import BleakScanner, BleakClient

# --- 設定 ---
# 你的藍牙模組名稱
TARGET_NAME = "exoskeleton"

# HM-10 常見的 TX/RX 特徵值 UUID (標準為 FFE1)
# 這裡使用完整格式
DEFAULT_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# --- 資料處理函式 ---
def notification_handler(sender, data):
    """當 Mac 收到藍牙模組傳來的資料時，會自動觸發這個函式"""
    try:
        text = data.decode('utf-8', errors='replace').strip()
        if text:
            print(f"📥 收到藍牙訊息: {text}")
    except Exception as e:
        print(f"⚠️ 無法解析的資料: {data}")

async def main():
    print("🔍 正在搜尋附近的藍牙裝置 (請稍候 5 秒)...")
    devices = await BleakScanner.discover(timeout=5.0)

    target_device = None
    
    for d in devices:
        name = d.name or "Unknown"
        if TARGET_NAME in name:
            target_device = d
            break

    if not target_device:
        print(f"\n❌ 找不到名稱包含 '{TARGET_NAME}' 的裝置。")
        return

    print(f"\n✅ 鎖定目標裝置: {target_device.name} [{target_device.address}]")
    print("🔗 正在嘗試連線...")

    try:
        async with BleakClient(target_device) as client:
            print("🎉 連線成功！\n")
            
            # --- 列出所有服務與特徵值 (除錯用) ---
            print("--- 裝置支援的特徵值列表 ---")
            services = client.services
            char_uuid_to_use = None
            
            for service in services:
                for char in service.characteristics:
                    print(f"  [特徵值] UUID: {char.uuid} | 屬性: {char.properties}")
                    # 尋找支援 'notify' 的特徵值 (通常就是我們要的)
                    if "notify" in char.properties:
                        char_uuid_to_use = char.uuid
            print("--------------------------\n")
            
            # 決定要訂閱哪個 UUID
            # 如果預設的 DEFAULT_CHAR_UUID 在列表裡，就用它；否則用找到的支援 notify 的 UUID
            target_uuid = DEFAULT_CHAR_UUID
            if char_uuid_to_use and DEFAULT_CHAR_UUID not in [c.uuid for s in services for c in s.characteristics]:
                 target_uuid = char_uuid_to_use
                 print(f"⚠️ 找不到預設的 FFE1，改用找到的 Notify 特徵值: {target_uuid}")

            print(f"開始接收資料 (訂閱 UUID: {target_uuid})... (按 Ctrl+C 結束)\n")

            # 訂閱特徵值
            await client.start_notify(target_uuid, notification_handler)

            while True:
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n[錯誤] 連線或通訊失敗: {e}")
    finally:
        print("\n🔌 藍牙連線已安全關閉。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程式結束。")