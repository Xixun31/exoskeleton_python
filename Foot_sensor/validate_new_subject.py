"""
新受試者獨立驗證程式
用途：
1. 載入已訓練好的 left_linear_model.joblib / right_linear_model.joblib
2. 使用 new_data.xlsx 預測新受試者，不重新訓練
3. 計算 MAE、RMSE、R²、MAPE、平均偏差與逐筆百分比誤差
4. 輸出 Excel 報告

請將本程式、new_data.xlsx、left_linear_model.joblib、
right_linear_model.joblib 放在同一個資料夾。
"""

from pathlib import Path
import warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

DATA_FILE = "new_data.xlsx"
LEFT_MODEL_FILE = "left_linear_model.joblib"
RIGHT_MODEL_FILE = "right_linear_model.joblib"
OUTPUT_FILE = "new_subject_validation_results.xlsx"

FEATURES = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
}
MODEL_FILES = {
    "left": LEFT_MODEL_FILE,
    "right": RIGHT_MODEL_FILE,
}


def calc_rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def main():
    base = Path(__file__).resolve().parent
    data_path = base / DATA_FILE
    output_path = base / OUTPUT_FILE

    if not data_path.exists():
        raise FileNotFoundError(
            f"找不到 {DATA_FILE}。請把資料檔放在程式同一資料夾，"
            "或修改程式上方的 DATA_FILE。"
        )

    df = pd.read_excel(data_path, header=0)
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

        features = FEATURES[condition]
        missing_features = [c for c in features if c not in df.columns]
        if missing_features:
            raise ValueError(
                f"資料缺少 {condition} 模型需要的感測器欄位："
                f"{missing_features}"
            )

        subset = df[df["condition"] == condition].copy()
        if subset.empty:
            warnings.warn(f"沒有 condition='{condition}' 的資料，略過。")
            continue

        for col in features:
            subset[col] = pd.to_numeric(subset[col], errors="coerce")

        valid = subset[features + ["reference_force_N"]].notna().all(axis=1)
        dropped = int((~valid).sum())
        subset = subset.loc[valid].copy()
        if subset.empty:
            warnings.warn(f"{condition} 沒有完整有效資料，略過。")
            continue

        model = joblib.load(model_path)
        X = subset[features].astype(float)
        y = subset["reference_force_N"].astype(float).to_numpy()

        # 只做預測，不呼叫 fit，不重新訓練模型。
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pred = np.asarray(model.predict(X), dtype=float)

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
            "n_rows_dropped_missing": dropped,
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
    print("報告工作表：overall_summary、posture_summary、row_predictions")


if __name__ == "__main__":
    main()
