"""
多顆 SPI IMU + SPI encoder 同步讀取檢查 (搭配韌體 mbed/multi_imu_sync)

IMU 以 100Hz 輸出，MCU 以 --rate 的頻率 (預設 500Hz) 輪詢 IMU 並讀取 encoder。

檢查項目：
  1. 傳輸完整性：週期編號是否連續、板子是否因序列埠太慢丟資料
  2. 讀取週期：週期抖動
  3. 讀取時間：同一週期內 encoder 與各 IMU 被讀取的時間差
  4. 漏讀：每顆 IMU 的 PacketCounter 是否連續 (每個封包剛好讀到一次)
  5. 調包：DeviceID 是否各不相同、PacketCounter / SampleTimeFine 是否有跳到別顆的跡象
     (--identify 會請你逐顆晃動 IMU，直接確認 CS 與實體 IMU 的對應)
  6. 同步性：錄製前後各做一次時間校準，把 SampleTimeFine 換算成 MCU 時間，
     算出每個封包從取樣到被讀到的延遲，以及同一時刻各 IMU 取樣時間的差
  7. Encoder 讀取錯誤

使用方式：
    python3 multi_imu_sync_check.py                    # 500Hz 讀取，錄 30 秒
    python3 multi_imu_sync_check.py --rate 100         # 100 / 200 / 400 / 500 / 1000
    python3 multi_imu_sync_check.py --identify         # 加做逐顆晃動的對應檢查
    python3 multi_imu_sync_check.py --bus-check        # 只檢查 SPI 匯流排 (接線除錯用)
    python3 multi_imu_sync_check.py --from-csv multi_imu_sync_raw.csv   # 重新分析
"""
import argparse
import csv
import glob
import os
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import serial

BAUD = 921600
RATE_CMD = {100: b'A', 200: b'B', 400: b'C', 500: b'D', 1000: b'E'}
SPI_CMD = {200: b'1', 500: b'2', 1000: b'3'}  # IMU SPI 時脈 (kHz)
STF_PER_PACKET = 100  # SampleTimeFine 單位 0.1ms，IMU 100Hz 輸出 → 每封包 +100
IMU_FIELDS = ('off', 'new', 'bad', 'pc', 'stf', 'pitch', 'gy')
RAW_CSV = 'multi_imu_sync_raw.csv'
CAL_CSV = 'multi_imu_sync_cal.csv'
PLOT_PNG = 'multi_imu_sync.png'
COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4']
ENC_COLOR = '#666666'


# ---------------- 序列埠 ----------------
def open_port(port):
    port = port or (glob.glob('/dev/ttyACM*') + [None])[0]
    if port is None:
        sys.exit('❌ 找不到板子的序列埠')
    try:
        return serial.Serial(port, BAUD, timeout=0.2)
    except serial.SerialException as e:
        sys.exit(f'❌ 無法開啟 {port}: {e}\n   (被占用時用 fuser -v {port} 查看)')


def read_init(ser, spi_khz=1000):
    ser.write(b'x')
    time.sleep(0.2)
    ser.write(SPI_CMD[spi_khz])  # 明確設定 SPI 時脈，避免沿用之前留下的設定
    time.sleep(0.1)
    ser.reset_input_buffer()
    ser.write(b'r')
    imus = []
    start = time.time()
    while time.time() - start < 15:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if line.startswith('INIT,'):
            p = line.split(',')
            info = dict(kv.split('=') for kv in p[3:])
            info.update(idx=int(p[1]), cs=p[2])
            imus.append(info)
        elif line.startswith('INIT_DONE'):
            return imus
    sys.exit('❌ 等不到 INIT 結果，請確認板子燒的是 multi_imu_sync 韌體')


def set_rate(ser, hz):
    ser.reset_input_buffer()
    ser.write(RATE_CMD[hz])
    start = time.time()
    while time.time() - start < 2:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if line.startswith('RATE,'):
            return int(line.split(',')[1])
    sys.exit('❌ 板子沒有回應頻率設定，請重新燒錄最新的 multi_imu_sync 韌體')


def parse_line(line):
    """D,cycle,t_us,enc_off,enc_deg,enc_err,K,[idx,off,new,bad,pc,stf,pitch,gy]*K,busy,dropped"""
    if not line.startswith('D,'):
        return None
    p = line.split(',')[1:]
    try:
        k = int(p[5])
        if len(p) != 8 + 8 * k:
            return None
        row = {'cycle': float(p[0]), 't_us': float(p[1]), 'enc_off': float(p[2]),
               'enc_deg': float(p[3]), 'enc_err': float(p[4]), 'busy': float(p[-2]),
               'dropped': float(p[-1])}
        for j in range(k):
            q = p[6 + 8 * j: 14 + 8 * j]
            i = int(q[0])
            for name, v in zip(IMU_FIELDS, q[1:]):
                row[f'{name}{i}'] = float(v)
        return row
    except (ValueError, IndexError):
        return None


