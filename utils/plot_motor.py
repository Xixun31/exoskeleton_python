import serial
import time
import collections
import glob
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# --- Config Serial Port ---
ports = glob.glob('/dev/ttyACM*')
COM_PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD_RATE = 115200

# --- Plot parameters ---
MAX_POINTS = 200  # Number of points shown on screen (200 * 50ms = 10s window)
target_data = collections.deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
actual_data = collections.deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
voltage_data = collections.deque([0.0] * MAX_POINTS, maxlen=MAX_POINTS)
x_data = list(range(MAX_POINTS))

def main():
    try:
        # Open Serial Port
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=0.1)
        print(f"✅ Successfully connected to STM32 ({COM_PORT})")
        print("📊 Launching real-time plot... Close the window to exit.\n")
        
        # Initialize Matplotlib Figure with 2 subplots (Angle and Voltage)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        fig.suptitle('Motor Position Control Real-time Response', fontsize=14, fontweight='bold')
        
        # Subplot 1: Angles
        ax1.set_ylabel('Angle (Degrees)', fontsize=12)
        ax1.set_ylim(-110, 110)
        ax1.grid(True, linestyle='--', alpha=0.6)
        line_target, = ax1.plot(x_data, target_data, 'r--', label='Target Angle', linewidth=2)
        line_actual, = ax1.plot(x_data, actual_data, 'b-', label='Actual Angle', linewidth=2)
        ax1.legend(loc='upper right')
        
        # Subplot 2: Control Voltage
        ax2.set_xlabel('Time (samples @ 20Hz)', fontsize=12)
        ax2.set_ylabel('Control Voltage (V)', fontsize=12)
        ax2.set_ylim(-13, 13)
        ax2.grid(True, linestyle='--', alpha=0.6)
        line_voltage, = ax2.plot(x_data, voltage_data, 'g-', label='Control Voltage', linewidth=1.5)
        ax2.legend(loc='upper right')

        # Real-time parsing callback
        def update_plot(frame):
            while ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        parts = line.split(',')
                        if len(parts) == 3:
                            volt = float(parts[0].strip())
                            target_deg = float(parts[1].strip())
                            actual_deg = float(parts[2].strip())
                            
                            target_data.append(target_deg)
                            actual_data.append(actual_deg)
                            voltage_data.append(volt)
                            
                            print(f"Target: {target_deg:6.1f}° | Actual: {actual_deg:6.1f}° | Error: {(target_deg-actual_deg):6.2f}° | Volt: {volt:6.2f}V")
                except Exception:
                    pass
            
            line_target.set_ydata(target_data)
            line_actual.set_ydata(actual_data)
            line_voltage.set_ydata(voltage_data)
            return line_target, line_actual, line_voltage

        ani = animation.FuncAnimation(
            fig, update_plot, interval=50, blit=True, cache_frame_data=False
        )
        
        plt.tight_layout()
        plt.show()
        
    except serial.SerialException as e:
        print(f"❌ Failed to open Serial Port: {COM_PORT}. Check USB connection.")
    except KeyboardInterrupt:
        print("\nExiting plotting program.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()
            print("Serial port closed.")

if __name__ == '__main__':
    main()
