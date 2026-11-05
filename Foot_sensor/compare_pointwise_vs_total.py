"""
比較三種模型設計，看「18點各自獨立權重」是不是真的比「先加總再套單一權重」
更好，還是只是在訓練集裡擬合雜訊：

  變體 A（目前的做法）：y = sum_i(w_i * P_i) + b + 6個工程特徵
                        → 24個參數
  變體 B（你提議的做法）：y = w * (sum of 18 points) + b
                        → 只有2個參數，完全不看姿態分佈
  變體 C（折衷）        ：y = w * (sum of 18 points) + b + 6個工程特徵
                        → 約7個參數，只用一個全局權重修正總和，
                          但保留COP等姿態相關資訊

三者都用同一份 foot_data.xlsx、同樣的 train / LOOCV 流程，輸出一張比較表。
注意：train 誤差 A 理論上一定 <= B/C（A的自由度最高），這是數學上必然的，
不能用 train 誤差判斷誰好；要看 LOOCV（更準確的話，看對新受試者的驗證表現）
哪個模型比較不會隨著資料集改變而晃動、誰的誤差比較低，才是真正該比較的依據。

這支腳本只是用來「比較、做決策」，不會輸出正式要拿去部署的 .joblib，
確定要用哪個變體之後，再回頭跟我說，我幫你把選定的版本接回正式的訓練/驗證流程。
"""
from pathlib import Path
from datetime import datetime
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import LeaveOneOut, cross_val_predict

import features as feat  # 共用特徵模組

INPUT_FILE = "foot_data.xlsx"
READ_HEADER_ROW = 1
OUTPUT_BASE_DIR = "model_comparison_output"  # 輸出總資料夾；每次執行建立獨立子資料夾
OUTPUT_FILE = "model_comparison_pointwise_vs_total.xlsx"

CONDITIONS = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
}

SENSOR_COLUMNS = (
    [f"L{i}" for i in range(1, 19)]
    + [f"R{i}" for i in range(1, 19)]
)
DEADBAND = 2.0
CLIP_ALL_NEGATIVE = False


def clean_sensor_data(df):
    df = df.copy()
    columns = [c for c in SENSOR_COLUMNS if c in df.columns]
    df[columns] = df[columns].apply(pd.to_numeric, errors="coerce")
    if CLIP_ALL_NEGATIVE:
        df[columns] = df[columns].clip(lower=0)
    else:
        df[columns] = df[columns].mask(df[columns].abs() < DEADBAND, 0)
    return df


def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def plot_reference_vs_predicted(y, pred, condition, variant, out_dir, kind):
    """
    kind: 'train' 或 'loocv'，決定圖的標題跟檔名，畫參考值 vs 預測值散佈圖。
    """
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y, pred, alpha=0.75)
    lo = float(min(np.min(y), np.min(pred)))
    hi = float(max(np.max(y), np.max(pred)))
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    ax.plot([lo, hi], [lo, hi], "--", label="Ideal: predicted = reference")
    kind_label = "Train" if kind == "train" else "LOOCV"
    ax.set(xlabel="Reference force (N)", ylabel=f"{kind_label} predicted force (N)",
           title=f"{condition} / {variant}: Reference vs {kind_label} predicted")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    safe_variant = variant.replace(" ", "").replace("+", "_")
    fig.savefig(out_dir / f"{condition}_{safe_variant}_{kind}_actual_vs_predicted.png", dpi=160)
    plt.close(fig)


def fit_and_eval(X, y, condition, label, out_dir):
    model = LinearRegression()
    model.fit(X, y)
    train_pred = model.predict(X)
    plot_reference_vs_predicted(y.to_numpy(), train_pred, condition, label, out_dir, "train")

    cv_mae = cv_rmse = cv_r2 = np.nan
    if len(y) >= 5:
        try:
            cv_pred = cross_val_predict(LinearRegression(), X, y, cv=LeaveOneOut())
            cv_mae = mean_absolute_error(y, cv_pred)
            cv_rmse = rmse(y, cv_pred)
            cv_r2 = r2_score(y, cv_pred)
            plot_reference_vs_predicted(y.to_numpy(), cv_pred, condition, label, out_dir, "loocv")
        except Exception as exc:
            warnings.warn(f"{label} LOOCV 失敗：{exc}")

    return {
        "variant": label,
        "n_features": X.shape[1],
        "train_MAE_N": mean_absolute_error(y, train_pred),
        "train_RMSE_N": rmse(y, train_pred),
        "train_R2": r2_score(y, train_pred),
        "LOOCV_MAE_N": cv_mae,
        "LOOCV_RMSE_N": cv_rmse,
        "LOOCV_R2": cv_r2,
    }


