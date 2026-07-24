#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""構成チェッカー v0.1 — BOM(機器リスト)を既知の落とし穴ルールと照合する。

CCW見積エクスポート等のCSVを読み込み、rules.yaml のルールDBと照合して
「警告(構成内の不整合)」と「確認事項(既存環境などBOMだけでは判定できない
必須質問)」をMarkdownレポートで出力する。

使い方:
    python checker.py 見積.csv
    python checker.py 見積.csv --rules rules.yaml --out report.md
    python checker.py 見積.csv --col-part "Part Number" --col-qty "Qty"
    python checker.py 見積.csv --no-header   # ヘッダー無し(型番,説明,数量の列順)

終了コード:
    0 = 指摘なし(ドラフトルールの参考指摘のみを含む)
    1 = 承認済みルールの警告または確認事項あり
    2 = 実行エラー(ファイルが読めない等)
"""

import argparse
import csv
import datetime
import os
import re
import sys
import unicodedata

# PyYAMLがあれば使い、無ければ同梱のサブセットパーサーで読む
try:
    import yaml as _pyyaml

    def _load_yaml(text):
        return _pyyaml.safe_load(text)

except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import miniyaml

    def _load_yaml(text):
        return miniyaml.load(text)


class CheckerError(Exception):
    pass


# ヘッダー自動判定に使う列名の候補(小文字・NFKC正規化後で比較)
PART_HEADER_CANDIDATES = {
    "part number", "product id", "product number", "part", "sku",
    "item number", "型番", "品番", "部品番号", "製品番号",
}
QTY_HEADER_CANDIDATES = {"quantity", "qty", "数量", "個数", "台数"}
DESC_HEADER_CANDIDATES = {"description", "desc", "説明", "品名", "製品説明", "製品名"}


def _norm(s):
    return unicodedata.normalize("NFKC", (s or "")).strip()


def _norm_header(s):
    return _norm(s).lower()


# ---------------------------------------------------------------------------
# ルールの読み込み
# ---------------------------------------------------------------------------

def load_rules(path):
    """rules.yaml を読み、(コンパイル済みパターン辞書, ルールリスト) を返す。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = _load_yaml(f.read())
    except OSError as e:
        raise CheckerError("ルールファイルを開けません: %s (%s)" % (path, e))
    if not isinstance(data, dict) or "patterns" not in data or "rules" not in data:
        raise CheckerError("ルールファイルには patterns: と rules: が必要です: %s" % path)

    compiled = {}
    for group, patterns in (data["patterns"] or {}).items():
        if not isinstance(patterns, list) or not patterns:
            raise CheckerError("patterns.%s は正規表現のリストにしてください" % group)
        regs = []
        for p in patterns:
            try:
                regs.append(re.compile(str(p), re.IGNORECASE))
            except re.error as e:
                raise CheckerError("patterns.%s の正規表現が不正です: %r (%s)" % (group, p, e))
        compiled[group] = regs

    rules = data["rules"] or []
    for rule in rules:
        _validate_rule(rule, compiled)
    return compiled, rules


def _validate_rule(rule, compiled):
    if not isinstance(rule, dict) or not rule.get("id"):
        raise CheckerError("id の無いルールがあります: %r" % (rule,))
    rid = rule["id"]
    if rule.get("type") not in ("question", "check"):
        raise CheckerError("[%s] type は question か check にしてください" % rid)
    trig = rule.get("trigger")
    if not isinstance(trig, dict) or not trig:
        raise CheckerError("[%s] trigger: がありません" % rid)
    for key in ("present", "absent"):
        for group in trig.get(key) or []:
            if group not in compiled:
                raise CheckerError("[%s] trigger.%s の未定義グループ: %s" % (rid, key, group))
    for group in (trig.get("min_qty") or {}):
        if group not in compiled:
            raise CheckerError("[%s] trigger.min_qty の未定義グループ: %s" % (rid, group))
    if rule["type"] == "check":
        spec = (rule.get("check") or {}).get("qty_at_least")
        if not isinstance(spec, dict) or "group" not in spec:
            raise CheckerError("[%s] check.qty_at_least.group がありません" % rid)
        for key in ("group", "reference"):
            group = spec.get(key)
            if group is not None and group not in compiled:
                raise CheckerError("[%s] check の未定義グループ: %s" % (rid, group))
        if "reference" not in spec and "min" not in spec:
            raise CheckerError("[%s] check.qty_at_least には reference か min が必要です" % rid)
    if rule["type"] == "question" and not rule.get("questions"):
        raise CheckerError("[%s] question型には questions: が必要です" % rid)


