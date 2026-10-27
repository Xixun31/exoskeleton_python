"""
新受試者獨立驗證程式
用途：
1. 載入已訓練好的 left_linear_model.joblib / right_linear_model.joblib
   （新版訓練腳本存的是 dict：model + 特徵欄位資訊，不是裸模型）
2. 使用 new_data.xlsx 預測新受試者，不重新訓練
3. 計算 MAE、RMSE、R²、MAPE、平均偏差與逐筆百分比誤差
4. 輸出 Excel 報告
5. 輸出左右腳各自的「實際 vs 預測」散佈圖（PNG）

請將本程式、features.py、new_data.xlsx、left_linear_model.joblib、
right_linear_model.joblib 放在同一個資料夾。
（features.py 是訓練/驗證共用的特徵計算邏輯，一定要跟訓練時用的是同一份，
不要自己重寫一份，否則特徵算法兩邊兜不起來，預測會不準。）
"""

from pathlib import Path
from datetime import datetime
import warnings
import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import features as feat  # 共用特徵模組，必須跟訓練腳本用同一份

DATA_FILE = "new_data.xlsx"
LEFT_MODEL_FILE = "left_linear_model.joblib"
RIGHT_MODEL_FILE = "right_linear_model.joblib"
OUTPUT_FILE = "new_subject_validation_results.xlsx"
OUTPUT_ROOT = "validation_output"  # 驗證結果總資料夾；每次執行會建立獨立子資料夾

MODEL_FILES = {
    "left": LEFT_MODEL_FILE,
    "right": RIGHT_MODEL_FILE,
}


def calc_rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))

# ==============================
# 感測器負值處理
# ==============================

SENSOR_COLUMNS = (
    [f"L{i}" for i in range(1, 19)]
    + [f"R{i}" for i in range(1, 19)]
)

DEADBAND = 2.0
CLIP_ALL_NEGATIVE = False


def clean_sensor_data(df):
    df = df.copy()

    columns = [col for col in SENSOR_COLUMNS if col in df.columns]

    df[columns] = df[columns].apply(
        pd.to_numeric, errors="coerce"
    )

    if CLIP_ALL_NEGATIVE:
        # 所有負值都歸零
        df[columns] = df[columns].clip(lower=0)
    else:
        # 只將絕對值小於 2 的數值歸零
        df[columns] = df[columns].mask(
            df[columns].abs() < DEADBAND, 0
        )

    return df


def plot_actual_vs_predicted(y, pred, condition, out_dir, posture=None):
    """
    畫單一 condition（或指定 posture 子集）的「參考值 vs 預測值」散佈圖，
    附上 y=x 理想線，存成 PNG。
    """
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y, pred, alpha=0.75)
    lo = float(min(y.min(), pred.min()))
    hi = float(max(y.max(), pred.max()))
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    ax.plot([lo, hi], [lo, hi], "--", label="Ideal: predicted = reference")
    title = f"{condition}: Reference vs Predicted (new subject)"
    if posture is not None:
        title += f" — {posture}"
    ax.set(xlabel="Reference force (N)", ylabel="Predicted force (N)", title=title)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()

    fname = f"{condition}_actual_vs_predicted"
    if posture is not None:
        safe_posture = str(posture).replace("/", "_").replace("\\", "_")
        fname += f"_{safe_posture}"
    fig.savefig(out_dir / f"{fname}.png", dpi=160)
    plt.close(fig)


