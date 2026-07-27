"""スナップショットの保存と比較。

CSVを置き換えると過去の状態が消えるので、読み込んだ時点の集計を残しておく。
「先月から何が変わったか」を聞けるようにするための仕組み。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

from .config import Config
from .models import Portfolio
from .analysis import concentration, margin, pnl

_SAFE_LABEL = re.compile(r"[^0-9A-Za-z一-龠ぁ-んァ-ヶー_-]")


def _digest(pf: Portfolio, cfg: Config) -> dict[str, Any]:
    """比較に使う要約だけを残す。生の建玉も残して差分を取れるようにする。"""
    return {
        "asof": pf.asof,
        "net_asset_value": round(pf.net_asset_value),
        "cash": round(pf.cash),
        "spot_market_value": round(pf.spot_market_value),
        "maintenance_rate_pct": margin.maintenance_rate(pf, cfg),
        "concentration": {
            k: v
            for k, v in concentration.summarize(pf).items()
            if k in ("hhi", "gross_exposure", "gross_leverage", "position_count", "top3_weight_pct")
        },
        "pnl": {
            k: v
            for k, v in pnl.summarize(pf, cfg).items()
            if k in ("total_unrealized_pnl", "nisa_unrealized_pnl", "taxable_unrealized_pnl")
        },
        "positions": {
            p.symbol: {
                "name": p.name,
                "quantity": p.quantity,
                "market_value": round(p.market_value or p.cost_basis),
                "unrealized_pnl": round(p.unrealized_pnl or 0.0),
            }
            for p in pf.spot
        },
        "margin_positions": {
            f"{m.symbol}:{m.side.value}": {
                "name": m.name,
                "quantity": m.quantity,
                "notional": round(m.notional),
                "unrealized_pnl": round(m.unrealized_pnl or 0.0),
            }
            for m in pf.margin
        },
    }


def save(pf: Portfolio, cfg: Config, label: str = "", now: Optional[dt.datetime] = None) -> Path:
    now = now or dt.datetime.now()
    cfg.snapshot_dir.mkdir(parents=True, exist_ok=True)
    safe = _SAFE_LABEL.sub("", label)[:40]
    name = now.strftime("%Y%m%d-%H%M") + (f"_{safe}" if safe else "") + ".json"
    path = cfg.snapshot_dir / name
    payload = {"saved_at": now.isoformat(timespec="seconds"), "label": label, **_digest(pf, cfg)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def listing(cfg: Config) -> list[dict[str, Any]]:
    if not cfg.snapshot_dir.exists():
        return []
    out = []
    for p in sorted(cfg.snapshot_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out.append(
            {
                "name": p.stem,
                "saved_at": data.get("saved_at"),
                "label": data.get("label"),
                "net_asset_value": data.get("net_asset_value"),
                "maintenance_rate_pct": data.get("maintenance_rate_pct"),
            }
        )
    return out


def _resolve(cfg: Config, name: str) -> Optional[dict[str, Any]]:
    path = cfg.snapshot_dir / f"{name}.json"
    if not path.exists():
        # 前方一致でも引けるようにする（日付だけ指定したいことが多い）
        matches = sorted(cfg.snapshot_dir.glob(f"{name}*.json"))
        if not matches:
            return None
        path = matches[0]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def compare(cfg: Config, older: str, newer: str) -> dict[str, Any]:
    a = _resolve(cfg, older)
    b = _resolve(cfg, newer)
    if a is None or b is None:
        missing = older if a is None else newer
        return {"error": f"スナップショット '{missing}' が見つからない。list_snapshots で確認してほしい。"}

    def diff_num(key: str) -> dict[str, Any]:
        av, bv = a.get(key), b.get(key)
        if av is None or bv is None:
            return {"from": av, "to": bv, "change": None}
        return {"from": av, "to": bv, "change": round(bv - av, 2)}

    pos_diff = []
    keys = set(a.get("positions", {})) | set(b.get("positions", {}))
    for k in sorted(keys):
        pa = a.get("positions", {}).get(k)
        pb = b.get("positions", {}).get(k)
        if pa and pb and pa["quantity"] == pb["quantity"] and pa["market_value"] == pb["market_value"]:
            continue
        pos_diff.append(
            {
                "symbol": k,
                "name": (pb or pa).get("name"),
                "status": "新規" if not pa else ("消滅" if not pb else "変化"),
                "quantity": {"from": (pa or {}).get("quantity"), "to": (pb or {}).get("quantity")},
                "market_value": {
                    "from": (pa or {}).get("market_value"),
                    "to": (pb or {}).get("market_value"),
                },
            }
        )

    return {
        "from": {"name": older, "saved_at": a.get("saved_at")},
        "to": {"name": newer, "saved_at": b.get("saved_at")},
        "net_asset_value": diff_num("net_asset_value"),
        "cash": diff_num("cash"),
        "spot_market_value": diff_num("spot_market_value"),
        "maintenance_rate_pct": diff_num("maintenance_rate_pct"),
        "position_changes": pos_diff,
    }
