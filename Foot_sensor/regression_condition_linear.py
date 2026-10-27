"""
普通線性迴歸（OLS）訓練版：只依 condition 訓練 left / right。
每次執行建立獨立資料夾，不覆蓋前次結果；輸出訓練預測、LOOCV 預測、
三種診斷圖、各 posture 的交叉驗證誤差統計、係數表及模型檔。
注意：這是訓練程式，不是用獨立新受測者資料做驗證的 validate_new_subject.py。

=== 這版多做的事（方案B的延伸：連續的姿態相關特徵） ===
除了原本的18個原始感測點讀值，額外加入從同一組讀值算出來的連續特徵
（COP_x, COP_y, active_count, std, front_back_ratio, medial_lateral_ratio），
取代原本討論中「每個姿態一個 one-hot 類別」的作法，理由是：
  1. 這些特徵是單腳自己18點就能算出來的，不需要知道「現在是哪個姿態」這個
     標籤，未來系統實際運作時（不知道使用者當下姿態）也一樣能算。
  2. 對沒在訓練集出現過的新姿態也能合理外推，不會像 one-hot 遇到新類別
     完全沒輒。
特徵計算邏輯全部寫在 features.py，這支腳本跟未來的驗證腳本都共用同一份，
避免訓練/推論兩邊特徵算法兜不起來。
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

import features as feat  # 共用特徵模組，跟驗證腳本要 import 同一份

INPUT_FILE = "foot_data.xlsx"
OUTPUT_BASE_DIR = "regression_output_linear_training"
READ_HEADER_ROW = 1  # Excel 第 1 列是說明文字，第 2 列是欄位名稱

SENSOR_COLS = [f"L{i}" for i in range(1, 19)] + [f"R{i}" for i in range(1, 19)]
CONDITIONS = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
}

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


# ==============================
# 以下接原本的程式
# ==============================

def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))

def main():
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        raise FileNotFoundError(
            f"找不到資料檔：{input_path.resolve()}，請修改 INPUT_FILE。"
        )
    df = pd.read_excel(input_path, header=READ_HEADER_ROW)
    df = clean_sensor_data(df)
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
    out_dir = root / f"training_run_{stamp}"
    suffix = 1
    while out_dir.exists():
        out_dir = root / f"training_run_{stamp}_{suffix}"
        suffix += 1
    out_dir.mkdir(parents=True)

    summaries, predictions, coefficients, posture_summaries = [], [], [], []

    for condition, raw_features in CONDITIONS.items():
        cdf = df[df["condition"] == condition].copy()
        if cdf.empty:
            warnings.warn(f"condition='{condition}' 沒有資料，略過。")
            continue
        missing_features = [c for c in raw_features if c not in cdf.columns]
        if missing_features:
            warnings.warn(f"{condition} 缺少欄位 {missing_features}，略過。")
            continue

        valid = cdf[raw_features + ["reference_force_N"]].notna().all(axis=1)
        data = cdf.loc[valid].copy()
        dropped = len(cdf) - len(data)
        if len(data) < 2:
            warnings.warn(f"{condition} 有效資料不足 2 筆，略過。")
            continue

        # ---- 新增：算連續的姿態相關特徵，併到原始18點後面 ----
        engineered = feat.build_engineered_frame(data, raw_features, condition)
        n_before = len(data)
        data = pd.concat([data, engineered], axis=1)
        # COP 等特徵在「這隻腳完全沒受力」時會是 nan（理論上不太該發生在這組
        # condition 篩選過的資料裡，但保險起見還是濾掉，並印出來讓你知道）
        data = data.dropna(subset=feat.ENGINEERED_FEATURE_NAMES)
        n_dropped_by_feat = n_before - len(data)
        if n_dropped_by_feat:
            warnings.warn(
                f"{condition} 有 {n_dropped_by_feat} 筆資料在算姿態特徵時出現 nan"
                "（通常代表18點讀值全部<=0），已從訓練集排除，請檢查這幾筆原始資料。"
            )

        features = raw_features + feat.ENGINEERED_FEATURE_NAMES

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
            "condition": condition, "model": "LinearRegression (OLS) + engineered features",
            "n_rows_in_condition": len(cdf), "n_valid_rows": len(data),
            "n_dropped_rows": dropped + n_dropped_by_feat, "n_features": len(features),
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

        # ---- 模型檔打包成 dict，連同算特徵需要的資訊一起存，不要只存裸模型 ----
        # 驗證腳本/未來的推論程式載入時，要用同一個 features.py 重新算一次
        # engineered 特徵，再把 raw_features + engineered 依這裡存的順序組成
        # X 丟進 model.predict()。
        bundle = {
            "model": model,
            "condition": condition,
            "raw_feature_names": raw_features,
            "engineered_feature_names": feat.ENGINEERED_FEATURE_NAMES,
            "all_feature_names": features,  # X 欄位順序，predict 前要照這個順序排
            "deadband": DEADBAND,
            "clip_all_negative": CLIP_ALL_NEGATIVE,
            "trained_at": stamp,
        }
        joblib.dump(bundle, out_dir / f"{condition}_linear_model.joblib")

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

        print(f"[{condition}] n={len(data)}; features={len(features)}; "
              f"train R2={r2_score(y, train_pred):.4f}; "
              f"LOOCV MAE={cv_mae:.3f} N; LOOCV RMSE={cv_rmse:.3f} N; LOOCV R2={cv_r2:.4f}")

    if not summaries:
        raise ValueError("沒有模型成功訓練，請檢查 condition、欄位名稱和有效資料。")

    pd.DataFrame(summaries).to_excel(out_dir / "linear_model_summary.xlsx", index=False)
    pd.concat(predictions, ignore_index=True).to_excel(out_dir / "linear_predictions_with_cv.xlsx", index=False)
    pd.concat(coefficients, ignore_index=True).to_excel(out_dir / "linear_coefficients.xlsx", index=False)
    if posture_summaries:
        pd.DataFrame(posture_summaries).to_excel(out_dir / "posture_cv_error_summary.xlsx", index=False)

    print(f"\n本次結果資料夾：{out_dir.resolve()}")
    print("這是【訓練版】結果；每次執行都會建立新的 training_run_時間戳資料夾，不會覆蓋前次結果。")

if __name__ == "__main__":
    main()