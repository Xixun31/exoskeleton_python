
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import numpy as np

# 1. 讀取資料
df = pd.read_excel("foot_data.xlsx")

# 2. 設定 36 個感測點
sensor_cols = (
    [f"L{i}" for i in range(1, 19)]
    + [f"R{i}" for i in range(1, 19)]
)

X = df[sensor_cols]
y = df["reference_force_N"]

# 3. 檢查資料
if X.isnull().any().any() or y.isnull().any():
    raise ValueError("資料有空白，請先檢查 Excel。")

if len(df) < 37:
    print("注意：樣本數少於 37，36 個權重與截距可能無法唯一估計。")

# 4. 建立多元線性迴歸
model = LinearRegression()
model.fit(X, y)

# 5. 計算預測值
y_pred = model.predict(X)

# 6. 輸出權重與截距
weights = pd.DataFrame({
    "sensor": sensor_cols,
    "weight": model.coef_
})

print("\n=== 36 個感測點的迴歸係數 ===")
print(weights.to_string(index=False))
print("\n截距:", model.intercept_)

# 7. 計算訓練資料上的誤差
mae = mean_absolute_error(y, y_pred)
rmse = np.sqrt(mean_squared_error(y, y_pred))
r2 = r2_score(y, y_pred)

print("\n=== 訓練資料上的結果（不是獨立驗證）===")
print(f"MAE  = {mae:.3f} N")
print(f"RMSE = {rmse:.3f} N")
print(f"R²   = {r2:.4f}")

# 8. 比較每一筆參考值與預測值
result = df[["trial", "posture", "reference_force_N"]].copy()
result["predicted_force_N"] = y_pred
result["error_N"] = y_pred - y

print("\n=== 每筆資料的預測結果 ===")
print(result.to_string(index=False))

# 9. 輸出結果檔案
weights.to_excel("regression_weights.xlsx", index=False)
result.to_excel("regression_results.xlsx", index=False)

print("\n已輸出 regression_weights.xlsx 和 regression_results.xlsx")