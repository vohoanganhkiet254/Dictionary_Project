# -*- coding: utf-8 -*-
"""
Kiểm tra chính tả tiếng Việt cho văn bản (tập trung lỗi OCR) — dùng RAPIDFUZZ.

Ý tưởng cốt lõi
---------------
Chuẩn hoá cả TỪ ĐIỂN lẫn TOKEN về dạng "fold":
    - bỏ dấu thanh / dấu phụ (đ -> d)
    - gộp các ký tự OCR dễ lẫn về CÙNG một lớp:
        0->o, 1->i, l->i, j->i, 5->s, 8->b, rn->m, cl->d, vv->w ...
Trên không gian fold đó, dùng **rapidfuzz** (Damerau-Levenshtein) để tìm âm tiết
gần nhất. Nhờ vậy xử lý đồng thời:
    1. OCR nhầm ký tự (kể cả sai NHIỀU ký tự):  "54u" -> "sau", "kh1" -> "khi"
    2. Mất / sai dấu:                            "hịên" -> "hiện"
    3. Sai chính tả chung:                       "đjnh" -> "định"
Lỗi dấu cách xử lý riêng bằng TRIE:
    4. dính từ  (merge):  "nhiệmvụ" -> "nhiệm vụ"
    5. tách từ  (split):  "ng ành"  -> "ngành"   (kể cả còn lẫn OCR: "rn ột" -> "một")

BỎ QUA: viết hoa (so khớp dạng thường), số, ngày tháng, mã văn bản, URL/email.

Cách dùng
---------
    python spellcheck_ocr.py "đoạn văn bản cần kiểm tra" --fix
    python spellcheck_ocr.py --file duong_dan.txt
    echo "văn bản" | python spellcheck_ocr.py
    (chạy không tham số -> chạy phần demo)
"""

import sys
import io
import os
import re
import argparse
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein

sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DICT = os.path.normpath(os.path.join(_HERE, "..", "dictionary", "FINAL_dictionary.txt"))


# --------------------------------------------------------------------------- #
#  Chuẩn hoá: NFC, skeleton (bỏ dấu), fold (gộp lớp ký tự OCR)
# --------------------------------------------------------------------------- #
def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


_SK_CACHE: dict[str, str] = {}


def skeleton(s: str) -> str:
    """Bỏ dấu thanh/dấu phụ, đ->d, về chữ thường (giữ nguyên ký tự số)."""
    if s in _SK_CACHE:
        return _SK_CACHE[s]
    d = unicodedata.normalize("NFD", s.lower())
    out = []
    for ch in d:
        if unicodedata.combining(ch):
            continue
        out.append("d" if ch == "đ" else ch)
    res = "".join(out)
    _SK_CACHE[s] = res
    return res


# Gộp cụm nhiều ký tự dễ lẫn (áp dụng TRƯỚC khi gộp từng ký tự)
FOLD_LIGATURES = [("rn", "m"), ("cl", "d"), ("vv", "w"), ("ii", "u")]

# Gộp từng ký tự về 1 đại diện của lớp lẫn OCR
FOLD_CHAR = {
    # chữ số bị OCR đọc thành chữ cái
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a",
    "5": "s", "6": "b", "7": "t", "8": "b", "9": "g",
    "|": "i", "!": "i", "$": "s", "@": "a", "€": "e",
    # chữ cái dễ lẫn nhau -> dồn về 1 lớp
    "l": "i", "j": "i",
}

_FOLD_CACHE: dict[str, str] = {}


def fold(s: str) -> str:
    """Khung khớp OCR: skeleton + gộp lớp ký tự dễ lẫn."""
    if s in _FOLD_CACHE:
        return _FOLD_CACHE[s]
    sk = skeleton(s)
    for bad, good in FOLD_LIGATURES:
        if bad in sk:
            sk = sk.replace(bad, good)
    res = "".join(FOLD_CHAR.get(c, c) for c in sk)
    _FOLD_CACHE[s] = res
    return res


