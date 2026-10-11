"""
比較多次 imu_encoder_freq_response.py 的量測結果 (重現性檢查)

使用方式：
    python3 compare_runs.py                 # 自動找 run* 資料夾
    python3 compare_runs.py run1 run3 run4  # 指定要比較的資料夾
    python3 compare_runs.py --ref inc       # 改用馬達增量 encoder 當參考，輸出到 compare_inc/
    python3 compare_runs.py --signal gyro run7 run8  # 比較陀螺儀通道，輸出到 compare_gyro/

每個資料夾需要有 freq_response_raw.csv，會用同一套分析重新計算，
輸出到 compare/：
    compare_bode.png      各次 Bode 圖疊圖 + 平均值模型
    compare_report.csv    每個頻率的平均值 / 標準差
    compare_model.txt     各次與合併資料的模型參數
"""
import argparse
import csv
import glob
import os

import matplotlib.pyplot as plt
import numpy as np

import imu_encoder_freq_response as fr

OUT_DIR = 'compare'
# 類別色 (固定順序)，搭配不同標記形狀，不靠顏色單獨辨識
RUN_STYLES = [('#2a78d6', 'o'), ('#eb6834', 's'), ('#1baf7a', '^'), ('#eda100', 'D'),
              ('#e87ba4', 'v'), ('#008300', 'P')]
MODEL_COLOR = '#444444'


