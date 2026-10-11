"""
普通線性迴歸（OLS）診斷版：依 condition 訓練 left / right / both。
每次執行建立獨立資料夾，不覆蓋前次結果；輸出訓練預測、LOOCV 預測、
三種診斷圖、各 posture 的交叉驗證誤差統計、係數表及模型檔。
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
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict

INPUT_FILE = "foot_data.xlsx"
OUTPUT_BASE_DIR = "regression_output_linear"
READ_HEADER_ROW = 1  # Excel 第 1 列是說明文字，第 2 列是欄位名稱

SENSOR_COLS = [f"L{i}" for i in range(1, 19)] + [f"R{i}" for i in range(1, 19)]
CONDITIONS = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
    "both": SENSOR_COLS,
}

def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))

def main():
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        raise FileNotFoundError(
            f"找不到資料檔：{input_path.resolve()}，請修改 INPUT_FILE。"
        )
    df = pd.read_excel(input_path, header=READ_HEADER_ROW)
    df.columns = [str(c).strip() for c in df.columns]
    missing = {"condition", "reference_force_N"} - set(df.columns)
    if missing:
        raise ValueError(
            f"缺少欄位 {sorted(missing)}；目前讀到：{list(df.columns)}。"
            "請確認 Excel 第 2 列是否為真正欄位名稱。"
        )

    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["reference_force_N"] = pd.to_numeric(df["reference_force_N"], errors="coerce")
    for col in SENSOR_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    root = Path(OUTPUT_BASE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = root / f"run_{stamp}"
    suffix = 1
    while out_dir.exists():
        out_dir = root / f"run_{stamp}_{suffix}"
        suffix += 1
    out_dir.mkdir(parents=True)

    summaries, predictions, coefficients, posture_summaries = [], [], [], []

    for condition, features in CONDITIONS.items():
        cdf = df[df["condition"] == condition].copy()
        if cdf.empty:
            warnings.warn(f"condition='{condition}' 沒有資料，略過。")
            continue
        missing_features = [c for c in features if c not in cdf.columns]
        if missing_features:
            warnings.warn(f"{condition} 缺少欄位 {missing_features}，略過。")
            continue

        valid = cdf[features + ["reference_force_N"]].notna().all(axis=1)
        data = cdf.loc[valid].copy()
        dropped = len(cdf) - len(data)
        if len(data) < 2:
            warnings.warn(f"{condition} 有效資料不足 2 筆，略過。")
            continue

        X = data[features].astype(float)
        y = data["reference_force_N"].astype(float)
        model = LinearRegression()
        model.fit(X, y)
        train_pred = model.predict(X)

        cv_pred = np.full(len(data), np.nan)
        cv_mae = cv_rmse = cv_r2 = np.nan
        if len(data) >= 5:
            try:
                cv_pred = cross_val_predict(LinearRegression(), X, y, cv=LeaveOneOut())
                cv_mae = mean_absolute_error(y, cv_pred)
                cv_rmse = rmse(y, cv_pred)
                cv_r2 = r2_score(y, cv_pred)
            except Exception as exc:
                warnings.warn(f"{condition} LOOCV 失敗：{exc}")

        summaries.append({
            "condition": condition, "model": "LinearRegression (OLS)",
            "n_rows_in_condition": len(cdf), "n_valid_rows": len(data),
            "n_dropped_rows": dropped, "n_features": len(features),
            "train_MAE_N": mean_absolute_error(y, train_pred),
            "train_RMSE_N": rmse(y, train_pred), "train_R2": r2_score(y, train_pred),
            "LOOCV_MAE_N": cv_mae, "LOOCV_RMSE_N": cv_rmse, "LOOCV_R2": cv_r2,
        })

        result = data.copy()
        result["condition_model"] = condition
        result["predicted_force_N"] = train_pred
        result["training_error_N"] = train_pred - y.to_numpy()
        result["cv_predicted_force_N"] = cv_pred
        result["cv_error_N"] = cv_pred - y.to_numpy()
        result["cv_absolute_error_N"] = np.abs(result["cv_error_N"])
        predictions.append(result)

        coef = pd.DataFrame({"feature": features, "coefficient": model.coef_})
        coef.loc[len(coef)] = ["intercept", model.intercept_]
        coef["condition_model"] = condition
        coefficients.append(coef)
        joblib.dump(model, out_dir / f"{condition}_linear_model.joblib")

        if len(data) >= 5 and np.isfinite(cv_pred).all():
            residual = cv_pred - y.to_numpy()

            fig, ax = plt.subplots(figsize=(7, 6))
            ax.scatter(y, cv_pred, alpha=0.75)
            lo, hi = float(min(y.min(), cv_pred.min())), float(max(y.max(), cv_pred.max()))
            if lo == hi:
                lo, hi = lo - 1, hi + 1
            ax.plot([lo, hi], [lo, hi], "--", label="Ideal: y = x")
            ax.set(xlabel="Reference force (N)", ylabel="Cross-validated predicted force (N)",
                   title=f"{condition}: Actual vs CV-predicted")
            ax.legend(); ax.grid(True, alpha=0.25); fig.tight_layout()
            fig.savefig(out_dir / f"{condition}_actual_vs_cv_predicted.png", dpi=160)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(7, 5))
            ax.scatter(cv_pred, residual, alpha=0.75)
            ax.axhline(0, linestyle="--")
            ax.set(xlabel="Cross-validated predicted force (N)",
                   ylabel="Residual: predicted - reference (N)",
                   title=f"{condition}: Residual plot")
            ax.grid(True, alpha=0.25); fig.tight_layout()
            fig.savefig(out_dir / f"{condition}_residual_plot.png", dpi=160)
            plt.close(fig)

            fig, ax = plt.subplots(figsize=(7, 5))
            ax.hist(np.abs(residual), bins="auto", edgecolor="black")
            ax.set(xlabel="Absolute cross-validated error (N)", ylabel="Number of samples",
                   title=f"{condition}: Absolute error distribution")
            ax.grid(True, axis="y", alpha=0.25); fig.tight_layout()
            fig.savefig(out_dir / f"{condition}_cv_absolute_error_histogram.png", dpi=160)
            plt.close(fig)

            if "posture" in result.columns:
                temp = result.copy()
                temp["posture"] = temp["posture"].fillna("unknown").astype(str)
                for posture, group in temp.groupby("posture", dropna=False):
                    errors = group["cv_error_N"].dropna()
                    if len(errors):
                        posture_summaries.append({
                            "condition": condition, "posture": posture, "n_samples": len(errors),
                            "CV_MAE_N": float(errors.abs().mean()),
                            "CV_RMSE_N": float(np.sqrt(np.mean(errors ** 2))),
                            "CV_mean_error_N": float(errors.mean()),
                        })

        print(f"[{condition}] n={len(data)}; train R2={r2_score(y, train_pred):.4f}; "
              f"LOOCV MAE={cv_mae:.3f} N; LOOCV RMSE={cv_rmse:.3f} N; LOOCV R2={cv_r2:.4f}")

    if not summaries:
        raise ValueError("沒有模型成功訓練，請檢查 condition、欄位名稱和有效資料。")

    pd.DataFrame(summaries).to_excel(out_dir / "linear_model_summary.xlsx", index=False)
    pd.concat(predictions, ignore_index=True).to_excel(out_dir / "linear_predictions_with_cv.xlsx", index=False)
    pd.concat(coefficients, ignore_index=True).to_excel(out_dir / "linear_coefficients.xlsx", index=False)
    if posture_summaries:
        pd.DataFrame(posture_summaries).to_excel(out_dir / "posture_cv_error_summary.xlsx", index=False)

    print(f"\n本次結果資料夾：{out_dir.resolve()}")
    print("每次執行都會建立新的 run_時間戳資料夾，不會覆蓋前次結果。")

if __name__ == "__main__":
    main()
