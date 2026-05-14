import asyncio
from bleak import BleakScanner

async def run():
    print("正在搜尋藍牙設備...")
    devices = await BleakScanner.discover()
    for d in devices:
        # 如果有名字，就印出來
        if d.name:
            print(f"發現設備: {d.name} | 位址: {d.address}")

asyncio.run(run())