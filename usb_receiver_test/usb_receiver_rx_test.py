import serial
import time

# ==========================================
# USB Receiver
# ==========================================
COM_PORT = "COM6"
BAUD_RATE = 115200

# ==========================================
# 必須跟送端一致
# ==========================================
TARGET_HZ = 20
TOTAL_PACKETS = 500

PACKET_SIZE = 39


def percentile(values, percent):

    if not values:
        return 0.0

    values = sorted(values)

    index = int(
        (len(values) - 1)
        * percent
    )

    return values[index]


ser = serial.Serial(
    COM_PORT,
    BAUD_RATE,
    timeout=0.05
)

print("========================================")
print("USB Receiver Bandwidth RX Test")
print("========================================")
print(f"COM Port     : {COM_PORT}")
print(f"Baud Rate    : {BAUD_RATE}")
print(f"Target Hz    : {TARGET_HZ}")
print(f"Target       : {TOTAL_PACKETS}")
print("等待資料...")
print()


buffer = bytearray()

received_packets = 0

lost_packets = 0
duplicate_packets = 0

expected_seq = 1

start_time = None
last_packet_time = None

intervals = []

max_cumulative_lag = 0.0

raw_bytes = 0


while received_packets < TOTAL_PACKETS:

    data = ser.read(
        ser.in_waiting or 1
    )

    if not data:
        continue

    raw_bytes += len(data)

    buffer.extend(data)

    # ==========================================
    # 以換行判斷一包
    # 因為TX人工封包最後是 \n
    # ==========================================
    while b"\n" in buffer:

        pos = buffer.index(b"\n")

        frame = bytes(
            buffer[:pos + 1]
        )

        del buffer[:pos + 1]

        # END
        if frame == b"END\n":
            continue

        # 長度不對就跳過
        if len(frame) != PACKET_SIZE:
            print(
                f"Bad length: {len(frame)}"
            )
            continue

        # ======================================
        # sequence number
        # 前6 bytes
        # ======================================
        try:

            seq = int(
                frame[:6].decode("ascii")
            )

        except ValueError:

            print(
                "Invalid sequence:",
                frame[:6]
            )

            continue


        now = time.perf_counter()


        # ======================================
        # 第一包
        # ======================================
        if start_time is None:

            start_time = now
            last_packet_time = now

            expected_seq = seq

            print(
                f"收到第一包 Seq={seq}，開始計時"
            )


        else:

            interval = (
                now - last_packet_time
            )

            intervals.append(interval)

            last_packet_time = now


        # ======================================
        # Sequence loss
        # ======================================
        if seq == expected_seq:

            expected_seq += 1

        elif seq > expected_seq:

            gap = seq - expected_seq

            lost_packets += gap

            print(
                f"LOSS: expected {expected_seq}, "
                f"received {seq}, "
                f"lost {gap}"
            )

            expected_seq = seq + 1

        else:

            duplicate_packets += 1

            print(
                f"DUP/OLD: "
                f"received {seq}, "
                f"expected {expected_seq}"
            )


        received_packets += 1


        # ======================================
        # Cumulative lag
        #
        # 理想上第N包應該在：
        #
        # (N-1)/TARGET_HZ
        #
        # 到達
        # ======================================
        ideal_elapsed = (
            (seq - 1) /
            TARGET_HZ
        )

        actual_elapsed = (
            now - start_time
        )

        cumulative_lag = (
            actual_elapsed -
            ideal_elapsed
        )

        if cumulative_lag > max_cumulative_lag:
            max_cumulative_lag = cumulative_lag


        if received_packets % 50 == 0:

            print(
                f"Received {received_packets} "
                f"| Seq {seq} "
                f"| Lost {lost_packets} "
                f"| Max Lag "
                f"{max_cumulative_lag * 1000:.1f} ms"
            )


# ==========================================
# Final result
# ==========================================
end_time = last_packet_time

elapsed = (
    end_time - start_time
)

actual_rx_hz = (
    (received_packets - 1)
    / elapsed
)

if intervals:

    average_interval = (
        sum(intervals)
        / len(intervals)
    )

    max_interval = max(intervals)

    p95_interval = percentile(
        intervals,
        0.95
    )

    p99_interval = percentile(
        intervals,
        0.99
    )

else:

    average_interval = 0
    max_interval = 0
    p95_interval = 0
    p99_interval = 0


print()
print("========================================")
print("USB Receiver Bandwidth RX Result")
print("========================================")

print(
    f"Received Packets   : "
    f"{received_packets}"
)

print(
    f"Lost Packets       : "
    f"{lost_packets}"
)

print(
    f"Duplicate / Old    : "
    f"{duplicate_packets}"
)

print(
    f"Raw Bytes          : "
    f"{raw_bytes}"
)

print(
    f"Total RX Time      : "
    f"{elapsed:.3f} s"
)

print(
    f"Actual RX Hz       : "
    f"{actual_rx_hz:.2f} Hz"
)

print(
    f"Average Interval   : "
    f"{average_interval * 1000:.2f} ms"
)

print(
    f"P95 Interval       : "
    f"{p95_interval * 1000:.2f} ms"
)

print(
    f"P99 Interval       : "
    f"{p99_interval * 1000:.2f} ms"
)

print(
    f"Max Interval       : "
    f"{max_interval * 1000:.2f} ms"
)

print(
    f"Max Cumulative Lag : "
    f"{max_cumulative_lag * 1000:.2f} ms"
)

print("========================================")

ser.close()