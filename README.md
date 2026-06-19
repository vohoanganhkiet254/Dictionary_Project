# Công cụ kiểm tra chính tả OCR tiếng Việt

Công cụ phát hiện và gợi ý sửa các lỗi **do OCR** trong văn bản hành chính tiếng Việt:
lẫn ký tự, mất/sai dấu, lỗi dấu cách, sai chính tả, gợi ý cụm từ ghép và viết hoa.
Gồm một **thư viện lõi** (dùng được trên dòng lệnh) và một **ứng dụng web** cho phép
tải file `.docx` lên, sửa trực tiếp và tải về.

## Cấu trúc thư mục

```
Dictionary_Project/
├── README.md                  # tài liệu này
├── BAO_CAO_TIEN_DO.md         # báo cáo tiến độ (công nghệ, thuật toán, kế hoạch)
├── dictionary/
│   └── FINAL_dictionary.txt   # từ điển (âm tiết + từ ghép). Cột: tu<TAB>tan_suat
├── scripts/
│   └── spellcheck_ocr.py      # thư viện lõi + CLI kiểm tra chính tả
└── web/
    ├── app.py                 # backend Flask
    ├── templates/index.html   # giao diện
    ├── static/app.js          # logic phía client
    ├── static/style.css       # CSS
    └── sample/mau_loi.docx    # file .docx mẫu có lỗi để thử
```

## Yêu cầu

- Python 3.10+ (đã thử trên 3.14)
- Thư viện:
  ```bash
  pip install rapidfuzz flask python-docx
  ```
  - `rapidfuzz` — fuzzy matching (Damerau–Levenshtein)
  - `flask` — web server (chỉ cần cho ứng dụng web)
  - `python-docx` — đọc/ghi file `.docx` (chỉ cần cho ứng dụng web)

## Cách dùng

### 1) Dòng lệnh (CLI)

```bash
# Kiểm tra một chuỗi và in văn bản đã tự sửa
python Dictionary_Project/scripts/spellcheck_ocr.py "54u kh1 thực hịên nhiệmvụ" --fix

# Kiểm tra một file văn bản
python Dictionary_Project/scripts/spellcheck_ocr.py --file duong_dan.txt

# Chạy không tham số -> chạy phần demo
python Dictionary_Project/scripts/spellcheck_ocr.py
```

Tham số: `--file <đường_dẫn>`, `--fix` (in thêm văn bản đã tự sửa),
`--dict <đường_dẫn>` (đổi từ điển, mặc định `FINAL_dictionary.txt`).

Dùng lại trong code khác:

```python
from spellcheck_ocr import Dictionary, SpellChecker, autocorrect
checker = SpellChecker(Dictionary())
issues = checker.check("văn bản cần kiểm tra")
print(autocorrect("văn bản cần kiểm tra", issues))
```

### 2) Ứng dụng web

```bash
python Dictionary_Project/web/app.py    
```

- **Tải file `.docx`** → hiển thị nội dung.
- Từ nghi sai được **gạch chân lượn sóng**; bấm vào để chọn **gợi ý sửa**.
- **Sửa trực tiếp** trong khung; bấm *Kiểm tra lại* để soát lại.
- **Tải về** file `.docx` đã chỉnh sửa.

## Các loại lỗi được kiểm tra

| Loại | Ví dụ |
|---|---|
| OCR nhầm ký tự | `54u → sau`, `kh1 → khi`, `cật chất → vật chất` |
| Sai / mất dấu | `hịên → hiện`, `quy đjnh → quy định` |
| Dính từ (thiếu dấu cách) | `nhiệmvụ → nhiệm vụ` |
| Tách từ (thừa dấu cách) | `ng ành → ngành`, `rn ột → một` |
| Gợi ý cụm từ ghép | `hop dong → hợp đồng`, `phoi hop → phối hợp` |
| Viết hoa | đầu câu chưa hoa; lẫn hoa giữa từ `nGười → người` |

**Bỏ qua**: số, ngày tháng, mã văn bản (vd `123/2026/NĐ-CP`), URL/email.

## Thuật toán (tóm tắt)

Dùng **Trie** để tra cứu chính xác & tách từ dính; chuẩn hoá văn bản về dạng **"fold"**
(bỏ dấu + gộp các lớp ký tự dễ lẫn OCR) rồi dùng **rapidfuzz** tìm ứng viên gần nhất,
chấm điểm bằng khoảng cách có trọng số (tôn trọng dấu sẵn có). Gợi ý cụm chỉ nhận từ ghép
có thật trong từ điển.

Chi tiết đầy đủ xem [BAO_CAO_TIEN_DO.md](BAO_CAO_TIEN_DO.md).
