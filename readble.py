import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME = "exoskeleton"
DEFAULT_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

def notification_handler(sender, data):
    """當 Mac 收到藍牙模組傳來的資料時，會觸發這裡"""
    try:
        text = data.decode('utf-8', errors='replace').strip()
        if text:
            print(f"🔵 [藍牙收到]: {text}")
    except Exception:
        pass

async def main():
    print(f"🔍 正在搜尋藍牙裝置 '{TARGET_NAME}'...")
    devices = await BleakScanner.discover(timeout=5.0)

    target_device = next((d for d in devices if d.name and TARGET_NAME in d.name), None)

    if not target_device:
        print(f"❌ 找不到 '{TARGET_NAME}'。請確認模組有通電。")
        return

    print(f"✅ 鎖定目標: {target_device.name}")
    print("🔗 正在嘗試藍牙連線...")

    try:
        async with BleakClient(target_device) as client:
            print("🎉 藍牙連線成功！正在監聽中... (按 Ctrl+C 關閉)\n")
            
            # 尋找支援 notify 的特徵值
            target_uuid = DEFAULT_CHAR_UUID
            if DEFAULT_CHAR_UUID not in [c.uuid for s in client.services for c in s.characteristics]:
                for s in client.services:
                    for c in s.characteristics:
                        if "notify" in c.properties:
                            target_uuid = c.uuid
                            break

            # 啟動接收通知
            await client.start_notify(target_uuid, notification_handler)

            # 讓程式保持執行
            while True:
                await asyncio.sleep(1)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n[錯誤] 藍牙連線斷開: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🔌 藍牙監聽已結束。")
        