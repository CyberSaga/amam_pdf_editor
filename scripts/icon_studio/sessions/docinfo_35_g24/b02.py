"""Batch 2 of the 35_文件資訊 24 px grid design. Run via run_session.py."""
from __future__ import annotations

from studio import Studio

s = Studio.open()
s.begin(6, "24 格：檢查整體、i 置中",
        "24/28/32 px 實際大小：倉鼠、寫了欄位的紙、紫色 i 章都讀得出來，和 03、04、05、28 並排一致。放大看：i 的直線 4 列"
        "一路接到圓章下緣的外框，上面留了一列紫色、下面沒有，i 偏低半格。比較四種：直線 4 列、3 列、圓章下移半格、"
        "i 上移一格——3 列置中最乾淨；圓章下移讓上下緣變糊，i 上移讓圓點黏住外框。",
        "直線改成 3 列（2×2 圓點、空 1 列、2×3 直線），上下各留 1 列紫色，i 置中在圓章裡。",
        tempo="normal")
s.look((13, 13, 10, 10), "i 偏低、直線黏外框")
s.mod("info_i", note="直線縮成 3 列，i 置中", d="M17 15h2v2h-2ZM17 18h2v3h-2Z")
s.commit()
