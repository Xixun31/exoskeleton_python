import asyncio
import time

from bleak import BleakClient
from bleak import BleakScanner


# ============================================================
# BLE 設定
# ============================================================

DEVICE_NAME = "BT05"

CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"


# ============================================================
# 測試設定
# ============================================================

TARGET_HZ = 20
TOTAL_PACKETS = 500

PACKET_SIZE = 39

# 每個完整39-byte packet拆成
# 20 bytes + 19 bytes
CHUNK1_SIZE = 20

# 兩個 BLE write 中間留一點時間
CHUNK_GAP = 0.005     # 5 ms


# ============================================================
# 建立39-byte packet
#
# 格式：
#
# 000001XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n
#
# 前6 bytes = sequence number
# 前38 bytes補X
# 第39 byte = \n
# ============================================================

def make_packet(seq):

    seq_text = f"{seq:06d}"

    packet = seq_text.encode("ascii")

    packet += b"X" * (38 - len(packet))

    packet += b"\n"

    assert len(packet) == PACKET_SIZE

    return packet


# ============================================================
# 主程式
# ============================================================

async def main():

    print("========================================")
    print("PC -> BT05 -> STM32 Bandwidth Test")
    print("========================================")

    print(f"Target Hz       : {TARGET_HZ}")
    print(f"Packets         : {TOTAL_PACKETS}")
    print(f"Packet Size     : {PACKET_SIZE} Bytes")
    print(f"BLE Split       : 20 + 19 Bytes")
    print(f"Chunk Gap       : {CHUNK_GAP * 1000:.1f} ms")

    print()
    print("Scanning BT05...")


    # ========================================================
    # 掃描 BT05
    # ========================================================

    device = await BleakScanner.find_device_by_filter(
        lambda d, adv:
        d.name is not None
        and DEVICE_NAME.lower() in d.name.lower(),
        timeout=10.0
    )


    if device is None:

        print("找不到 BT05")
        return


    print("Found   :", device.name)
    print("Address :", device.address)


    # ========================================================
    # 連線
    # ========================================================

    async with BleakClient(device) as client:

        print("Connected :", client.is_connected)
        print()


        # ====================================================
        # 看 characteristic 資訊
        # ====================================================

        char = client.services.get_characteristic(
            CHAR_UUID
        )


        if char is None:

            print("找不到 FFE1 characteristic")
            return


        print("Characteristic UUID :")
        print(char.uuid)

        print(
            "Properties :",
            char.properties
        )


        try:

            print(
                "Max Write Without Response :",
                char.max_write_without_response_size,
                "Bytes"
            )

        except Exception:

            print(
                "Max Write Without Response : "
                "無法取得"
            )


        print()
        print("開始發送...")
        print()


        # ====================================================
        # 發送排程
        # ====================================================

        period = 1.0 / TARGET_HZ

        start_time = time.perf_counter()

        max_schedule_lag = 0.0


        for seq in range(
            1,
            TOTAL_PACKETS + 1
        ):

            # ------------------------------------------------
            # 理論上這一包應該開始送出的時間
            # ------------------------------------------------

            ideal_time = (
                start_time
                + (seq - 1) * period
            )


            now = time.perf_counter()


            # ------------------------------------------------
            # 還沒到時間就等待
            # ------------------------------------------------

            if now < ideal_time:

                await asyncio.sleep(
                    ideal_time - now
                )


            actual_start = time.perf_counter()


            # ------------------------------------------------
            # Python本身排程晚了多少
            # ------------------------------------------------

            schedule_lag = (
                actual_start
                - ideal_time
            )


            if schedule_lag > max_schedule_lag:

                max_schedule_lag = (
                    schedule_lag
                )


            # =================================================
            # 建立39-byte packet
            # =================================================

            packet = make_packet(seq)


            # =================================================
            # 拆成20 + 19
            # =================================================

            chunk1 = packet[:CHUNK1_SIZE]

            chunk2 = packet[CHUNK1_SIZE:]


            # =================================================
            # 送第一段20 bytes
            # =================================================

            await client.write_gatt_char(
                CHAR_UUID,
                chunk1,
                response=False
            )


            # =================================================
            # 等5 ms
            # =================================================

            if CHUNK_GAP > 0:

                await asyncio.sleep(
                    CHUNK_GAP
                )


            # =================================================
            # 送第二段19 bytes
            # =================================================

            await client.write_gatt_char(
                CHAR_UUID,
                chunk2,
                response=False
            )


            # =================================================
            # 每50包顯示一次
            # =================================================

            if seq % 50 == 0:

                print(
                    f"Sent {seq}/{TOTAL_PACKETS}"
                )


        # ====================================================
        # 發完500包
        # ====================================================

        end_time = time.perf_counter()

        elapsed = (
            end_time - start_time
        )


        if elapsed > 0:

            actual_tx_hz = (
                (TOTAL_PACKETS - 1)
                / elapsed
            )

        else:

            actual_tx_hz = 0


        print()
        print("========================================")
        print("PC -> BT05 TX Result")
        print("========================================")

        print(
            f"Target TX Hz      : "
            f"{TARGET_HZ:.2f}"
        )

        print(
            f"Actual TX Hz      : "
            f"{actual_tx_hz:.2f}"
        )

        print(
            f"Packets           : "
            f"{TOTAL_PACKETS}"
        )

        print(
            f"Packet Size       : "
            f"{PACKET_SIZE} Bytes"
        )

        print(
            f"Total Time        : "
            f"{elapsed:.3f} s"
        )

        print(
            f"Max Schedule Lag  : "
            f"{max_schedule_lag * 1000:.2f} ms"
        )

        print("========================================")


        # ====================================================
        # 告訴STM32測試結束
        #
        # STM32程式收到 END\n 後
        # 會印出正式統計結果
        # ====================================================

        print()
        print("Sending END...")


        for _ in range(3):

            await client.write_gatt_char(
                CHAR_UUID,
                b"END\n",
                response=False
            )

            await asyncio.sleep(
                0.05
            )


        print("Done.")


# ============================================================
# Run
# ============================================================

asyncio.run(main())