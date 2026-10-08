import serial
import time
import glob
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200

# 50 turns = 50 * 360 degrees = 18000 degrees
TURNS = 50.0
TARGET_DEG = TURNS * 360.0  # 18000°
TIMEOUT_LIMIT = 40.0        # Max time allowed for each leg in seconds
# =================================================

def unwrap_angle(raw_angles, start_offset=0.0):
    """
    Unwraps 0-360 absolute encoder angles into a continuous multi-turn trajectory.
    """
    unwrapped = []
    if len(raw_angles) == 0:
        return unwrapped
        
    # Subtract initial value to align starting point near 0
    base_val = raw_angles[0]
    prev_val = base_val
    cumulative_offset = 0.0
    
    for val in raw_angles:
        # Calculate step change
        diff = val - prev_val
        # If jump is larger than 180, it wrapped around
        if diff < -180.0:
            cumulative_offset += 360.0
        elif diff > 180.0:
            cumulative_offset -= 360.0
            
        prev_val = val
        unwrapped.append((val + cumulative_offset - base_val) + start_offset)
        
    return unwrapped

def run_multi_turn_test():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        # Use short timeout to keep reads non-blocking
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("               Motor Multi-Turn Tracking Test                ")
    print("=============================================================")
    print(f"This test will command the motor to spin {TURNS} turns forward ")
    print(f"({TARGET_DEG}°) and then {TURNS} turns backward back to 0°.")
    print("It evaluates encoder tracking linearity and zero-return accuracy.")
    print("=============================================================\n")

    # Center motor first
    print("Centering motor to 0°...")
    ser.write(b"0\n")
    time.sleep(2.0)
    ser.reset_input_buffer()

    timestamps = []
    target_angles = []
    motor_angles = []
    abs_raw_angles = []

    # Helper function to read serial port dynamically until motor settles
    def record_leg(target_goal, label):
        print(f"\n🚀 Leg: {label} (Targeting {target_goal}°)...")
        ser.write(f"{target_goal}\n".encode())
        
        leg_start = time.time()
        settle_start = None
        
        while time.time() - leg_start < TIMEOUT_LIMIT:
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
                    target_angles.append(target_deg)
                    motor_angles.append(motor_deg)
                    abs_raw_angles.append(abs_deg)
                    
                    # Check if motor has settled near target
                    if abs(motor_deg - target_goal) < 1.0:
                        if settle_start is None:
                            settle_start = time.time()
                        elif time.time() - settle_start > 1.5:
                            # Settled for 1.5 seconds
                            print(f"   ✅ Motor settled at target: {motor_deg:.2f}°")
                            break
                    else:
                        settle_start = None
                except ValueError:
                    continue
        else:
            print("   ⚠️ Leg timeout reached before complete settling.")

    start_time = time.time()
    
    # 1. Forward Leg
    record_leg(TARGET_DEG, f"Forward {TURNS} Turns")
    
    # Wait at peak
    print("Waiting at 50 turns for 2.0s...")
    time.sleep(2.0)
    
    # 2. Backward Leg
    record_leg(0.0, f"Backward {TURNS} Turns to Zero")

    ser.close()

    if not timestamps:
        print("❌ No data recorded. Please check motor connections.")
        return

    # Post-process data
    t_arr = np.array(timestamps)
    target_arr = np.array(target_angles)
    motor_arr = np.array(motor_angles)
    abs_raw_arr = np.array(abs_raw_angles)

    # Unwrap the 0-360 absolute encoder values
    # To determine tracking direction:
    # If motor increases, absolute encoder might increase or decrease depending on mounting orientation.
    # Let's inspect raw absolute encoder trend in the first few seconds
    # and invert if necessary so they plot in the same direction.
    raw_abs_unwrapped = unwrap_angle(abs_raw_arr)
    
    # Check correlation to see if absolute encoder increases or decreases when motor increases
    slope = np.polyfit(motor_arr[:len(motor_arr)//2], raw_abs_unwrapped[:len(raw_abs_unwrapped)//2], 1)[0]
    invert_factor = -1.0 if slope < 0 else 1.0
    
    abs_unwrapped = [x * invert_factor for x in raw_abs_unwrapped]

    # Save to CSV log
    csv_filename = "multi_turn_test_data.csv"
    with open(csv_filename, "w") as f:
        f.write("Time_s,Target_deg,Motor_Ref_deg,Abs_Encoder_deg_Raw,Abs_Encoder_deg_Unwrapped\n")
        for i in range(len(t_arr)):
            f.write(f"{t_arr[i]:.4f},{target_arr[i]:.2f},{motor_arr[i]:.2f},{abs_raw_arr[i]:.2f},{abs_unwrapped[i]:.2f}\n")
    print(f"\nReport successfully saved to: {os.path.abspath(csv_filename)}")

    # Print final accuracy report
    final_motor = motor_arr[-1]
    final_abs = abs_unwrapped[-1]
    peak_motor = np.max(np.abs(motor_arr))
    peak_abs = np.max(np.abs(abs_unwrapped))
    
    print("\n=========================================================================")
    print("                       Multi-Turn Accuracy Report                        ")
    print("=========================================================================")
    print(f" Peak Position Reached (Motor Ref)    : {peak_motor:.2f}° ({peak_motor/360.0:.2f} turns)")
    print(f" Peak Position Reached (Abs Encoder)  : {peak_abs:.2f}° ({peak_abs/360.0:.2f} turns)")
    print("-------------------------------------------------------------------------")
    print(f" Final Position at Zero (Motor Ref)   : {final_motor:+.3f}°")
    print(f" Final Position at Zero (Abs Encoder) : {final_abs:+.3f}°")
    print(f" Return-to-Zero Steady-State Error    : {abs(final_motor):.3f}°")
    print("=========================================================================\n")

    # Plot response curves
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    # Subplot 1: Trajectories
    ax1.plot(t_arr, target_arr, 'k--', label='Target Angle Command', alpha=0.7)
    ax1.plot(t_arr, motor_arr, 'b-', label='Motor Reference Position (Incremental)', linewidth=2.0)
    ax1.plot(t_arr, abs_unwrapped, 'r-', label='Absolute Encoder Position (Unwrapped)', linewidth=1.5)
    ax1.set_ylabel('Position (Degrees)')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()
    ax1.set_title(f'Multi-Turn Tracking Test (50 Turns Forward & Backward)')

    # Subplot 2: Trajectory Error Difference (Motor Ref - Absolute Encoder)
    tracking_diff = motor_arr - np.array(abs_unwrapped)
    ax2.plot(t_arr, tracking_diff, 'm-', label='Mismatch Error (Motor Ref - Abs Encoder)')
    ax2.set_xlabel('Time (Seconds)')
    ax2.set_ylabel('Mismatch (Degrees)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    
    plt.tight_layout()
    plot_filename = "multi_turn_tracking_plot.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Plot saved to: {os.path.abspath(plot_filename)}")
    print("Displaying plot...")
    plt.show()

if __name__ == '__main__':
    run_multi_turn_test()