def to_columns(rows):
    keys = list(rows[0].keys())
    rows = [r for r in rows if r.keys() == rows[0].keys()]
    return {k: np.array([r[k] for r in rows]) for k in keys}


def record(ser, seconds):
    ser.reset_input_buffer()
    ser.write(b'g')
    rows, bad_lines = [], 0
    start = time.time()
    while time.time() - start < seconds:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        r = parse_line(line)
        if r is None:
            bad_lines += 1
        else:
            rows.append(r)
    ser.write(b'x')
    time.sleep(0.1)
    return (to_columns(rows) if rows else None), bad_lines


def calibrate(ser):
    """時間校準：回傳 [(imu, t_us, pc, stf, n_new), ...]"""
    ser.reset_input_buffer()
    ser.write(b'p')
    rows = []
    start = time.time()
    while time.time() - start < 10:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if line.startswith('P,'):
            try:
                rows.append([float(x) for x in line.split(',')[1:]])
            except ValueError:
                pass
        elif line == 'PCAL_END':
            break
    return rows


def bus_check(ser):
    """所有 CS 都不選時 MISO 應該沒有回應；逐顆選取時握手應為 FA FF FF FF"""
    ser.write(b'x')
    time.sleep(0.1)
    ser.reset_input_buffer()
    ser.write(b'b')
    lines = []
    start = time.time()
    while time.time() - start < 5:
        line = ser.readline().decode('utf-8', errors='replace').strip()
        if line.startswith('BUS,'):
            lines.append(line.split(','))
        elif line == 'BUS_DONE':
            break
    print('\n=== SPI 匯流排檢查 ===')
    idle = [p for p in lines if p[1] == 'none']
    claimed = any(p[2] == 'FAFFFFFF' for p in idle)
    echo = any(p[2].startswith(('0100', '0000')) and p[2] != '00000000' for p in idle)
    print('全部不選取：' + ', '.join(p[2] for p in idle))
    if claimed:
        print('   ❌ 沒選取也有 IMU 回應 → 某顆 IMU 的 CS 浮接 / 接錯 / 兩條 CS 短路')
    elif echo:
        print('   ❌ MISO 讀到 MOSI 送出的資料 → MISO 與 MOSI 有短路 (檢查麵包板與各 IMU 線材)')
    else:
        print('   ✅ 沒有 IMU 佔用 MISO')
    for i in sorted({p[1] for p in lines if p[1] != 'none'}):
        fws = [p[2] for p in lines if p[1] == i]
        good = sum(f == 'FAFFFFFF' for f in fws)
        print(f"單選 IMU{i}：握手 {', '.join(fws)} → "
              + ('✅' if good == len(fws) else '❌ 有錯誤 (此路 CS / 線材 / IMU 有問題)' if good
                 else '❌ 沒有正確回應 (沒接 IMU 時這是正常的)'))


def identify(ser, active):
    """逐顆晃動 IMU，看哪個通道的 gyro 變化最大"""
    print('\n=== 調包檢查：逐顆晃動 IMU ===')
    for i in active:
        input(f'接在 IMU{i} 的那顆準備好後按 Enter，然後只晃動「這一顆」約 3 秒...')
        data, _ = record(ser, 3.0)
        if data is None:
            print('   沒有收到資料')
            continue
        var = {j: np.std(data[f'gy{j}']) for j in active}
        best = max(var, key=var.get)
        mark = '✅' if best == i else '❌ 調包!'
        print('   gyro 變化量: ' + ', '.join(f'IMU{j}={v:.1f}' for j, v in var.items())
              + f'  → 變化最大的是 IMU{best} {mark}')


# ---------------- 分析 ----------------
def stf_mapping(cal, i):
    """由校準資料求 t_mcu = a + b * stf (取到達時間的下包絡，扣掉輪詢造成的延遲)"""
    c = np.array([r for r in cal if int(r[0]) == i and r[4] == 1])
    if len(c) < 20:
        return None
    t, stf = c[:, 1], c[:, 3]
    b, a = np.polyfit(stf, t, 1)
    resid = t - (a + b * stf)
    a += np.percentile(resid, 2)
    return a, b, (b / 100.0 - 1) * 1e6  # 理想 b = 100 us / tick


