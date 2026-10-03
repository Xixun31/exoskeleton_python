import serial
import time
import glob
import sys

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
# =================================================

def run_basic_motor_test():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n-------------------------------------------------------------")
    print(" Running Basic Motor Step Test (0 to 90 degrees) ")
    print("-------------------------------------------------------------\n")

    # 1. Move to 0
    print("Commanding motor to 0°...")
    ser.write(b"0\n")
    time.sleep(2.0)
    
    # Clear serial buffer
    ser.reset_input_buffer()
    
    # 2. Command to 90 degrees
    print("🚀 Commanding motor to 90°...")
    ser.write(b"90\n")
    
    start_time = time.time()
    print(f"{'Time (s)':<10} | {'Target (deg)':<15} | {'Increm (deg)':<15} | {'Absol (deg)':<15} | {'Voltage (V)':<12}")
    print("-" * 75)
    
    # Record for 3 seconds
    while time.time() - start_time < 3.0:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
            continue
        parts = line.split(',')
        if len(parts) == 7:
            try:
                t_now = time.time() - start_time
                abs_deg = float(parts[1].strip())
                voltage = float(parts[4].strip())
                target_deg = float(parts[5].strip())
                current_deg = float(parts[6].strip())
                
                # Print every ~100ms to avoid flooding terminal
                if int(t_now * 100) % 10 == 0:
                    print(f"{t_now:<10.3f} | {target_deg:<15.2f} | {current_deg:<15.2f} | {abs_deg:<15.2f} | {voltage:<12.4f}")
            except ValueError:
                continue
                
    # 3. Return to 0
    print("\nReturning motor to 0°...")
    ser.write(b"0\n")
    time.sleep(1.0)
    ser.close()
    print("Done!")

if __name__ == '__main__':
    run_basic_motor_test()
