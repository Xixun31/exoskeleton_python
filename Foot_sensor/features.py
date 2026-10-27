"""
共用的姿態相關特徵萃取模組。

重要：訓練腳本（regression_condition_linear.py）跟驗證腳本（validate_new_subject.py
之類）都必須 import 這份模組來算特徵，不要各自複製一份邏輯——
確保「訓練時看到的特徵」跟「推論時算出來的特徵」永遠是同一套公式。

這份座標目前跟韌體 main.cpp 裡的 sensor_x / sensor_y / origin_x / origin_y /
MIRROR_LEFT_X 是同一組數字。未來任一邊（韌體或這裡）調整了感測點座標或原點，
兩邊都要同步改，否則 Python 端算出來的 COP 會跟韌體端對不上。
"""
import numpy as np

# ============================================================
# 18 個感測區域幾何中心（AutoCAD 世界座標，mm）—— 複製自 main.cpp
# ============================================================
SENSOR_X = [
    1943.9325, 1940.0133, 1973.6715, 1972.9752,
    1965.7372, 1957.7049, 1963.0637, 1955.6792,
    1995.8721, 1996.5690, 1983.1920, 1980.9491,
    1982.3130, 1970.9490, 2000.9966, 2003.7015,
    2001.4963, 1988.7695,
]

SENSOR_Y = [
    2600.1604, 2637.9524, 2444.2083, 2482.2769,
    2521.7471, 2561.9473, 2599.0265, 2642.2744,
    2444.2212, 2482.2769, 2520.6611, 2559.8462,
    2599.0265, 2641.6030, 2521.0309, 2560.0963,
    2597.5737, 2633.6218,
]

# 之後決定腳跟原點後，跟韌體一起改這裡
ORIGIN_X = 1984.7721
ORIGIN_Y = 2415.3761

# 跟韌體邏輯一致：如果 sensor_x/y 是右腳 CAD、而左腳想鏡射共用同一組身體座標系，
# 改成 True；左右腳各自有自己局部座標系的話維持 False。
MIRROR_LEFT_X = False

# 判斷「這個感測點有沒有受力」的門檻（g），跟韌體 FORCE_THRESHOLD 一致
FORCE_THRESHOLD = 50.0

N_POINTS = 18

ENGINEERED_FEATURE_NAMES = [
    "cop_x", "cop_y", "active_count", "std",
    "front_back_ratio", "medial_lateral_ratio",
]


def _effective_x(condition: str) -> np.ndarray:
    """依 condition 決定要不要把 x 座標鏡射（跟韌體邏輯一致）。"""
    x = np.array(SENSOR_X, dtype=float)
    if condition == "left" and MIRROR_LEFT_X:
        x = 2 * ORIGIN_X - x
    return x


def compute_cop(values, condition: str):
    """
    values: 長度18的陣列，該腳 P1~P18 的讀值（可以含負值/雜訊，函式內部會處理）。
    回傳 (cop_x, cop_y)，已相對 origin 平移（單位 mm）。
    若全部讀值都 <= 0（完全沒有受力，比如該腳沒踩上去），回傳 (nan, nan)，
    呼叫端要自己決定缺值怎麼處理（通常是整列根本不該拿來訓練）。
    """
    v = np.clip(np.asarray(values, dtype=float), 0, None)
    total = v.sum()
    if total <= 0:
        return float("nan"), float("nan")

    x = _effective_x(condition)
    y = np.array(SENSOR_Y, dtype=float)

    cop_x = float((v * x).sum() / total) - ORIGIN_X
    cop_y = float((v * y).sum() / total) - ORIGIN_Y
    return cop_x, cop_y


def extract_posture_features(values, condition: str) -> dict:
    """
    從單腳18點原始讀值，算出一組「跟姿態相關、但不需要姿態標籤」的連續特徵。
    回傳 dict 的 key 就是要併入回歸特徵矩陣的欄位名稱（見 ENGINEERED_FEATURE_NAMES）。

    注意：front_back_ratio / medial_lateral_ratio 的分界方向（哪邊算前腳掌、
    哪邊算內側）是先用 origin_x / origin_y 當分界線猜的，CAD座標的方向我沒有
    實際核對過——如果你套進資料後發現這兩個比例跟直覺的前後/內外側相反，
    把對應那行的不等號方向(`<` 改 `>`)反過來就好，不影響其他特徵。
    """
    v = np.asarray(values, dtype=float)
    v_pos = np.clip(v, 0, None)

    cop_x, cop_y = compute_cop(v, condition)

    active_count = float((v_pos > FORCE_THRESHOLD).sum())
    std = float(v_pos.std())

    y = np.array(SENSOR_Y, dtype=float)
    front_mask = y < ORIGIN_Y
    back_mask = ~front_mask
    front_sum = float(v_pos[front_mask].sum())
    back_sum = float(v_pos[back_mask].sum())
    front_back_ratio = front_sum / (back_sum + 1e-6)

    x = _effective_x(condition)
    medial_mask = x < ORIGIN_X
    lateral_mask = ~medial_mask
    medial_sum = float(v_pos[medial_mask].sum())
    lateral_sum = float(v_pos[lateral_mask].sum())
    medial_lateral_ratio = medial_sum / (lateral_sum + 1e-6)

    return {
        "cop_x": cop_x,
        "cop_y": cop_y,
        "active_count": active_count,
        "std": std,
        "front_back_ratio": front_back_ratio,
        "medial_lateral_ratio": medial_lateral_ratio,
    }


def build_engineered_frame(raw_df, sensor_cols, condition: str):
    """
    raw_df: 一個 DataFrame，欄位至少包含 sensor_cols 這18欄（已經是乾淨的數值）。
    sensor_cols: 該 condition 對應的18個欄名，例如 ['L1',...,'L18'] 或 ['R1',...,'R18']。
    回傳一個新的 DataFrame（跟 raw_df 同樣的 index），欄位是 ENGINEERED_FEATURE_NAMES。
    """
    import pandas as pd

    rows = []
    for _, row in raw_df[sensor_cols].iterrows():
        rows.append(extract_posture_features(row.to_numpy(), condition))
    return pd.DataFrame(rows, index=raw_df.index)
