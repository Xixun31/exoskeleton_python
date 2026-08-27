import asyncio
import time
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "ESP32_BW_TEST"
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

TARGET_HZ = 75
#TEST_SECONDS = 30
TOTAL_PACKETS = 500

PACKET_SIZE = 39
CHUNK1_SIZE = 20
CHUNK_GAP_S = 0.0

def make_packet(seq: int) -> bytes:
    seq_text = f"{seq:06d}".encode("ascii")
    packet = seq_text + b"X" * (38 - len(seq_text)) + b"\n"
    assert len(packet) == PACKET_SIZE
    return packet

async def main():
    #total_packets = int(TARGET_HZ * TEST_SECONDS)
    total_packets = TOTAL_PACKETS

    print("========================================")
    print("PC -> BLE -> ESP32 -> STM32 Bandwidth Test")
    print("========================================")
    print(f"Target Hz       : {TARGET_HZ}")
    #print(f"Test seconds    : {TEST_SECONDS}")
    print(f"Packets         : {total_packets}")
    print(f"Packet size     : {PACKET_SIZE} bytes")
    print()

    device = await BleakScanner.find_device_by_filter(
        lambda d, adv:
            d.name is not None
            and DEVICE_NAME.lower() in d.name.lower(),
        timeout=10.0,
    )

    if device is None:
        print("找不到 ESP32_BW_TEST")
        return

    print("Found   :", device.name)
    print("Address :", device.address)

    async with BleakClient(device) as client:
        print("Connected:", client.is_connected)

        char = client.services.get_characteristic(CHAR_UUID)

        if char is None:
            print("找不到測試 characteristic")
            return

        start_cmd = f"START,{TARGET_HZ}\n".encode("ascii")
        await client.write_gatt_char(CHAR_UUID, start_cmd, response=True)
        await asyncio.sleep(0.2)

        print("開始發送...")

        period = 1.0 / TARGET_HZ
        start_time = time.perf_counter()
        max_schedule_lag = 0.0

        for seq in range(1, total_packets + 1):
            ideal_time = start_time + (seq - 1) * period
            now = time.perf_counter()

            if now < ideal_time:
                await asyncio.sleep(ideal_time - now)

            actual_start = time.perf_counter()
            schedule_lag = actual_start - ideal_time
            max_schedule_lag = max(max_schedule_lag, schedule_lag)

            packet = make_packet(seq)
            chunk1 = packet[:CHUNK1_SIZE]
            chunk2 = packet[CHUNK1_SIZE:]

            await client.write_gatt_char(CHAR_UUID, chunk1, response=False)

            if CHUNK_GAP_S > 0:
                await asyncio.sleep(CHUNK_GAP_S)

            await client.write_gatt_char(CHAR_UUID, chunk2, response=False)

            if seq % max(TARGET_HZ, 1) == 0:
                print(f"Sent {seq}/{total_packets}")

        end_time = time.perf_counter()
        elapsed = end_time - start_time

        actual_tx_hz = (
            (total_packets - 1) / elapsed
            if elapsed > 0 and total_packets > 1
            else 0.0
        )

        end_cmd = f"END,{total_packets}\n".encode("ascii")
        await client.write_gatt_char(CHAR_UUID, end_cmd, response=True)
        await asyncio.sleep(0.5)

        print()
        print("========================================")
        print("PC TX Result")
        print("========================================")
        print(f"Target TX Hz      : {TARGET_HZ:.2f}")
        print(f"Actual TX Hz      : {actual_tx_hz:.2f}")
        print(f"Packets           : {total_packets}")
        print(f"Total Time        : {elapsed:.3f} s")
        print(f"Max Schedule Lag  : {max_schedule_lag * 1000:.2f} ms")
        print("========================================")
        print("請查看 STM32 Serial Monitor 的接收結果。")

asyncio.run(main())
