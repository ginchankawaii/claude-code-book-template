# -*- coding: utf-8 -*-
"""ごく小さなYAMLサブセットローダー。

pipが使えない業務端末などPyYAMLが入っていない環境でも rules.yaml を
読めるようにするための予備パーサー。PyYAMLがある環境ではそちらが
優先される（checker.py参照）。

対応: ネストしたマップ / リスト / スカラー / "引用符" / # コメント /
      1行フローリスト [a, "b,c", 1] / 先頭の --- と末尾の ... /
      yes,no,on,off の真偽値(YAML 1.1互換)
非対応(明確なエラーになる): 複数行スカラー(| や >) / アンカー・エイリアス /
      フローマップ {a: 1} / ネストしたフロー形式 / タブインデント /
      引用符内のエスケープシーケンス(\\n等) / 複数ドキュメント
既知の差異: 0始まりの整数(010)は8進数ではなく10進数として読む。
"""

# 引用符が「開き引用符」とみなされるのは、直前がこれらの文字のときだけ。
# (Bob's のような語中のアポストロフィを引用符と誤認しないため)
_QUOTE_OPENERS = " \t:,-["


class MiniYamlError(ValueError):
    def __init__(self, message, lineno=None):
        if lineno is not None:
            message = "%d行目: %s" % (lineno, message)
        super().__init__(message)


def load(text):
    """YAMLサブセットのテキストをPythonオブジェクトにして返す。"""
    lines = _significant_lines(text)
    if lines and lines[0][0] == 0 and lines[0][1] == "---":
        lines = lines[1:]
    if lines and lines[-1][0] == 0 and lines[-1][1] == "...":
        lines = lines[:-1]
    for _ind, content, lineno in lines:
        if content == "---":
            raise MiniYamlError("複数ドキュメントには対応していません", lineno)
    if not lines:
        return None
    value, next_i = _parse_block(lines, 0, lines[0][0])
    if next_i != len(lines):
        raise MiniYamlError("インデント構造が不正です", lines[next_i][2])
    return value


def _significant_lines(text):
    """(インデント幅, 中身, 行番号) のリストに正規化する。"""
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        leading = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in leading:
            raise MiniYamlError("インデントにタブは使えません", lineno)
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        out.append((indent, line.strip(), lineno))
    return out


def _strip_comment(line):
    """引用符の外にある ' #' 以降を落とす。"""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"') and (i == 0 or line[i - 1] in _QUOTE_OPENERS):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _parse_block(lines, i, indent):
    content = lines[i][1]
    if content == "-" or content.startswith("- "):
        return _parse_list(lines, i, indent)
    return _parse_map(lines, i, indent)


def _parse_list(lines, i, indent):
    result = []
    while i < len(lines):
        ind, content, lineno = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise MiniYamlError("リスト項目のインデントが揃っていません", lineno)
        if not (content == "-" or content.startswith("- ")):
            break
        rest = content[1:].lstrip()
        if rest == "":
            # 「-」単独: 次行以降のネストブロックが項目の値
            if i + 1 < len(lines) and lines[i + 1][0] > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result.append(value)
            else:
                result.append(None)
                i += 1
        elif _split_key(rest) is not None:
            # 「- key: ...」: マップ項目。仮想インデントを立てて部分パース
            offset = len(content) - len(rest)
            virtual = ind + offset
            sub = [(virtual, rest, lineno)]
            i += 1
            while i < len(lines) and lines[i][0] >= virtual:
                sub.append(lines[i])
                i += 1
            value, consumed = _parse_map(sub, 0, virtual)
            if consumed != len(sub):
                raise MiniYamlError("リスト項目内のインデントが不正です", sub[consumed][2])
            result.append(value)
        else:
            result.append(_parse_scalar(rest, lineno))
            i += 1
    return result, i


def _parse_map(lines, i, indent):
    result = {}
    while i < len(lines):
        ind, content, lineno = lines[i]
        if ind < indent:
            break
        if ind > indent:
            raise MiniYamlError("インデントが揃っていません", lineno)
        if content == "-" or content.startswith("- "):
            raise MiniYamlError("マップの中にリスト項目が直接現れました", lineno)
        kv = _split_key(content)
        if kv is None:
            raise MiniYamlError("'key: value' 形式ではありません: %s" % content, lineno)
        key, val = kv
        if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
            key = key[1:-1]
        if key in result:
            raise MiniYamlError("キーが重複しています: %s" % key, lineno)
        if val == "":
            if i + 1 < len(lines) and lines[i + 1][0] > ind:
                value, i = _parse_block(lines, i + 1, lines[i + 1][0])
                result[key] = value
            else:
                result[key] = None
                i += 1
        else:
            if val in ("|", "|-", "|+", ">", ">-", ">+"):
                raise MiniYamlError("複数行スカラー(| / >)には対応していません", lineno)
            result[key] = _parse_scalar(val, lineno)
            i += 1
    return result, i


def _split_key(s):
    """引用符の外にある「: 」または行末の「:」でキーと値に分ける。"""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"') and (i == 0 or s[i - 1] in _QUOTE_OPENERS):
            quote = ch
        elif ch == ":":
            if i + 1 == len(s):
                return s[:i].strip(), ""
            if s[i + 1] == " ":
                return s[:i].strip(), s[i + 2 :].strip()
    return None


def _parse_scalar(s, lineno=None):
    s = s.strip()
    if not s:
        return None
    first = s[0]
    if first in ("'", '"'):
        end = s.find(first, 1)
        if end == -1:
            raise MiniYamlError("引用符が閉じていません: %s" % s, lineno)
        if end != len(s) - 1:
            raise MiniYamlError("引用符の後に余分な文字があります: %s" % s, lineno)
        inner = s[1:-1]
        if first == '"' and "\\" in inner:
            raise MiniYamlError(
                "引用符内のエスケープシーケンス(\\)には対応していません", lineno)
        return inner
    if first == "[":
        if not s.endswith("]"):
            raise MiniYamlError("フローリストが閉じていません: %s" % s, lineno)
        return _parse_flow_list(s[1:-1], lineno)
    if first == "{":
        if s == "{}":
            return {}
        raise MiniYamlError("フローマップ({a: 1}形式)には対応していません", lineno)
    if first in ("&", "*"):
        raise MiniYamlError("アンカー/エイリアス(& *)には対応していません", lineno)
    low = s.lower()
    if low in ("null", "~"):
        return None
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_flow_list(inner, lineno=None):
    inner = inner.strip()
    if not inner:
        return []
    items = []
    buf = []
    quote = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"') and not "".join(buf).strip():
            buf.append(ch)
            quote = ch
        elif ch in "[{":
            raise MiniYamlError("ネストしたフロー形式には対応していません", lineno)
        elif ch == ",":
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quote:
        raise MiniYamlError("引用符が閉じていません", lineno)
    items.append("".join(buf))
    return [_parse_scalar(item.strip(), lineno) for item in items]