# --------------------------------------------------------------------------- #
#  Khoảng cách có trọng số (để CHẤM ĐIỂM ứng viên, tôn trọng dấu sẵn có)
#     - giống ký tự           : 0
#     - cùng chữ gốc, khác dấu : 0.3   (lỗi dấu thanh/dấu phụ)
#     - cùng lớp lẫn OCR       : 0.2   (0/o, 1/i/l, j/ị, 5/s ...)
#     - khác hẳn               : 1.0
# --------------------------------------------------------------------------- #
def _char_cost(c1: str, c2: str) -> float:
    if c1 == c2:
        return 0.0
    b1, b2 = skeleton(c1), skeleton(c2)
    if b1 == b2:
        return 0.3
    if FOLD_CHAR.get(b1, b1) == FOLD_CHAR.get(b2, b2):
        return 0.2
    return 1.0


def weighted_dist(a: str, b: str) -> float:
    """Levenshtein có trọng số ký tự (chèn/xoá = 1.0)."""
    prev = [j * 1.0 for j in range(len(b) + 1)]
    for i in range(1, len(a) + 1):
        cur = [i * 1.0]
        for j in range(1, len(b) + 1):
            cur.append(min(
                cur[-1] + 1.0,                              # chèn
                prev[j] + 1.0,                             # xoá
                prev[j - 1] + _char_cost(a[i - 1], b[j - 1]),  # thay
            ))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------------- #
#  TRIE (prefix tree) — tra cứu chính xác + tách từ dính
# --------------------------------------------------------------------------- #
class TrieNode:
    __slots__ = ("children", "is_word", "freq")

    def __init__(self):
        self.children: dict[str, "TrieNode"] = {}
        self.is_word = False
        self.freq = 0


class Trie:
    def __init__(self):
        self.root = TrieNode()
        self.size = 0

    def insert(self, word: str, freq: int = 1) -> None:
        node = self.root
        for ch in word:
            nxt = node.children.get(ch)
            if nxt is None:
                nxt = TrieNode()
                node.children[ch] = nxt
            node = nxt
        if not node.is_word:
            self.size += 1
        node.is_word = True
        node.freq = max(node.freq, freq)

    def contains(self, word: str) -> bool:
        node = self.root
        for ch in word:
            node = node.children.get(ch)
            if node is None:
                return False
        return node.is_word


