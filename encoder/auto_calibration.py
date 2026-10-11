import serial
import time
import glob
import os
import sys
import math
import csv
import matplotlib.pyplot as plt

# ================= Configuration =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200

SETTLE_TIME = 2.5   # Time in seconds to wait for motor to settle at each step
SAMPLE_TIME = 2.0   # Time in seconds to gather static data at each step
ENCODER_RESOLUTION = 4096.0  # 12-bit absolute encoder
# =================================================

def circular_mean(angles_deg):
    """Calculate circular mean of angles to prevent wrapping errors at 0/360 boundary."""
    if not angles_deg:
        return 0.0
    x = 0.0
    y = 0.0
    for a in angles_deg:
        rad = math.radians(a)
        x += math.cos(rad)
        y += math.sin(rad)
    mean_rad = math.atan2(y, x)
    mean_deg = math.degrees(mean_rad) % 360.0
    return mean_deg

def circular_mean_raw(raw_vals, resolution=ENCODER_RESOLUTION):
    """Calculate circular mean of raw encoder values to prevent wrapping errors."""
    if not raw_vals:
        return 0.0
    x = 0.0
    y = 0.0
    for r in raw_vals:
        angle_rad = (r / resolution) * 2.0 * math.pi
        x += math.cos(angle_rad)
        y += math.sin(angle_rad)
    mean_rad = math.atan2(y, x)
    mean_val = ((mean_rad / (2.0 * math.pi)) * resolution) % resolution
    return mean_val

def angular_difference(a, b):
    """Calculate shortest angular difference (a - b) in range [-180, 180)."""
    return (a - b + 180) % 360 - 180

