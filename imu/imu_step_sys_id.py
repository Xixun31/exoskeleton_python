import serial
import time
import glob
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import minimize

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200
RECORD_TIME = 3.0  # Seconds to record step transient response
# =================================================

def circular_mean(angles_deg):
    """Calculates circular mean of angles to prevent wrapping errors."""
    if len(angles_deg) == 0: return 0.0
    rads = np.radians(angles_deg)
    mean_rad = np.arctan2(np.sum(np.sin(rads)), np.sum(np.cos(rads)))
    return np.degrees(mean_rad) % 360.0

def angular_difference(a, b):
    """Calculates shortest angular difference (a - b) in range [-180, 180)."""
    return (a - b + 180) % 360 - 180

def simulate_2nd_order(t, u, zeta, wn, delay_sec):
    """
    Simulates a second-order system output y given input u and time t.
    G(s) = wn^2 / (s^2 + 2*zeta*wn*s + wn^2) with time delay.
    Uses sub-stepping Euler integration for numerical stability.
    """
    n = len(t)
    y_sim = np.zeros(n)
    
    # Delay index
    delay_samples = int(round(delay_sec / 0.01))
    u_delayed = np.zeros(n)
    if delay_samples > 0 and delay_samples < n:
        u_delayed[delay_samples:] = u[:-delay_samples]
        u_delayed[:delay_samples] = u[0]
    else:
        u_delayed[:] = u
        
    # Initial state
    y = u[0]
    dy = 0.0
    y_sim[0] = y
    
    # Sub-stepping factor to ensure Euler stability
    steps = 10
    
    for i in range(1, n):
        dt_full = t[i] - t[i-1]
        dt = dt_full / steps
        u_val = u_delayed[i]
        
        for _ in range(steps):
            d2y = (wn**2) * (u_val - y) - 2.0 * zeta * wn * dy
            y += dy * dt
            dy += d2y * dt
            
        y_sim[i] = y
        
    return y_sim