# --------------------------------------------------------------------------- #
#  Từ điển: Trie (âm tiết) + bản đồ fold -> âm tiết (cho rapidfuzz)
# --------------------------------------------------------------------------- #
class Dictionary:
    def __init__(self, path: str = DEFAULT_DICT):
        self.trie = Trie()
        self.syllables: set[str] = set()
        self.freq: dict[str, int] = {}              # âm tiết & cụm -> tần suất
        self.fold_map: dict[str, list[str]] = {}    # fold -> [âm tiết] (sắp theo freq giảm)
        self.fold_keys: list[str] = []              # danh sách khoá fold cho rapidfuzz
        self.phrases: set[str] = set()              # các mục từ GHÉP (>=2 âm tiết)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Không thấy từ điển: {path}")
        self._load_file(path)
        self._build_index()

    def _load_file(self, path: str):
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                entry = nfc(parts[0]).strip().lower()
                freq = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                if not entry:
                    continue
                syls = entry.split()
                for syl in syls:                     # tách từ ghép -> âm tiết
                    if syl not in self.syllables:
                        self.syllables.add(syl)
                        self.trie.insert(syl, freq)
                    self.freq[syl] = max(self.freq.get(syl, 0), freq)
                if len(syls) >= 2:                    # giữ lại cụm để gợi ý từ ghép
                    self.phrases.add(entry)
                    self.freq[entry] = max(self.freq.get(entry, 0), freq)

    def _build_index(self):
        for syl in self.syllables:
            self.fold_map.setdefault(fold(syl), []).append(syl)
        for fk in self.fold_map:
            self.fold_map[fk].sort(key=lambda s: -self.freq.get(s, 0))
        self.fold_keys = list(self.fold_map.keys())

    # --- tra cứu ---------------------------------------------------------- #
    def is_valid(self, syl: str) -> bool:
        return syl in self.syllables

    def fold_exact(self, token: str):
        """Âm tiết có cùng 'fold' với token (khớp OCR/dấu trực tiếp)."""
        return self.fold_map.get(fold(token), [])

    def fuzzy(self, token: str, max_dist: int, limit: int = 12):
        """Dùng rapidfuzz tìm các khoá fold gần 'fold(token)' nhất.
        Trả về [(âm_tiết, khoảng_cách)]."""
        qf = fold(token)
        if not qf:
            return []
        matches = process.extract(
            qf, self.fold_keys,
            scorer=DamerauLevenshtein.distance,
            score_cutoff=max_dist,
            limit=limit,
        )
        out = []
        for key, dist, _ in matches:
            for syl in self.fold_map[key]:
                out.append((syl, dist))
        return out

    def syllable_options(self, low: str, limit: int = 5, tone_only: bool = False):
        """Các âm tiết hợp lệ khả dĩ cho 1 token (gồm chính nó nếu đã đúng).
        Trả [(âm_tiết, điểm)] điểm nhỏ = tốt — dùng để ghép cụm.
        tone_only=True: chỉ nhận biến thể KHÁC DẤU (cùng skeleton) — để không
        làm sai token bên trái vốn đã đúng chữ gốc."""
        opts: dict[str, float] = {}
        if self.is_valid(low):
            opts[low] = 0.0
        max_dist = 1 if len(fold(low)) <= 3 else 2
        sk = skeleton(low)
        for syl, _fd in self.fuzzy(low, max_dist):
            same_sk = skeleton(syl) == sk
            if tone_only and not same_sk:
                continue
            # đổi dấu (cùng skeleton) coi như miễn phí -> để tần suất quyết định;
            # biến thể lệch xa hơn bị phạt theo weighted_dist
            sc = 0.0 if same_sk else 0.30 + weighted_dist(low, syl)
            if syl not in opts or sc < opts[syl]:
                opts[syl] = sc
        return sorted(opts.items(), key=lambda x: (round(x[1], 2), -self.freq.get(x[0], 0)))[:limit]

    def segment(self, token: str, max_parts: int = 3):
        """Tách 'token' thành chuỗi âm tiết hợp lệ (sửa lỗi DÍNH từ)."""
        n = len(token)
        best: list = [None] * (n + 1)
        best[0] = ([], 0)
        for i in range(1, n + 1):
            for j in range(max(0, i - 8), i):
                if best[j] is None:
                    continue
                piece = token[j:i]
                if len(piece) < 2:                  # tránh mảnh 1 ký tự (nhiễu)
                    continue
                if piece in self.syllables:
                    parts, cnt = best[j]
                    cand = (parts + [piece], cnt + 1)
                    if best[i] is None or cand[1] < best[i][1]:
                        best[i] = cand
        res = best[n]
        if res and 2 <= len(res[0]) <= max_parts:
            return res[0]
        return None


# --------------------------------------------------------------------------- #
#  Phân loại token cần BỎ QUA
# --------------------------------------------------------------------------- #
_RE_NUMBERLIKE = re.compile(r"^[0-9]+([.,:/\-][0-9]+)*%?$")
_RE_HAS_URL = re.compile(r"(https?://|www\.|@)", re.IGNORECASE)


def strip_edges(tok: str):
    """Bỏ dấu câu ở 2 đầu, trả (core, độ_dài_tiền_tố_đã_bỏ)."""
    m = re.match(r"^(\W*)(.*?)(\W*)$", tok, re.UNICODE)
    if not m:
        return tok, 0
    return m.group(2), len(m.group(1))


def should_skip(core: str) -> bool:
    """Bỏ qua thứ CHẮC CHẮN không phải từ: số thuần, ngày, URL/email, mã có '/'.
    Token lẫn chữ + số (vd '54u') KHÔNG bỏ ở đây — để thử sửa OCR trước."""
    if not core:
        return True
    if _RE_NUMBERLIKE.match(core):
        return True
    if _RE_HAS_URL.search(core):
        return True
    if "/" in core or "\\" in core:
        return True
    if not any(c.isalpha() for c in core):
        return True
    return False


# --------------------------------------------------------------------------- #
#  Kiểm tra VIẾT HOA
#     - đầu câu phải viết hoa
#     - viết hoa sai giữa từ (mẫu thường→HOA kiểu OCR: "nGười") -> đưa về thường
#  Né từ viết tắt toàn HOA (UBND, TW, QĐ-TTg) vì không có mẫu thường→HOA.
# --------------------------------------------------------------------------- #
SENT_END = set(".!?…")


