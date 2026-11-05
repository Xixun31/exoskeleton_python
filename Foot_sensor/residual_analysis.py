"""
殘差分析：找出模型（預設是 C 變體：Total + 6個工程特徵）的誤差跟什麼有關。

殘差 = 預測值 - 參考值（正 = 高估，負 = 低估），跟 validate_new_subject.py 同方向。

做兩件事：
  1. 訓練資料：用 LOOCV 預測值算殘差（比訓練擬合值誠實，不會被過擬合蓋掉）。
  2. （可選）驗證資料：如果同資料夾有 new_data.xlsx 跟模型檔，也分析驗證殘差。

輸出（每次執行建立獨立資料夾）：
  - residual_vs_<變數>.png ：殘差對各個變數的散佈圖，圖上標示相關係數與趨勢線
  - residual_by_posture.png：各姿態的殘差箱形圖
  - residual_summary.xlsx  ：相關係數表、各姿態殘差統計、殘差最大的前幾筆資料

請把本程式、features.py、foot_data.xlsx 放同一資料夾。
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
from sklearn.model_selection import LeaveOneOut, cross_val_predict

import features as feat

# ---------- 設定 ----------
TRAIN_FILE = "foot_data.xlsx"
TRAIN_HEADER_ROW = 1          # foot_data.xlsx：第2列才是欄位名稱
# 如果要分析砝碼校正後的檔案（例如 row_predictions 那種欄位名稱在第1列的檔案），
# 改成 TRAIN_FILE = "你的檔名.xlsx"、TRAIN_HEADER_ROW = 0，
# 並且一次只分析一份，輸出資料夾是依時間戳分開的，不會互相覆蓋。

VALID_FILE = "new_data.xlsx"  # 沒有這個檔就自動略過驗證資料分析
VALID_HEADER_ROW = 0
# 驗證資料要用哪個模型檔（要跟 validate_new_subject.py 設定一致）
VALID_MODEL_FILES = {
    "left": "left_C_total_engineered_linear_model.joblib",
    "right": "right_C_total_engineered_linear_model.joblib",
}

OUTPUT_BASE_DIR = "residual_analysis_output"
FIT_INTERCEPT = True          # 訓練資料分析用的模型設定
TOP_N_WORST = 10              # 每個 condition 列出殘差最大的幾筆

CONDITIONS = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
}
SENSOR_COLUMNS = CONDITIONS["left"] + CONDITIONS["right"]
DEADBAND = 2.0

plt.rcParams["font.sans-serif"] = [
    "Microsoft JhengHei", "Noto Sans CJK TC", "PingFang TC", "Arial Unicode MS", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def clean_sensor_data(df):
    df = df.copy()
    cols = [c for c in SENSOR_COLUMNS if c in df.columns]
    df[cols] = df[cols].apply(pd.to_numeric, errors="coerce")
    df[cols] = df[cols].mask(df[cols].abs() < DEADBAND, 0)
    return df


DERIVED_COLUMNS = feat.ENGINEERED_FEATURE_NAMES + [
    "Total", "n_zero_points", "max_point_share", "predicted_N", "residual_N",
    "model_used", "predicted_force_N", "error_N_pred_minus_reference", "absolute_error_N",
    "signed_percentage_error_pct", "absolute_percentage_error_pct", "variant",
]


def drop_derived(df):
    """
    如果輸入檔是 validate 輸出的 row_predictions（已經帶有 cop_x、Total、
    predicted_force_N 這類算好的欄位），先移除，避免跟這支程式重算的欄位重複。
    """
    return df.drop(columns=[c for c in DERIVED_COLUMNS if c in df.columns])


def add_diagnostic_columns(data, raw_cols):
    """殘差分析用的額外診斷變數（不進模型，只用來看誤差跟什麼有關）。"""
    raw = data[raw_cols].clip(lower=0)
    data["Total"] = raw.sum(axis=1)
    data["n_zero_points"] = (raw == 0).sum(axis=1)                  # 讀值為0的點數（死區的指標）
    data["max_point_share"] = raw.max(axis=1) / data["Total"].replace(0, np.nan)  # 最大單點佔總和比例（集中程度）
    return data


# 解讀提醒：已經在模型裡的變數（Total、cop_x...），殘差跟它們的「線性相關係數」
# 在訓練資料上幾乎一定接近 0（最小平方法的數學性質），所以那些圖要看的是
# 「形狀」（有沒有彎曲、扇形、分群），不是看 r 值。
# 不在模型裡的變數（n_zero_points、max_point_share、trial）的 r 值才有診斷意義。
# 另外殘差(預測-參考)跟 reference 通常帶負相關是正常的（回歸向中間收斂），
# 所以也放了 predicted_N（標準的殘差圖）當對照。
DIAG_VARS = [
    "reference_force_N", "predicted_N", "Total", "active_count", "n_zero_points", "max_point_share",
    "cop_x", "cop_y", "std", "front_back_ratio", "medial_lateral_ratio", "trial",
]


def scatter_with_trend(ax, x, y, xlabel, title_prefix):
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    ax.scatter(x, y, alpha=0.7)
    ax.axhline(0, linestyle="--", color="gray")
    r = np.nan
    if len(x) >= 3 and np.ptp(x) > 0:
        r = float(np.corrcoef(x, y)[0, 1])
        slope, intercept = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax.plot(xs, slope * xs + intercept, color="red", label=f"trend (r={r:.2f})")
        ax.legend()
    ax.set(xlabel=xlabel, ylabel="Residual: predicted - reference (N)",
           title=f"{title_prefix}")
    ax.grid(True, alpha=0.25)
    return r


def analyze(tag, condition, data, residual, out_dir, summary_rows, worst_rows, posture_rows):
    data = data.copy()
    data["residual_N"] = residual
    data["predicted_N"] = data["reference_force_N"].to_numpy() + residual

    # 殘差對各變數的散佈圖
    present = [v for v in DIAG_VARS if v in data.columns]
    n = len(present)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, var in zip(axes, present):
        x = pd.to_numeric(data[var], errors="coerce").to_numpy(float)
        r = scatter_with_trend(ax, x, data["residual_N"].to_numpy(float), var, f"vs {var}")
        s = pd.Series(x).corr(pd.Series(data["residual_N"].to_numpy(float)), method="spearman")
        summary_rows.append({"dataset": tag, "condition": condition, "variable": var,
                             "pearson_r": r, "spearman_r": s})
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(f"{tag} / {condition}: residual vs diagnostic variables", y=1.0)
    fig.tight_layout()
    fig.savefig(out_dir / f"{tag}_{condition}_residual_vs_variables.png", dpi=140)
    plt.close(fig)

    # 各姿態殘差箱形圖 + 統計
    if "posture" in data.columns:
        data["posture"] = data["posture"].fillna("unknown").astype(str)
        groups = [(p, g["residual_N"].to_numpy()) for p, g in data.groupby("posture")]
        fig, ax = plt.subplots(figsize=(max(7, 1.0 * len(groups) + 3), 5))
        ax.boxplot([g for _, g in groups])  # 不傳 labels（不同 matplotlib 版本參數名稱不同）
        ax.set_xticks(range(1, len(groups) + 1))
        ax.set_xticklabels([p for p, _ in groups])
        ax.axhline(0, linestyle="--", color="gray")
        ax.set(ylabel="Residual: predicted - reference (N)",
               title=f"{tag} / {condition}: residual by posture")
        ax.grid(True, axis="y", alpha=0.25)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
        fig.tight_layout()
        fig.savefig(out_dir / f"{tag}_{condition}_residual_by_posture.png", dpi=140)
        plt.close(fig)
        for p, g in groups:
            posture_rows.append({
                "dataset": tag, "condition": condition, "posture": p, "n": len(g),
                "mean_residual_N": float(np.mean(g)), "std_residual_N": float(np.std(g)),
                "MAE_N": float(np.mean(np.abs(g))),
                "bias_share": float(abs(np.mean(g)) / np.mean(np.abs(g))) if np.mean(np.abs(g)) > 0 else np.nan,
            })

    # 殘差最大的幾筆
    cols = [c for c in ["trial", "posture", "reference_force_N", "load_kg", "Total", "active_count",
                        "n_zero_points", "cop_x", "cop_y", "residual_N"] if c in data.columns]
    worst = data.reindex(data["residual_N"].abs().sort_values(ascending=False).index).head(TOP_N_WORST)
    w = worst[cols].copy()
    w.insert(0, "condition", condition)
    w.insert(0, "dataset", tag)
    worst_rows.append(w)


def run_training(base, out_dir, summary_rows, worst_rows, posture_rows):
    path = base / TRAIN_FILE
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請確認 {TRAIN_FILE} 跟程式在同一資料夾。")
    df = pd.read_excel(path, header=TRAIN_HEADER_ROW)
    df.columns = [str(c).strip() for c in df.columns]
    df = drop_derived(df)
    df = clean_sensor_data(df)
    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["reference_force_N"] = pd.to_numeric(df["reference_force_N"], errors="coerce")
    if "trial" in df.columns:
        df["trial"] = pd.to_numeric(df["trial"], errors="coerce")

    for condition, raw_cols in CONDITIONS.items():
        cdf = df[df["condition"] == condition].copy()
        for c in raw_cols:
            cdf[c] = pd.to_numeric(cdf[c], errors="coerce")
        data = cdf[cdf[raw_cols + ["reference_force_N"]].notna().all(axis=1)].copy()
        if len(data) < 5:
            warnings.warn(f"{condition} 資料太少，略過。")
            continue
        data = pd.concat([data, feat.build_engineered_frame(data, raw_cols, condition)], axis=1)
        data = data.dropna(subset=feat.ENGINEERED_FEATURE_NAMES)
        data = add_diagnostic_columns(data, raw_cols)

        features = ["Total"] + feat.ENGINEERED_FEATURE_NAMES
        X, y = data[features].astype(float), data["reference_force_N"].astype(float)
        cv_pred = cross_val_predict(LinearRegression(fit_intercept=FIT_INTERCEPT), X, y, cv=LeaveOneOut())
        analyze("train_loocv", condition, data, cv_pred - y.to_numpy(), out_dir,
                summary_rows, worst_rows, posture_rows)
        print(f"[train/{condition}] n={len(data)} LOOCV residual: "
              f"mean={np.mean(cv_pred - y):.1f} N, MAE={np.mean(np.abs(cv_pred - y)):.1f} N")


def run_validation(base, out_dir, summary_rows, worst_rows, posture_rows):
    path = base / VALID_FILE
    if not path.exists():
        print(f"（找不到 {VALID_FILE}，略過驗證資料分析）")
        return
    df = pd.read_excel(path, header=VALID_HEADER_ROW)
    df.columns = [str(c).strip() for c in df.columns]
    df = drop_derived(df)
    df = clean_sensor_data(df)
    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["reference_force_N"] = pd.to_numeric(df["reference_force_N"], errors="coerce")
    if "trial" in df.columns:
        df["trial"] = pd.to_numeric(df["trial"], errors="coerce")

    for condition, raw_cols in CONDITIONS.items():
        mpath = base / VALID_MODEL_FILES[condition]
        if not mpath.exists():
            print(f"（找不到 {mpath.name}，略過驗證 {condition}）")
            continue
        bundle = joblib.load(mpath)
        cdf = df[df["condition"] == condition].copy()
        for c in raw_cols:
            cdf[c] = pd.to_numeric(cdf[c], errors="coerce")
        data = cdf[cdf[raw_cols + ["reference_force_N"]].notna().all(axis=1)].copy()
        if data.empty:
            continue
        data = pd.concat([data, feat.build_engineered_frame(data, raw_cols, condition)], axis=1)
        data = data.dropna(subset=feat.ENGINEERED_FEATURE_NAMES)
        data = add_diagnostic_columns(data, raw_cols)
        pred = bundle["model"].predict(data[bundle["all_feature_names"]].astype(float))
        analyze("validation", condition, data, pred - data["reference_force_N"].to_numpy(), out_dir,
                summary_rows, worst_rows, posture_rows)
        print(f"[validation/{condition}] n={len(data)} residual mean="
              f"{np.mean(pred - data['reference_force_N']):.1f} N")


def main():
    base = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = base / OUTPUT_BASE_DIR / f"residual_run_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)

    summary_rows, worst_rows, posture_rows = [], [], []
    run_training(base, out_dir, summary_rows, worst_rows, posture_rows)
    run_validation(base, out_dir, summary_rows, worst_rows, posture_rows)

    with pd.ExcelWriter(out_dir / "residual_summary.xlsx", engine="openpyxl") as w:
        pd.DataFrame(summary_rows).to_excel(w, sheet_name="correlations", index=False)
        if posture_rows:
            pd.DataFrame(posture_rows).to_excel(w, sheet_name="by_posture", index=False)
        if worst_rows:
            pd.concat(worst_rows, ignore_index=True).to_excel(w, sheet_name="worst_rows", index=False)

    print(f"\n結果資料夾：{out_dir}")


if __name__ == "__main__":
    main()