def main():
    path = Path(INPUT_FILE)
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path.resolve()}，請修改 INPUT_FILE。")

    df = pd.read_excel(path, header=READ_HEADER_ROW)
    df = clean_sensor_data(df)
    df.columns = [str(c).strip() for c in df.columns]
    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["reference_force_N"] = pd.to_numeric(df["reference_force_N"], errors="coerce")

    root = Path(OUTPUT_BASE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = root / f"comparison_run_{stamp}"
    suffix = 1
    while out_dir.exists():
        out_dir = root / f"comparison_run_{stamp}_{suffix}"
        suffix += 1
    out_dir.mkdir(parents=True)

    results = []

    for condition, raw_cols in CONDITIONS.items():
        cdf = df[df["condition"] == condition].copy()
        if cdf.empty:
            warnings.warn(f"{condition} 沒有資料，略過。")
            continue

        for col in raw_cols:
            cdf[col] = pd.to_numeric(cdf[col], errors="coerce")

        valid = cdf[raw_cols + ["reference_force_N"]].notna().all(axis=1)
        data = cdf.loc[valid].copy()
        if len(data) < 2:
            warnings.warn(f"{condition} 有效資料不足，略過。")
            continue

        engineered = feat.build_engineered_frame(data, raw_cols, condition)
        data = pd.concat([data, engineered], axis=1)
        data = data.dropna(subset=feat.ENGINEERED_FEATURE_NAMES)
        if data.empty:
            warnings.warn(f"{condition} 算完特徵後沒有可用資料，略過。")
            continue

        data["Total"] = data[raw_cols].sum(axis=1)

        y = data["reference_force_N"].astype(float)

        # 變體 A：18點各自獨立權重 + 工程特徵（目前的正式做法）
        X_A = data[raw_cols + feat.ENGINEERED_FEATURE_NAMES].astype(float)
        results.append({"condition": condition, **fit_and_eval(X_A, y, condition, "A_pointwise_18 + engineered", out_dir)})

        # 變體 B：純粹先加總，只有1個全局權重，完全不看分佈
        X_B = data[["Total"]].astype(float)
        results.append({"condition": condition, **fit_and_eval(X_B, y, condition, "B_total_only", out_dir)})

        # 變體 C：先加總 + 工程特徵（折衷版本）
        X_C = data[["Total"] + feat.ENGINEERED_FEATURE_NAMES].astype(float)
        results.append({"condition": condition, **fit_and_eval(X_C, y, condition, "C_total + engineered", out_dir)})

    if not results:
        raise ValueError("沒有任何模型成功訓練，請檢查資料。")

    result_df = pd.DataFrame(results)
    result_df = result_df[[
        "condition", "variant", "n_features",
        "train_MAE_N", "train_RMSE_N", "train_R2",
        "LOOCV_MAE_N", "LOOCV_RMSE_N", "LOOCV_R2",
    ]]
    output_path = out_dir / OUTPUT_FILE
    result_df.to_excel(output_path, index=False)

    print("\n=== 三種模型設計比較（train 一定 A<=B/C 很正常，重點看 LOOCV）===")
    for _, row in result_df.iterrows():
        print(f"[{row['condition']}] {row['variant']} (features={row['n_features']}): "
              f"train MAE={row['train_MAE_N']:.2f}N R2={row['train_R2']:.3f} | "
              f"LOOCV MAE={row['LOOCV_MAE_N']:.2f}N RMSE={row['LOOCV_RMSE_N']:.2f}N R2={row['LOOCV_R2']:.3f}")

    print(f"\n完整比較表與散佈圖都在這個資料夾：{out_dir.resolve()}")
    print("每個 condition x 變體 都有兩張圖：*_train_actual_vs_predicted.png（訓練擬合）、"
          "*_loocv_actual_vs_predicted.png（交叉驗證，比較模型好壞看這張）。")


if __name__ == "__main__":
    main()