def cap_suggestions(core: str, sentence_start: bool):
    """Trả danh sách gợi ý sửa viết hoa cho 1 token (rỗng nếu không có lỗi)."""
    fi = next((i for i, c in enumerate(core) if c.isalpha()), None)
    if fi is None:
        return []
    # viết hoa lộn xộn giữa từ: có chữ HOA ngay sau một chữ thường
    mid = any(core[k].isupper() and core[k - 1].isalpha() and core[k - 1].islower()
              for k in range(fi + 1, len(core)))
    start_bad = sentence_start and core[fi].islower()
    if not mid and not start_bad:
        return []

    out = []
    if mid:
        low = "".join(c.lower() if c.isalpha() else c for c in core)
        cap = low[:fi] + low[fi].upper() + low[fi + 1:]
        out = [cap, low] if sentence_start else [low, cap]
    else:  # chỉ thiếu hoa đầu câu
        out = [core[:fi] + core[fi].upper() + core[fi + 1:]]

    # khử trùng lặp, bỏ trùng bản gốc
    seen, res = set(), []
    for s in out:
        if s != core and s not in seen:
            seen.add(s)
            res.append(s)
    return res


# --------------------------------------------------------------------------- #
#  Bộ kiểm tra
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    index: int
    start: int
    end: int
    original: str
    err_type: str
    suggestions: list = field(default_factory=list)   # [(gợi_ý, loại, điểm)]


ERR_LABEL = {
    "ocr_char": "OCR nhầm ký tự",
    "missing_diacritic": "Sai/mất dấu",
    "spacing_merge": "Dính từ (thiếu dấu cách)",
    "spacing_split": "Tách từ (thừa dấu cách)",
    "spelling": "Sai chính tả",
    "phrase": "Cụm từ ghép (gợi ý)",
    "capitalization": "Viết hoa",
    "unknown": "Không nhận dạng",
}


