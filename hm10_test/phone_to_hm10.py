import serial

ser = serial.Serial(
    "COM8",       # 改成你的 COM
    115200,       # 要跟 BT05 UART baud 一樣
    timeout=0.1
)

print("等待 BT05 資料...")

while True:
    data = ser.read(ser.in_waiting or 1)

    if data:
        print("HEX :", data.hex(" ").upper())

        try:
            print("ASCII:", data.decode("utf-8"))
        except UnicodeDecodeError:
            pass