def run_step_sys_id():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
        print("Waiting for Nucleo Board to boot up (2s)...")
        time.sleep(2.0)
        # Force default incremental encoder feedback mode
        ser.write(b"feedback 0\n")
        time.sleep(0.1)
        ser.write(b"reset\n")
        time.sleep(0.1)
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("      IMU System Identification: Unidirectional Step Response ")
    print("=============================================================")
    print("This script will send a single step command, record the ")
    print("transient response of both Motor Encoder & IMU Pitch, and")
    print("identify the IMU transfer function G_IMU(s) and time delay.")
    print("=============================================================\n")

    print("⚠️  HARDWARE SETUP PREPARATION:")
    print("   Please tie the rubber band / spring now to preload the motor shaft.")
    print("   This keeps gear teeth meshed and eliminates backlash.")
    input("\n👉 Press Enter when you are ready to position motor and calibrate...")

    # 1. Move motor to 0° and perform zero-offset calibration
    print("\nMoving motor to 0° for Zero-Offset Calibration...")
    ser.write(b"0\n")
    time.sleep(3.0)
    
    print("Sampling zero-offset baselines (2.0s)...")
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
                motor_deg = float(parts[1].strip()) # Use absolute encoder D9 as the reference input
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
        
    print(f"✅ Calibration baselines set -> Absolute Encoder Base: {motor_baseline:.2f}°, IMU Pitch Base: {imu_baseline:.2f}°")

    # Get step target from user
    step_goal = float(input("\nEnter target step angle in degrees (default: 90.0): ").strip() or 90.0)
    
    print("\nPress Enter to trigger the step command and start recording...")
    input()
    
    print(f"🚀 Sending step command: {step_goal}°")
    ser.write(f"{step_goal}\n".encode())
    
    # 2. Record dynamic transient
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
                motor_deg = float(parts[1].strip()) # Use absolute encoder D9 as the reference input
                
                t_data.append(t_now)
                motor_data.append(motor_deg)
                imu_data.append(imu_pitch)
            except ValueError:
                continue
                
    # Centering motor back to 0° after test
    print("\nTest finished. Returning motor to 0°...")
    ser.write(b"0\n")
    ser.close()

    if len(t_data) < 50:
        print("❌ Not enough data gathered to perform identification.")
        return
        
    t_arr = np.array(t_data)
    mot_arr = np.array(motor_data)
    imu_arr = np.array(imu_data)
    
    # Align offsets
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

    # ================= System Identification using Scipy =================
    print("\nFitting second-order dynamic model to step response data...")
    
    def loss_func(params):
        zeta, wn, delay = params
        # Enforce bounds physically
        if zeta < 0.05 or zeta > 3.0 or wn < 2.0 or wn > 300.0 or delay < 0.0 or delay > 0.3:
            return 1e9
        y_sim = simulate_2nd_order(t_arr, mot_aligned, zeta, wn, delay)
        return np.sum((y_sim - imu_aligned)**2)

    # Grid search for initial guess
    best_loss = 1e9
    best_guess = [0.7, 50.0, 0.02]
    
    for z in [0.2, 0.5, 0.9, 1.4]:
        for w in [20.0, 60.0, 110.0, 170.0]:
            for d in [0.005, 0.02, 0.04]:
                l = loss_func([z, w, d])
                if l < best_loss:
                    best_loss = l
                    best_guess = [z, w, d]
                    
    # Optimize parameters
    res = minimize(loss_func, best_guess, method='Nelder-Mead', options={'maxiter': 500})
    zeta, wn, delay_sec = res.x
    fn = wn / (2.0 * np.pi)
    delay_ms = delay_sec * 1000.0
    
    # Calculate simulated output with optimized parameters
    y_sim_opt = simulate_2nd_order(t_arr, mot_aligned, zeta, wn, delay_sec)
    
    # Bandwidth (-3dB frequency)
    bw_rad = wn * np.sqrt((1.0 - 2.0*zeta**2) + np.sqrt((1.0 - 2.0*zeta**2)**2 + 1.0))
    bw_hz = bw_rad / (2.0 * np.pi)
    
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

    # Save to CSV
    csv_filename = "imu_step_sys_id_report.csv"
    with open(csv_filename, 'w') as f:
        f.write("Time_s,Motor_Ref_deg,Measured_IMU_deg,Simulated_IMU_deg\n")
        for i in range(len(t_arr)):
            f.write(f"{t_arr[i]:.4f},{mot_aligned[i]:.2f},{imu_aligned[i]:.2f},{y_sim_opt[i]:.2f}\n")
    print(f"Report successfully saved to: {os.path.abspath(csv_filename)}")

    # Print Results
    print("\n=========================================================================")
    print("                 IMU Step Identification Results (單向階躍)              ")
    print("=========================================================================")
    print(f" identified IMU Damping Ratio (ζ)         : {zeta:.3f}")
    print(f" identified IMU Natural Frequency (ωn)    : {wn:.3f} rad/s ({fn:.2f} Hz)")
    print(f" identified IMU Pure Time Delay (L)       : {delay_ms:.1f} ms ({delay_sec:.4f} s)")
    print(f" IMU Sensor Bandwidth (-3dB Frequency)    : {bw_rad:.3f} rad/s ({bw_hz:.2f} Hz)")
    print("-------------------------------------------------------------------------")
    print(" 📋 IMU TRANSFER FUNCTION (轉移函數):")
    print(f"                          {wn**2:.2f}")
    print(f"     G_IMU(s) = ----------------------------- * e^(-{delay_sec:.4f} s)")
    print(f"                 s^2 + {2.0*zeta*wn:.2f} s + {wn**2:.2f}")
    print("-------------------------------------------------------------------------")
    print(" 📋 IMU DIFFERENTIAL EQUATION (系統微分方程):")
    print(f"     y''(t) + {2.0*zeta*wn:.2f} y'(t) + {wn**2:.2f} y(t) = {wn**2:.2f} u(t - {delay_sec:.4f})")
    print("     (其中 u(t) 為外接絕對編碼器實際角度，y(t) 為 IMU 讀取角度)")
    print("-------------------------------------------------------------------------")
    print(" 📋 THEORETICAL STEP RESPONSE (理論階躍響應特性):")
    print(f"     Overshoot (超調量)        : {overshoot:.1f} %")
    print(f"     Rise Time (上升時間)      : {rise_time:.3f} s")
    print(f"     Settling Time (2% 收斂時間): {settling_time:.3f} s")
    print("=========================================================================\n")

    # ================= Plotting =================
    plt.figure(figsize=(10, 6))
    plt.plot(t_arr, mot_aligned, 'b-', label='Absolute Encoder Position (Input)', linewidth=2.0)
    plt.plot(t_arr, imu_aligned, 'g-', label='IMU Pitch Position (Measured, Output)', linewidth=1.8)
    plt.plot(t_arr, y_sim_opt, 'r--', label='Identified Model Output (Simulated)', linewidth=1.5)
    
    plt.title(f'IMU Step Response & Model Identification\nζ={zeta:.3f}, ωn={wn:.2f} rad/s, Delay={delay_ms:.1f} ms')
    plt.xlabel('Time (Seconds)')
    plt.ylabel('Relative Position (Degrees)')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.tight_layout()
    
    plot_filename = "imu_step_sys_id_plot.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Bode step fitting plot saved to: {os.path.abspath(plot_filename)}")
    print("Displaying plot...")
    plt.show()

if __name__ == '__main__':
    run_step_sys_id()