class SpellChecker:
    def __init__(self, dictionary: Dictionary):
        self.dic = dictionary

    def _classify(self, token_low: str, syl: str) -> str:
        return "missing_diacritic" if skeleton(token_low) == skeleton(syl) else "ocr_char"

    def _phrase_suggestions(self, low_a: str, low_b: str, limit: int = 5,
                            a_tone_only: bool = False):
        """Ghép 2 token thành cụm — CHỈ nhận cụm là TỪ GHÉP CÓ THẬT trong từ điển
        (không sinh tổ hợp Descartes vô nghĩa kiểu "no cơ").
        a_tone_only: token bên trái chỉ được đổi DẤU (không đổi chữ gốc).
        Trả ([(cụm, điểm)], có_từ_ghép_trong_từ_điển)."""
        a_opts = self.dic.syllable_options(low_a, tone_only=a_tone_only)
        b_opts = self.dic.syllable_options(low_b)
        if not a_opts or not b_opts:
            return [], False
        combos: dict[str, float] = {}
        for a, sa in a_opts:
            for b, sb in b_opts:
                phrase = f"{a} {b}"
                if phrase not in self.dic.phrases:       # bỏ tổ hợp không có thật
                    continue
                score = sa + sb
                if phrase not in combos or score < combos[phrase]:
                    combos[phrase] = score
        if not combos:
            return [], False
        # xếp theo gần OCR, rồi độ phổ biến của cụm
        ranked = sorted(combos.items(),
                        key=lambda x: (round(x[1], 1), -self.dic.freq.get(x[0], 0)))
        return [(p, sc) for p, sc in ranked[:limit]], True

    def _candidates(self, low: str):
        """Sinh gợi ý cho 1 âm tiết (không xét hàng xóm). [(gợi_ý, loại, điểm)] — điểm nhỏ = tốt.

        - SINH ứng viên: rapidfuzz trên không gian fold (gồm cả khớp fold chính xác).
        - CHẤM điểm: nếu chỉ khác DẤU (cùng skeleton) -> điểm thấp cố định, tin TẦN SUẤT;
          ngược lại -> phạt theo weighted_dist (tôn trọng dấu sẵn có + lớp OCR).
        """
        out: dict[str, tuple[str, float]] = {}
        sk_low = skeleton(low)

        def add(sugg, typ, score):
            if sugg == low:
                return
            if sugg not in out or score < out[sugg][1]:
                out[sugg] = (typ, score)

        # 1) ứng viên âm tiết từ rapidfuzz (fold-distance nhỏ)
        max_dist = 1 if len(fold(low)) <= 3 else 2
        for syl, _fd in self.dic.fuzzy(low, max_dist):
            if skeleton(syl) == sk_low:
                add(syl, "missing_diacritic", 0.30)        # chỉ sai dấu -> tin tần suất
            else:
                add(syl, self._classify(low, syl), 0.30 + weighted_dist(low, syl))

        # 2) tách từ dính
        seg = self.dic.segment(low)
        if seg:
            add(" ".join(seg), "spacing_merge", 0.55)

        ranked = sorted(
            ((s, t, sc) for s, (t, sc) in out.items()),
            key=lambda x: (round(x[2], 2), -self.dic.freq.get(x[0].split()[0], 0)),
        )
        return ranked

    def check(self, text: str):
        text = nfc(text)
        toks = [(m.group(0), m.start()) for m in re.finditer(r"\S+", text)]
        cores = []
        for raw, off in toks:
            core, pre = strip_edges(raw)
            cores.append({"raw": raw, "off": off, "core": core, "pre": pre})

        issues: list[Issue] = []
        skip_next = False
        for i, tk in enumerate(cores):
            if skip_next:
                skip_next = False
                continue
            core = tk["core"]
            if should_skip(core):
                continue
            low = core.lower()
            if self.dic.is_valid(low):
                continue

            start = tk["off"] + tk["pre"]
            end = start + len(core)

            # --- lỗi TÁCH từ: ghép với token kế tiếp (kể cả còn lẫn OCR qua fold) ---
            if i + 1 < len(cores):
                nxt = cores[i + 1]
                if not should_skip(nxt["core"]):
                    joined = low + nxt["core"].lower()
                    fix = None
                    if self.dic.is_valid(joined):
                        fix = joined
                    else:
                        fe = self.dic.fold_exact(joined)
                        if fe:
                            fix = fe[0]
                    if fix:
                        issues.append(Issue(
                            i, start, nxt["off"] + nxt["pre"] + len(nxt["core"]),
                            core + " " + nxt["core"], "spacing_split",
                            [(fix, "spacing_split", 0.35)],
                        ))
                        skip_next = True
                        continue

            # Token lẫn chữ + số: chỉ báo khi 'fold' ra ĐÚNG một âm tiết thật
            # (vd "54u"->"sau"); nếu không -> coi là mã/số -> bỏ qua (vd "A80").
            if any(c.isdigit() for c in core):
                if self.dic.fold_exact(low):
                    cands = self._candidates(low)
                    if cands:
                        issues.append(Issue(i, start, end, core, cands[0][1], cands[:5]))
                continue

            # --- ghép với token BÊN TRÁI nếu tạo thành từ ghép CÓ THẬT (vd "phoi hop" -> "phối hợp") ---
            prev = cores[i - 1] if i > 0 else None
            if (prev and not should_skip(prev["core"])
                    and self.dic.is_valid(prev["core"].lower())):
                lphr, lhas = self._phrase_suggestions(prev["core"].lower(), low, a_tone_only=True)
                if lhas:
                    start_l = prev["off"] + prev["pre"]
                    suggs = [(p, "phrase", sc) for p, sc in lphr]
                    issues.append(Issue(i - 1, start_l, end,
                                        prev["core"] + " " + core, "phrase", suggs))
                    continue

            # --- lỗi mức âm tiết ---
            cands = self._candidates(low)

            # --- gợi ý mức TỪ GHÉP với token kế tiếp ---
            nxt = cores[i + 1] if i + 1 < len(cores) else None
            phr, has_dict = ([], False)
            if nxt and not should_skip(nxt["core"]):
                phr, has_dict = self._phrase_suggestions(low, nxt["core"].lower())

            # Gộp thành cụm khi: là từ ghép có thật / token kế cũng sai / không có gợi ý đơn
            if phr and (has_dict or not self.dic.is_valid(nxt["core"].lower()) or not cands):
                end2 = nxt["off"] + nxt["pre"] + len(nxt["core"])
                suggs = [(p, "phrase", sc) for p, sc in phr]
                issues.append(Issue(i, start, end2, core + " " + nxt["core"], "phrase", suggs))
                skip_next = True
                continue

            # Ngược lại: báo lỗi âm tiết, dành chỗ kèm vài gợi ý cụm để tham khảo
            suggs = list(cands[:3])
            if phr:
                suggs += [(p, "phrase", sc) for p, sc in phr[:3]]
            etype = cands[0][1] if cands else "unknown"
            issues.append(Issue(i, start, end, core, etype, suggs))

        # --- pass VIẾT HOA: gộp thêm, bỏ qua vùng đã có lỗi chính tả ---
        issues += self._cap_pass(cores, issues)
        issues.sort(key=lambda it: it.start)
        return issues

    def _cap_pass(self, cores, existing):
        """Quét lỗi viết hoa; bỏ qua token trùng vùng đã báo lỗi chính tả."""
        spans = [(it.start, it.end) for it in existing]

        def overlaps(s, e):
            return any(s < be and e > bs for bs, be in spans)

        out = []
        sentence_start = True
        for i, tk in enumerate(cores):
            core, raw, pre = tk["core"], tk["raw"], tk["pre"]
            has_alpha = any(c.isalpha() for c in core)
            start = tk["off"] + pre
            end = start + len(core)
            if has_alpha and not should_skip(core) and not overlaps(start, end):
                sg = cap_suggestions(core, sentence_start)
                if sg:
                    out.append(Issue(i, start, end, core, "capitalization",
                                     [(s, "capitalization", 0.2) for s in sg]))
            if has_alpha:
                sentence_start = False
            suffix = raw[pre + len(core):]
            if any(ch in SENT_END for ch in suffix):
                sentence_start = True
        return out