def analyze(d, imus=None, cal=None):
    report = {}
    ok_all = True
    active = sorted(int(k[3:]) for k in d if k.startswith('new') and np.any(d[k] > 0))
    period = float(np.median(np.diff(d['t_us'])))
    rate = 1e6 / period

    print('\n' + '=' * 80)
    print(f' 多 IMU 同步讀取檢查  (讀取頻率 {rate:.0f} Hz，IMU 輸出 100 Hz)')
    print('=' * 80)

    # 1. 傳輸完整性
    cyc = d['cycle']
    gaps = np.diff(cyc) - 1
    missing = int(gaps[gaps > 0].sum())
    dropped = int(d['dropped'][-1] - d['dropped'][0])
    dur = (d['t_us'][-1] - d['t_us'][0]) / 1e6
    ok = missing == 0 and dropped == 0
    ok_all &= ok
    print(f"[1] 傳輸完整性  {len(cyc)} 個週期 / {dur:.1f} s，缺少週期 {missing}，板子丟棄 {dropped} "
          f"-> {'PASS' if ok else 'FAIL'}")
    if dropped:
        print('    (板子丟棄 = 序列埠來不及送出，降低 --rate 或減少 IMU 數量)')

    # 2. 讀取週期
    dt = np.diff(d['t_us'])[np.diff(cyc) == 1]
    late = int(np.sum(np.abs(dt - period) > 0.1 * period))
    ok = late == 0
    ok_all &= ok
    print(f"[2] 讀取週期    平均 {dt.mean():.1f} us，標準差 {dt.std():.1f} us，"
          f"範圍 {dt.min():.0f}~{dt.max():.0f} us，偏差 >10% 共 {late} 次 -> {'PASS' if ok else 'FAIL'}")
    report['dt'] = dt
    if 'busy' in d:
        busy = d['busy']
        over = int(np.sum(busy > period))
        ok = over == 0
        ok_all &= ok
        print(f"    每週期處理時間 平均 {busy.mean():.0f} us，最大 {busy.max():.0f} us "
              f"(週期 {period:.0f} us，使用率最高 {busy.max() / period * 100:.0f}%)，超時 {over} 次 "
              f"-> {'PASS' if ok else 'FAIL'}")
        report['busy'] = busy

    if imus:
        for m in imus:
            if m['ok'] != '1' and m['fw'] != '00000000':
                ok_all = False
                print(f"    ❌ IMU{m['idx']} (CS {m['cs']}) 有回應但初始化失敗：fill word {m['fw']}")
    if not active:
        ok_all = False
        print('    ❌ 沒有任何 IMU 傳回資料')

    # 3. 讀取時間
    print('[3] 讀取時間    (各裝置開始讀取的時間，相對週期開始)')
    offs = {'encoder': d['enc_off']}
    print(f"      encoder : 平均 {d['enc_off'].mean():6.0f} us")
    for i in active:
        o = d[f'off{i}']
        offs[f'IMU{i}'] = o
        print(f"      IMU{i}    : 平均 {o.mean():6.0f} us，最大 {o.max():6.0f} us")
    if active:
        span = offs[f'IMU{active[-1]}'] - offs['encoder']
        print(f"      → 從讀 encoder 到開始讀最後一顆 IMU：平均 {span.mean():.0f} us，最大 {span.max():.0f} us")
    report['offs'] = offs

    # 4/5. 漏讀與調包
    print('[4] 漏讀 / [5] 調包 (每顆 IMU)')
    for i in active:
        new, pc, stf, bad = d[f'new{i}'], d[f'pc{i}'], d[f'stf{i}'], d[f'bad{i}']
        sel = np.where(new > 0)[0]
        dpc = np.diff(pc[sel]) % 65536
        lost = dpc - new[sel][1:]
        n_lost = int(lost[(lost > 0) & (lost < 1000)].sum())
        jumps = int(np.sum((lost < 0) | (lost >= 1000)))
        dstf = np.diff(stf[sel]) / np.maximum(dpc, 1)
        stf_bad = int(np.sum(np.abs(dstf - STF_PER_PACKET) > 5))
        n_pkts = int(new.sum())
        expect = dur * 100
        multi = int(np.sum(new >= 2))
        n_bad = int(bad.sum())
        ok = n_lost == 0 and jumps == 0 and stf_bad == 0 and n_bad == 0
        ok_all &= ok
        print(f"      IMU{i}: 收到 {n_pkts} 個封包 (100Hz 預期約 {expect:.0f})，一次讀到 2 個以上 {multi} 次 | "
              f"漏讀 {n_lost} | PacketCounter 異常跳動 {jumps} | SampleTimeFine 異常 {stf_bad} | "
              f"讀取錯誤 {n_bad} -> {'PASS' if ok else 'FAIL'}")
    if imus:
        good = [m for m in imus if m['ok'] == '1']
        dids = [m['did'] for m in good]
        dup = {x for x in dids if dids.count(x) > 1}
        ok = not dup
        ok_all &= ok
        print('      DeviceID：' + ', '.join(f"IMU{m['idx']}={m['did']}" for m in good)
              + (f'  ❌ 重複 {dup}' if dup else '  (各不相同)') + f" -> {'PASS' if ok else 'FAIL'}")

    # 6. 同步性
    print('[6] 同步性')
    sample_time = {}
    if cal:
        for i in active:
            mp = stf_mapping(cal, i)
            if mp is None:
                print(f'      IMU{i}: 校準資料不足')
                continue
            a, b, ppm = mp
            sel = d[f'new{i}'] > 0
            stf = d[f'stf{i}']
            ts = a + b * stf  # 每週期最新封包在 MCU 時間軸上的取樣時刻
            fresh = np.cumsum(sel) > 0  # 錄製開始後收到第一個新封包之前的值是舊的，不算
            sample_time[i] = np.where(fresh & (stf > 0), ts, np.nan)
            # 延遲：封包被讀到的時刻 - 取樣時刻 (只看有新封包的週期)
            age = ((d['t_us'] + d[f'off{i}'] - ts) / 1000)[sel]
            report[f'age{i}'] = age
            print(f'      IMU{i}: 時鐘相對 MCU {ppm:+.0f} ppm；封包從到達到被讀到 '
                  f'平均 {np.mean(age):.2f} ms，95% {np.percentile(age, 95):.2f} ms，最大 {np.max(age):.2f} ms')
        print(f'      (理論上延遲不超過一個讀取週期 {period / 1000:.1f} ms；不含 IMU 內部處理時間)')
    else:
        print('      沒有校準資料，無法換算取樣時刻')
    if len(sample_time) >= 2:
        st = np.vstack([sample_time[i] for i in sample_time])
        keep = ~np.any(np.isnan(st), axis=0)
        spread = (st[:, keep].max(axis=0) - st[:, keep].min(axis=0)) / 1000
        print(f'      IMU 之間最新樣本的取樣時刻差：平均 {spread.mean():.2f} ms，'
              f'95% {np.percentile(spread, 95):.2f} ms，最大 {spread.max():.2f} ms')
        print('      註：MTi 沒有外部同步時各顆以自己的時鐘取樣，彼此差 0~10ms 屬正常；'
              '需要更準的同步要用 SyncIn')
        report['spread'] = spread
    if sample_time:
        enc_t = d['t_us'] + d['enc_off']
        lag = np.concatenate([(enc_t - sample_time[i])[~np.isnan(sample_time[i])] / 1000 for i in sample_time])
        print(f'      encoder 取樣時刻 - 同一週期 IMU 最新樣本的取樣時刻：平均 {lag.mean():.2f} ms，'
              f'範圍 {lag.min():.2f}~{lag.max():.2f} ms')

    # 7. encoder
    enc_err = int(d['enc_err'].sum())
    ok = enc_err == 0
    ok_all &= ok
    print(f"[7] Encoder     {len(cyc)} 次讀取，錯誤 (bit15≠1) {enc_err} 次"
          + ('，數值都是 0 → encoder 可能沒接' if np.all(d['enc_deg'] == 0) else '')
          + f" -> {'PASS' if ok else 'FAIL'}")
    print('=' * 80)
    print(f" 總結：{'全部通過' if ok_all else '有項目未通過'}  "
          f"(線上 IMU：{', '.join(f'IMU{i}' for i in active) or '無'})")
    print('=' * 80)
    report.update(active=active, data=d, period=period)
    return report


