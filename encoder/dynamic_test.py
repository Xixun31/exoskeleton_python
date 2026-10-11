import serial
import time
import glob
import os
import sys
import matplotlib.pyplot as plt

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
TEST_DURATION = 3.0  # Duration to record in seconds
# =================================================

def run_dynamic_test():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("             Encoder Dynamic Response Test Script            ")
    print("=============================================================")
    print("This script will send a step command to the motor, and record")
    print("the transient trajectory of the absolute encoder vs the")
    print("motor's incremental encoder reference at 100Hz.")
    print("=============================================================\n")

    # Command target angle selection
    try:
        target_input = input("Enter target step angle in degrees (default: 90.0): ").strip()
        target_angle = float(target_input) if target_input else 90.0
    except ValueError:
        print("Invalid input. Using default 90.0 degrees.")
        target_angle = 90.0

    print("\nPreparing test...")
    print("1. Sending target 0.0° to center motor...")
    ser.write(b"0\n")
    time.sleep(2.0)  # Wait for motor to reach 0 and settle
    
    # Flush incoming buffers to clear stale lines
    ser.reset_input_buffer()
    
    print("\nReady! Press Enter to trigger the step command and start recording...")
    input()
    
    print(f"🚀 Sending step target: {target_angle}°")
    # Trigger the step command
    ser.write(f"{target_angle}\n".encode())
    
    start_time = time.time()
    timestamps = []
    abs_angles = []
    motor_angles = []
    target_angles = []
    
    print(f"Recording data for {TEST_DURATION}s...")
    while time.time() - start_time < TEST_DURATION:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
            continue
            
        parts = line.split(',')
        if len(parts) == 5:
            try:
                t_now = time.time() - start_time
                abs_deg = float(parts[1].strip())
                target_deg = float(parts[3].strip())
                motor_deg = float(parts[4].strip())
                
                timestamps.append(t_now)
                abs_angles.append(abs_deg)
                motor_angles.append(motor_deg)
                target_angles.append(target_deg)
            except ValueError:
                continue

    ser.close()
    
    if not timestamps:
        print("❌ No data recorded. Please check if the board is outputting serial data.")
        return
        
    print(f"✅ Successfully recorded {len(timestamps)} data points.")

    # Un-wrap absolute encoder degrees around the 0/360 boundary if necessary
    # Since we start near a baseline, we shift absolute angles to align with initial motor position
    # and correct wrapping jumps
    import numpy as np
    
    abs_arr = np.array(abs_angles)
    motor_arr = np.array(motor_angles)
    
    # Calculate offset at start
    start_offset = abs_arr[0] - motor_arr[0]
    
    # Correct wrapping around 360/0
    corrected_abs = []
    prev_corrected = abs_arr[0] - start_offset
    for a in abs_arr:
        # Subtract offset
        a_offset = a - start_offset
        # Resolve wrap relative to prev_corrected
        diff = a_offset - prev_corrected
        # Wrap diff to range [-180, 180]
        diff = (diff + 180) % 360 - 180
        curr_corrected = prev_corrected + diff
        corrected_abs.append(curr_corrected)
        prev_corrected = curr_corrected

    corrected_abs = np.array(corrected_abs)
    
    # Save CSV Log
    log_filename = "dynamic_response_data.csv"
    with open(log_filename, "w") as f:
        f.write("Time_s,Target_deg,Motor_Ref_deg,Abs_Encoder_deg_Raw,Abs_Encoder_deg_Corrected\n")
        for i in range(len(timestamps)):
            f.write(f"{timestamps[i]:.4f},{target_angles[i]:.2f},{motor_angles[i]:.2f},{abs_angles[i]:.2f},{corrected_abs[i]:.2f}\n")
    print(f"Raw data saved to: {os.path.abspath(log_filename)}")

    # Plot response curves
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    # Subplot 1: Position trajectories
    ax1.plot(timestamps, target_angles, 'k--', label='Target Angle (Command)', alpha=0.7)
    ax1.plot(timestamps, motor_angles, 'b-', label='Motor Reference Angle (TIM2)', linewidth=2)
    ax1.plot(timestamps, corrected_abs, 'r-', label='Absolute Encoder Angle (SPI)', linewidth=1.5)
    ax1.set_ylabel('Position (Degrees)')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()
    ax1.set_title(f'Dynamic Step Response ({target_angle}° Step)')

    # Subplot 2: Errors
    # 1. Motor PID tracking error (target - actual)
    pid_error = np.array(target_angles) - motor_arr
    # 2. Dynamic mismatch error (absolute encoder - motor reference)
    mismatch_error = corrected_abs - motor_arr
    
    ax2.plot(timestamps, pid_error, 'b-', label='Motor Control Error (Target - Motor Ref)')
    ax2.plot(timestamps, mismatch_error, 'r-', label='Encoder Mismatch Error (Abs - Motor Ref)')
    ax2.set_xlabel('Time (Seconds)')
    ax2.set_ylabel('Error (Degrees)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    
    plt.tight_layout()
    plot_filename = "dynamic_response_plot.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Plot saved to: {os.path.abspath(plot_filename)}")
    print("Displaying plot...")
    plt.show()

if __name__ == '__main__':
    run_dynamic_test()