# --------------------------------------------------------------------------- #
#  Báo cáo & tự sửa
# --------------------------------------------------------------------------- #
def format_report(text: str, issues: list[Issue]) -> str:
    if not issues:
        return "✓ Không phát hiện lỗi."
    lines = [f"Phát hiện {len(issues)} vấn đề:\n"]
    for it in issues:
        lbl = ERR_LABEL.get(it.err_type, it.err_type)
        lines.append(f"  • [{lbl}] \"{it.original}\"  (vị trí {it.start}-{it.end})")
        if it.suggestions:
            sugg = ", ".join(f'"{s}"' for s, _, _ in it.suggestions[:6])
            lines.append(f"      → gợi ý: {sugg}")
        else:
            lines.append("      → (không có gợi ý)")
    return "\n".join(lines)


def autocorrect(text: str, issues: list[Issue]) -> str:
    text = nfc(text)
    out, last = [], 0
    for it in sorted(issues, key=lambda x: x.start):
        if not it.suggestions:
            continue
        out.append(text[last:it.start])
        out.append(it.suggestions[0][0])
        last = it.end
    out.append(text[last:])
    return "".join(out)


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Kiểm tra chính tả OCR tiếng Việt (rapidfuzz + trie).")
    ap.add_argument("text", nargs="?", help="Chuỗi văn bản cần kiểm tra")
    ap.add_argument("--file", help="Đọc văn bản từ file")
    ap.add_argument("--dict", default=DEFAULT_DICT, help="Đường dẫn từ điển (mặc định FINAL_dictionary.txt)")
    ap.add_argument("--fix", action="store_true", help="In thêm văn bản đã tự sửa")
    args = ap.parse_args()

    if args.file:
        with io.open(args.file, encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = None

    dic = Dictionary(args.dict)
    print(f"[Từ điển] {dic.trie.size} âm tiết, {len(dic.fold_keys)} khoá fold "
          f"từ {os.path.basename(args.dict)}\n", file=sys.stderr)
    checker = SpellChecker(dic)

    if text is None:
        demo = ("Cộng h0à xã hộl chủ nghĩa Vlệt Nam, 54u kh1 các cơ quan thực hịên "
                "nhiệmvụ kiểm tra theo quy đjnh số 123/2026/NĐ-CP ngày 01/01/2026.")
        print(">>> DEMO\nVăn bản:", demo, "\n")
        issues = checker.check(demo)
        print(format_report(demo, issues))
        print("\nĐã sửa:", autocorrect(demo, issues))
        return

    issues = checker.check(text)
    print(format_report(text, issues))
    if args.fix:
        print("\n--- Văn bản đã tự sửa ---")
        print(autocorrect(text, issues))


if __name__ == "__main__":
    main()