def plot(report, path):
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'Noto Sans CJK JP', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    active = report['active']

    ax = axes[0, 0]
    ax.hist(report['dt'] / 1000, bins=50, color=COLORS[0])
    ax.set_title('讀取週期分布')
    ax.set_xlabel('週期 (ms)')
    ax.set_ylabel('次數')

    ax = axes[0, 1]
    names = list(report['offs'].keys())
    bp = ax.boxplot([report['offs'][n] / 1000 for n in names], labels=names, patch_artist=True,
                    showfliers=False)
    for patch, n in zip(bp['boxes'], names):
        patch.set_facecolor(ENC_COLOR if n == 'encoder' else COLORS[int(n[3:]) % len(COLORS)])
    ax.set_title('同一週期內各裝置開始讀取的時間')
    ax.set_ylabel('相對週期開始 (ms)')

    ax = axes[1, 0]
    ages = {i: report[f'age{i}'] for i in active if f'age{i}' in report}
    if ages:
        for i, age in ages.items():
            ax.hist(age, bins=40, alpha=0.6, color=COLORS[i % len(COLORS)], label=f'IMU{i}')
        ax.axvline(report['period'] / 1000, color='#888', linestyle='--', linewidth=1)
        ax.set_title('封包從到達到被讀到的延遲 (虛線 = 一個讀取週期)')
        ax.set_xlabel('延遲 (ms)')
        ax.set_ylabel('封包數')
        ax.legend(frameon=False, fontsize=9)
    else:
        ax.text(0.5, 0.5, '沒有校準資料', ha='center', va='center', transform=ax.transAxes)

    ax = axes[1, 1]
    d = report['data']
    t = (d['t_us'] - d['t_us'][0]) / 1e6
    ax.plot(t, d['enc_deg'], color=ENC_COLOR, linewidth=1, label='encoder (deg)')
    for i in active:
        ax.plot(t, d[f'pitch{i}'], color=COLORS[i % len(COLORS)], linewidth=1, label=f'IMU{i} pitch')
    ax.set_title('原始資料')
    ax.set_xlabel('時間 (s)')
    ax.legend(frameon=False, fontsize=9)

    for ax in axes.flat:
        ax.grid(True, linestyle='--', alpha=0.35)
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    print(f'圖表已存到 {os.path.abspath(path)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=float, default=30.0)
    parser.add_argument('--rate', type=int, default=500, choices=sorted(RATE_CMD))
    parser.add_argument('--spi', type=int, default=1000, choices=sorted(SPI_CMD), help='IMU SPI 時脈 (kHz)')
    parser.add_argument('--port')
    parser.add_argument('--identify', action='store_true', help='逐顆晃動 IMU 確認 CS 對應 (調包檢查)')
    parser.add_argument('--bus-check', action='store_true', help='只做 SPI 匯流排檢查')
    parser.add_argument('--from-csv', help='用之前存的原始資料重新分析')
    args = parser.parse_args()

    if args.bus_check:
        with open_port(args.port) as ser:
            bus_check(ser)
        return

    imus, cal = None, None
    if args.from_csv:
        with open(args.from_csv) as fp:
            rows = list(csv.DictReader(fp))
        data = {k: np.array([float(x[k]) for x in rows]) for k in rows[0]}
        cal_path = os.path.join(os.path.dirname(args.from_csv) or '.', CAL_CSV)
        if os.path.exists(cal_path):
            with open(cal_path) as fp:
                cal = [[float(x) for x in r] for r in list(csv.reader(fp))[1:]]
    else:
        ser = open_port(args.port)
        with ser:
            imus = read_init(ser, args.spi)
            print('IMU 初始化結果：')
            for m in imus:
                mark = '✅' if m['ok'] == '1' else ('(沒接)' if m['fw'] == '00000000' else '❌')
                print(f"   IMU{m['idx']} CS={m['cs']:<5} fill word {m['fw']}  DeviceID {m['did']}  {mark}")
            rate = set_rate(ser, args.rate)
            print(f'\n讀取頻率 {rate} Hz，IMU SPI {args.spi} kHz')
            print('時間校準 (1/2) ...')
            cal = calibrate(ser)
            print(f'錄製 {args.seconds:.0f} 秒 (IMU 可以靜止或移動) ...')
            data, bad_lines = record(ser, args.seconds)
            if bad_lines:
                print(f'⚠️ 有 {bad_lines} 行格式不完整 (序列埠傳輸錯誤)')
            print('時間校準 (2/2) ...')
            cal += calibrate(ser)
            if args.identify:
                identify(ser, [m['idx'] for m in imus if m['ok'] == '1'])
        if data is None:
            sys.exit('❌ 沒有收到資料')
        with open(RAW_CSV, 'w', newline='') as fp:
            w = csv.writer(fp)
            w.writerow(data.keys())
            w.writerows(zip(*data.values()))
        with open(CAL_CSV, 'w', newline='') as fp:
            w = csv.writer(fp)
            w.writerow(['imu', 't_us', 'pc', 'stf', 'new'])
            w.writerows(cal)
        print(f'原始資料已存到 {os.path.abspath(RAW_CSV)}、{CAL_CSV}')

    report = analyze(data, imus, cal)
    plot(report, PLOT_PNG)


if __name__ == '__main__':
    main()
