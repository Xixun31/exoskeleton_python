import serial
import time

# ==============================
# 設定
# ==============================
COM_PORT = "COM6"      # 改成你的 USB receiver COM port
BAUD_RATE = 115200

PACKET_SIZE = 39
TARGET_PACKETS = 500

HEADER_1 = 0xAA
HEADER_2 = 0x01   # 左腳；右腳可改 0x02


# ==============================
# checksum
# ==============================
def check_checksum(packet):
    checksum = sum(packet[:38]) & 0xFF
    return checksum == packet[38]


# ==============================
# 主程式
# ==============================
ser = serial.Serial(
    COM_PORT,
    BAUD_RATE,
    timeout=0.01
)

print("========================================")
print("USB Receiver Sensor Test")
print("========================================")
print(f"COM Port     : {COM_PORT}")
print(f"Baud Rate    : {BAUD_RATE}")
print(f"Packet Size  : {PACKET_SIZE} Bytes")
print(f"Target       : {TARGET_PACKETS}")
print("等待感測器資料...")
print()


packet = bytearray()

waiting_for_01 = False
receiving = False

valid_packets = 0
checksum_errors = 0

start_time = None
previous_time = None

total_interval = 0.0
max_interval = 0.0

raw_bytes = 0


while valid_packets < TARGET_PACKETS:

    data = ser.read(1)

    if not data:
        continue

    c = data[0]
    raw_bytes += 1

    # ======================================
    # 還沒開始接收封包
    # 搜尋 AA 01
    # ======================================
    if not receiving:

        if waiting_for_01:

            if c == HEADER_2:

                packet = bytearray([
                    HEADER_1,
                    HEADER_2
                ])

                receiving = True
                waiting_for_01 = False

            elif c == HEADER_1:

                # AA AA
                waiting_for_01 = True

            else:

                waiting_for_01 = False

            continue

        if c == HEADER_1:
            waiting_for_01 = True

        continue


    # ======================================
    # 已找到 AA 01
    # 固定收滿39 bytes
    # ======================================
    packet.append(c)

    if len(packet) < PACKET_SIZE:
        continue


    # ======================================
    # 收滿39 bytes
    # ======================================
    now = time.perf_counter()

    if check_checksum(packet):

        if valid_packets == 0:
            start_time = now
            previous_time = now

            print("收到第一個有效封包，開始計時")

        else:
            interval = now - previous_time

            total_interval += interval

            if interval > max_interval:
                max_interval = interval

            previous_time = now

        valid_packets += 1

        if valid_packets % 50 == 0:
            print(
                f"有效封包：{valid_packets}/{TARGET_PACKETS} "
                f"| Checksum Error：{checksum_errors}"
            )

    else:

        checksum_errors += 1


    # ======================================
    # 重新搜尋下一個 AA 01
    # ======================================
    packet = bytearray()
    receiving = False
    waiting_for_01 = False


# ==============================
# 結果
# ==============================
end_time = previous_time

elapsed = end_time - start_time


if valid_packets > 1:
    actual_hz = (
        (valid_packets - 1) / elapsed
    )

    average_interval = (
        total_interval /
        (valid_packets - 1)
    )

else:
    actual_hz = 0
    average_interval = 0


print()
print("========================================")
print("USB Receiver Test Result")
print("========================================")

print(
    f"有效封包       : "
    f"{valid_packets} / {TARGET_PACKETS}"
)

print(
    f"Checksum Error : "
    f"{checksum_errors}"
)

print(
    f"UART/USB Bytes : "
    f"{raw_bytes}"
)

print(
    f"總接收時間     : "
    f"{elapsed:.3f} s"
)

print(
    f"實際接收頻率   : "
    f"{actual_hz:.2f} Hz"
)

print(
    f"平均封包間隔   : "
    f"{average_interval * 1000:.2f} ms"
)

print(
    f"最大封包間隔   : "
    f"{max_interval * 1000:.2f} ms"
)

print("========================================")

ser.close()