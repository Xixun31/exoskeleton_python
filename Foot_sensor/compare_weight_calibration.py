from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)


# ============================================================
# 基本設定
# ============================================================

INPUT_FILE = Path("foot_data.xlsx")
OUTPUT_ROOT = Path("weight_calibration_comparison")

# Excel 第 2 列是欄位名稱
# pandas 使用 0-based index，所以設定為 1
HEADER_ROW = 1

CONDITION_COLUMN = "condition"
REFERENCE_COLUMN = "reference_force_N"

LEFT_COLUMNS = [f"L{i}" for i in range(1, 19)]
RIGHT_COLUMNS = [f"R{i}" for i in range(1, 19)]

G0 = 9.80665


# ============================================================
# 砝碼校正資料
# ============================================================

loading_kg = np.arange(0, 11, dtype=float)

loading = np.array([
    [0, 0, 0, 0, 0],
    [52, 0, 0, 0, 0],
    [1722, 1298, 1240, 954, 610],
    [3440, 2654, 2805, 2342, 2485],
    [4918, 3564, 4436, 3663, 4292],
    [6310, 4840, 5860, 5020, 5652],
    [7785, 6518, 7058, 6260, 7435],
    [8910, 8128, 8120, 7739, 9046],
    [9840, 9037, 9138, 9028, 10790],
    [10706, 10344, 10002, 10027, 12077],
    [11750, 12365, 11095, 10947, 13237]
], dtype=float)


unloading_kg = np.arange(10, -1, -1, dtype=float)

unloading = np.array([
    [11843, 13037, 11196, 11083, 13348],
    [10924, 11175, 10544, 10434, 12692],
    [10499, 9902, 9679, 9505, 11568],
    [9641, 8503, 8027, 8132, 9659],
    [8632, 8039, 6517, 6988, 8646],
    [7303, 6571, 5842, 5986, 7036],
    [6341, 4719, 4857, 4456, 5645],
    [4185, 3562, 3161, 2468, 3503],
    [2590, 2094, 1438, 1218, 1607],
    [212, 102, 0, 0, 0],
    [0, 0, 0, 0, 0]
], dtype=float)


# ============================================================
# 建立兩條校正線
# ============================================================

def fit_lines():

    x = np.concatenate([
        loading.ravel(),
        unloading.ravel()
    ])

    mass = np.concatenate([
        np.repeat(loading_kg, loading.shape[1]),
        np.repeat(unloading_kg, unloading.shape[1])
    ])

    y = mass * G0

    # 帶截距：F = a*x + b
    a_i, b_i = np.polyfit(x, y, 1)

    # 通過原點：F = a*x
    a_o = np.dot(x, y) / np.dot(x, x)

    pred_i = a_i * x + b_i
    pred_o = a_o * x

    return a_i, b_i, a_o, x, y, pred_i, pred_o


# ============================================================
# 計算誤差指標
# ============================================================

def metrics(y, p):

    y = np.asarray(y, float)
    p = np.asarray(p, float)

    valid = np.isfinite(y) & np.isfinite(p)

    y = y[valid]
    p = p[valid]

    if not len(y):
        return {
            "n": 0,
            "MAE_N": np.nan,
            "RMSE_N": np.nan,
            "Mean_Error_N": np.nan,
            "MAPE_pct": np.nan,
            "R2": np.nan
        }

    nonzero = np.abs(y) > 1e-9

    mape = (
        np.mean(
            np.abs((p[nonzero] - y[nonzero]) / y[nonzero])
        ) * 100
        if nonzero.any()
        else np.nan
    )

    return {
        "n": len(y),
        "MAE_N": mean_absolute_error(y, p),
        "RMSE_N": mean_squared_error(y, p) ** 0.5,
        "Mean_Error_N": float(np.mean(p - y)),
        "MAPE_pct": mape,
        "R2": r2_score(y, p) if len(y) > 1 else np.nan
    }


# ============================================================
# 繪製散佈圖
# ============================================================

def scatter(y, p1, p2, title, filename):

    y = np.asarray(y, float)
    p1 = np.asarray(p1, float)
    p2 = np.asarray(p2, float)

    valid = (
        np.isfinite(y)
        & np.isfinite(p1)
        & np.isfinite(p2)
    )

    y = y[valid]
    p1 = p1[valid]
    p2 = p2[valid]

    if not len(y):
        return

    lo = min(y.min(), p1.min(), p2.min())
    hi = max(y.max(), p1.max(), p2.max())

    pad = (hi - lo) * 0.05 if hi > lo else 1

    plt.figure(figsize=(7.5, 7))

    plt.scatter(
        y, p1,
        alpha=0.72,
        label="With intercept"
    )

    plt.scatter(
        y, p2,
        alpha=0.72,
        label="Through origin"
    )

    plt.plot(
        [lo - pad, hi + pad],
        [lo - pad, hi + pad],
        "k--",
        label="Ideal: prediction = reference"
    )

    plt.xlabel("Reference force (N)")
    plt.ylabel("Predicted force (N)")
    plt.title(title)

    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()

    plt.savefig(filename, dpi=180)
    plt.close()


# ============================================================
# 主程式
# ============================================================