# ---------------------------------------------------------------------------
# BOM(CSV)の読み込み
# ---------------------------------------------------------------------------

def read_bom(path, col_part=None, col_qty=None, col_desc=None, no_header=False):
    """CSVを読み、(行リスト, 読み込み警告リスト, 使用エンコーディング) を返す。

    行は {"part", "desc", "qty", "line"} の辞書。
    """
    raw_rows, encoding = _read_csv_rows(path)
    warnings = []

    if no_header:
        header_idx, part_col, qty_col, desc_col = -1, 0, 2, 1
    else:
        found = _find_header(raw_rows, col_part)
        if found is None:
            raise CheckerError(
                "ヘッダー行が見つかりません。列名を --col-part で指定するか、"
                "ヘッダーが無い場合は --no-header (型番,説明,数量の列順) を使ってください。"
                "自動判定できる列名: %s" % ", ".join(sorted(PART_HEADER_CANDIDATES))
            )
        header_idx, part_col, header_cells = found
        qty_col = _find_col(header_cells, col_qty, QTY_HEADER_CANDIDATES)
        desc_col = _find_col(header_cells, col_desc, DESC_HEADER_CANDIDATES)
        if qty_col is None:
            warnings.append("数量列が見つからないため、全行を数量1として扱います")

    rows = []
    for i, raw in enumerate(raw_rows):
        if i <= header_idx:
            continue
        lineno = i + 1
        part = _norm(raw[part_col]).upper() if part_col < len(raw) else ""
        if not part:
            continue
        desc = _norm(raw[desc_col]) if desc_col is not None and desc_col < len(raw) else ""
        if qty_col is not None and qty_col < len(raw):
            qty = _parse_qty(raw[qty_col], lineno, warnings)
        else:
            qty = 1
        rows.append({"part": part, "desc": desc, "qty": qty, "line": lineno})

    if not rows:
        raise CheckerError("型番の行が1件も読み取れませんでした: %s" % path)
    return rows, warnings, encoding


def _read_csv_rows(path):
    last_error = None
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with open(path, "r", encoding=encoding, newline="") as f:
                return list(csv.reader(f)), encoding
        except UnicodeDecodeError as e:
            last_error = e
        except OSError as e:
            raise CheckerError("BOMファイルを開けません: %s (%s)" % (path, e))
    raise CheckerError("文字コードを判定できません(UTF-8/CP932以外?): %s (%s)" % (path, last_error))


def _find_header(raw_rows, col_part):
    targets = {_norm_header(col_part)} if col_part else PART_HEADER_CANDIDATES
    for idx, row in enumerate(raw_rows[:30]):
        cells = [_norm_header(c) for c in row]
        for j, cell in enumerate(cells):
            if cell in targets:
                return idx, j, cells
    return None


def _find_col(header_cells, override, candidates):
    targets = {_norm_header(override)} if override else candidates
    for j, cell in enumerate(header_cells):
        if cell in targets:
            return j
    return None


def _parse_qty(value, lineno, warnings):
    s = _norm(value).replace(",", "")
    if not s:
        warnings.append("%d行目: 数量が空欄のため1とみなしました" % lineno)
        return 1
    try:
        return int(float(s))
    except ValueError:
        warnings.append("%d行目: 数量 %r を数値として読めないため1とみなしました" % (lineno, s))
        return 1


# ---------------------------------------------------------------------------
# 照合と評価
# ---------------------------------------------------------------------------

