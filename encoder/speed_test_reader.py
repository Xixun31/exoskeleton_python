"""
讀取 mbed/encoder_speed_test 的測試結果，存成 CSV 並畫圖。

使用方式：
    python3 speed_test_reader.py            # 自動用 openocd 重置板子
    python3 speed_test_reader.py --no-reset # 自己按板子上的黑色 RESET 鍵

測試時請保持編碼器靜止不動。
"""
import argparse
import csv
import glob
import shutil
import subprocess
import time

import matplotlib.pyplot as plt
import serial

# --- 設定 Serial Port ---
ports = glob.glob('/dev/ttyACM*')
COM_PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD_RATE = 115200
TIMEOUT_S = 60  # 等待測試完成的最長時間

CSV_FILE = 'speed_test_result.csv'
PNG_FILE = 'speed_test_result.png'

# CS 等待時間是有順序的數值，用同一色系由淺到深表示 (淺 = 等待久)
CS_COLORS = {10: '#86b6ef', 5: '#5598e7', 2: '#2a78d6', 1: '#1c5cab', 0: '#0d366b'}


def reset_board():
    """用 openocd 重置板子，讓測試從頭跑一次。失敗就請使用者手動按 RESET。"""
    if shutil.which('openocd'):
        cmd = ['openocd', '-f', 'interface/stlink.cfg', '-f', 'target/stm32f4x.cfg',
               '-c', 'init; reset run; exit']
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            print('已用 openocd 重置板子')
            return
    print('請按一下板子上的黑色 RESET 鍵...')


def parse_row(line):
    """解析表格中的一列，例如：
    1000000     10   27.50   28.10     36364        0        0  OK
    """
    parts = line.split()
    if len(parts) != 8 or parts[7] not in ('OK', 'FAIL'):
        return None
    try:
        return {
            'spi_hz': int(parts[0]),
            'cs_us': int(parts[1]),
            'avg_us': float(parts[2]),
            'max_us': float(parts[3]),
            'rate_hz': float(parts[4]),
            'bad_hdr': int(parts[5]),
            'bad_val': int(parts[6]),
            'status': parts[7],
        }
    except ValueError:
        return None


def read_results(ser):
    rows = []
    start = time.time()
    finished = False
    while time.time() - start < TIMEOUT_S:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        print(line)  # 原樣顯示板子輸出

        row = parse_row(line)
        if row:
            rows.append(row)
        # 結論區的最後一行
        if line.startswith('註：') or line.startswith('沒有任何設定'):
            finished = True
            break
        if line.startswith('錯誤：'):
            break

    if not finished:
        print('\n[警告] 沒有收到完整結果 (逾時或板子回報錯誤)')
    return rows


def save_csv(rows):
    with open(CSV_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f'結果已存到 {CSV_FILE}')


def plot(rows):
    fig, ax = plt.subplots(figsize=(9, 5.5))

    for cs in sorted({r['cs_us'] for r in rows}, reverse=True):
        data = sorted((r for r in rows if r['cs_us'] == cs), key=lambda r: r['spi_hz'])
        x = [r['spi_hz'] / 1e6 for r in data]
        y = [r['rate_hz'] for r in data]
        color = CS_COLORS.get(cs, '#2a78d6')
        ax.plot(x, y, '-', color=color, linewidth=2, label=f'CS 等待 {cs} us')

        ok = [(xi, yi) for xi, yi, r in zip(x, y, data) if r['status'] == 'OK']
        bad = [(xi, yi) for xi, yi, r in zip(x, y, data) if r['status'] == 'FAIL']
        if ok:
            ax.plot(*zip(*ok), 'o', color=color, markersize=8,
                    markeredgecolor='white', markeredgewidth=2)
        if bad:
            ax.plot(*zip(*bad), 'x', color=color, markersize=10, markeredgewidth=2.5)

        # 線尾直接標註，不用一直對照圖例
        ax.annotate(f'{cs} us', (x[-1], y[-1]), xytext=(8, 0),
                    textcoords='offset points', va='center', fontsize=9, color='#444')

    # 標出最佳設定 (0 錯誤且最快)
    good = [r for r in rows if r['status'] == 'OK']
    if good:
        best = max(good, key=lambda r: r['rate_hz'])
        ax.annotate(f"最高 {best['rate_hz']:.0f} Hz\n"
                    f"({best['spi_hz'] / 1e6:g} MHz, CS {best['cs_us']} us)",
                    (best['spi_hz'] / 1e6, best['rate_hz']),
                    xytext=(0.97, 0.06), textcoords='axes fraction', ha='right',
                    fontsize=11, color='#222',
                    arrowprops=dict(arrowstyle='->', color='#888'))

    # 圖例裡補上 OK / FAIL 標記說明
    ax.plot([], [], 'o', color='#666', label='OK (資料正確)')
    ax.plot([], [], 'x', color='#666', markeredgewidth=2.5, label='FAIL (資料錯誤)')

    ax.set_xscale('log')
    xticks = sorted({r['spi_hz'] / 1e6 for r in rows})
    ax.set_xticks(xticks)
    ax.minorticks_off()
    ax.set_xticklabels([f'{v:g}' for v in xticks])
    ax.set_ylim(bottom=0)
    ax.set_title('Encoder SPI 最高讀取頻率', fontsize=14)
    ax.set_xlabel('SPI clock (MHz)', fontsize=12)
    ax.set_ylabel('讀取頻率 (Hz)', fontsize=12)
    ax.grid(True, linestyle='--', alpha=0.4)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)
    ax.legend(loc='upper left', frameon=False, fontsize=9)

    plt.tight_layout()
    fig.savefig(PNG_FILE, dpi=150)
    print(f'圖表已存到 {PNG_FILE}')
    plt.show()


def setup_chinese_font():
    """讓 matplotlib 能顯示中文 (Linux 常見的中文字型)"""
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'Noto Sans CJK JP',
                                       'WenQuanYi Zen Hei', 'AR PL UMing TW', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-reset', action='store_true', help='不用 openocd 重置，自己按 RESET')
    parser.add_argument('--port', default=COM_PORT)
    args = parser.parse_args()

    try:
        ser = serial.Serial(args.port, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f'[錯誤] 無法開啟 Serial Port: {args.port}\n詳細錯誤: {e}')
        return

    with ser:
        print(f'成功連接到 {args.port}，Baud Rate: {BAUD_RATE}')
        ser.reset_input_buffer()
        if args.no_reset:
            print('請按一下板子上的黑色 RESET 鍵...')
        else:
            reset_board()
        print('等待測試結果 (請保持編碼器靜止)...\n')
        rows = read_results(ser)

    if not rows:
        print('沒有收到任何測試資料。')
        return

    save_csv(rows)
    setup_chinese_font()
    plot(rows)


if __name__ == '__main__':
    main()
