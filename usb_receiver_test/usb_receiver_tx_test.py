import asyncio
import time
from bleak import BleakClient

# ==========================================
# BLE 設定
# 改成你的 BLE 接收目標
# ==========================================
BLE_ADDRESS = "78:DB:2F:0B:A0:25"
CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"

# ==========================================
# 測試設定
# ==========================================
TARGET_HZ = 20
TOTAL_PACKETS = 500

PACKET_SIZE = 39

# BLE 4.0 常見單次 payload 20 bytes
CHUNK1_SIZE = 20

# 如果對方需要一點間隔，可以保留
CHUNK_GAP = 0.005


def make_packet(seq):
    """
    產生固定39 bytes ASCII封包

    例如：
    000001XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX

    最後一個 byte 用 \n
    """

    seq_text = f"{seq:06d}"

    payload = seq_text.encode("ascii")

    # 前38 bytes
    payload += b"X" * (38 - len(payload))

    # 第39 byte
    payload += b"\n"

    assert len(payload) == PACKET_SIZE

    return payload


async def main():

    print("========================================")
    print("USB Receiver Bandwidth TX Test")
    print("========================================")
    print(f"Target Hz     : {TARGET_HZ}")
    print(f"Packets       : {TOTAL_PACKETS}")
    print(f"Packet Size   : {PACKET_SIZE} Bytes")
    print()

    async with BleakClient(BLE_ADDRESS) as client:

        print("BLE connected")
        print()

        period = 1.0 / TARGET_HZ

        start_time = time.perf_counter()

        max_schedule_lag = 0.0

        for seq in range(1, TOTAL_PACKETS + 1):

            ideal_time = (
                start_time +
                (seq - 1) * period
            )

            now = time.perf_counter()

            # 還沒到時間就等
            if now < ideal_time:
                await asyncio.sleep(
                    ideal_time - now
                )

            actual_start = time.perf_counter()

            schedule_lag = (
                actual_start - ideal_time
            )

            if schedule_lag > max_schedule_lag:
                max_schedule_lag = schedule_lag

            packet = make_packet(seq)

            # --------------------------------------
            # 拆成20 + 19 bytes
            # --------------------------------------
            chunk1 = packet[:CHUNK1_SIZE]
            chunk2 = packet[CHUNK1_SIZE:]

            await client.write_gatt_char(
                CHAR_UUID,
                chunk1,
                response=False
            )

            if CHUNK_GAP > 0:
                await asyncio.sleep(CHUNK_GAP)

            await client.write_gatt_char(
                CHAR_UUID,
                chunk2,
                response=False
            )

            if seq % 50 == 0:
                print(
                    f"Sent {seq}/{TOTAL_PACKETS}"
                )

        end_time = time.perf_counter()

        elapsed = end_time - start_time

        actual_tx_hz = (
            (TOTAL_PACKETS - 1) /
            elapsed
        )

        print()
        print("========================================")
        print("TX Result")
        print("========================================")

        print(
            f"Target TX Hz      : {TARGET_HZ:.2f}"
        )

        print(
            f"Actual TX Hz      : {actual_tx_hz:.2f}"
        )

        print(
            f"Total Time        : {elapsed:.3f} s"
        )

        print(
            f"Max Schedule Lag  : "
            f"{max_schedule_lag * 1000:.2f} ms"
        )

        print("========================================")

        # 告訴接收端測試結束
        for _ in range(3):

            await client.write_gatt_char(
                CHAR_UUID,
                b"END\n",
                response=False
            )

            await asyncio.sleep(0.05)


asyncio.run(main())