def match_groups(rows, compiled):
    """{グループ名: {"qty": 数量合計, "rows": 該当行リスト}} を返す。"""
    groups = {}
    for group, regs in compiled.items():
        hit_rows = [r for r in rows if any(reg.search(r["part"]) for reg in regs)]
        groups[group] = {"qty": sum(r["qty"] for r in hit_rows), "rows": hit_rows}
    return groups


def evaluate(rules, groups):
    """発火した指摘のリスト [{"rule", "level"}] を返す。level は warning/confirm。"""
    findings = []
    for rule in rules:
        if not _trigger_fired(rule["trigger"], groups):
            continue
        if rule["type"] == "question":
            findings.append({"rule": rule, "level": "confirm"})
        else:  # check
            if not _check_passed(rule["check"], groups):
                findings.append({"rule": rule, "level": "warning"})
    return findings


def _trigger_fired(trigger, groups):
    for group in trigger.get("present") or []:
        if groups[group]["qty"] <= 0:
            return False
    for group in trigger.get("absent") or []:
        if groups[group]["qty"] > 0:
            return False
    for group, minimum in (trigger.get("min_qty") or {}).items():
        if groups[group]["qty"] < int(minimum):
            return False
    return True


def _check_passed(check, groups):
    spec = check["qty_at_least"]
    qty = groups[spec["group"]]["qty"]
    if "reference" in spec:
        return qty >= groups[spec["reference"]]["qty"]
    return qty >= int(spec["min"])


def _format_message(message, groups):
    def repl(m):
        group = m.group(1)
        return str(groups[group]["qty"]) if group in groups else m.group(0)

    return re.sub(r"\{qty:([A-Za-z0-9_]+)\}", repl, message or "")


# ---------------------------------------------------------------------------
# レポート出力
# ---------------------------------------------------------------------------

