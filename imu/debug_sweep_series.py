import serial
import time
import glob
import sys

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
# =================================================

def run_series_diagnostics():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print("✅ Connection Successful!")
        # Disable Linux TTY Echo to prevent loopback
        try:
            import termios
            fd = ser.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[3] = attrs[3] & ~termios.ECHO
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            print("⚙️ Linux TTY Echo Disabled.")
        except Exception as te:
            print(f"⚠️ Warning: Could not disable TTY echo: {te}")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    # 1. Wait for boot and reset feedback
    print("Waiting for Nucleo Board to boot up (2s)...")
    time.sleep(2.0)
    ser.reset_input_buffer()
    
    print("Forcing feedback 0...")
    ser.write(b"feedback 0\n")
    time.sleep(0.1)
    ser.write(b"reset\n")
    time.sleep(0.4)
    
    # Read and print any response
    while ser.in_waiting:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        print("   [BOOT]:", line)

    # 2. Command to 0
    print("Commanding motor to 0°...")
    ser.write(b"0\n")
    time.sleep(1.0)
    ser.reset_input_buffer()

    # 3. Start sweep
    print("🚀 Starting sweep: sine 25 0.5 0...")
    ser.write(b"sine 25 0.5 0\n")
    time.sleep(0.1)  # Wait a bit for command to process
    
    print(f"\n{'Time (s)':<10} | {'Target (deg)':<15} | {'Increm (deg)':<15} | {'Absol (deg)':<15} | {'Voltage (V)':<12}")
    print("-" * 75)
    
    start_time = time.time()
    lines_read = 0
    
    # Read 50 lines (0.5 seconds at 100Hz)
    while lines_read < 50 and time.time() - start_time < 3.0:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
            if line:
                print(f"   [MSG]: {line}")
            continue
        parts = line.split(',')
        if len(parts) == 7:
            try:
                t_now = time.time() - start_time
                abs_deg = float(parts[1].strip())
                voltage = float(parts[4].strip())
                target_deg = float(parts[5].strip())
                current_deg = float(parts[6].strip())
                
                print(f"{t_now:<10.3f} | {target_deg:<15.2f} | {current_deg:<15.2f} | {abs_deg:<15.2f} | {voltage:<12.4f}")
                lines_read += 1
            except ValueError:
                continue

    # 4. Restore 0 target
    ser.write(b"0\n")
    ser.close()
    print("\nDiagnostics Done!")

if __name__ == '__main__':
    run_series_diagnostics()
