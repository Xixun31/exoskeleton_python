"""
即時顯示 mbed/enc_imu_sd_logger 的 encoder 與 IMU 數值，用來確認感測器是否正常。

使用方式：
    python3 live_plot_enc_imu.py              # 自動找 /dev/ttyACM*，顯示最近 10 秒
    python3 live_plot_enc_imu.py --window 20  # 顯示最近 20 秒

程式會送 'S' 讓板子以 50Hz 輸出即時資料，關閉視窗時再送一次 'S' 停止 (SD 紀錄不受影響)。
畫面：
    1. encoder1 / encoder2 角度 (相對零點)；紅色 x = 通訊錯誤
    2. IMU 姿態角 roll / pitch / yaw
    3. IMU 角速度 gx / gy / gz
    4. IMU 加速度 ax / ay / az 與 |a| (靜止時應接近 9.81)
    標題列：板子每秒的 STAT (通訊錯誤、磁場警告、IMU 漏讀、丟失週期)，這一秒有錯誤時變紅色
"""
import argparse
import glob
import threading
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.animation import FuncAnimation

COMM_ERR = 0x01 | 0x02 | 0x04 | 0x20  # 同位 / OCF / COF / 起始 bit；磁場警告 (0x08、0x10) 不算
CYCLE_S = 0.01  # 板子每個週期 10ms

# D,cycle,enc1_deg,enc1_err,enc2_deg,enc2_err,imu_new,roll,pitch,yaw,gx,gy,gz,ax,ay,az
FIELDS = ['cycle', 'enc1', 'enc1_err', 'enc2', 'enc2_err', 'imu_new',
          'roll', 'pitch', 'yaw', 'gx', 'gy', 'gz', 'ax', 'ay', 'az']


def parse_args():
    ports = glob.glob('/dev/ttyACM*')
    p = argparse.ArgumentParser()
    p.add_argument('--port', default=ports[0] if ports else '/dev/ttyACM0')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--window', type=float, default=10.0, help='顯示最近幾秒')
    return p.parse_args()


class Reader(threading.Thread):
    """背景執行緒：讀序列埠，把 D 行存進 buffer，記錄最新的 STAT 行"""

    def __init__(self, ser, maxlen):
        super().__init__(daemon=True)
        self.ser = ser
        self.buf = {k: deque(maxlen=maxlen) for k in FIELDS}
        self.stat = ''
        self.lock = threading.Lock()
        self.running = True

    def run(self):
        while self.running:
            line = self.ser.readline().decode(errors='replace').strip()
            if line.startswith('D,'):
                parts = line.split(',')[1:]
                if len(parts) != len(FIELDS):
                    continue
                try:
                    vals = [float(x) for x in parts]
                except ValueError:
                    continue
                with self.lock:
                    for k, v in zip(FIELDS, vals):
                        self.buf[k].append(v)
            elif line.startswith('STAT'):
                self.stat = line
            elif line:
                print(line)  # 其他訊息 (REC start、WARN、ZERO...) 印在終端機

    def snapshot(self):
        with self.lock:
            return {k: np.array(v) for k, v in self.buf.items()}


_last_dropped = [None]


def stat_has_error(stat):
    """這一秒的 STAT 有通訊錯誤、IMU 漏讀 / 錯誤，或 dropped (累計值) 有增加，就算有錯"""
    kv = dict(item.split('=', 1) for item in stat.split()[1:] if '=' in item)
    try:
        enc = [int(x) for x in kv.get('enc_err', '0/0').split('/')]
        dropped = int(kv.get('dropped', 0))
    except ValueError:
        return False
    new_drop = _last_dropped[0] is not None and dropped > _last_dropped[0]
    _last_dropped[0] = dropped
    return sum(enc) > 0 or int(kv.get('imu_miss', 0)) > 0 or int(kv.get('imu_bad', 0)) > 0 or new_drop


def main():
    args = parse_args()
    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    ser.reset_input_buffer()
    ser.write(b'S')  # 開啟 50Hz 即時輸出
    reader = Reader(ser, maxlen=int(args.window * 50) + 50)
    reader.start()

    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(11, 9))
    fig.canvas.manager.set_window_title('encoder + IMU live')
    specs = [
        ('Encoder angle (deg)', [('enc1', 'enc1'), ('enc2', 'enc2')]),
        ('IMU Euler (deg)', [('roll', 'roll'), ('pitch', 'pitch'), ('yaw', 'yaw')]),
        ('IMU gyro (deg/s)', [('gx', 'gx'), ('gy', 'gy'), ('gz', 'gz')]),
        ('IMU acc (m/s^2)', [('ax', 'ax'), ('ay', 'ay'), ('az', 'az'), ('|a|', None)]),
    ]
    lines = []
    for ax, (title, series) in zip(axes, specs):
        ax.set_ylabel(title, fontsize=9)
        ax.grid(alpha=0.3)
        row = []
        for label, _ in series:
            (ln,) = ax.plot([], [], lw=1.2, label=label, color='k' if label == '|a|' else None)
            row.append(ln)
        ax.legend(loc='upper left', fontsize=8, ncol=len(series))
        lines.append(row)
    err_marks = [axes[0].plot([], [], 'rx', ms=6, label='_comm err')[0] for _ in range(2)]
    axes[-1].set_xlabel('time (s, from board cycle counter)')
    value_text = axes[0].text(1.0, 1.02, '', transform=axes[0].transAxes, ha='right', fontsize=9,
                              family='monospace')
    status = fig.suptitle('waiting for data...', fontsize=9, family='monospace')

    def update(_):
        d = reader.snapshot()
        if len(d['cycle']) < 2:
            return
        t = d['cycle'] * CYCLE_S
        for ln, (label, key) in zip(lines[0], specs[0][1]):
            ln.set_data(t, d[key])
        for ln, (label, key) in zip(lines[1], specs[1][1]):
            ln.set_data(t, d[key])
        for ln, (label, key) in zip(lines[2], specs[2][1]):
            ln.set_data(t, d[key])
        amag = np.sqrt(d['ax'] ** 2 + d['ay'] ** 2 + d['az'] ** 2)
        for ln, (label, key) in zip(lines[3], specs[3][1]):
            ln.set_data(t, amag if key is None else d[key])
        for i, mark in enumerate(err_marks):
            bad = (d[f'enc{i + 1}_err'].astype(int) & COMM_ERR) != 0
            mark.set_data(t[bad], d[f'enc{i + 1}'][bad])

        axes[0].set_xlim(max(t[0], t[-1] - args.window), t[-1] + 0.05)
        for ax in axes:
            ax.relim()
            ax.autoscale_view(scalex=False)

        value_text.set_text(
            f"enc1 {d['enc1'][-1]:7.2f}  enc2 {d['enc2'][-1]:7.2f}  |  "
            f"rpy {d['roll'][-1]:7.2f} {d['pitch'][-1]:7.2f} {d['yaw'][-1]:7.2f}  |  |a| {amag[-1]:5.2f}")
        if reader.stat and reader.stat != status.get_text():
            status.set_text(reader.stat)
            status.set_color('red' if stat_has_error(reader.stat) else 'black')

    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)  # noqa: F841 (要留著參考)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    try:
        plt.show()
    finally:
        reader.running = False
        ser.write(b'S')  # 關閉即時輸出
        time.sleep(0.1)
        ser.close()


if __name__ == '__main__':
    main()