def main(out_dir):

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"找不到 {INPUT_FILE.resolve()}，"
            "請確認 foot_data.xlsx 是否與程式放在同一資料夾。"
        )

    # 建立校正線
    a_i, b_i, a_o, xw, yw, pwi, pwo = fit_lines()

    fit_summary = pd.DataFrame([
        {
            "method": "with_intercept",
            "equation": f"F_N = {a_i:.10f} * x + {b_i:.6f}",
            **metrics(yw, pwi)
        },
        {
            "method": "through_origin",
            "equation": f"F_N = {a_o:.10f} * x",
            **metrics(yw, pwo)
        }
    ])

    # 輸出砝碼校正資料
    pd.DataFrame({
        "raw_output": xw,
        "reference_force_N": yw,
        "pred_with_intercept_N": pwi,
        "pred_through_origin_N": pwo
    }).to_excel(
        out_dir / "weight_calibration_fit_points.xlsx",
        index=False
    )

    fit_summary.to_excel(
        out_dir / "weight_calibration_line_metrics.xlsx",
        index=False
    )

    # ========================================================
    # 讀取 Excel
    # ========================================================

    df = pd.read_excel(
        INPUT_FILE,
        header=HEADER_ROW
    )

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    # 檢查必要欄位
    required_columns = [
        CONDITION_COLUMN,
        REFERENCE_COLUMN,
        *LEFT_COLUMNS,
        *RIGHT_COLUMNS
    ]

    for c in required_columns:

        if c not in df.columns:

            raise KeyError(
                f"找不到欄位 {c!r}。\n"
                f"目前讀到的欄位：{list(df.columns)}。\n"
                "請確認 Excel 標題列及欄位名稱。"
            )

    # 將感測器數值轉成數字
    for c in [
        *LEFT_COLUMNS,
        *RIGHT_COLUMNS,
        REFERENCE_COLUMN
    ]:

        df[c] = pd.to_numeric(
            df[c].replace("-", np.nan),
            errors="coerce"
        )

    # 整理 condition
    df["_condition"] = (
        df[CONDITION_COLUMN]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    # 只保留 left 和 right
    df = df[
        df["_condition"].isin(["left", "right"])
    ].copy()

    all_metrics = []
    pooled = {}

    # 保留原始 foot_data 格式
    row_predictions = df.drop(
        columns=["_condition"],
        errors="ignore"
    ).copy()

    for cond, cols in [
        ("left", LEFT_COLUMNS),
        ("right", RIGHT_COLUMNS)
    ]:

        # 依照 condition 分類
        sub_all = df[df["_condition"] == cond].copy()

        # 只檢查該腳的 18 個感測器
        valid = (
            sub_all[REFERENCE_COLUMN].notna()
            & sub_all[cols].notna().all(axis=1)
        )

        sub = sub_all.loc[valid].copy()

        if sub.empty:
            print(f"警告：condition={cond!r} 沒有完整資料列，略過。")
            continue

        raw = sub[cols].to_numpy(float)

        # 兩種校正方式
        cal_i = np.where(raw == 0, 0, a_i * raw + b_i)
        cal_o = np.where(raw == 0, 0, a_o * raw)

        ref = sub[REFERENCE_COLUMN].to_numpy(float)

        # 原始值與校正後的18點加總
        raw_sum = raw.sum(axis=1)
        pred_i = cal_i.sum(axis=1)
        pred_o = cal_o.sum(axis=1)

        # 比較未校正及兩種校正方式
        for method, pred in [
            ("raw_uncalibrated_sensor_sum", raw_sum),
            ("with_intercept", pred_i),
            ("through_origin", pred_o)
        ]:
            all_metrics.append({
                "condition": cond,
                "method": method,
                **metrics(ref, pred)
            })

        pooled[cond] = (
            ref,
            raw_sum,
            pred_i,
            pred_o
        )

        # 將帶截距校正後的數值填回原始資料
        # left -> L1~L18
        # right -> R1~R18
        row_predictions.loc[sub.index, cols] = cal_i

        # 保留左右腳各自的散佈圖
        scatter(
            ref,
            pred_i,
            pred_o,
            f"{cond.title()} foot: two calibration lines",
            out_dir / f"{cond}_scatter_comparison.png"
        )

        print(
            f"{cond.upper()}：有效資料 {len(sub)} 筆，"
            f"校正值填入對應欄位。"
        )

    # 輸出合併後的 row_predictions.xlsx
    output_columns = [
        "trial",
        "category",
        "condition",
        "posture",
        "reference_force_N",
        "load_kg",
        *LEFT_COLUMNS,
        *RIGHT_COLUMNS
    ]

    row_predictions = row_predictions[output_columns]

    row_predictions.to_excel(
        out_dir / "row_predictions.xlsx",
        index=False
    )

    # 計算左右腳合併後的整體指標
    for method, idx in [
        ("raw_uncalibrated_sensor_sum", 1),
        ("with_intercept", 2),
        ("through_origin", 3)
    ]:

        ys = (
            np.concatenate([v[0] for v in pooled.values()])
            if pooled else np.array([])
        )

        ps = (
            np.concatenate([v[idx] for v in pooled.values()])
            if pooled else np.array([])
        )

        if len(ys):
            all_metrics.append({
                "condition": "overall",
                "method": method,
                **metrics(ys, ps)
            })

    metric_df = pd.DataFrame(all_metrics)

    metric_df.to_excel(
        out_dir / "foot_data_comparison_metrics.xlsx",
        index=False
    )

    print("\n=== 砝碼資料建立的兩條共同校正線 ===")
    print(f"帶截距：F(N) = {a_i:.10f} * x + {b_i:.6f}")
    print(f"通過原點：F(N) = {a_o:.10f} * x")

    print("\n砝碼校正線擬合指標：")
    print(fit_summary.to_string(index=False))

    print("\nfoot_data 比較指標：")
    print(metric_df.to_string(index=False))

    print(f"\n輸出資料夾：{out_dir.resolve()}")
    print("已輸出合併左右腳的 row_predictions.xlsx")


# ============================================================
# 執行
# ============================================================

if __name__ == "__main__":

    out = OUTPUT_ROOT / (
        f"run_{datetime.now():%Y%m%d_%H%M%S}"
    )

    out.mkdir(
        parents=True,
        exist_ok=True
    )

    main(out)