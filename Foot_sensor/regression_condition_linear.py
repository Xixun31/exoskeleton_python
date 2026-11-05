"""
普通線性迴歸（OLS）訓練版：依 condition 訓練 left / right，
每個 condition 底下再各自訓練 A / B / C 三種變體（見下方說明），
每個變體存成獨立的 .joblib，方便之後混搭（例如左腳用A、右腳用C）。

變體定義：
  A_pointwise_18 + engineered：18個原始感測點各自獨立權重 + 6個工程特徵（24個輸入）
  B_total_only               ：只用18點加總後的 Total，1個輸入，不看分佈
  C_total + engineered       ：Total + 6個工程特徵，7個輸入（折衷版本）

每次執行建立獨立資料夾，不覆蓋前次結果；輸出：
  - 每個 condition x 變體：train/LOOCV 指標、train/loocv 的參考值vs預測值圖、模型檔
  - 每個 condition：一張「參考值 vs 原始感測器讀值(Total)」的診斷圖
    （還沒套任何模型前的原始關係，用來先目視確認資料本身有沒有明顯的線性趨勢）
  - 逐姿態的交叉驗證誤差統計（只對A變體做，跟之前習慣一致；其他變體如果需要
    一樣可以拉出來看，架構都在）
  - 各變體係數表

注意：這是訓練程式，不是用獨立新受測者資料做驗證的 validate_new_subject.py。
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
from sklearn.model_selection import LeaveOneOut, LeaveOneGroupOut, cross_val_predict

import features as feat  # 共用特徵模組，跟驗證腳本要 import 同一份

INPUT_FILE = "foot_data.xlsx"
OUTPUT_BASE_DIR = "regression_output_linear_training"

# 截距開關：True = 一般回歸（有偏移量 b）；False = 強制截距為 0
# （物理意義：所有讀值都是 0 時，預測力就是 0 N）。
# 注意 cop_y 等特徵本身恆為正，可能偷偷補回一個隱藏截距，
# 所以 False 不一定有效，要拿新受試者驗證結果比較後再決定。
FIT_INTERCEPT = True
READ_HEADER_ROW = 1  # Excel 第 1 列是說明文字，第 2 列是欄位名稱

# ==============================
# 受試者 / 批次分組（留一人交叉驗證用）
# ==============================
# foot_data.xlsx 需要有這兩個欄位：
#   subject_id：這筆資料是誰測的（p1 / p2 / p3）。留一人驗證就是依這欄分組。
#   session   ：測量批次（p1_main / p2_main / p3_main / p2_1 ...）。
#               同一個人的補測資料要「subject_id 一樣、session 不同」。
SUBJECT_COL = "subject_id"
SESSION_COL = "session"

# 想做「有/沒有補測資料」的對照時，把要排除的 session 填在這裡再重跑，例如 ["p2_1"]。
# 排除的資料不會用在訓練，也不會用在任何交叉驗證。
EXCLUDE_SESSIONS = []
# 若要把某位受試者完全排除（例如留給驗證用），填 subject_id，例如 ["p3"]。
EXCLUDE_SUBJECTS = []

# MAPE 在低負載會被放大，另外多算一個「參考力 >= 這個值」的 MAPE 當輔助指標（N）
MAPE_MIN_REF_N = 200.0

CONDITIONS = {
    "left": [f"L{i}" for i in range(1, 19)],
    "right": [f"R{i}" for i in range(1, 19)],
}

# 三種變體：key是存檔名跟報表用的標籤，value是一個函式，
# 輸入該 condition 的18個原始欄名，回傳這個變體要用的特徵欄位清單。
VARIANTS = {
    "A_pointwise_18 + engineered": lambda raw_cols: raw_cols + feat.ENGINEERED_FEATURE_NAMES,
    "B_total_only": lambda raw_cols: ["Total"],
    "C_total + engineered": lambda raw_cols: ["Total"] + feat.ENGINEERED_FEATURE_NAMES,
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
    df[columns] = df[columns].apply(pd.to_numeric, errors="coerce")
    if CLIP_ALL_NEGATIVE:
        df[columns] = df[columns].clip(lower=0)
    else:
        df[columns] = df[columns].mask(df[columns].abs() < DEADBAND, 0)
    return df


# ==============================
# 以下接原本的程式
# ==============================

def rmse(y_true, y_pred):
    return float(np.sqrt(mean_squared_error(y_true, y_pred)))


def safe_name(label):
    return label.replace(" ", "").replace("+", "_")


def mape_pct(y_true, y_pred, min_ref=0.0):
    """平均絕對百分比誤差(%)，只計算參考值 > min_ref 的樣本。"""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = y_true > min_ref
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs(y_pred[mask] - y_true[mask]) / y_true[mask]) * 100)


def prepare_groups(df):
    """整理 subject_id / session 欄位，並套用 EXCLUDE_SESSIONS / EXCLUDE_SUBJECTS。"""
    for col in (SUBJECT_COL, SESSION_COL):
        if col not in df.columns:
            warnings.warn(f"資料檔沒有 '{col}' 欄位，"
                          + ("無法做留一人交叉驗證。" if col == SUBJECT_COL else "無法依批次分析。"))
            continue
        s = df[col].astype(str).str.strip()
        s = s.where(~s.str.lower().isin(["", "nan", "none"]), "unknown")
        df[col] = s
        n_unknown = int((s == "unknown").sum())
        if n_unknown:
            warnings.warn(f"'{col}' 有 {n_unknown} 筆空白，已標成 'unknown'"
                          "（留一人驗證時會被當成同一個人，請補齊）。")

    n0 = len(df)
    if EXCLUDE_SESSIONS and SESSION_COL in df.columns:
        df = df[~df[SESSION_COL].isin(EXCLUDE_SESSIONS)]
    if EXCLUDE_SUBJECTS and SUBJECT_COL in df.columns:
        df = df[~df[SUBJECT_COL].isin(EXCLUDE_SUBJECTS)]
    if len(df) != n0:
        print(f"依 EXCLUDE 設定排除了 {n0 - len(df)} 筆資料"
              f"（sessions={EXCLUDE_SESSIONS}, subjects={EXCLUDE_SUBJECTS}）。")
    return df


def repeatability_table(data, condition):
    """
    同一人、同批次、同姿態、同負重的重複量測，算參考力與 Total 的標準差。
    這是「重複性雜訊」：就算模型完美，誤差也不會比這個更小。
    """
    keys = [c for c in [SUBJECT_COL, SESSION_COL, "posture", "load_kg"] if c in data.columns]
    if not keys:
        return None
    rows = []
    for key, g in data.groupby(keys, dropna=False):
        if len(g) < 2:
            continue
        key = key if isinstance(key, tuple) else (key,)
        ref, tot = g["reference_force_N"], g["Total"]
        tot_cv = float(tot.std(ddof=1) / tot.mean() * 100) if tot.mean() > 0 else float("nan")
        rows.append({
            **dict(zip(keys, key)), "condition": condition, "n_repeats": len(g),
            "ref_mean_N": float(ref.mean()), "ref_std_N": float(ref.std(ddof=1)),
            "total_mean": float(tot.mean()), "total_std": float(tot.std(ddof=1)),
            "total_cv_pct": tot_cv,
            "approx_force_noise_N": tot_cv / 100 * float(ref.mean()) if np.isfinite(tot_cv) else float("nan"),
        })
    return pd.DataFrame(rows) if rows else None


def plot_actual_vs_predicted(y, pred, condition, label, out_dir, kind, posture=None):
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y, pred, alpha=0.75)
    lo = float(min(np.min(y), np.min(pred)))
    hi = float(max(np.max(y), np.max(pred)))
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    ax.plot([lo, hi], [lo, hi], "--", label="Ideal: predicted = reference")
    kind_label = {"train": "Train", "cv": "LOOCV", "loso": "Leave-one-subject-out",
                  "raw": "Raw sensor Total"}[kind]
    title = f"{condition} / {label}: Reference vs {kind_label}"
    if posture is not None:
        title += f" — {posture}"
    xlabel = "Reference force (N)"
    ylabel = f"{kind_label} value"
    ax.set(xlabel=xlabel, ylabel=ylabel, title=title)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fname = f"{condition}_{safe_name(label)}_{kind}_actual_vs_predicted"
    if posture is not None:
        fname += f"_{str(posture).replace('/', '_')}"
    fig.savefig(out_dir / f"{fname}.png", dpi=160)
    plt.close(fig)


def plot_raw_reference_vs_total(y, total, condition, out_dir):
    """
    完全沒套任何模型前，原始 Total(18點加總) vs reference_force_N 的散佈圖，
    用來先目視檢查資料本身的線性趨勢、有沒有明顯離群值。
    注意這張圖的 x/y 單位本來就不一樣（Total是感測器的原始讀值單位，
    reference是牛頓），不是 y=x 的關係，不畫理想線，純粹看趨勢形狀。
    """
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.scatter(y, total, alpha=0.75)
    ax.set(xlabel="Reference force (N)", ylabel="Raw sensor Total (sum of 18 points, raw units)",
           title=f"{condition}: Reference vs raw sensor Total (before any model)")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / f"{condition}_reference_vs_raw_total.png", dpi=160)
    plt.close(fig)


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
    df = prepare_groups(df)

    root = Path(OUTPUT_BASE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = root / f"training_run_{stamp}"
    suffix = 1
    while out_dir.exists():
        out_dir = root / f"training_run_{stamp}_{suffix}"
        suffix += 1
    out_dir.mkdir(parents=True)

    summaries, predictions_A, coefficients, posture_summaries_A = [], [], [], []
    all_predictions, subject_summaries, posture_loso_summaries, repeat_tables = [], [], [], []

    for condition, raw_cols in CONDITIONS.items():
        cdf = df[df["condition"] == condition].copy()
        if cdf.empty:
            warnings.warn(f"condition='{condition}' 沒有資料，略過。")
            continue
        missing_features = [c for c in raw_cols if c not in cdf.columns]
        if missing_features:
            warnings.warn(f"{condition} 缺少欄位 {missing_features}，略過。")
            continue

        for col in raw_cols:
            cdf[col] = pd.to_numeric(cdf[col], errors="coerce")

        valid = cdf[raw_cols + ["reference_force_N"]].notna().all(axis=1)
        data = cdf.loc[valid].copy()
        dropped = len(cdf) - len(data)
        if len(data) < 2:
            warnings.warn(f"{condition} 有效資料不足 2 筆，略過。")
            continue

        # ---- 算一次共用的特徵：Total + 6個工程特徵，三個變體共用，不用重算 ----
        engineered = feat.build_engineered_frame(data, raw_cols, condition)
        n_before = len(data)
        data = pd.concat([data, engineered], axis=1)
        data["Total"] = data[raw_cols].sum(axis=1)
        data = data.dropna(subset=feat.ENGINEERED_FEATURE_NAMES)
        n_dropped_by_feat = n_before - len(data)
        if n_dropped_by_feat:
            warnings.warn(
                f"{condition} 有 {n_dropped_by_feat} 筆資料算姿態特徵時出現 nan"
                "（通常代表18點讀值全部<=0），已從訓練集排除，請檢查這幾筆原始資料。"
            )
        if data.empty:
            warnings.warn(f"{condition} 算完特徵後沒有可用資料，略過。")
            continue

        y = data["reference_force_N"].astype(float)

        # ---- 原始 Total vs reference 的診斷圖（套模型之前先看一眼）----
        plot_raw_reference_vs_total(y.to_numpy(), data["Total"].to_numpy(), condition, out_dir)

        # ---- 重複性雜訊：同人/同批次/同姿態/同負重重複量測的離散程度 ----
        rep = repeatability_table(data, condition)
        if rep is not None:
            repeat_tables.append(rep)
            print(f"[{condition}] 重複性：Total 變異係數中位數 {rep['total_cv_pct'].median():.1f}%，"
                  f"約對應力雜訊中位數 {rep['approx_force_noise_N'].median():.1f} N，"
                  f"參考力(體重計)重複標準差中位數 {rep['ref_std_N'].median():.1f} N")

        groups = data[SUBJECT_COL].to_numpy() if SUBJECT_COL in data.columns else None
        n_subjects = len(set(groups)) if groups is not None else 0

        for variant_label, feature_fn in VARIANTS.items():
            features = feature_fn(raw_cols)
            X = data[features].astype(float)

            model = LinearRegression(fit_intercept=FIT_INTERCEPT)
            model.fit(X, y)
            train_pred = model.predict(X)
            plot_actual_vs_predicted(y.to_numpy(), train_pred, condition, variant_label, out_dir, "train")

            cv_pred = np.full(len(data), np.nan)
            cv_mae = cv_rmse = cv_r2 = np.nan
            if len(data) >= 5:
                try:
                    cv_pred = cross_val_predict(
                        LinearRegression(fit_intercept=FIT_INTERCEPT), X, y, cv=LeaveOneOut()
                    )
                    cv_mae = mean_absolute_error(y, cv_pred)
                    cv_rmse = rmse(y, cv_pred)
                    cv_r2 = r2_score(y, cv_pred)
                    plot_actual_vs_predicted(y.to_numpy(), cv_pred, condition, variant_label, out_dir, "cv")
                except Exception as exc:
                    warnings.warn(f"{condition}/{variant_label} LOOCV 失敗：{exc}")

            # ---- 留一人交叉驗證：整個人拿掉當驗證，用其他人訓練 ----
            loso_pred = np.full(len(data), np.nan)
            loso_mae = loso_rmse = loso_r2 = loso_mape = loso_mape_hi = np.nan
            if groups is not None and n_subjects >= 2:
                try:
                    loso_pred = cross_val_predict(
                        LinearRegression(fit_intercept=FIT_INTERCEPT), X, y,
                        cv=LeaveOneGroupOut(), groups=groups,
                    )
                    loso_mae = mean_absolute_error(y, loso_pred)
                    loso_rmse = rmse(y, loso_pred)
                    loso_r2 = r2_score(y, loso_pred)
                    loso_mape = mape_pct(y, loso_pred)
                    loso_mape_hi = mape_pct(y, loso_pred, MAPE_MIN_REF_N)
                    plot_actual_vs_predicted(y.to_numpy(), loso_pred, condition, variant_label, out_dir, "loso")
                except Exception as exc:
                    warnings.warn(f"{condition}/{variant_label} 留一人驗證失敗：{exc}")

            pred_cols = [c for c in [SUBJECT_COL, SESSION_COL, "trial", "posture", "load_kg"] if c in data.columns]
            rec = data[pred_cols].copy()
            rec["condition"] = condition
            rec["variant"] = variant_label
            rec["reference_force_N"] = y.to_numpy()
            rec["loocv_pred_N"] = cv_pred
            rec["loso_pred_N"] = loso_pred
            rec["loso_error_N"] = loso_pred - y.to_numpy()
            all_predictions.append(rec)

            if np.isfinite(loso_pred).all():
                def _summ(g, extra):
                    e = g["loso_error_N"]
                    ref = g["reference_force_N"]
                    return {
                        "condition": condition, "variant": variant_label, **extra, "n": len(g),
                        "LOSO_MAE_N": float(e.abs().mean()),
                        "LOSO_mean_error_N": float(e.mean()),
                        "LOSO_MAPE_pct": mape_pct(ref, ref + e),
                        f"LOSO_MAPE_ref>={MAPE_MIN_REF_N:.0f}N_pct": mape_pct(ref, ref + e, MAPE_MIN_REF_N),
                    }
                for subj, g in rec.groupby(SUBJECT_COL):
                    subject_summaries.append(_summ(g, {"subject_id": subj}))
                if "posture" in rec.columns:
                    for posture, g in rec.groupby("posture", dropna=False):
                        posture_loso_summaries.append(_summ(g, {"posture": posture}))

            summaries.append({
                "condition": condition, "variant": variant_label,
                "fit_intercept": FIT_INTERCEPT,
                "n_rows_in_condition": len(cdf), "n_valid_rows": len(data),
                "n_dropped_rows": dropped + n_dropped_by_feat, "n_features": len(features),
                "train_MAE_N": mean_absolute_error(y, train_pred),
                "train_RMSE_N": rmse(y, train_pred), "train_R2": r2_score(y, train_pred),
                "LOOCV_MAE_N": cv_mae, "LOOCV_RMSE_N": cv_rmse, "LOOCV_R2": cv_r2,
                "n_subjects": n_subjects,
                "LOSO_MAE_N": loso_mae, "LOSO_RMSE_N": loso_rmse, "LOSO_R2": loso_r2,
                "LOSO_MAPE_pct": loso_mape,
                f"LOSO_MAPE_ref>={MAPE_MIN_REF_N:.0f}N_pct": loso_mape_hi,
            })

            coef = pd.DataFrame({"feature": features, "coefficient": model.coef_})
            coef.loc[len(coef)] = ["intercept", model.intercept_]
            coef["condition"] = condition
            coef["variant"] = variant_label
            coefficients.append(coef)

            bundle = {
                "model": model,
                "condition": condition,
                "variant": variant_label,
                "fit_intercept": FIT_INTERCEPT,
                "raw_feature_names": raw_cols,  # 18個原始欄名，推論時用來算Total/engineered
                "engineered_feature_names": feat.ENGINEERED_FEATURE_NAMES,
                "all_feature_names": features,  # 這個模型實際用的欄位、順序
                "deadband": DEADBAND,
                "clip_all_negative": CLIP_ALL_NEGATIVE,
                "trained_at": stamp,
                "exclude_sessions": list(EXCLUDE_SESSIONS),
                "exclude_subjects": list(EXCLUDE_SUBJECTS),
                "trained_subjects": sorted(set(groups)) if groups is not None else None,
            }
            joblib.dump(bundle, out_dir / f"{condition}_{safe_name(variant_label)}_linear_model.joblib")

            # 逐姿態 LOOCV 誤差統計，只對 A 變體做（跟你之前習慣的報表一致；
            # 其他變體要看的話，這段邏輯一樣可以照抄套用）
            if variant_label.startswith("A_") and len(data) >= 5 and np.isfinite(cv_pred).all():
                result = data.copy()
                result["cv_predicted_force_N"] = cv_pred
                result["cv_error_N"] = cv_pred - y.to_numpy()
                predictions_A.append(result)
                if "posture" in result.columns:
                    temp = result.copy()
                    temp["posture"] = temp["posture"].fillna("unknown").astype(str)
                    for posture, group in temp.groupby("posture", dropna=False):
                        errors = group["cv_error_N"].dropna()
                        if len(errors):
                            posture_summaries_A.append({
                                "condition": condition, "posture": posture, "n_samples": len(errors),
                                "CV_MAE_N": float(errors.abs().mean()),
                                "CV_RMSE_N": float(np.sqrt(np.mean(errors ** 2))),
                                "CV_mean_error_N": float(errors.mean()),
                            })

            print(f"[{condition}/{variant_label}] n={len(data)}; features={len(features)}; "
                  f"train R2={r2_score(y, train_pred):.4f}; "
                  f"LOOCV MAE={cv_mae:.3f} N; LOOCV RMSE={cv_rmse:.3f} N; LOOCV R2={cv_r2:.4f}; "
                  f"LOSO MAE={loso_mae:.3f} N; LOSO MAPE={loso_mape:.1f}%; LOSO R2={loso_r2:.4f}")

    if not summaries:
        raise ValueError("沒有模型成功訓練，請檢查 condition、欄位名稱和有效資料。")

    pd.DataFrame(summaries).to_excel(out_dir / "linear_model_summary.xlsx", index=False)
    pd.concat(coefficients, ignore_index=True).to_excel(out_dir / "linear_coefficients.xlsx", index=False)
    if predictions_A:
        pd.concat(predictions_A, ignore_index=True).to_excel(
            out_dir / "linear_predictions_with_cv_variantA.xlsx", index=False
        )
    if posture_summaries_A:
        pd.DataFrame(posture_summaries_A).to_excel(
            out_dir / "posture_cv_error_summary_variantA.xlsx", index=False
        )

    if all_predictions:
        pd.concat(all_predictions, ignore_index=True).to_excel(
            out_dir / "predictions_all_variants_loocv_loso.xlsx", index=False
        )
    if subject_summaries:
        pd.DataFrame(subject_summaries).to_excel(out_dir / "loso_error_by_subject.xlsx", index=False)
    if posture_loso_summaries:
        pd.DataFrame(posture_loso_summaries).to_excel(out_dir / "loso_error_by_posture.xlsx", index=False)
    if repeat_tables:
        pd.concat(repeat_tables, ignore_index=True).to_excel(out_dir / "repeatability_summary.xlsx", index=False)

    print("\n提醒：LOOCV 會讓同一人的重複量測同時出現在訓練與驗證，數字偏樂觀；")
    print("      請以 LOSO（留一人）的 MAE/MAPE 當作『對新的人』的真實表現。")
    print(f"\n本次結果資料夾：{out_dir.resolve()}")
    print("這是【訓練版】結果；每次執行都會建立新的 training_run_時間戳資料夾，不會覆蓋前次結果。")
    print("每個 condition 都訓練了 A/B/C 三種變體，各自存成獨立的 .joblib，")
    print("檔名格式：{condition}_{變體安全名稱}_linear_model.joblib，例如 left_A_pointwise_18_engineered_linear_model.joblib")


if __name__ == "__main__":
    main()