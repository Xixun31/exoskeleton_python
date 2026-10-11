"""
逐顆檢查 SPI IMU (Xsens MTi) 是否正常

搭配韌體：mbed/imu_spi_test
流程：接上一顆 IMU → 按 Enter 測試 → 換下一顆 → ... → 輸入 q 結束並列出總表

使用方式：
    python3 imu_spi_check.py            # 預設測 6 顆
    python3 imu_spi_check.py --count 3

換 IMU 時建議先拔掉 USB (板子與 IMU 一起斷電) 再換，接回後程式會自動重新連線。
"""
import argparse
import csv
import glob
import os
import time
from datetime import datetime

import serial

BAUD = 115200
RESULT_CSV = 'imu_spi_check_results.csv'
TEST_TIMEOUT = 20.0  # 秒


def find_port():
    ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
    return ports[0] if ports else None


def open_port(wait=15.0):
    """開啟序列埠；拔插 USB 後埠會暫時消失，等它回來"""
    start = time.time()
    while time.time() - start < wait:
        port = find_port()
        if port:
            try:
                return serial.Serial(port, BAUD, timeout=0.2)
            except serial.SerialException:
                pass
        time.sleep(0.5)
    return None


def parse_result(line):
    fields = {}
    for item in line.strip().split(',')[1:]:
        if '=' in item:
            k, v = item.split('=', 1)
            fields[k] = v
    return fields


def run_one(label):
    ser = open_port()
    if ser is None:
        print('❌ 找不到板子的序列埠，請確認 USB 已接上')
        return None
    with ser:
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(b't')  # 觸發一次測試 (板子剛開機時自己也會測一次，這裡只取送出後完整的一份)
        lines = []
        started = False
        skip_boot = False  # 板子剛開機時會自己測一次，IMU 可能還沒準備好，跳過那一次
        start = time.time()
        while time.time() - start < TEST_TIMEOUT:
            line = ser.readline().decode('utf-8', errors='replace').strip()
            if not line:
                continue
            if 'MTi SPI 單顆測試韌體' in line:
                skip_boot = True
                print('   (板子剛開機，略過開機時的自動測試)')
                continue
            if 'IMU SPI TEST START' in line:
                started, lines = True, []
            if not started:
                continue
            print('   ' + line)
            lines.append(line)
            if 'IMU SPI TEST END' in line:
                if skip_boot:
                    skip_boot, started = False, False
                    continue
                break
        else:
            print('❌ 等不到測試結果，請確認板子燒的是 imu_spi_test 韌體 (或按一下板子的 RESET)')
            return None

    result_line = next((l for l in lines if l.startswith('RESULT,')), None)
    if result_line is None:
        print('❌ 測試輸出不完整')
        return None
    r = parse_result(result_line)
    r['label'] = label
    r['diagnosis'] = diagnose(r)
    r['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return r


def diagnose(r):
    """由握手訊號 (fill word) 判斷可能原因"""
    if r.get('pass') == '1':
        return '正常'
    fw = r.get('fw', '')
    if r.get('prot') == '1':
        return 'SPI 正常但資料有問題，看各項目'
    if fw == '00000000':
        return 'MISO 無訊號：IMU 沒電或 MISO 斷線'
    if fw == 'FFFFFFFF':
        return 'IMU 沒回應：非 SPI 模式 (PSEL) 或 CS 沒接'
    if fw.endswith('000102'):
        return 'MISO 讀到 MOSI：兩線短路或接反'
    if fw.startswith(('F', '7')):
        return '接近正確但有位元錯：接觸不良 (CS/SCLK/GND)'
    return '握手訊號錯誤：檢查接線'


def save(results):
    keys = ['label', 'time', 'pass', 'diagnosis', 'fw', 'did', 'prot', 'rate', 'pkts', 'cksum_err', 'acc', 'acc_std',
            'gx', 'gy', 'gz', 'gstd', 'roll', 'pitch', 'tilt_err']
    with open(RESULT_CSV, 'w', newline='') as fp:
        w = csv.DictWriter(fp, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)
    print(f'\n結果已存到 {os.path.abspath(RESULT_CSV)}')


def print_summary(results):
    print('\n' + '=' * 96)
    print(f"{'IMU':<8} {'結果':<6} {'DeviceID':<10} {'速率Hz':>7} {'cksum錯':>7} {'|a|':>7} "
          f"{'陀螺儀平均 (deg/s)':>22} {'gyro std':>9} {'傾角差':>7}")
    print('-' * 96)
    for r in results:
        ok = '✅ 正常' if r.get('pass') == '1' else '❌ 異常'
        gyro = f"{float(r['gx']):+.2f} {float(r['gy']):+.2f} {float(r['gz']):+.2f}"
        print(f"{r['label']:<8} {ok:<6} {r['did']:<10} {float(r['rate']):7.1f} {r['cksum_err']:>7} "
              f"{float(r['acc']):7.3f} {gyro:>22} {float(r['gstd']):9.3f} {float(r['tilt_err']):7.2f}")
        if r.get('pass') != '1':
            print(f"{'':<8} ↳ fill word {r.get('fw', '?')}：{r['diagnosis']}")
    print('=' * 96)
    dids = [r['did'] for r in results if r['did'] != '00000000']
    dup = {d for d in dids if dids.count(d) > 1}
    if dup:
        print(f"⚠️  DeviceID 重複：{', '.join(sorted(dup))} — 可能同一顆測了兩次")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=6, help='要測幾顆 IMU (預設 6)')
    args = parser.parse_args()

    print('逐顆 IMU SPI 測試：測試時請讓 IMU 靜止不動')
    results = []
    n = 1
    while True:
        default = f'IMU{n}'
        prompt = (f'\n接上第 {n} 顆 IMU 後輸入名稱並按 Enter (直接 Enter = {default}，'
                  f'r = 重測上一顆，q = 結束)：')
        ans = input(prompt).strip()
        if ans.lower() == 'q':
            break
        if ans.lower() == 'r':
            if not results:
                continue
            label = results.pop()['label']
            n -= 1
        else:
            label = ans or default
        r = run_one(label)
        if r is None:
            continue
        results.append(r)
        print(f"→ {label}: {'✅ 正常' if r['pass'] == '1' else '❌ 異常'} (DeviceID {r['did']})"
              + ('' if r['pass'] == '1' else f"  可能原因：{r['diagnosis']}"))
        save(results)
        n += 1
        if len(results) >= args.count:
            more = input(f'\n已測完 {args.count} 顆，還要繼續測嗎？(y/N) ').strip().lower()
            if more != 'y':
                break

    if results:
        print_summary(results)
        save(results)


if __name__ == '__main__':
    main()