def render_report(bom_path, rules_path, encoding, rules, groups, findings, warnings):
    confirmed = [f for f in findings if (f["rule"].get("status") or "confirmed") != "draft"]
    drafts = [f for f in findings if (f["rule"].get("status") or "confirmed") == "draft"]
    n_warn = sum(1 for f in confirmed if f["level"] == "warning")
    n_confirm = sum(1 for f in confirmed if f["level"] == "confirm")

    out = []
    out.append("# 構成チェック結果")
    out.append("")
    out.append("- 対象ファイル: `%s` (文字コード: %s)" % (os.path.basename(bom_path), encoding))
    out.append("- ルールDB: `%s` (承認済み %d 件 / ドラフト %d 件)" % (
        os.path.basename(rules_path),
        sum(1 for r in rules if (r.get("status") or "confirmed") != "draft"),
        sum(1 for r in rules if (r.get("status") or "confirmed") == "draft"),
    ))
    out.append("- 実行日時: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    if confirmed:
        out.append("- 結果: ⚠️ 警告 %d 件 / ❓ 確認事項 %d 件" % (n_warn, n_confirm))
    else:
        out.append("- 結果: ✅ 承認済みルールからの指摘なし")
    out.append("")

    warn_findings = [f for f in confirmed if f["level"] == "warning"]
    if warn_findings:
        out.append("## ⚠️ 警告(構成内の不整合)")
        out.append("")
        for f in warn_findings:
            _render_finding(out, f["rule"], groups, with_message=True)

    confirm_findings = [f for f in confirmed if f["level"] == "confirm"]
    if confirm_findings:
        out.append("## ❓ 確認事項(回答を前提条件としてレビュー提出物に添付)")
        out.append("")
        out.append("BOMだけでは判定できない項目です。**全て回答してから**レビューに提出してください。")
        out.append("")
        for f in confirm_findings:
            _render_finding(out, f["rule"], groups, with_message=False)

    if drafts:
        out.append("## 📝 ドラフトルールからの参考指摘(赤入れ募集中)")
        out.append("")
        out.append("以下は精度未検証のドラフトです。的外れなら rules.yaml に赤を入れてください。")
        out.append("")
        for f in drafts:
            _render_finding(out, f["rule"], groups, with_message=(f["level"] == "warning"))

    out.append("## (参考)パターン照合の内訳")
    out.append("")
    out.append("| グループ | 数量計 | 該当行 |")
    out.append("|---|---:|---|")
    for group in sorted(groups):
        info = groups[group]
        parts = ", ".join("`%s` x%d" % (r["part"], r["qty"]) for r in info["rows"][:6])
        if len(info["rows"]) > 6:
            parts += " 他%d行" % (len(info["rows"]) - 6)
        out.append("| %s | %d | %s |" % (group, info["qty"], parts or "-"))
    out.append("")

    if warnings:
        out.append("## 読み込み時の注意")
        out.append("")
        for w in warnings:
            out.append("- %s" % w)
        out.append("")

    return "\n".join(out)


def _render_finding(out, rule, groups, with_message):
    status = "" if (rule.get("status") or "confirmed") != "draft" else " [DRAFT]"
    out.append("### [%s]%s %s" % (rule["id"], status, rule.get("name") or ""))
    out.append("")
    if with_message and rule.get("message"):
        out.append(_format_message(rule["message"], groups))
        out.append("")
    for q in rule.get("questions") or []:
        out.append("- [ ] %s" % q)
        out.append("      → 回答: ")
    if rule.get("questions"):
        out.append("")
    if rule.get("rationale"):
        out.append("- 根拠: %s" % rule["rationale"])
    if rule.get("incident"):
        out.append("- 過去事例: %s" % rule["incident"])
    evidence_groups = _rule_groups(rule)
    evidence = []
    for group in evidence_groups:
        for r in groups.get(group, {}).get("rows", [])[:4]:
            evidence.append("`%s` x%d (%d行目)" % (r["part"], r["qty"], r["line"]))
    if evidence:
        out.append("- 該当行: %s" % ", ".join(evidence))
    out.append("")


def _rule_groups(rule):
    seen = []
    trig = rule.get("trigger") or {}
    for group in (trig.get("present") or []) + list((trig.get("min_qty") or {}).keys()):
        if group not in seen:
            seen.append(group)
    spec = (rule.get("check") or {}).get("qty_at_least") or {}
    for group in (spec.get("group"), spec.get("reference")):
        if group and group not in seen:
            seen.append(group)
    return seen


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def run_check(bom_path, rules_path, col_part=None, col_qty=None, col_desc=None,
              no_header=False):
    """チェックを実行し (レポート文字列, 承認済み指摘の有無) を返す。"""
    compiled, rules = load_rules(rules_path)
    rows, warnings, encoding = read_bom(
        bom_path, col_part=col_part, col_qty=col_qty, col_desc=col_desc,
        no_header=no_header)
    groups = match_groups(rows, compiled)
    findings = evaluate(rules, groups)
    report = render_report(bom_path, rules_path, encoding, rules, groups,
                           findings, warnings)
    has_confirmed = any((f["rule"].get("status") or "confirmed") != "draft"
                        for f in findings)
    return report, has_confirmed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="BOM(機器リスト)を既知の落とし穴ルールと照合します")
    parser.add_argument("bom", help="BOMのCSVファイル(CCW見積エクスポート等)")
    parser.add_argument("--rules", default=None,
                        help="ルールファイル(既定: このスクリプトと同じ場所の rules.yaml)")
    parser.add_argument("--col-part", default=None, help="型番の列名(自動判定できない場合)")
    parser.add_argument("--col-qty", default=None, help="数量の列名(自動判定できない場合)")
    parser.add_argument("--col-desc", default=None, help="説明の列名(自動判定できない場合)")
    parser.add_argument("--no-header", action="store_true",
                        help="ヘッダー行なし(型番,説明,数量の列順)として読む")
    parser.add_argument("--out", default=None, help="レポートの出力先(既定: 標準出力)")
    args = parser.parse_args(argv)

    rules_path = args.rules or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "rules.yaml")

    try:
        report, has_findings = run_check(
            args.bom, rules_path, col_part=args.col_part, col_qty=args.col_qty,
            col_desc=args.col_desc, no_header=args.no_header)
    except CheckerError as e:
        print("エラー: %s" % e, file=sys.stderr)
        return 2

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print("レポートを書き出しました: %s" % args.out)
    else:
        print(report)
    return 1 if has_findings else 0


if __name__ == "__main__":
    sys.exit(main())
