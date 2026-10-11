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
# =================================================

def fit_sine(t, y, freq):
    """Fits a sine wave of a known frequency to the data (t, y) using least-squares."""
    omega = 2.0 * np.pi * freq
    M = np.column_stack((np.sin(omega * t), np.cos(omega * t), np.ones_like(t)))
    try:
        coeff, _, _, _ = np.linalg.lstsq(M, y, rcond=None)
        a, b, C = coeff
        amp = np.sqrt(a**2 + b**2)
        phi = np.arctan2(b, a)
        return amp, phi, C
    except Exception:
        return 0.0, 0.0, 0.0

def circular_mean(angles_deg):
    """Calculates circular mean of angles to prevent wrapping errors."""
    if len(angles_deg) == 0: return 0.0
    rads = np.radians(angles_deg)
    mean_rad = np.arctan2(np.sum(np.sin(rads)), np.sum(np.cos(rads)))
    return np.degrees(mean_rad) % 360.0

def angular_difference(a, b):
    """Calculates shortest angular difference (a - b) in range [-180, 180)."""
    return (a - b + 180) % 360 - 180

def run_static_test(ser):
    print("\n-------------------------------------------------------------")
    # Sweep from 0 to 90 degrees in steps of 15 (one-way)
    targets = list(range(0, 91, 15))
    results = []
    
    print("Resetting motor to 0° for Zero-Offset Calibration...")
    ser.write(b"0\n")
    time.sleep(3.0)
    
    # Sample zero baseline
    print("Sampling zero-offset baselines (2.0s)...")
    ser.reset_input_buffer()
    start_cal = time.time()
    cal_motor_samples = []
    cal_imu_samples = []
    
    while time.time() - start_cal < 2.0:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
            continue
        parts = line.split(',')
        if len(parts) == 7:
            try:
                imu_pitch = float(parts[3].strip())
                motor_deg = float(parts[6].strip())
                cal_imu_samples.append(imu_pitch)
                cal_motor_samples.append(motor_deg)
            except ValueError:
                continue
                
    if len(cal_motor_samples) >= 10:
        motor_baseline = circular_mean(cal_motor_samples)
        imu_baseline = circular_mean(cal_imu_samples)
    else:
        motor_baseline = 0.0
        imu_baseline = 0.0
        print("⚠️ Warning: Not enough samples for calibration. Using default zero baselines.")
        
    print(f"✅ Calibration baselines set -> Motor Base: {motor_baseline:.2f}°, IMU Base: {imu_baseline:.2f}°")
    
    invert_factor = 1.0
    direction_detected = False
    
    for t_deg in targets:
        print(f"\n👉 Target: {t_deg}°")
        ser.write(f"{t_deg}\n".encode())
        
        # Settle
        print("   Settling for 2.5s...")
        time.sleep(2.5)
        
        # Sample for 2.0s
        print("   Sampling for 2.0s...")
        ser.reset_input_buffer()
        start = time.time()
        
        abs_deg_samples = []
        imu_pitch_samples = []
        motor_deg_samples = []
        
        while time.time() - start < 2.0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
                continue
            parts = line.split(',')
            if len(parts) == 7:
                try:
                    abs_deg = float(parts[1].strip())
                    imu_pitch = float(parts[3].strip())
                    motor_deg = float(parts[6].strip())
                    
                    abs_deg_samples.append(abs_deg)
                    imu_pitch_samples.append(imu_pitch)
                    motor_deg_samples.append(motor_deg)
                except ValueError:
                    continue
                    
        if len(motor_deg_samples) < 10:
            print("   ⚠️ No data gathered. Skipping.")
            continue
            
        m_ref_raw = circular_mean(motor_deg_samples)
        m_abs = circular_mean(abs_deg_samples)
        m_imu_raw = circular_mean(imu_pitch_samples)
        
        # Calibrate relative to baseline
        m_ref = angular_difference(m_ref_raw, motor_baseline)
        m_imu_rel = angular_difference(m_imu_raw, imu_baseline)
        
        # Detect direction inversion on the first significant movement (e.g. > 5 degrees)
        if not direction_detected and abs(m_ref) > 5.0:
            if (m_imu_rel * m_ref) < 0:
                invert_factor = -1.0
                print("   ℹ️ Detected opposite IMU rotation direction. Inverting IMU sign for calibration.")
            else:
                invert_factor = 1.0
                print("   ℹ️ Detected matching IMU rotation direction.")
            direction_detected = True
            
        m_imu = m_imu_rel * invert_factor
        
        # Calculate error (IMU relative to motor standards)
        err_vs_ref = angular_difference(m_imu, m_ref)
        err_vs_abs = angular_difference(m_imu, m_abs)
        
        print(f"   Motor Ref (Calibrated): {m_ref:6.2f}° | IMU Pitch (Calibrated): {m_imu:6.2f}°")
        print(f"   IMU Error vs Motor Ref: {err_vs_ref:+6.2f}°")
        
        results.append({
            'target': t_deg,
            'ref_motor': m_ref,
            'ref_abs': m_abs,
            'imu_pitch': m_imu,
            'err_vs_ref': err_vs_ref,
            'err_vs_abs': err_vs_abs
        })

    # Save to CSV
    csv_filename = "motor_imu_static_report.csv"
    with open(csv_filename, 'w') as f:
        f.write("Target_deg,Motor_Ref_deg,Abs_Encoder_deg,IMU_Pitch_deg,Error_vs_Ref,Error_vs_Abs\n")
        for r in results:
            f.write(f"{r['target']:.1f},{r['ref_motor']:.2f},{r['ref_abs']:.2f},{r['imu_pitch']:.2f},{r['err_vs_ref']:.3f},{r['err_vs_abs']:.3f}\n")
    print(f"\nReport successfully saved to: {os.path.abspath(csv_filename)}")

    # Plot
    ref_vals = [r['ref_motor'] for r in results]
    err_ref = [r['err_vs_ref'] for r in results]
    
    plt.figure(figsize=(10, 6))
    plt.plot(ref_vals, err_ref, 'rs-', label='IMU Pitch Error vs. Motor Reference', linewidth=1.5)
    plt.axhline(0, color='gray', linestyle=':')
    plt.title('IMU Static Pitch Calibration Error Curve')
    plt.xlabel('Reference Angle (Degrees)')
    plt.ylabel('IMU Measurement Error (Degrees)')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.tight_layout()
    
    plot_filename = "motor_imu_static_plot.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Plot saved to: {os.path.abspath(plot_filename)}")
    plt.show()

