import serial
import time
import glob
import sys

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
# =================================================

def run_diagnostics():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    # Clean buffer
    ser.reset_input_buffer()
    
    # 1. Send feedback 0
    print("\n1. Sending 'feedback 0'...")
    ser.write(b"feedback 0\n")
    time.sleep(0.5)
    while ser.in_waiting:
        print("   [MBED RAW]:", ser.readline().decode('utf-8', errors='ignore').strip())

    # 2. Send 0 target
    print("\n2. Sending target '0'...")
    ser.write(b"0\n")
    time.sleep(0.5)
    while ser.in_waiting:
        print("   [MBED RAW]:", ser.readline().decode('utf-8', errors='ignore').strip())

    # 3. Send sine command
    print("\n3. Sending 'sine 25 0.5 0'...")
    ser.write(b"sine 25 0.5 0\n")
    time.sleep(0.5)
    
    print("\n4. Reading 30 lines of raw data:")
    for _ in range(30):
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        print("   [MBED DATA]:", line)

    # 4. Cleanup
    ser.write(b"0\n")
    ser.close()

if __name__ == '__main__':
    run_diagnostics()