def run_calibration():
    print(f"Connecting to Nucleo Board on {PORT} @ {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Failed to open serial port: {e}")
        print("Available ports:")
        for p in ports:
            print(f" - {p}")
        sys.exit(1)

    print("\n=============================================================")
    print("        Automated Encoder Static Calibration Experiment      ")
    print("=============================================================")
    print("This script will automatically command the motor to sweep ")
    print("from 0 to 360 degrees in 15-degree steps. It will use the ")
    print("motor's position (via incremental encoder) as the standard ")
    print("reference to measure and calibrate the absolute SPI encoder.")
    print("=============================================================\n")

    # Clear buffers
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    # Sweep from 0 to 360 in steps of 15
    target_angles = list(range(0, 361, 15))
    results = []

    # Reset motor to 0 first
    print("Resetting motor to 0 degrees...")
    ser.write(b"0\n")
    time.sleep(3.0)

    try:
        for target in target_angles:
            print(f"👉 Commanding motor to target: {target}°")
            ser.write(f"{target}\n".encode())
            
            # 1. Wait for motor to settle
            print(f"   Waiting {SETTLE_TIME}s for motor to settle...")
            time.sleep(SETTLE_TIME)
            
            # 2. Gather data
            print(f"   Sampling data for {SAMPLE_TIME}s...")
            ser.reset_input_buffer() # Clear old data
            start_time = time.time()
            
            abs_raw_samples = []
            abs_deg_samples = []
            motor_deg_samples = []
            
            while time.time() - start_time < SAMPLE_TIME:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line or line.startswith(">>"):
                    continue
                
                parts = line.split(',')
                if len(parts) == 5:
                    try:
                        abs_raw = int(parts[0].strip())
                        abs_deg = float(parts[1].strip())
                        motor_deg = float(parts[4].strip())
                        
                        abs_raw_samples.append(abs_raw)
                        abs_deg_samples.append(abs_deg)
                        motor_deg_samples.append(motor_deg)
                    except ValueError:
                        continue
            
            if not abs_deg_samples:
                print("   ⚠️ No data gathered! Please check SPI wiring or serial output format.")
                continue
                
            # Compute statistical means
            mean_abs_deg = circular_mean(abs_deg_samples)
            mean_abs_raw = circular_mean_raw(abs_raw_samples)
            mean_motor_deg = circular_mean(motor_deg_samples)
            
            # Calculate local error relative to motor reference standard
            err = angular_difference(mean_abs_deg, mean_motor_deg)
            
            print(f"   ✅ Sampled {len(abs_deg_samples)} points")
            print(f"   Motor Std Ref: {mean_motor_deg:6.2f}° | Abs Enc Measured: {mean_abs_deg:6.2f}° (Raw: {mean_abs_raw:6.1f})")
            print(f"   Static Error: {err:+.3f}°\n")
            
            results.append({
                'target': target,
                'ref_motor_deg': mean_motor_deg,
                'abs_raw_mean': mean_abs_raw,
                'abs_deg_mean': mean_abs_deg,
                'error': err
            })

    except KeyboardInterrupt:
        print("\nExperiment interrupted by user.")
    
    if not results:
        print("No data gathered. Exiting.")
        ser.close()
        return

    # Post-processing: Calculate Offset Calibration
    # We choose the first measurement (near 0) as the offset base
    zero_point = min(results, key=lambda x: abs(x['target']))
    offset = zero_point['error']
    print(f"Calibration Bias Offset (measured at target {zero_point['target']}°): {offset:+.3f}°")

    # Print Report
    print("\n=========================================================================")
    print("                       Calibration Analysis Report                       ")
    print("=========================================================================")
    print(" Target | Motor Ref | Abs Raw | Abs Measured | Raw Error | Offset Corrected Error")
    print("-------------------------------------------------------------------------")
    
    csv_filename = "auto_calibration_report.csv"
    with open(csv_filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Target_Angle', 'Motor_Ref_Angle', 'Abs_Encoder_Raw', 'Abs_Encoder_Angle', 'Raw_Error', 'Corrected_Error'])
        
        plot_ref = []
        plot_err_raw = []
        plot_err_corr = []
        
        for r in results:
            target = r['target']
            ref = r['ref_motor_deg']
            raw = r['abs_raw_mean']
            measured = r['abs_deg_mean']
            raw_err = r['error']
            
            # Corrected error
            corrected_deg = (measured - offset) % 360.0
            corrected_err = angular_difference(corrected_deg, ref)
            
            print(f"  {target:3}°  |  {ref:7.2f}°  | {raw:7.1f} |  {measured:10.2f}°  |  {raw_err:+7.2f}° |  {corrected_err:+18.2f}°")
            writer.writerow([target, f"{ref:.2f}", f"{raw:.2f}", f"{measured:.2f}", f"{raw_err:.2f}", f"{corrected_err:.2f}"])
            
            plot_ref.append(ref)
            plot_err_raw.append(raw_err)
            plot_err_corr.append(corrected_err)
            
    print("-------------------------------------------------------------------------")
    print(f"Report successfully saved to: {os.path.abspath(csv_filename)}")
    print("=========================================================================\n")

    # Close serial
    ser.close()

    # Plot results
    plt.figure(figsize=(10, 6))
    plt.plot(plot_ref, plot_err_raw, 'bo--', label='Raw Error (Uncalibrated)', linewidth=1.5)
    plt.plot(plot_ref, plot_err_corr, 'rs-', label='Corrected Error (Offset Calibrated)', linewidth=1.5)
    plt.axhline(0, color='gray', linestyle=':', label='Ideal Zero Error')
    plt.title('Static Calibration: Absolute SPI Encoder Error relative to Motor Reference')
    plt.xlabel('Motor Reference Angle (Degrees)')
    plt.ylabel('Encoder Static Measurement Error (Degrees)')
    plt.grid(True, linestyle='--', alpha=0.6)
    plt.legend()
    plt.tight_layout()
    
    chart_filename = "auto_calibration_plot.png"
    plt.savefig(chart_filename, dpi=300)
    print(f"Chart saved to: {os.path.abspath(chart_filename)}")
    print("Displaying chart...")
    plt.show()

if __name__ == '__main__':
    run_calibration()
