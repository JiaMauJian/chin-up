# chin-up

常駐在系統匣的久坐提醒小工具。

連續使用電腦 15 分鐘就提醒你起來動一動，並輪流建議一個脖子運動（收下巴、收下巴後仰、後仰左右轉）。離開電腦超過 5 分鐘會自動重新計時。

## 安裝

需要 Python 3.14。

```
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## 使用

雙擊 `start.bat`，右下角系統匣會出現一個箭頭圖示（可能藏在 `^` 裡）。在圖示上按右鍵可以：

- 看已經連續坐了幾分鐘
- 改提醒間隔

### 開機自動啟動

按 `Win + R`，輸入 `shell:startup`，把 `start.bat` 的捷徑放進打開的資料夾。

## 設定

在選單改過提醒間隔後會產生 `config.json`，也可以自己建立或直接修改（改完要重新啟動）：

| 設定 | 預設 | 說明 |
|---|---|---|
| `sit_minutes` | 15 | 連續坐多久提醒一次 |
| `idle_reset_minutes` | 5 | 離開電腦多久，久坐計時歸零 |

出錯時看 `chin-up.log`。