def analyze_run(folder, axis, signal='angle'):
    raw = fr.load_raw(os.path.join(folder, 'freq_response_raw.csv'))
    if axis == 'auto':
        f0 = min(raw)
        d = raw[f0]
        axis = fr.choose_axis(d['t'] - d['t'][0], d['euler'], f0)
    results, _ = fr.analyze(raw, axis)
    if signal == 'gyro':
        results = fr.gyro_results(results)
        if results is None:
            raise SystemExit(f'❌ {folder} 沒有陀螺儀資料 (需要新版韌體量測的資料)')
    return results, axis


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('folders', nargs='*')
    parser.add_argument('--ref', default='enc', choices=['enc', 'inc'],
                        help='參考角度：enc = 外接 encoder (預設)，inc = 馬達增量 encoder')
    parser.add_argument('--signal', default='angle', choices=['angle', 'gyro'],
                        help='angle = IMU 角度 (預設)，gyro = IMU 陀螺儀角速度')
    args = parser.parse_args()
    fr.REF = args.ref
    gyro = args.signal == 'gyro'
    out_dir = OUT_DIR + ('_gyro' if gyro else '') + ('_inc' if args.ref == 'inc' else '')
    fit = fr.fit_gyro_model if gyro else fr.fit_model
    response = fr.gyro_model_response if gyro else fr.model_response

    folders = args.folders or sorted(glob.glob('run*'), key=lambda p: (len(p), p))
    folders = [f for f in folders if os.path.isfile(os.path.join(f, 'freq_response_raw.csv'))]
    if len(folders) < 2:
        print('❌ 至少需要 2 個含 freq_response_raw.csv 的資料夾')
        return
    os.makedirs(out_dir, exist_ok=True)

    runs = {}
    axis = 'auto'
    for folder in folders:
        print(f'分析 {folder} ...')
        runs[folder], axis = analyze_run(folder, axis, args.signal)  # 第一次自動選軸，之後沿用
    what = f"IMU 陀螺儀 ({next(iter(runs.values()))[0]['gyro_axis']} 軸)" if gyro else f'IMU ({axis})'

    # 只比較每一次都有的頻率
    freqs = sorted(set.intersection(*[{r['freq'] for r in res} for res in runs.values()]))
    ratio = np.array([[next(r['ratio'] for r in res if r['freq'] == f) for f in freqs]
                      for res in runs.values()])
    phase = np.array([[next(r['phase'] for r in res if r['freq'] == f) for f in freqs]
                      for res in runs.values()])

    # ---------- 統計表 ----------
    print('\n' + '=' * 78)
    print(f' {len(folders)} 次量測比較：{what} / {fr.ref_label()}')
    print('=' * 78)
    print(f"{'f (Hz)':>7} | {'Ratio 平均':>10} {'標準差':>8} {'範圍':>15} | "
          f"{'Phase 平均':>10} {'標準差':>7} {'範圍':>16}")
    rows = []
    for i, f in enumerate(freqs):
        rm, rs = ratio[:, i].mean(), ratio[:, i].std(ddof=1)
        pm, ps = phase[:, i].mean(), phase[:, i].std(ddof=1)
        print(f"{f:7.2f} | {rm:10.3f} {rs:8.3f} {ratio[:, i].min():7.3f}~{ratio[:, i].max():6.3f} | "
              f"{pm:+9.2f}° {ps:6.2f}° {phase[:, i].min():+7.2f}~{phase[:, i].max():+6.2f}°")
        rows.append([f, rm, rs, 20 * np.log10(rm), pm, ps, -pm / 360.0 / f * 1000.0])
    print('=' * 78)

    with open(os.path.join(out_dir, 'compare_report.csv'), 'w', newline='') as fp:
        w = csv.writer(fp)
        w.writerow(['Frequency_Hz', 'Ratio_Mean', 'Ratio_Std', 'Ratio_Mean_dB',
                    'Phase_Mean_deg', 'Phase_Std_deg', 'Time_Delay_Mean_ms'] +
                   [f'Ratio_{k}' for k in runs] + [f'Phase_{k}' for k in runs])
        for i, row in enumerate(rows):
            w.writerow([f'{v:.4f}' for v in row] + [f'{v:.4f}' for v in ratio[:, i]] +
                       [f'{v:.4f}' for v in phase[:, i]])

    # ---------- 模型：各次 + 平均 ----------
    models = {}
    for name, res in runs.items():
        models[name] = fit(res)
    mean_results = [{'freq': f, 'ratio': r[1], 'phase': r[4]} for f, r in zip(freqs, rows)]
    models['平均'] = fit(mean_results)
    if gyro:
        lines = [f'陀螺儀模型：{fr.GYRO_MODEL_FORMULA}', '',
                 f"{'':>8} {'K':>7} {'fc (Hz)':>8} {'Td (ms)':>8} {'RMS':>6}"]
        for name, m in models.items():
            lines.append(f"{name:>8} {m['K']:7.3f} {m['fc']:8.1f} {m['td'] * 1000:8.2f} {m['rms'] * 100:5.1f}%")
        per_run = np.array([[m['K'], m['fc'], m['td'] * 1000] for k, m in models.items() if k != '平均'])
        lines.append(f"{'標準差':>8} {per_run[:, 0].std(ddof=1):7.3f} {per_run[:, 1].std(ddof=1):8.1f} "
                     f"{per_run[:, 2].std(ddof=1):8.2f}")
        # 低頻總延遲 = Td + 一階低通的群延遲 1/wc，比 fc、Td 個別值穩定
        total = [m['td'] * 1000 + 1000 / (2 * np.pi * m['fc']) for k, m in models.items() if k != '平均']
        lines.append(f"\n低頻總延遲 (Td + 1/wc) = {np.mean(total):.2f} ± {np.std(total, ddof=1):.2f} ms")
        if models['平均']['fc'] > 3 * max(freqs):
            lines.append(f"⚠️ fc 遠高於最高量測頻率 {max(freqs):g} Hz，fc 與 Td 會互相抵換，請看總延遲")
    else:
        lines = [f'模型 (IMU 柔性安裝)：{fr.MODEL_FORMULA}', '',
                 f"{'':>8} {'K':>7} {'fn (Hz)':>8} {'zeta':>7} {'Td (ms)':>8} {'RMS':>6}"]
        for name, m in models.items():
            lines.append(f"{name:>8} {m['K']:7.3f} {m['fn']:8.2f} {m['zeta']:7.3f} "
                         f"{m['td'] * 1000:8.2f} {m['rms'] * 100:5.1f}%")
        per_run = np.array([[m['K'], m['fn'], m['zeta'], m['td'] * 1000]
                            for k, m in models.items() if k != '平均'])
        lines.append(f"{'標準差':>8} {per_run[:, 0].std(ddof=1):7.3f} {per_run[:, 1].std(ddof=1):8.2f} "
                     f"{per_run[:, 2].std(ddof=1):7.3f} {per_run[:, 3].std(ddof=1):8.2f}")
        if models['平均']['fn'] > max(freqs):
            lines.append(f"\n⚠️ fn 高於最高量測頻率 {max(freqs):g} Hz，是外插估計")
    text = '\n'.join(lines)
    print('\n' + text + '\n')
    with open(os.path.join(out_dir, 'compare_model.txt'), 'w') as fp:
        fp.write(text + '\n')

    # ---------- 疊圖 ----------
    fr.setup_style()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    fg = np.geomspace(min(freqs), max(freqs), 300)
    Hg = response(models['平均']['params'], fg)
    m = models['平均']
    if gyro:
        model_label = f"平均值模型 fc={m['fc']:.1f}Hz, Td={m['td'] * 1000:.1f}ms"
    else:
        model_label = f"平均值模型 fn={m['fn']:.1f}Hz, ζ={m['zeta']:.2f}, Td={m['td'] * 1000:.1f}ms"
    ax1.semilogx(fg, 20 * np.log10(np.abs(Hg)), '--', color=MODEL_COLOR, linewidth=1.5,
                 label=model_label)
    ax2.semilogx(fg, np.degrees(np.unwrap(np.angle(Hg))), '--', color=MODEL_COLOR, linewidth=1.5)

    for i, name in enumerate(runs):
        color, marker = RUN_STYLES[i % len(RUN_STYLES)]
        ax1.semilogx(freqs, 20 * np.log10(ratio[i]), marker, color=color, markersize=7,
                     markeredgecolor='white', markeredgewidth=1.2, linestyle='none', label=name)
        ax2.semilogx(freqs, phase[i], marker, color=color, markersize=7,
                     markeredgecolor='white', markeredgewidth=1.2, linestyle='none')

    ax1.axhline(0, color='#888', linewidth=1)
    ax2.axhline(0, color='#888', linewidth=1)
    ax1.set_ylabel('Magnitude (dB)')
    ax2.set_ylabel('Phase Difference (deg)')
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_xticks(freqs)
    ax2.set_xticklabels([f'{v:g}' for v in freqs])
    ax2.minorticks_off()
    ax1.set_title(f'{len(runs)} 次量測比較：{what} / {fr.ref_label()}', fontsize=14)
    ax1.legend(loc='best', frameon=False, fontsize=9)
    fr.style_ax(ax1)
    fr.style_ax(ax2)
    plt.tight_layout()
    path = os.path.join(out_dir, 'compare_bode.png')
    fig.savefig(path, dpi=150)
    print(f'結果已存到 {os.path.abspath(out_dir)}/')
    plt.show()


if __name__ == '__main__':
    main()