def run_dynamic_test(ser):
    print("\n-------------------------------------------------------------")
    print("Select dynamic excitation mode:")
    print("  1. Step Response Test (e.g. 0° -> 60°)")
    print("  2. Sinusoidal Tracking Test (sine wave oscillation)")
    choice = input("Enter choice (1 or 2): ").strip()
    
    ser.write(b"0\n")
    time.sleep(2.0)
    ser.reset_input_buffer()
    
    if choice == '2':
        # Sine tracking mode
        freq = float(input("Enter oscillation frequency in Hz (e.g. 1.5): ").strip() or 1.5)
        amp = float(input("Enter oscillation amplitude in degrees (e.g. 25.0): ").strip() or 25.0)
        
        print(f"\nTriggering sine sweep: amplitude {amp}°, frequency {freq} Hz...")
        ser.write(f"sine {amp} {freq}\n".encode())
        time.sleep(1.5) # Wait for startup transient
        ser.reset_input_buffer()
        
        # Record
        start = time.time()
        t_data, target_data, motor_data, abs_data, imu_data = [], [], [], [], []
        
        while time.time() - start < 4.0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
                continue
            parts = line.split(',')
            if len(parts) == 7:
                try:
                    t_now = time.time() - start
                    abs_deg = float(parts[1].strip())
                    imu_pitch = float(parts[3].strip())
                    target_deg = float(parts[5].strip())
                    motor_deg = float(parts[6].strip())
                    
                    t_data.append(t_now)
                    target_data.append(target_deg)
                    motor_data.append(motor_deg)
                    abs_data.append(abs_deg)
                    imu_data.append(imu_pitch)
                except ValueError:
                    continue
        
        ser.write(b"0\n") # Centering
        
        if len(t_data) < 50:
            print("❌ No data gathered.")
            return
            
        t_arr = np.array(t_data)
        mot_arr = np.array(motor_data)
        imu_arr = np.array(imu_data)
        
        # Subtract initial offset to align
        mot_offset = mot_arr[0]
        imu_offset = imu_arr[0]
        mot_aligned = mot_arr - mot_offset
        imu_aligned = imu_arr - imu_offset
        
        # Detect direction inversion
        std_mot = np.std(mot_aligned)
        std_imu = np.std(imu_aligned)
        correlation = 1.0
        if std_mot > 1e-4 and std_imu > 1e-4:
            correlation = np.corrcoef(mot_aligned, imu_aligned)[0, 1]
            
        invert_factor = 1.0
        if correlation < -0.5:
            invert_factor = -1.0
            imu_aligned = -imu_aligned
            print("   ℹ️ Detected opposite IMU rotation direction. Inverting IMU sign for analysis.")
            
        # Fit sine to find phase delay
        amp_mot, phi_mot, _ = fit_sine(t_arr, mot_aligned, freq)
        amp_imu, phi_imu, _ = fit_sine(t_arr, imu_aligned, freq)
        
        phase_lag_rad = phi_imu - phi_mot
        phase_lag_rad = (phase_lag_rad + np.pi) % (2.0 * np.pi) - np.pi
        phase_lag_deg = np.degrees(phase_lag_rad)
        if phase_lag_deg > 30.0: phase_lag_deg -= 360.0
        
        # Time delay
        time_delay_ms = (-phase_lag_rad / (2.0 * np.pi * freq)) * 1000.0
        
        print("\n=======================================================")
        print("             Dynamic Sine Test Results                 ")
        print("=======================================================")
        print(f" Frequency                  : {freq:.2f} Hz")
        print(f" Motor Amplitude (Encoder)  : {amp_mot:.2f}°")
        print(f" IMU Amplitude (Measured)   : {amp_imu:.2f}°")
        print(f" IMU Phase Lag vs Motor Ref : {phase_lag_deg:+.2f}°")
        print(f" Equivalent Time Delay (ms) : {time_delay_ms:.1f} ms")
        print("=======================================================\n")
        
        # Plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        ax1.plot(t_arr, target_data, 'k--', label='Target Command', alpha=0.5)
        ax1.plot(t_arr, mot_arr, 'b-', label='Motor Reference (Encoder)', linewidth=2)
        ax1.plot(t_arr, mot_offset + imu_aligned, 'g-', label='IMU Pitch Output (Calibrated Direction & Offset)', linewidth=1.5)
        ax1.set_ylabel('Position (Degrees)')
        ax1.legend()
        ax1.grid(True)
        ax1.set_title(f'IMU Sinusoidal Dynamic Tracking at {freq} Hz')
        
        # Mismatch error
        ax2.plot(t_arr, (imu_offset + imu_aligned) - mot_arr, 'r-', label='Tracking Mismatch Error (IMU - Motor Ref)')
        ax2.set_xlabel('Time (Seconds)')
        ax2.set_ylabel('Error (Degrees)')
        ax2.legend()
        ax2.grid(True)
        
        plt.tight_layout()
        plt.savefig("motor_imu_dynamic_plot.png", dpi=300)
        print("Dynamic tracking plot saved as motor_imu_dynamic_plot.png")
        plt.show()

    else:
        # Step response mode
        step_goal = float(input("Enter step angle in degrees (e.g. 60.0): ").strip() or 60.0)
        
        print("\nPreparing step test...")
        ser.write(b"0\n")
        time.sleep(2.0)
        ser.reset_input_buffer()
        
        print("Press Enter to trigger step change and start recording...")
        input()
        
        print(f"🚀 Sending step command: {step_goal}°")
        ser.write(f"{step_goal}\n".encode())
        
        start = time.time()
        t_data, target_data, motor_data, abs_data, imu_data = [], [], [], [], []
        
        while time.time() - start < 3.0:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
                continue
            parts = line.split(',')
            if len(parts) == 7:
                try:
                    t_now = time.time() - start
                    abs_deg = float(parts[1].strip())
                    imu_pitch = float(parts[3].strip())
                    target_deg = float(parts[5].strip())
                    motor_deg = float(parts[6].strip())
                    
                    t_data.append(t_now)
                    target_data.append(target_deg)
                    motor_data.append(motor_deg)
                    abs_data.append(abs_deg)
                    imu_data.append(imu_pitch)
                except ValueError:
                    continue
                    
        if len(t_data) < 50:
            print("❌ No data gathered.")
            return
            
        t_arr = np.array(t_data)
        mot_arr = np.array(motor_data)
        imu_arr = np.array(imu_data)
        
        # Align offsets
        mot_offset = mot_arr[0]
        imu_offset = imu_arr[0]
        mot_aligned = mot_arr - mot_offset
        imu_aligned = imu_arr - imu_offset
        
        # Detect direction inversion
        std_mot = np.std(mot_aligned)
        std_imu = np.std(imu_aligned)
        correlation = 1.0
        if std_mot > 1e-4 and std_imu > 1e-4:
            correlation = np.corrcoef(mot_aligned, imu_aligned)[0, 1]
            
        invert_factor = 1.0
        if correlation < -0.5:
            invert_factor = -1.0
            imu_aligned = -imu_aligned
            print("   ℹ️ Detected opposite IMU rotation direction. Inverting IMU sign for analysis.")
            
        imu_plotted = mot_offset + imu_aligned
        
        # Save CSV Log
        csv_filename = "motor_imu_dynamic_report.csv"
        with open(csv_filename, 'w') as f:
            f.write("Time_s,Target_deg,Motor_Ref_deg,Abs_Encoder_deg,IMU_Pitch_deg_Raw,IMU_Pitch_deg_Aligned\n")
            for i in range(len(t_arr)):
                f.write(f"{t_data[i]:.4f},{target_data[i]:.2f},{motor_data[i]:.2f},{abs_data[i]:.2f},{imu_data[i]:.2f},{imu_plotted[i]:.2f}\n")
        print(f"\nReport successfully saved to: {os.path.abspath(csv_filename)}")
        
        # Plot
        plt.figure(figsize=(10, 6))
        plt.plot(t_arr, target_data, 'k--', label='Target Angle Command', alpha=0.6)
        plt.plot(t_arr, motor_data, 'b-', label='Motor Reference (Encoder)', linewidth=2)
        plt.plot(t_arr, imu_plotted, 'g-', label='IMU Pitch Position (Calibrated Direction & Offset)', linewidth=1.5)
        plt.title(f'IMU Step Response Profile ({step_goal}° Step)')
        plt.xlabel('Time (Seconds)')
        plt.ylabel('Angle (Degrees)')
        plt.grid(True, linestyle='--', alpha=0.6)
        plt.legend()
        plt.tight_layout()
        
        plt.savefig("motor_imu_dynamic_plot.png", dpi=300)
        print("Dynamic step plot saved as motor_imu_dynamic_plot.png")
        plt.show()

def main():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("            Motor-IMU Dynamic & Static Calibration           ")
    print("=============================================================")
    print("Select test mode:")
    print("  1. Static Sweep Calibration (0 -> 90 -> 0 degrees sweep)")
    print("  2. Dynamic Tracking Test (sine tracking / step response)")
    mode = input("Enter choice (1 or 2): ").strip()
    
    if mode == '1':
        run_static_test(ser)
    elif mode == '2':
        run_dynamic_test(ser)
    else:
        print("Invalid choice.")
        
    ser.close()

if __name__ == '__main__':
    main()
