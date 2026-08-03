# Lovart 產品批次製作

`lovart_batch.py` 會掃描 `產品資料/`，將每個產品的 3–9 張圖片（以及鄉村風音樂）交給本地 Lovart skill，結果下載到 `批次輸出/<產品名>/`，進度保存在 `批次輸出/state.json`。

在專案根目錄建立 `.env`（可複製 `.env.example`），填入：

```bash
cp .env.example .env
# 編輯 .env，填入你的真實金鑰
```

程式會自動讀取 `.env`；若 shell 中已經設定同名變數，shell 變數優先。

先做不消耗額度的檢查：

```bash
python3 lovart_batch.py --dry-run
```

正式執行（已有 active project 時可省略 `--project-id`）：

```bash
python3 lovart_batch.py --project-id YOUR_PROJECT_ID --mode fast
```

`--mode fast` 會消耗額度但適合 24 小時時限；`--mode unlimited` 可能排隊。未指定時保留目前 Lovart 模式。

影片可能回傳 `pending_confirmation`。這是 Lovart skill 的強制安全流程，程式會保存 thread ID 並停止，不會自動代替你確認付費。確認費用後執行：

```bash
python3 lovart-skill/lovart-skill/agent_skill.py confirm \
  --thread-id THREAD_ID --json --download \
  --output-dir "批次輸出/產品名稱"
python3 lovart_batch.py --mode keep
```

若只先試一個產品：

```bash
python3 lovart_batch.py --only "小獅王 矽膠練習牙刷" --mode fast
```

不要在 Lovart canvas 開著的瀏覽器分頁時執行批次；skill 指出瀏覽器自動儲存可能覆蓋 API 插入的 canvas 元素。完成後可重新開啟。
