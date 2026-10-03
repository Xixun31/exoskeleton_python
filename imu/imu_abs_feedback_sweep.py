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

# Frequencies to sweep in Hz
FREQUENCIES = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
SWEEP_AMP = 25.0    # Sine wave amplitude in degrees (safe for all frequencies)
SETTLE_TIME = 2.0  # Seconds to wait for transient to decay
RECORD_TIME = 4.0  # Seconds to record data for analysis
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

def run_abs_feedback_sweep():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("      IMU Sweep with Absolute Encoder as Motor Feedback       ")
    print("=============================================================")
    print("Select absolute encoder for feedback source:")
    print("  1. Absolute Encoder 1 (CS on D9)")
    print("  2. Absolute Encoder 2 (CS on D10)")
    choice = input("Enter choice (1 or 2, default: 2): ").strip() or "2"
    
    feedback_mode = 2 if choice == "2" else 1
    feedback_name = f"Absolute Encoder {feedback_mode}"
    
    print(f"\n🔄 Switching motor feedback source to: {feedback_name}")
    # Command Mbed to switch feedback source (feedback 1 or feedback 2)
    ser.write(f"feedback {feedback_mode}\n".encode())
    time.sleep(0.5)

    print("\n⚠️  HARDWARE SETUP PREPARATION:")
    print("   Please tie the rubber band / spring now to preload the motor shaft.")
    print("   This keeps gear teeth meshed and eliminates backlash.")
    input("\n👉 Press Enter when you are ready to start the sweep calibration...")

    # 1. Center motor and perform zero-offset calibration at 0°
    print("Moving motor to 0° for Zero-Offset Calibration...")
    ser.write(b"0\n")
    time.sleep(3.0)
    
    print("Sampling zero-offset baselines at 0° (2.0s)...")
    ser.reset_input_buffer()
    start_cal = time.time()
    cal_motor_samples = []
    cal_imu_pitch_samples = []
    
    while time.time() - start_cal < 2.0:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
            continue
        parts = line.split(',')
        if len(parts) == 7:
            try:
                imu_pitch = float(parts[3].strip())
                motor_deg = float(parts[6].strip())
                cal_imu_pitch_samples.append(imu_pitch)
                cal_motor_samples.append(motor_deg)
            except ValueError:
                continue
                
    if len(cal_motor_samples) >= 10:
        motor_baseline = circular_mean(cal_motor_samples)
        imu_baseline = circular_mean(cal_imu_pitch_samples)
    else:
        motor_baseline = 0.0
        imu_baseline = 0.0
        print("⚠️ Warning: Not enough samples for calibration. Using default zero baselines.")
        
    print(f"✅ Calibration baselines set at 0° -> Motor Base: {motor_baseline:.2f}°, IMU Pitch Base: {imu_baseline:.2f}°")

    sweep_freqs = []
    sweep_gains = []
    sweep_phases = []

    try:
        for f in FREQUENCIES:
            print(f"\n👉 Sweeping frequency: {f} Hz (amplitude: {SWEEP_AMP}°, offset: 0°)...")
            
            # Send sine command to board with 0 degrees offset
            ser.write(f"sine {SWEEP_AMP} {f} 0\n".encode())
            
            # Wait for startup transient to settle
            time.sleep(SETTLE_TIME)
            
            # Record data
            ser.reset_input_buffer()
            start_time = time.time()
            
            t_data = []
            motor_data = []
            imu_data = []
            
            while time.time() - start_time < RECORD_TIME:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
                    continue
                parts = line.split(',')
                if len(parts) == 7:
                    try:
                        t_now = time.time() - start_time
                        imu_pitch = float(parts[3].strip())
                        motor_deg = float(parts[6].strip())
                        
                        t_data.append(t_now)
                        motor_data.append(motor_deg)
                        imu_data.append(imu_pitch)
                    except ValueError:
                        continue
            
            if len(t_data) < 50:
                print(f"   ⚠️ Too few data points ({len(t_data)}). Skipping.")
                continue
                
            t_arr = np.array(t_data)
            mot_arr = np.array(motor_data)
            imu_arr = np.array(imu_data)
            
            # Align offsets using angular_difference to handle wrapping properly
            mot_aligned = np.array([angular_difference(val, motor_baseline) for val in mot_arr])
            imu_aligned = np.array([angular_difference(val, imu_baseline) for val in imu_arr])
            
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
                print("   ℹ️ Inverting IMU sign for analysis.")
                
            # Fit sine waves to input (motor) and output (imu)
            amp_in, phi_in, C_in = fit_sine(t_arr, mot_aligned, f)
            amp_out, phi_out, C_out = fit_sine(t_arr, imu_aligned, f)
            
            # Calculate gain and phase difference
            gain = amp_out / amp_in if amp_in > 0.1 else 0.0
            gain_db = 20.0 * np.log10(gain) if gain > 0.0 else -99.0
            
            phase_diff_rad = phi_out - phi_in
            phase_diff_rad = (phase_diff_rad + np.pi) % (2.0 * np.pi) - np.pi
            phase_diff_deg = np.degrees(phase_diff_rad)
            if phase_diff_deg > 30.0: phase_diff_deg -= 360.0
            
            print(f"   Motor Amp: {amp_in:.2f}° | IMU Amp: {amp_out:.2f}°")
            print(f"   Gain: {gain:6.3f} ({gain_db:6.2f} dB) | Phase Lag: {phase_diff_deg:+6.2f}°")
            
            sweep_freqs.append(f)
            sweep_gains.append(gain)
            sweep_phases.append(phase_diff_deg)
            
    except KeyboardInterrupt:
        print("\nSweep interrupted by user.")
    
    # Return to 0, turn off sine, and restore incremental feedback mode (feedback 0)
    print("\nStopping sweep and restoring default incremental feedback...")
    ser.write(b"0\n")
    ser.write(b"feedback 0\n")
    ser.close()

    if len(sweep_freqs) < 3:
        print("❌ Not enough frequency data points gathered to identify the IMU model. Exiting.")
        return

    # ================= IMU System Identification (SysID) =================
    # Fit a second-order model: G_IMU(s) = wn^2 / (s^2 + 2*z*wn*s + wn^2)
    w_experimental = 2.0 * np.pi * np.array(sweep_freqs)
    H_experimental = np.array(sweep_gains) * np.exp(1j * np.radians(sweep_phases))
    
    best_err = float('inf')
    best_zeta = 0.7
    best_wn = 20.0
    
    zetas = np.linspace(0.1, 1.8, 171)
    wns = np.linspace(5.0, 250.0, 2451)
    
    for z in zetas:
        for wn in wns:
            H_theo = (wn**2) / (-w_experimental**2 + 2.0j * z * wn * w_experimental + wn**2)
            err = np.sum(np.abs(H_experimental - H_theo)**2)
            if err < best_err:
                best_err = err
                best_zeta = z
                best_wn = wn
                
    zeta = best_zeta
    wn = best_wn
    fn = wn / (2.0 * np.pi)
    
    # Save sweep results to CSV
    csv_filename = "imu_abs_feedback_sweep_report.csv"
    with open(csv_filename, "w") as f:
        f.write("Frequency_Hz,Gain_linear,Gain_dB,Phase_deg\n")
        for i in range(len(sweep_freqs)):
            f.write(f"{sweep_freqs[i]:.2f},{sweep_gains[i]:.4f},{20*np.log10(sweep_gains[i]):.2f},{sweep_phases[i]:.2f}\n")
    print(f"\nReport successfully saved to: {os.path.abspath(csv_filename)}")

    # Calculate step response characteristics based on identified parameters
    if zeta < 1.0:
        overshoot = np.exp(-np.pi * zeta / np.sqrt(1.0 - zeta**2)) * 100.0
        wd = wn * np.sqrt(1.0 - zeta**2)
        beta = np.arccos(zeta)
        rise_time = (np.pi - beta) / wd
    else:
        overshoot = 0.0
        rise_time = (1.0 + 1.5 * zeta + 0.5 * zeta**2) / wn
        
    settling_time = 4.0 / (zeta * wn)
    
    # Bandwidth calculation
    bw_rad = wn * np.sqrt((1.0 - 2.0*zeta**2) + np.sqrt((1.0 - 2.0*zeta**2)**2 + 1.0))
    bw_hz = bw_rad / (2.0 * np.pi)

    # Print IMU SysID results
    print("\n=========================================================================")
    print("                      IMU Sensor Identification Results                  ")
    print("=========================================================================")
    print(f" identified IMU Damping Ratio (ζ)     : {zeta:.3f}")
    print(f" identified IMU Natural Frequency (ωn): {wn:.3f} rad/s ({fn:.2f} Hz)")
    print(f" IMU Sensor Bandwidth (-3dB Frequency): {bw_rad:.3f} rad/s ({bw_hz:.2f} Hz)")
    print("-------------------------------------------------------------------------")
    print(" 📋 IMU TRANSFER FUNCTION (轉移函數):")
    print(f"                 {wn**2:.2f}")
    print(f"     G_IMU(s) = -------------------------")
    print(f"               s^2 + {2.0*zeta*wn:.2f} s + {wn**2:.2f}")
    print("-------------------------------------------------------------------------")
    print(" 📋 IMU DIFFERENTIAL EQUATION (系統微分方程):")
    print(f"     y''(t) + {2.0*zeta*wn:.2f} y'(t) + {wn**2:.2f} y(t) = {wn**2:.2f} u(t)")
    print("     (其中 u(t) 為馬達實際角度，y(t) 為 IMU 讀取角度)")
    print("-------------------------------------------------------------------------")
    print(" 📋 IMU THEORETICAL STEP RESPONSE (理論階躍響應特性):")
    print(f"     Overshoot (超調量)        : {overshoot:.1f} %")
    print(f"     Rise Time (上升時間)      : {rise_time:.3f} s")
    print(f"     Settling Time (2% 收斂時間): {settling_time:.3f} s")
    print("=========================================================================\n")

    # ================= Plotting =================
    freq_grid = np.linspace(min(sweep_freqs)*0.8, max(sweep_freqs)*1.2, 500)
    w_grid = 2.0 * np.pi * freq_grid
    H_grid = (wn**2) / (-w_grid**2 + 2.0j * zeta * wn * w_grid + wn**2)
    
    gain_grid_db = 20.0 * np.log10(np.abs(H_grid))
    phase_grid_deg = np.degrees(np.angle(H_grid))
    phase_grid_deg = (phase_grid_deg + 180.0) % 360.0 - 180.0
    phase_grid_deg[phase_grid_deg > 30.0] -= 360.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    # Subplot 1: Gain
    ax1.semilogx(sweep_freqs, 20.0*np.log10(sweep_gains), 'bo', label='IMU Experimental Data', markersize=8)
    ax1.semilogx(freq_grid, gain_grid_db, 'r-', label=f'Fitted IMU Model (ζ={zeta:.2f}, fn={fn:.1f}Hz)', linewidth=2)
    ax1.set_ylabel('Gain (dB)')
    ax1.grid(True, which="both", linestyle='--', alpha=0.6)
    ax1.legend()
    ax1.set_title('IMU Bode Plot (Absolute Encoder Feedback)')

    # Subplot 2: Phase
    ax2.semilogx(sweep_freqs, sweep_phases, 'bo', label='IMU Experimental Data', markersize=8)
    ax2.semilogx(freq_grid, phase_grid_deg, 'r-', label=f'Fitted IMU Model', linewidth=2)
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('Phase (Degrees)')
    ax2.grid(True, which="both", linestyle='--', alpha=0.6)
    
    plt.tight_layout()
    plot_filename = "imu_abs_feedback_sweep_plot.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Bode plot saved to: {os.path.abspath(plot_filename)}")
    plt.show()

if __name__ == '__main__':
    run_abs_feedback_sweep()
