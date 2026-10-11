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
FREQUENCIES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
SWEEP_AMP = 25.0    # Sine wave amplitude in degrees (safe for all frequencies)
SETTLE_TIME = 2.0  # Seconds to wait for transient to decay
RECORD_TIME = 4.0  # Seconds to record data for analysis
# =================================================

def fit_sine(t, y, freq):
    """
    Fits a sine wave of a known frequency to the data (t, y) using least-squares.
    y = A * sin(2*pi*freq * t + phi) + C
      = a * sin(2*pi*freq * t) + b * cos(2*pi*freq * t) + C
    """
    omega = 2.0 * np.pi * freq
    M = np.column_stack((np.sin(omega * t), np.cos(omega * t), np.ones_like(t)))
    try:
        # Solve least squares
        coeff, _, _, _ = np.linalg.lstsq(M, y, rcond=None)
        a, b, C = coeff
        amp = np.sqrt(a**2 + b**2)
        phi = np.arctan2(b, a) # Phase in radians
        return amp, phi, C
    except Exception as e:
        print(f"Error fitting sine: {e}")
        return 0.0, 0.0, 0.0

def run_sweep():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.01)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        sys.exit(1)

    print("\n=============================================================")
    print("      Motor System Identification: Sinusoidal Sweep          ")
    print("=============================================================")
    print("This script will sweep the motor target through several ")
    print("frequencies, measure the amplitude ratio (Gain) and phase ")
    print("lag, and identify the closed-loop transfer function.")
    print("=============================================================\n")

    # Center motor first
    print("Centering motor to 0°...")
    ser.write(b"0\n")
    time.sleep(2.0)
    ser.reset_input_buffer()

    sweep_freqs = []
    sweep_gains = []
    sweep_phases = []

    try:
        for f in FREQUENCIES:
            print(f"👉 Sweeping frequency: {f} Hz (amplitude: {SWEEP_AMP}°)...")
            
            # Send sine command to board: e.g. "sine 25 2.0\n"
            ser.write(f"sine {SWEEP_AMP} {f}\n".encode())
            
            # 1. Wait for transient to settle
            time.sleep(SETTLE_TIME)
            
            # 2. Record data
            ser.reset_input_buffer()
            start_time = time.time()
            
            t_data = []
            target_data = []
            actual_data = []
            
            while time.time() - start_time < RECORD_TIME:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line or line.startswith(">>") or line.startswith("==") or "Started" in line:
                    continue
                parts = line.split(',')
                if len(parts) >= 5:
                    try:
                        t_now = time.time() - start_time
                        if len(parts) == 7:
                            target_deg = float(parts[5].strip())
                            actual_deg = float(parts[6].strip())
                        else:
                            target_deg = float(parts[3].strip())
                            actual_deg = float(parts[4].strip())
                        
                        t_data.append(t_now)
                        target_data.append(target_deg)
                        actual_data.append(actual_deg)
                    except ValueError:
                        continue
            
            if len(t_data) < 50:
                print(f"   ⚠️ Too few data points ({len(t_data)}). Skipping.")
                continue
                
            t_arr = np.array(t_data)
            target_arr = np.array(target_data)
            actual_arr = np.array(actual_data)
            
            # Fit sine waves to input and output
            amp_in, phi_in, C_in = fit_sine(t_arr, target_arr, f)
            amp_out, phi_out, C_out = fit_sine(t_arr, actual_arr, f)
            
            # Calculate gain and phase difference
            gain = amp_out / amp_in if amp_in > 0.1 else 0.0
            gain_db = 20.0 * np.log10(gain) if gain > 0.0 else -99.0
            
            phase_diff_rad = phi_out - phi_in
            # Wrap phase difference to [-pi, pi]
            phase_diff_rad = (phase_diff_rad + np.pi) % (2.0 * np.pi) - np.pi
            phase_diff_deg = np.degrees(phase_diff_rad)
            
            # Since the output lags the input, phase difference should be negative
            # If it wrapped to positive, shift it by -360
            if phase_diff_deg > 30.0:
                phase_diff_deg -= 360.0
            
            print(f"   Gain: {gain:6.3f} ({gain_db:6.2f} dB) | Phase Lag: {phase_diff_deg:+6.2f}°")
            
            sweep_freqs.append(f)
            sweep_gains.append(gain)
            sweep_phases.append(phase_diff_deg)
            
    except KeyboardInterrupt:
        print("\nSweep interrupted by user.")
    
    # Return to 0 and turn off sine mode
    print("\nStopping sweep and centering motor...")
    ser.write(b"0\n")
    ser.close()

    if len(sweep_freqs) < 3:
        print("❌ Not enough frequency data points gathered to identify the model. Exiting.")
        return

    # ================= System Identification (SysID) =================
    # We fit a second-order transfer function model:
    # G(s) = omega_n^2 / (s^2 + 2 * zeta * omega_n * s + omega_n^2)
    # G(jw) = omega_n^2 / (-w^2 + 2*j*zeta*omega_n * w + omega_n^2)
    
    w_experimental = 2.0 * np.pi * np.array(sweep_freqs)
    H_experimental = np.array(sweep_gains) * np.exp(1j * np.radians(sweep_phases))
    
    # Grid search for optimal zeta and omega_n to minimize squared error in complex space
    best_err = float('inf')
    best_zeta = 0.7
    best_wn = 10.0
    
    # Grid limits
    zetas = np.linspace(0.1, 1.8, 171) # Damping ratio search range
    wns = np.linspace(5.0, 80.0, 751)  # Natural frequency (rad/s) search range
    
    for z in zetas:
        for wn in wns:
            # Theoretical response
            H_theo = (wn**2) / (-w_experimental**2 + 2.0j * z * wn * w_experimental + wn**2)
            # Weighted least squares error (putting more weight on low/mid frequencies)
            err = np.sum(np.abs(H_experimental - H_theo)**2)
            if err < best_err:
                best_err = err
                best_zeta = z
                best_wn = wn
                
    zeta = best_zeta
    wn = best_wn
    fn = wn / (2.0 * np.pi)
    
    # Save sweep results to CSV
    csv_filename = "sys_id_sweep_report.csv"
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
        # For overdamped system, approximate rise time
        rise_time = (1.0 + 1.5 * zeta + 0.5 * zeta**2) / wn
        
    settling_time = 4.0 / (zeta * wn) # 2% settling criterion
    
    # Bandwidth calculation (-3dB frequency)
    # |G(jw)|^2 = 0.5 -> solve for w
    # w_3db = wn * sqrt( (1 - 2*zeta^2) + sqrt( (1 - 2*zeta^2)^2 + 1 ) )
    bw_rad = wn * np.sqrt((1.0 - 2.0*zeta**2) + np.sqrt((1.0 - 2.0*zeta**2)**2 + 1.0))
    bw_hz = bw_rad / (2.0 * np.pi)

    # Print Results
    print("\n=========================================================================")
    print("                      System Identification Results                      ")
    print("=========================================================================")
    print(f" identified Damping Ratio (ζ)         : {zeta:.3f}")
    print(f" identified Natural Frequency (ωn)    : {wn:.3f} rad/s ({fn:.2f} Hz)")
    print(f" system Bandwidth (-3dB Frequency)    : {bw_rad:.3f} rad/s ({bw_hz:.2f} Hz)")
    print("-------------------------------------------------------------------------")
    print(" 📋 TRANSFER FUNCTION (轉移函數):")
    print(f"                 {wn**2:.2f}")
    print(f"     G(s) = -------------------------")
    print(f"             s^2 + {2.0*zeta*wn:.2f} s + {wn**2:.2f}")
    print("-------------------------------------------------------------------------")
    print(" 📋 DIFFERENTIAL EQUATION (系統微分方程):")
    print(f"     y''(t) + {2.0*zeta*wn:.2f} y'(t) + {wn**2:.2f} y(t) = {wn**2:.2f} u(t)")
    print("-------------------------------------------------------------------------")
    print(" 📋 THEORETICAL STEP RESPONSE (階躍響應特性):")
    print(f"     Overshoot (超調量)        : {overshoot:.1f} %")
    print(f"     Rise Time (上升時間)      : {rise_time:.3f} s")
    print(f"     Settling Time (2% 收斂時間): {settling_time:.3f} s")
    print("=========================================================================\n")

    # ================= Plotting =================
    # High-resolution frequency vector for plotting the theoretical model
    freq_grid = np.linspace(min(sweep_freqs)*0.8, max(sweep_freqs)*1.2, 500)
    w_grid = 2.0 * np.pi * freq_grid
    H_grid = (wn**2) / (-w_grid**2 + 2.0j * zeta * wn * w_grid + wn**2)
    
    gain_grid_db = 20.0 * np.log10(np.abs(H_grid))
    phase_grid_deg = np.degrees(np.angle(H_grid))
    # Correct wrapping for phase plot
    phase_grid_deg = (phase_grid_deg + 180.0) % 360.0 - 180.0
    phase_grid_deg[phase_grid_deg > 30.0] -= 360.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    
    # Subplot 1: Gain
    ax1.semilogx(sweep_freqs, 20.0*np.log10(sweep_gains), 'bo', label='Experimental Data', markersize=8)
    ax1.semilogx(freq_grid, gain_grid_db, 'r-', label=f'Fitted Model (ζ={zeta:.2f}, fn={fn:.1f}Hz)', linewidth=2)
    ax1.set_ylabel('Gain (dB)')
    ax1.grid(True, which="both", linestyle='--', alpha=0.6)
    ax1.legend()
    ax1.set_title('Bode Plot: Closed-Loop Motor Frequency Response')

    # Subplot 2: Phase
    ax2.semilogx(sweep_freqs, sweep_phases, 'bo', label='Experimental Data', markersize=8)
    ax2.semilogx(freq_grid, phase_grid_deg, 'r-', label=f'Fitted Model', linewidth=2)
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('Phase (Degrees)')
    ax2.grid(True, which="both", linestyle='--', alpha=0.6)
    
    plt.tight_layout()
    plot_filename = "sys_id_analysis.png"
    plt.savefig(plot_filename, dpi=300)
    print(f"Bode plot saved to: {os.path.abspath(plot_filename)}")
    
    # Plot Step Response
    t_step = np.linspace(0, max(settling_time*1.2, 1.0), 1000)
    if zeta < 1.0:
        # Underdamped
        wd = wn * np.sqrt(1.0 - zeta**2)
        step_response = 1.0 - (np.exp(-zeta * wn * t_step) / np.sqrt(1.0 - zeta**2)) * np.sin(wd * t_step + np.arccos(zeta))
    elif zeta == 1.0:
        # Critically damped
        step_response = 1.0 - (1.0 + wn * t_step) * np.exp(-wn * t_step)
    else:
        # Overdamped
        r1 = -zeta * wn + wn * np.sqrt(zeta**2 - 1.0)
        r2 = -zeta * wn - wn * np.sqrt(zeta**2 - 1.0)
        step_response = 1.0 + (r2 * np.exp(r1 * t_step) - r1 * np.exp(r2 * t_step)) / (r1 - r2)
        
    plt.figure(figsize=(8, 5))
    plt.plot(t_step, step_response, 'r-', linewidth=2, label='Fitted Step Response')
    plt.axhline(1.0, color='gray', linestyle=':', label='Steady State Value')
    plt.axhline(1.0 + (overshoot/100.0 if overshoot > 0 else 0.0), color='g', linestyle='--', label='Peak Value' if overshoot > 0 else '')
    plt.title(f'Theoretical Step Response (from identified G(s))\nζ={zeta:.3f}, ωn={wn:.2f}rad/s')
    plt.xlabel('Time (Seconds)')
    plt.ylabel('Normalized Output')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.tight_layout()
    
    step_filename = "sys_id_step_response.png"
    plt.savefig(step_filename, dpi=300)
    print(f"Step response plot saved to: {os.path.abspath(step_filename)}")
    print("Displaying plots...")
    plt.show()

if __name__ == '__main__':
    run_sweep()