# ==============================
# 以下接原本的程式
# ==============================
def main():
    base = Path(__file__).resolve().parent
    data_path = base / DATA_FILE

    # 每次驗證建立一個獨立的時間戳記資料夾，避免覆蓋先前結果。
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base / OUTPUT_ROOT / f"validation_run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    output_path = run_dir / f"new_subject_validation_results_{timestamp}.xlsx"

    if not data_path.exists():
        raise FileNotFoundError(
            f"找不到 {DATA_FILE}。請把資料檔放在程式同一資料夾，"
            "或修改程式上方的 DATA_FILE。"
        )

    df = pd.read_excel(data_path, header=0)
    df = clean_sensor_data(df)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"condition", "reference_force_N"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"資料缺少欄位：{sorted(missing)}。"
            f"目前欄位：{df.columns.tolist()}"
        )

    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["reference_force_N"] = pd.to_numeric(
        df["reference_force_N"], errors="coerce"
    )

    predictions = []
    summaries = []
    posture_summaries = []

    for condition in ["left", "right"]:
        model_path = base / MODEL_FILES[condition]
        if not model_path.exists():
            raise FileNotFoundError(
                f"找不到模型檔 {MODEL_FILES[condition]}。"
                "請確認模型檔與程式在同一資料夾。"
            )

        bundle = joblib.load(model_path)
        # 新版訓練腳本存的是 dict；若不小心載到舊版裸模型檔會在這裡直接報錯，
        # 提醒你要用新版訓練腳本重新訓練、或換回舊版驗證腳本。
        if not isinstance(bundle, dict) or "model" not in bundle:
            raise TypeError(
                f"{MODEL_FILES[condition]} 看起來是舊版格式（裸模型，不是 dict）。"
                "請用新版 regression_condition_linear.py 重新訓練產生模型檔。"
            )

        model = bundle["model"]
        raw_cols = bundle["raw_feature_names"]
        engineered_cols = bundle["engineered_feature_names"]
        all_cols = bundle["all_feature_names"]

        missing_features = [c for c in raw_cols if c not in df.columns]
        if missing_features:
            raise ValueError(
                f"資料缺少 {condition} 模型需要的感測器欄位："
                f"{missing_features}"
            )

        subset = df[df["condition"] == condition].copy()
        if subset.empty:
            warnings.warn(f"沒有 condition='{condition}' 的資料，略過。")
            continue

        for col in raw_cols:
            subset[col] = pd.to_numeric(subset[col], errors="coerce")

        valid = subset[raw_cols + ["reference_force_N"]].notna().all(axis=1)
        dropped = int((~valid).sum())
        subset = subset.loc[valid].copy()
        if subset.empty:
            warnings.warn(f"{condition} 沒有完整有效資料，略過。")
            continue

        # ---- 用跟訓練時同一份 features.py，算出同一組連續特徵 ----
        engineered = feat.build_engineered_frame(subset, raw_cols, condition)
        n_before = len(subset)
        subset = pd.concat([subset, engineered], axis=1)
        subset = subset.dropna(subset=engineered_cols)
        n_dropped_by_feat = n_before - len(subset)
        if n_dropped_by_feat:
            warnings.warn(
                f"{condition} 有 {n_dropped_by_feat} 筆資料算姿態特徵時出現 nan"
                "（通常是18點讀值全部<=0），已從驗證集排除。"
            )
        if subset.empty:
            warnings.warn(f"{condition} 算完特徵後沒有可用資料，略過。")
            continue

        X = subset[all_cols].astype(float)
        y = subset["reference_force_N"].astype(float).to_numpy()

        # 只做預測，不呼叫 fit，不重新訓練模型。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = np.asarray(model.predict(X), dtype=float)

        # ---- 畫這個 condition 整體的「參考值 vs 預測值」散佈圖 ----
        plot_actual_vs_predicted(y, pred, condition, run_dir)

        error = pred - y
        abs_error = np.abs(error)
        abs_pct_error = np.full(len(y), np.nan, dtype=float)
        nonzero = np.abs(y) > 1e-12
        abs_pct_error[nonzero] = abs_error[nonzero] / np.abs(y[nonzero]) * 100
        signed_pct_error = np.full(len(y), np.nan, dtype=float)
        signed_pct_error[nonzero] = error[nonzero] / np.abs(y[nonzero]) * 100

        subset["model_used"] = f"{condition}_linear_model"
        subset["predicted_force_N"] = pred
        subset["error_N_pred_minus_reference"] = error
        subset["absolute_error_N"] = abs_error
        subset["signed_percentage_error_pct"] = signed_pct_error
        subset["absolute_percentage_error_pct"] = abs_pct_error
        predictions.append(subset)

        denom = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - np.sum(error ** 2) / denom if denom > 0 else np.nan
        valid_pct = abs_pct_error[np.isfinite(abs_pct_error)]

        summaries.append({
            "condition": condition,
            "n_valid": len(y),
            "n_rows_dropped_missing": dropped + n_dropped_by_feat,
            "MAE_N": mean_absolute_error(y, pred),
            "RMSE_N": calc_rmse(y, pred),
            "mean_error_N_pred_minus_reference": float(np.mean(error)),
            "R2": r2,
            "MAPE_pct": float(np.mean(valid_pct)) if len(valid_pct) else np.nan,
            "P95_absolute_percentage_error_pct": (
                float(np.percentile(valid_pct, 95)) if len(valid_pct) else np.nan
            ),
            "max_absolute_percentage_error_pct": (
                float(np.max(valid_pct)) if len(valid_pct) else np.nan
            ),
            "note": "MAPE 是新受試者獨立驗證；不是訓練誤差或 LOOCV。"
        })

        # 若驗證集這個 condition 剛好少了某個訓練時出現過的 posture（例如你說的
        # 拿重量情境少一種姿態），這裡就只會列出驗證集實際有的 posture，
        # 不需要額外處理，groupby 本來就只會列出有資料的類別。
        if "posture" in subset.columns:
            for posture, group in subset.groupby("posture", dropna=False):
                pct = pd.to_numeric(
                    group["absolute_percentage_error_pct"], errors="coerce"
                ).dropna()
                e = group["error_N_pred_minus_reference"].to_numpy()
                posture_summaries.append({
                    "condition": condition,
                    "posture": str(posture),
                    "n_samples": len(group),
                    "MAE_N": float(np.mean(np.abs(e))),
                    "RMSE_N": float(np.sqrt(np.mean(e ** 2))),
                    "mean_error_N": float(np.mean(e)),
                    "MAPE_pct": float(pct.mean()) if len(pct) else np.nan,
                    "max_absolute_error_N": float(np.max(np.abs(e))),
                })

    if not summaries:
        raise ValueError(
            "沒有成功完成驗證。請檢查 condition 是否使用 left / right，"
            "以及資料欄位是否正確。"
        )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(summaries).to_excel(
            writer, sheet_name="overall_summary", index=False
        )
        if posture_summaries:
            pd.DataFrame(posture_summaries).to_excel(
                writer, sheet_name="posture_summary", index=False
            )
        pd.concat(predictions, ignore_index=True).to_excel(
            writer, sheet_name="row_predictions", index=False
        )

        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for cells in ws.columns:
                max_len = max(
                    (len(str(cell.value)) if cell.value is not None else 0)
                    for cell in cells[:150]
                )
                ws.column_dimensions[cells[0].column_letter].width = min(
                    max(max_len + 2, 12), 36
                )

    print("\n=== 新受試者獨立驗證結果 ===")
    for row in summaries:
        print(f"\n條件：{row['condition']}")
        print(f"有效筆數：{row['n_valid']}")
        print(f"MAE：{row['MAE_N']:.2f} N")
        print(f"RMSE：{row['RMSE_N']:.2f} N")
        print(f"平均偏差（預測-參考）：{row['mean_error_N_pred_minus_reference']:.2f} N")
        print(f"R²：{row['R2']:.4f}")
        print(f"MAPE：{row['MAPE_pct']:.2f}%")
        print(f"絕對百分比誤差第 95 百分位：{row['P95_absolute_percentage_error_pct']:.2f}%")
        print(f"最大絕對百分比誤差：{row['max_absolute_percentage_error_pct']:.2f}%")

    print(f"\n完整報告已輸出：{output_path}")
    print(f"散佈圖（{', '.join(MODEL_FILES.keys())} 各一張 actual_vs_predicted.png）"
          f"也存在：{run_dir}")
    print("報告工作表：overall_summary、posture_summary、row_predictions")


if __name__ == "__main__":
    main()