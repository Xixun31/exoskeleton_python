"""
IMU vs 外接絕對 Encoder 頻率響應量測

搭配韌體：mbed/imu_freq_response
  馬達以不同頻率做正弦運動，同時記錄外接 encoder (輸入/參考) 與 IMU (輸出) 的角度，
  每個頻率用正弦擬合算出：
    amplitude ratio = IMU 振幅 / Encoder 振幅
    phase difference = IMU 相位 - Encoder 相位 (負值 = IMU 落後)
  最後畫出 frequency response 與 Bode plot。

使用方式：
    python3 imu_encoder_freq_response.py                 # 實際量測
    python3 imu_encoder_freq_response.py --from-csv FILE # 用之前存的原始資料重新分析
    python3 imu_encoder_freq_response.py --from-csv FILE --ref inc
                                         # 改用馬達增量 encoder 當參考 (輸出檔名加 _inc)
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
from scipy.optimize import least_squares

# ================= 設定區 =================
ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
PORT = ports[0] if ports else '/dev/ttyACM0'
BAUD = 115200

FREQUENCIES = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]  # Hz (資料取樣 100Hz，建議 <= 10Hz)
SWEEP_AMP = 20.0     # 低頻時的馬達正弦命令振幅 (deg)
MAX_PEAK_VEL = 400.0 # 最高轉速限制 (deg/s)：高頻自動降低振幅，避免電流過大讓馬達停住
MIN_AMP = 5.0        # 振幅下限 (deg)
SETTLE_TIME = 2.0    # 每個頻率先等暫態消失 (s)，至少等 2 個週期
RECORD_TIME = 4.0    # 每個頻率記錄時間 (s)，至少記錄 RECORD_CYCLES 個週期
RECORD_CYCLES = 5
MAX_ATTEMPTS = 3     # 偵測到馬達停住時最多重測幾次
PITCH_LIMIT = 70.0   # 擺動時 |pitch| 不要超過這個角度 (歐拉角在 ±90° 有奇異點)
STALL_RATIO = 0.3    # 某一段擺幅 < 正常擺幅的 30% 視為停住

# IMU 用哪個軸量測馬達轉動：'auto' 自動選振幅最大的軸，或指定 'roll' / 'pitch' / 'yaw'
IMU_AXIS = 'auto'

RAW_CSV = 'freq_response_raw.csv'
REPORT_CSV = 'freq_response_report.csv'
FR_PNG = 'freq_response.png'
BODE_PNG = 'freq_response_bode.png'
TIME_PNG = 'freq_response_timeseries.png'
MODEL_TXT = 'freq_response_model.txt'
GYRO_FR_PNG = 'freq_response_gyro.png'
GYRO_BODE_PNG = 'freq_response_gyro_bode.png'
GYRO_MODEL_TXT = 'freq_response_gyro_model.txt'
# ==========================================

AXES = {'roll': 0, 'pitch': 1, 'yaw': 2}

# 參考角度來源：'enc' = 外接絕對 encoder，'inc' = 馬達本身的增量 encoder (用 --ref 選)
REF = 'enc'
REF_LABELS = {'enc': '外接 Encoder', 'inc': '增量 Encoder'}


def ref_label():
    return REF_LABELS[REF]


def ref_angle(d):
    """參考角度 (deg)。外接 encoder 是 0~360 需要 unwrap，增量 encoder 本來就是連續角度"""
    return unwrap_deg(d['enc']) if REF == 'enc' else np.asarray(d['inc'], dtype=float)


def out_name(path):
    """用增量 encoder 當參考時，輸出檔名加上 _inc，避免覆蓋外接 encoder 的結果"""
    if REF == 'enc':
        return path
    base, ext = os.path.splitext(path)
    return f'{base}_inc{ext}'
ENC_COLOR = '#2a78d6'
IMU_COLOR = '#eb6834'
GYRO_COLOR = '#1baf7a'


# ---------------- 序列埠 ----------------
def parse_line(line):
    """D,t_us,enc_deg,roll,pitch,yaw,target_deg,inc_deg,imu_packets,enc_errors,dropped[,imu_age_us]"""
    if not line.startswith('D,'):
        return None
    parts = line.split(',')
    if len(parts) not in (11, 12, 15):
        return None
    try:
        return {
            't': int(parts[1]) * 1e-6,
            'enc': float(parts[2]),
            'euler': [float(parts[3]), float(parts[4]), float(parts[5])],
            'target': float(parts[6]),
            'inc': float(parts[7]),
            'imu_packets': int(parts[8]),
            'enc_errors': int(parts[9]),
            'dropped': int(parts[10]),
            # IMU 資料在取樣當下已經放了多久 (舊韌體沒有這欄就當 0)
            'imu_age': int(parts[11]) * 1e-6 if len(parts) >= 12 else 0.0,
            # IMU 陀螺儀角速度 (deg/s)，舊韌體沒有就是 None
            'gyro': [float(parts[12]), float(parts[13]), float(parts[14])] if len(parts) == 15 else None,
        }
    except ValueError:
        return None


def record(ser, duration):
    """從板子讀 duration 秒的資料，時間用板子上的時間戳"""
    ser.reset_input_buffer()
    segments = [[]]
    start = time.time()
    while time.time() - start < duration:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        s = parse_line(line)
        if not s:
            continue
        # 時間戳不連續就切一段新的：ST-LINK 會暫存開頭的舊資料，傳輸中也可能有損壞的行
        seg = segments[-1]
        if seg and not (0 < s['t'] - seg[-1]['t'] < 0.5):
            segments.append([])
        segments[-1].append(s)
    return max(segments, key=len)


def span(values):
    return max(values) - min(values) if values else 0.0


def amp_for(f):
    """頻率越高振幅越小：峰值轉速 = 振幅 x 2πf 不超過 MAX_PEAK_VEL"""
    return max(MIN_AMP, min(SWEEP_AMP, MAX_PEAK_VEL / (2.0 * np.pi * f)))


def robust_span(y):
    """擺幅 (忽略少數突波)"""
    return np.percentile(y, 97) - np.percentile(y, 3) if len(y) else 0.0


def stall_mask(t, enc, f):
    """把資料切成小段，擺幅明顯變小的段落視為馬達停住，回傳 (有效 mask, 停住比例)"""
    win = max(0.15, 1.0 / f)  # 每段約一個週期
    valid = np.ones(len(t), dtype=bool)
    windows = []
    a = t[0]
    while a < t[-1]:
        m = (t >= a) & (t < a + win)
        if m.sum() >= 5:
            windows.append((m, robust_span(enc[m])))
        a += win
    if not windows:
        return valid, 0.0
    ref = np.percentile([sp for _, sp in windows], 80)
    for m, sp in windows:
        if sp < STALL_RATIO * ref:
            valid[m] = False
    return valid, 1.0 - valid.mean()


def to_arrays(samples):
    return {
        't': np.array([s['t'] for s in samples]),
        'enc': np.array([s['enc'] for s in samples]),
        'euler': np.array([s['euler'] for s in samples]),
        'target': np.array([s['target'] for s in samples]),
        'inc': np.array([s['inc'] for s in samples]),
        'imu_age': np.array([s['imu_age'] for s in samples]),
        'gyro': np.array([s['gyro'] for s in samples]) if samples[0]['gyro'] is not None else None,
    }


# ---------------- 分析 ----------------
def unwrap_deg(a):
    return np.degrees(np.unwrap(np.radians(a)))


def fit_sine(t, y, freq):
    """最小平方擬合 y = A sin(wt + phi) + C，回傳 (A, phi[rad], C, residual)"""
    w = 2.0 * np.pi * freq
    M = np.column_stack((np.sin(w * t), np.cos(w * t), np.ones_like(t)))
    coeff, _, _, _ = np.linalg.lstsq(M, y, rcond=None)
    a, b, c = coeff
    return np.hypot(a, b), np.arctan2(b, a), c, y - M @ coeff


def robust_fit_sine(t, y, freq):
    """擬合後剔除突波 (例如 encoder 偶發讀錯) 再擬合一次，回傳 (A, phi, C, r2, n_outliers)"""
    amp, phi, c, res = fit_sine(t, y, freq)
    mad = np.median(np.abs(res - np.median(res))) * 1.4826
    keep = np.abs(res) <= max(5.0 * mad, 1.0)
    if keep.sum() > 10 and not keep.all():
        amp, phi, c, _ = fit_sine(t[keep], y[keep], freq)
    res_keep = y[keep] - (amp * np.sin(2 * np.pi * freq * t[keep] + phi) + c)
    ss_tot = np.sum((y[keep] - y[keep].mean()) ** 2)
    r2 = 1.0 - np.sum(res_keep ** 2) / ss_tot if ss_tot > 0 else 0.0
    return amp, phi, c, r2, int((~keep).sum())


def wrap_deg(d):
    return (d + 180.0) % 360.0 - 180.0


def choose_axis(t, euler, freq):
    """選擇振幅最大的 IMU 軸"""
    amps = [robust_fit_sine(t, unwrap_deg(euler[:, i]), freq)[0] for i in range(3)]
    names = list(AXES.keys())
    best = int(np.argmax(amps))
    print('   IMU 各軸振幅: ' + ', '.join(f'{n}={a:.2f}°' for n, a in zip(names, amps)))
    return names[best]


def analyze(raw, axis_name):
    """raw: {freq: dict of arrays}；回傳每個頻率的結果 list"""
    results = []
    sign = None
    gyro_axis = None  # 陀螺儀用哪一軸：最低頻時振幅最大的軸
    gyro_sign = None
    for f in sorted(raw):
        d = raw[f]
        valid = d.get('valid', np.ones(len(d['t']), dtype=bool))
        age = d.get('imu_age', np.zeros(len(d['t'])))
        t = (d['t'] - d['t'][0])[valid]
        t_imu = t - age[valid]  # IMU 資料實際到達的時間
        enc = ref_angle(d)[valid]
        imu = unwrap_deg(d['euler'][:, AXES[axis_name]])[valid]

        a_enc, p_enc, _, r2_enc, out_enc = robust_fit_sine(t, enc, f)
        a_imu, p_imu, _, r2_imu, out_imu = robust_fit_sine(t_imu, imu, f)
        phase = np.degrees(p_imu - p_enc)

        # IMU 與 encoder 的方向可能相反：用最低頻決定一次正負號，之後固定
        if sign is None:
            sign = -1.0 if abs(wrap_deg(phase)) > 90.0 else 1.0
            if sign < 0:
                print(f'ℹ️  IMU {axis_name} 方向與 encoder 相反，分析時已反轉 IMU 正負號')
        if sign < 0:
            phase += 180.0

        # 陀螺儀比對：參考角度 A sin(wt+p) 的角速度 = wA sin(wt+p+90°)
        gyro_ratio = gyro_phase = np.nan
        gyro = d.get('gyro')
        if gyro is not None and np.any(gyro):
            if gyro_axis is None:
                gyro_axis = int(np.argmax([robust_fit_sine(t_imu, gyro[valid, i], f)[0] for i in range(3)]))
            a_g, p_g, _, _, _ = robust_fit_sine(t_imu, gyro[valid, gyro_axis], f)
            gyro_phase = np.degrees(p_g - p_enc) - 90.0
            if gyro_sign is None:
                gyro_sign = -1.0 if abs(wrap_deg(gyro_phase)) > 90.0 else 1.0
            if gyro_sign < 0:
                gyro_phase += 180.0
            gyro_ratio = a_g / (2.0 * np.pi * f * a_enc) if a_enc > 1e-6 else np.nan
            gyro_phase = wrap_deg(gyro_phase)

        results.append({
            'freq': f,
            'gyro_ratio': gyro_ratio,
            'gyro_phase': gyro_phase,
            'gyro_axis': 'xyz'[gyro_axis] if gyro_axis is not None else '',
            'cmd_amp': robust_span(d['target']) / 2.0,
            'stall_pct': 100.0 * (1.0 - valid.mean()),
            'enc_amp': a_enc,
            'imu_amp': a_imu,
            'ratio': a_imu / a_enc if a_enc > 1e-6 else np.nan,
            'phase': wrap_deg(phase),
            'r2_enc': r2_enc,
            'r2_imu': r2_imu,
            'outliers': out_enc + out_imu,
            'n': len(t),
            'imu_age_ms': float(np.mean(age[valid])) * 1000.0,
        })

    # 相位跨頻率連續化 (避免在 ±180° 跳動)
    phases = np.degrees(np.unwrap(np.radians([r['phase'] for r in results])))
    if len(phases) and phases[0] > 90.0:
        phases -= 360.0
    if not np.isnan(results[0]['gyro_phase']):
        gph = np.degrees(np.unwrap(np.radians([r['gyro_phase'] for r in results])))
        if gph[0] > 90.0:
            gph -= 360.0
        for r, p in zip(results, gph):
            r['gyro_phase'] = p
    for r, p in zip(results, phases):
        r['phase'] = p
        r['ratio_db'] = 20.0 * np.log10(r['ratio']) if r['ratio'] > 0 else np.nan
        r['delay_ms'] = -p / 360.0 / r['freq'] * 1000.0
    return results, sign


# ---------------- 模型擬合 ----------------
MODEL_FORMULA = 'H(s) = K * (2*zeta*wn*s + wn^2) / (s^2 + 2*zeta*wn*s + wn^2) * e^(-s*Td)'


def model_response(params, f):
    """柔性安裝 (base excitation) 模型：IMU 透過彈簧-阻尼連接在 encoder 量的軸上
    H(s) = K * (2*zeta*wn*s + wn^2) / (s^2 + 2*zeta*wn*s + wn^2) * e^(-s*Td)
    比單純二階低通多一個零點：低頻相位落後較少、接近共振時振幅比 > 1
    """
    K, fn, zeta, td = params
    w = 2.0 * np.pi * np.asarray(f, dtype=float)
    wn = 2.0 * np.pi * fn
    s_ = 1j * w
    return K * (2.0 * zeta * wn * s_ + wn ** 2) / (s_ ** 2 + 2.0 * zeta * wn * s_ + wn ** 2) * np.exp(-s_ * td)


def fit_model(results):
    """用 IMU/Encoder 的頻率響應擬合柔性安裝模型 + 時間延遲，回傳 dict 或 None"""
    f = np.array([r['freq'] for r in results])
    H = np.array([r['ratio'] * np.exp(1j * np.radians(r['phase'])) for r in results])
    if len(f) < 4:
        return None

    def residual(p):
        e = (model_response(p, f) - H) / np.abs(H)  # 相對誤差，各頻率權重相同
        return np.concatenate([e.real, e.imag])

    lower = [0.5, 0.5, 0.005, 0.0]
    upper = [2.0, 200.0, 3.0, 0.05]
    best = None
    for fn0 in (5.0, 10.0, 15.0, 25.0, 50.0):
        for z0 in (0.1, 0.3, 0.7):
            sol = least_squares(residual, [1.0, fn0, z0, 0.005], bounds=(lower, upper))
            if best is None or sol.cost < best.cost:
                best = sol
    K, fn, zeta, td = best.x
    rms = np.sqrt(np.mean(np.abs(model_response(best.x, f) - H) ** 2 / np.abs(H) ** 2))
    return {'K': K, 'fn': fn, 'zeta': zeta, 'td': td, 'rms': rms,
            'params': best.x, 'f_max': f.max(),
            'at_bound': bool(np.any(np.isclose(best.x, lower)) or np.any(np.isclose(best.x, upper)))}


GYRO_MODEL_FORMULA = 'H(s) = K / (s/wc + 1) * e^(-s*Td)'


def gyro_model_response(params, f):
    """陀螺儀通道模型：一階低通 + 時間延遲 H(s) = K / (s/wc + 1) * e^(-s*Td)"""
    K, fc, td = params
    s_ = 2j * np.pi * np.asarray(f, dtype=float)
    return K / (s_ / (2.0 * np.pi * fc) + 1.0) * np.exp(-s_ * td)


def gyro_results(results):
    """把陀螺儀的比對結果整理成和角度結果相同的格式 (沒有陀螺儀資料就回傳 None)"""
    if not results or np.isnan(results[0].get('gyro_ratio', np.nan)):
        return None
    out = []
    for r in results:
        out.append({'freq': r['freq'], 'ratio': r['gyro_ratio'], 'phase': r['gyro_phase'],
                    'ratio_db': 20.0 * np.log10(r['gyro_ratio']),
                    'delay_ms': -r['gyro_phase'] / 360.0 / r['freq'] * 1000.0,
                    'gyro_axis': r['gyro_axis']})
    return out


def fit_gyro_model(gres):
    f = np.array([r['freq'] for r in gres])
    H = np.array([r['ratio'] * np.exp(1j * np.radians(r['phase'])) for r in gres])
    if len(f) < 3:
        return None

    def residual(p):
        e = (gyro_model_response(p, f) - H) / np.abs(H)
        return np.concatenate([e.real, e.imag])

    lower, upper = [0.5, 0.5, 0.0], [2.0, 500.0, 0.1]
    best = None
    for fc0 in (5.0, 20.0, 50.0, 200.0):
        sol = least_squares(residual, [1.0, fc0, 0.01], bounds=(lower, upper))
        if best is None or sol.cost < best.cost:
            best = sol
    K, fc, td = best.x
    rms = np.sqrt(np.mean(np.abs(gyro_model_response(best.x, f) - H) ** 2 / np.abs(H) ** 2))
    return {'K': K, 'fc': fc, 'td': td, 'rms': rms, 'params': best.x, 'f_max': f.max(),
            'kind': 'gyro',
            'at_bound': bool(np.any(np.isclose(best.x, lower)) or np.any(np.isclose(best.x, upper)))}


def report_gyro_model(model, gyro_axis, path):
    lines = [
        f'IMU 陀螺儀 ({gyro_axis} 軸) / {ref_label()} 模型：{GYRO_MODEL_FORMULA}',
        f'  K  (低頻增益)       = {model["K"]:.3f}',
        f'  fc (低通截止頻率)   = {model["fc"]:.1f} Hz',
        f'  Td (純時間延遲)     = {model["td"] * 1000:.2f} ms',
        f'  擬合誤差 (相對 RMS) = {model["rms"] * 100:.1f} %',
    ]
    if model['fc'] > 3 * model['f_max']:
        lines.append(f'  ⚠️ fc 遠高於最高量測頻率 {model["f_max"]:g} Hz，低通效果在量測範圍內很小，fc 不確定性大')
    if model['at_bound']:
        lines.append('  ⚠️ 有參數碰到搜尋範圍邊界，模型可能不適合這組資料')
    text = '\n'.join(lines)
    print('\n' + text + '\n')
    with open(path, 'w') as fp:
        fp.write(text + '\n')
    print(f'陀螺儀模型參數已存到 {os.path.abspath(path)}')


def report_model(model, axis_name, path):
    lines = [
        f'IMU ({axis_name}) / {ref_label()} 模型 (IMU 柔性安裝)：{MODEL_FORMULA}',
        f'  K    (低頻增益)           = {model["K"]:.3f}',
        f'  fn   (安裝座/連桿共振頻率) = {model["fn"]:.2f} Hz  (wn = {2 * np.pi * model["fn"]:.1f} rad/s)',
        f'  zeta (阻尼比)             = {model["zeta"]:.3f}',
        f'  Td   (純時間延遲)         = {model["td"] * 1000:.2f} ms',
        f'  擬合誤差 (相對 RMS)       = {model["rms"] * 100:.1f} %',
    ]
    if model['fn'] > model['f_max']:
        lines.append(f'  ⚠️ fn 高於最高量測頻率 {model["f_max"]:g} Hz，是外插估計，fn 與 zeta 的不確定性較大')
    if model['at_bound']:
        lines.append('  ⚠️ 有參數碰到搜尋範圍邊界，模型可能不適合這組資料')
    text = '\n'.join(lines)
    print('\n' + text + '\n')
    with open(path, 'w') as fp:
        fp.write(text + '\n')
    print(f'模型參數已存到 {os.path.abspath(path)}')


# ---------------- 存檔 ----------------
def save_raw(raw, path):
    with open(path, 'w', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(['freq_hz', 't_s', 'enc_deg', 'roll', 'pitch', 'yaw', 'target_deg', 'inc_deg', 'valid', 'imu_age_us', 'gx', 'gy', 'gz'])
        for f in sorted(raw):
            d = raw[f]
            valid = d.get('valid', np.ones(len(d['t']), dtype=bool))
            age = d.get('imu_age', np.zeros(len(d['t'])))
            gyro = d.get('gyro')
            for i in range(len(d['t'])):
                w.writerow([f, f"{d['t'][i]:.6f}", d['enc'][i], *d['euler'][i], d['target'][i], d['inc'][i],
                            int(valid[i]), int(round(age[i] * 1e6)),
                            *(gyro[i] if gyro is not None else ['', '', ''])])
    print(f'原始資料已存到 {os.path.abspath(path)}')


def load_raw(path):
    rows = {}
    with open(path) as fp:
        for r in csv.DictReader(fp):
            rows.setdefault(float(r['freq_hz']), []).append(r)
    raw = {}
    for f, rs in rows.items():
        raw[f] = {
            't': np.array([float(r['t_s']) for r in rs]),
            'enc': np.array([float(r['enc_deg']) for r in rs]),
            'euler': np.array([[float(r['roll']), float(r['pitch']), float(r['yaw'])] for r in rs]),
            'target': np.array([float(r['target_deg']) for r in rs]),
            'inc': np.array([float(r['inc_deg']) for r in rs]),
            'valid': np.array([r.get('valid', '1') != '0' for r in rs]),
            'imu_age': np.array([float(r.get('imu_age_us') or 0) * 1e-6 for r in rs]),
            'gyro': (np.array([[float(r['gx']), float(r['gy']), float(r['gz'])] for r in rs])
                     if rs[0].get('gx') not in (None, '') else None),
        }
    return raw


def save_report(results, axis_name, path):
    keys = ['freq', 'cmd_amp', 'stall_pct', 'enc_amp', 'imu_amp', 'ratio', 'ratio_db', 'phase', 'delay_ms',
            'r2_enc', 'r2_imu', 'outliers', 'n', 'imu_age_ms', 'gyro_ratio', 'gyro_phase']
    header = ['Frequency_Hz', 'Command_Amp_deg', 'Stall_Removed_pct',
              'Encoder_Amp_deg' if REF == 'enc' else 'IncEncoder_Amp_deg', f'IMU_{axis_name}_Amp_deg', 'Amplitude_Ratio',
              'Amplitude_Ratio_dB', 'Phase_Diff_deg', 'Time_Delay_ms', 'Fit_R2_Encoder',
              'Fit_R2_IMU', 'Outliers_Removed', 'Samples', 'IMU_Age_Corrected_ms',
              'Gyro_Ratio', 'Gyro_Phase_Diff_deg']
    with open(path, 'w', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(header)
        for r in results:
            w.writerow([f'{r[k]:.4f}' if isinstance(r[k], float) else r[k] for k in keys])
    print(f'分析結果已存到 {os.path.abspath(path)}')


def print_table(results, axis_name):
    print('\n' + '=' * 92)
    print(f' IMU ({axis_name}) 相對於{ref_label()}的頻率響應')
    print('=' * 92)
    print(f"{'f (Hz)':>7} {'Ref amp':>9} {'IMU amp':>9} {'Ratio':>7} {'Ratio dB':>9} "
          f"{'Phase':>8} {'Delay':>9} {'R2 enc':>7} {'R2 imu':>7} {'突波':>5}")
    for r in results:
        warn = ''
        if r['enc_amp'] < 2.0:
            warn += ' ⚠️encoder振幅太小'
        if min(r['r2_enc'], r['r2_imu']) < 0.9:
            warn += ' ⚠️擬合不佳'
        if r['stall_pct'] > 0:
            warn += f" (馬達停住 {r['stall_pct']:.0f}% 已排除)"
        print(f"{r['freq']:7.2f} {r['enc_amp']:8.2f}° {r['imu_amp']:8.2f}° {r['ratio']:7.3f} "
              f"{r['ratio_db']:8.2f}  {r['phase']:+7.1f}° {r['delay_ms']:7.1f}ms "
              f"{r['r2_enc']:7.3f} {r['r2_imu']:7.3f} {r['outliers']:5d}{warn}")
    print('=' * 92)
    print(f' Ratio = IMU振幅 / {ref_label()}振幅 (1 = 完全一致)；Phase < 0 代表 IMU 落後')
    print(' Delay = 相位差換算成的時間延遲 = -Phase / 360 / f\n')

    if not np.isnan(results[0]['gyro_ratio']):
        print(f" 陀螺儀比對 (gyro {results[0]['gyro_axis']} 軸角速度 vs {ref_label()}角度微分)")
        print(f"{'f (Hz)':>7} | {'角度 Ratio':>10} {'陀螺儀 Ratio':>12} | {'角度 Phase':>10} {'陀螺儀 Phase':>12}")
        for r in results:
            print(f"{r['freq']:7.2f} | {r['ratio']:10.3f} {r['gyro_ratio']:12.3f} | "
                  f"{r['phase']:+9.1f}° {r['gyro_phase']:+11.1f}°")
        print(' 陀螺儀 Ratio 也 > 1 → IMU 真的晃得比較大 (機構共振)')
        print(' 陀螺儀 Ratio ≈ 1 但角度 Ratio > 1 → IMU 姿態演算法的誤差\n')


# ---------------- 繪圖 ----------------
def setup_style():
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK TC', 'Noto Sans CJK JP',
                                       'WenQuanYi Zen Hei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False


def style_ax(ax):
    ax.grid(True, which='both', linestyle='--', alpha=0.35)
    for side in ('top', 'right'):
        ax.spines[side].set_visible(False)


def plot_response(results, axis_name, log_scale, path, model=None, signal='angle'):
    """signal='angle'：IMU 角度；signal='gyro'：IMU 陀螺儀角速度 (results 用 gyro_results 轉換)"""
    f = np.array([r['freq'] for r in results])
    ratio = np.array([r['ratio'] for r in results])
    phase = np.array([r['phase'] for r in results])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7.5), sharex=True)
    fmt = 'o' if model is not None else '-o'  # 有模型時量測值只畫點
    if model is not None:
        # 模型曲線只畫在量測範圍內
        fg = np.geomspace(f.min(), f.max(), 300) if log_scale else np.linspace(f.min(), f.max(), 300)
        if signal == 'gyro':
            Hg = gyro_model_response(model['params'], fg)
            label = f"模型 fc={model['fc']:.1f}Hz, Td={model['td'] * 1000:.1f}ms"
        else:
            Hg = model_response(model['params'], fg)
            label = (f"模型 fn={model['fn']:.1f}Hz, ζ={model['zeta']:.2f}, "
                     f"Td={model['td'] * 1000:.1f}ms")
        mag = np.abs(Hg)
        ph = np.degrees(np.unwrap(np.angle(Hg)))
        ax1.plot(fg, 20 * np.log10(mag) if log_scale else mag, color=IMU_COLOR,
                 linewidth=1.5, linestyle='--', label=label)
        ax2.plot(fg, ph, color=IMU_COLOR, linewidth=1.5, linestyle='--')
    if log_scale:
        ax1.semilogx(f, 20 * np.log10(ratio), fmt, color=ENC_COLOR, linewidth=2, label='量測值',
                     markersize=7, markeredgecolor='white', markeredgewidth=1.5)
        ax1.axhline(0, color='#888', linewidth=1)
        ax1.axhline(-3, color='#888', linewidth=1, linestyle=':')
        ax1.text(f[0], -3, ' -3 dB', va='bottom', fontsize=9, color='#666')
        ax1.set_ylabel('Magnitude (dB)')
        ax2.semilogx(f, phase, fmt, color=ENC_COLOR, linewidth=2,
                     markersize=7, markeredgecolor='white', markeredgewidth=1.5)
        title = f'Bode Plot：IMU ({axis_name}) / {ref_label()}'
        if signal == 'gyro':
            title = f"Bode Plot：IMU 陀螺儀 ({results[0]['gyro_axis']} 軸) / {ref_label()}"
    else:
        ax1.plot(f, ratio, fmt, color=ENC_COLOR, linewidth=2, label='量測值',
                 markersize=7, markeredgecolor='white', markeredgewidth=1.5)
        ax1.axhline(1, color='#888', linewidth=1)
        ax1.set_ylabel('Amplitude Ratio (IMU / Encoder)')
        ax2.plot(f, phase, fmt, color=ENC_COLOR, linewidth=2,
                 markersize=7, markeredgecolor='white', markeredgewidth=1.5)
        ax2.set_xlim(left=0)
        title = f'Frequency Response：IMU ({axis_name}) / {ref_label()}'
        if signal == 'gyro':
            title = f"Frequency Response：IMU 陀螺儀 ({results[0]['gyro_axis']} 軸) / {ref_label()}"
        ax1.set_ylim(0, max(1.15, np.nanmax(ratio) * 1.1))

    ax2.axhline(0, color='#888', linewidth=1)
    ax2.set_ylabel('Phase Difference (deg)')
    ax2.set_xlabel('Frequency (Hz)')
    if log_scale:
        ax2.set_xticks(f)
        ax2.set_xticklabels([f'{v:g}' for v in f])
        ax2.minorticks_off()
    gyro_ratio = np.array([r.get('gyro_ratio', np.nan) for r in results])
    if not np.all(np.isnan(gyro_ratio)):
        gyro_phase = np.array([r['gyro_phase'] for r in results])
        gy = 20 * np.log10(gyro_ratio) if log_scale else gyro_ratio
        ax1.plot(f, gy, 's', color=GYRO_COLOR, markersize=7, markeredgecolor='white',
                 markeredgewidth=1.5, label=f"陀螺儀角速度 ({results[0]['gyro_axis']} 軸)")
        ax2.plot(f, gyro_phase, 's', color=GYRO_COLOR, markersize=7, markeredgecolor='white',
                 markeredgewidth=1.5)
        if not log_scale:
            ax1.set_ylim(0, max(1.15, np.nanmax(np.concatenate([ratio, gyro_ratio])) * 1.1))
        ax1.lines[[l.get_label() for l in ax1.lines].index('量測值')].set_label(f'{axis_name} 角度')
    if model is not None or not np.all(np.isnan(gyro_ratio)):
        ax1.legend(loc='best', frameon=False, fontsize=9)
    ax1.set_title(title, fontsize=14)
    style_ax(ax1)
    style_ax(ax2)
    plt.tight_layout()
    fig.savefig(path, dpi=150)
    print(f'圖表已存到 {os.path.abspath(path)}')


def plot_timeseries(raw, results, axis_name, sign, path):
    """每個頻率的時域波形 (去除平均值)，用來檢查擬合是否合理"""
    n = len(results)
    cols = 3
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(12, 2.6 * rows), squeeze=False)
    for ax, r in zip(axes.flat, results):
        d = raw[r['freq']]
        valid = d.get('valid', np.ones(len(d['t']), dtype=bool))
        t = d['t'] - d['t'][0]
        enc = ref_angle(d)
        imu = sign * unwrap_deg(d['euler'][:, AXES[axis_name]])
        enc = np.where(valid, enc - np.median(enc[valid]), np.nan)  # 馬達停住的段落不畫
        imu = np.where(valid, imu - np.median(imu[valid]), np.nan)
        # 畫有效資料的最後 3 個週期
        t_end = t[valid][-1]
        mask = (t >= t_end - 3.0 / r['freq']) & (t <= t_end)
        ax.plot(t[mask], enc[mask], color=ENC_COLOR, linewidth=1.8, label=ref_label())
        t_imu = t - d.get('imu_age', np.zeros(len(t)))
        ax.plot(t_imu[mask], imu[mask], color=IMU_COLOR, linewidth=1.8, label='IMU')
        ax.set_title(f"{r['freq']:g} Hz  ratio {r['ratio']:.2f}, {r['phase']:+.0f}°", fontsize=10)
        ax.tick_params(labelsize=8)
        style_ax(ax)
    for ax in list(axes.flat)[n:]:
        ax.axis('off')
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='upper center', ncol=2, frameon=False, fontsize=10)
    fig.supxlabel('Time (s)')
    fig.supylabel('Angle − median (deg)')
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(path, dpi=150)
    print(f'圖表已存到 {os.path.abspath(path)}')


# ---------------- 主流程 ----------------
def measure(port):
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except serial.SerialException as e:
        print(f'❌ 無法開啟 {port}: {e}')
        print('   如果是 Device or resource busy，請先關掉 screen (fuser -v /dev/ttyACM0)')
        sys.exit(1)
    print(f'✅ 已連接 {port} @ {BAUD}')

    raw = {}
    with ser:
        ser.write(b'feedback 0\n')  # 馬達用自己的增量 encoder 控制，外接 encoder 只當量測參考
        ser.write(b'0\n')
        print('馬達回到 0°...')
        time.sleep(2.0)

        # 靜止時檢查資料是否正常
        idle = record(ser, 1.5)
        if len(idle) < 50:
            print(f'❌ 只收到 {len(idle)} 筆資料，請確認板子燒的是 imu_freq_response 韌體')
            sys.exit(1)
        dt = idle[-1]['t'] - idle[0]['t']
        imu_rate = (idle[-1]['imu_packets'] - idle[0]['imu_packets']) / dt
        log_rate = (len(idle) - 1) / dt
        print(f'資料速率: {log_rate:.1f} Hz | IMU 封包速率: {imu_rate:.1f} Hz | '
              f"encoder 讀錯累計: {idle[-1]['enc_errors']} | 遺失樣本: {idle[-1]['dropped']}")
        if imu_rate < 1:
            print('❌ 沒有收到 IMU 資料，請檢查 IMU 接線 (PC_10/PC_11) 與電源')
            sys.exit(1)
        if imu_rate < 4 * max(FREQUENCIES):
            print(f'⚠️  IMU 速率 {imu_rate:.0f} Hz 對最高頻 {max(FREQUENCIES)} Hz 來說偏低，高頻結果參考就好')

        # 歐拉角在 pitch = ±90° 有奇異點 (roll/yaw 翻轉、pitch 摺回)，擺動時不能靠近
        pitch_now = np.median([s['euler'][1] for s in idle])
        print(f'目前 IMU 姿態: roll {idle[-1]["euler"][0]:.1f}° / pitch {pitch_now:.1f}° / '
              f'yaw {idle[-1]["euler"][2]:.1f}°')
        if abs(pitch_now) + SWEEP_AMP > PITCH_LIMIT:
            print(f'\n⚠️  pitch {pitch_now:.1f}° ± 擺動 {SWEEP_AMP:.0f}° 會超過 ±{PITCH_LIMIT:.0f}°，'
                  f'接近 ±90° 奇異點，IMU 角度資料會錯誤 (陀螺儀不受影響)')
            print('   建議：關掉程式 → 馬達斷電 → 把擺臂轉到 IMU 大約水平 → 重新上電 (重設增量 encoder 零點)')
            if input('   仍要繼續量測嗎？(y/N) ').strip().lower() != 'y':
                print('已取消量測')
                sys.exit(0)

        input('\n請確認馬達周圍淨空，按 Enter 開始掃頻 (Ctrl+C 可中斷)...')

        try:
            for f in FREQUENCIES:
                amp = amp_for(f)
                settle = max(SETTLE_TIME, 2.0 / f)
                rec = max(RECORD_TIME, RECORD_CYCLES / f)
                print(f'\n👉 {f:g} Hz，振幅 {amp:.1f}°：等待 {settle:.1f}s，記錄 {rec:.1f}s ...')

                best = None  # (資料, 停住比例, 最後一筆)
                for attempt in range(MAX_ATTEMPTS):
                    ser.write(f'sine {amp:.2f} {f} 0\n'.encode())
                    time.sleep(settle)
                    samples = record(ser, rec)
                    if len(samples) < 50 or span([s['target'] for s in samples]) < amp:
                        print('   ⚠️ 板子沒收到 sine 命令 (target 沒有變化)，重送...')
                        continue
                    d = to_arrays(samples)
                    d['valid'], stall = stall_mask(d['t'], unwrap_deg(d['enc']), f)
                    if best is None or stall < best[1]:
                        best = (d, stall, samples[-1])
                    if stall == 0:
                        break
                    print(f'   ⚠️ 馬達有 {stall * 100:.0f}% 的時間停住，重測 ({attempt + 1}/{MAX_ATTEMPTS})...')
                if best is None:
                    print(f'   ❌ {MAX_ATTEMPTS} 次都失敗，跳過這個頻率')
                    continue
                d, stall, last = best

                # 第一個頻率檢查馬達有沒有真的在動
                enc_span = robust_span(unwrap_deg(d['enc']))
                inc_span = robust_span(d['inc'])
                print(f'   馬達實際擺動: 外接 encoder {enc_span:.1f}° / 增量 encoder {inc_span:.1f}° '
                      f'(命令 {2 * amp:.0f}°)')
                if f == FREQUENCIES[0] and enc_span < 1.0 and inc_span < 1.0:
                    print('\n❌ 馬達沒有在動！target 有變化但兩個 encoder 都幾乎不動。請檢查：')
                    print('   1. 馬達驅動板的電源 (12V 以上) 有沒有打開、電源有沒有限流')
                    print('   2. 馬達線與驅動板 (PA7/PA8/PA9/PB0 PWM) 接線')
                    print('   3. 機構有沒有卡住')
                    print('   可以先按板子上的藍色按鈕測試，正常的話馬達會在 ±90° 之間切換')
                    break

                valid_time = d['valid'].sum() / 100.0
                if valid_time < 2.0 / f or d['valid'].sum() < 50:
                    print(f'   ❌ 馬達有在動的資料只有 {valid_time:.1f}s，不足以分析，跳過這個頻率')
                    continue
                if stall > 0:
                    print(f'   ⚠️ 重測後仍有 {stall * 100:.0f}% 停住，分析時只用馬達有在動的部分')
                raw[f] = d
                print(f"   收到 {len(d['t'])} 筆 | encoder 讀錯累計 {last['enc_errors']} | "
                      f"遺失樣本累計 {last['dropped']}")
        except KeyboardInterrupt:
            print('\n使用者中斷，分析已量到的頻率')
        finally:
            ser.write(b'0\n')  # 停止正弦運動並回到 0°
            print('馬達已停止正弦運動，回到 0°')
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-csv', help='用之前存的原始資料重新分析，不連接板子')
    parser.add_argument('--port', default=PORT)
    parser.add_argument('--axis', default=IMU_AXIS, choices=['auto', 'roll', 'pitch', 'yaw'])
    parser.add_argument('--ref', default='enc', choices=['enc', 'inc'],
                        help='參考角度：enc = 外接 encoder (預設)，inc = 馬達增量 encoder')
    args = parser.parse_args()
    global REF
    REF = args.ref

    if args.from_csv:
        raw = load_raw(args.from_csv)
    else:
        raw = measure(args.port)
        if raw:
            save_raw(raw, RAW_CSV)

    if len(raw) < 2:
        print('❌ 有效頻率點太少，無法繪圖')
        return

    axis = args.axis
    if axis == 'auto':
        f0 = min(raw)
        d = raw[f0]
        axis = choose_axis(d['t'] - d['t'][0], d['euler'], f0)
        print(f'自動選擇 IMU 軸: {axis} (可用 --axis 指定)')

    results, sign = analyze(raw, axis)
    print_table(results, axis)
    save_report(results, axis, out_name(REPORT_CSV))

    model = fit_model(results)
    if model is not None:
        report_model(model, axis, out_name(MODEL_TXT))

    setup_style()
    plot_response(results, axis, log_scale=False, path=out_name(FR_PNG), model=model)
    plot_response(results, axis, log_scale=True, path=out_name(BODE_PNG), model=model)
    plot_timeseries(raw, results, axis, sign, out_name(TIME_PNG))

    # 陀螺儀通道 (韌體有輸出陀螺儀資料時)
    gres = gyro_results(results)
    if gres is not None:
        gmodel = fit_gyro_model(gres)
        if gmodel is not None:
            report_gyro_model(gmodel, gres[0]['gyro_axis'], out_name(GYRO_MODEL_TXT))
        plot_response(gres, axis, log_scale=False, path=out_name(GYRO_FR_PNG), model=gmodel, signal='gyro')
        plot_response(gres, axis, log_scale=True, path=out_name(GYRO_BODE_PNG), model=gmodel, signal='gyro')
    plt.show()


if __name__ == '__main__':
    main()
