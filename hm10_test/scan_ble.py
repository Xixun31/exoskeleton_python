import asyncio
from bleak import BleakClient

MAC_ADDRESS = "78:DB:2F:0B:A0:25"

async def explore_device(address):
    print(f"嘗試連線到 {address} 探索服務...")
    try:
        async with BleakClient(address) as client:
            print("連線成功！以下是可用的服務與特徵值 (UUID)：\n")
            
            # 修正處：直接讀取 client.services
            services = client.services 
            
            if not services:
                print("⚠️ 無法獲取服務列表。")
                return
                
            for service in services:
                print(f"🔹 服務 (Service): {service.uuid}")
                for char in service.characteristics:
                    print(f"   🔸 特徵值 (Characteristic): {char.uuid}")
                    print(f"      屬性 (Properties): {char.properties}")
                    
    except Exception as e:
        print(f"連線或探索失敗: {e}")

asyncio.run(explore_device(MAC_ADDRESS))