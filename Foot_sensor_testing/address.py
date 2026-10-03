import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning...\n")

    devices = await BleakScanner.discover(
        timeout=10,
        return_adv=True
    )

    for key, (device, adv) in devices.items():
        print("====================================")
        print("Name :", device.name)
        print("Address :", device.address)
        print("RSSI :", adv.rssi)
        print("Service UUIDs :", adv.service_uuids)
        print("Manufacturer Data :", adv.manufacturer_data)
        print("Service Data :", adv.service_data)

asyncio.run(main())