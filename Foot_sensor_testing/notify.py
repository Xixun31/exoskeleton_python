import asyncio
from bleak import BleakScanner, BleakClient

TARGET_NAME = "NB-FF2405103703"

async def main():
    print("Scanning...")

    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: d.name == TARGET_NAME,
        timeout=10.0
    )

    if device is None:
        print("找不到感測器")
        return

    print("找到裝置")
    print("Name    :", device.name)
    print("Address :", device.address)

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)

        for service in client.services:
            print("\n================================")
            print("SERVICE")
            print(service.uuid)

            for char in service.characteristics:
                print("  Characteristic:")
                print("   UUID       :", char.uuid)
                print("   Properties :", char.properties)

                for desc in char.descriptors:
                    print(
                        "   Descriptor :",
                        desc.uuid
                    )

asyncio.run(main())