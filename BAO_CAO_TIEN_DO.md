# Báo cáo tiến độ — Công cụ kiểm tra chính tả OCR tiếng Việt dùng cho văn bản hành chính nhà nước

> Cập nhật: 2026-06-19
> Phạm vi: bộ kiểm tra chính tả cho văn bản hành chính số hoá (OCR), gồm thư viện lõi và ứng dụng web tải/sửa file `.docx`.

---

## 1. Tổng quan

Công cụ phát hiện và gợi ý sửa các lỗi **do OCR** trong văn bản tiếng Việt, tập trung vào:
lẫn ký tự, mất/sai dấu, lỗi dấu cách, sai chính tả, gợi ý cụm từ ghép, và viết hoa.
Người dùng có thể tải file `.docx` lên web, xem nội dung, bấm vào từ gạch chân để chọn
gợi ý, sửa trực tiếp và tải file đã sửa về.


## 2. Công nghệ sử dụng

| Hạng mục | Công nghệ |
|---|---|
| Ngôn ngữ | Python 3.14 |
| Fuzzy matching | **rapidfuzz 3.14** |
| Chuẩn hoá Unicode | `unicodedata` (NFC / NFD) |

---

## 3. Dữ liệu từ điển

- **Nguồn**: corpus ~3,5 triệu ký tự trích từ 100 văn bản hành chính (PDF có text-layer + crawl),
  đã sửa OCR sơ bộ, tách từ bằng `pyvi`, lọc tần suất ≥ 2.
- **`FINAL_dictionary.txt`**: >4500 từ (âm tiết + từ ghép)

---

## 4. Thuật toán

### 4.1. Cấu trúc dữ liệu
- **Prefix tree (Trie)**: tra cứu chính xác âm tiết và tách từ dính.
- **Bản đồ "fold" → âm tiết**: khoá là dạng chuẩn hoá khử nhiễu OCR, dùng làm không gian tìm kiếm cho rapidfuzz.

### 4.2. Chuẩn hoá hai mức
1. **skeleton**: bỏ toàn bộ dấu thanh/dấu phụ, `đ→d`, về chữ thường.
2. **fold** = skeleton + **gộp các lớp ký tự dễ lẫn OCR** về một đại diện:
   `0→o, 1/l/j→i, 5→s, 8→b, rn→m, cl→d, vv→w …`

### 4.3. Sinh ứng viên & chấm điểm
- **Sinh ứng viên**: `rapidfuzz.process.extract` với scorer Damerau–Levenshtein chạy trên tập khoá fold (ngưỡng khoảng cách 1–2 tuỳ độ dài).
- **Chấm điểm** bằng *khoảng cách có trọng số* trên token gốc (giữ được dấu sẵn có):
  - cùng ký tự = 0; khác dấu cùng chữ gốc = 0.3; cùng lớp OCR = 0.2; khác hẳn = 1.0.
  - Trường hợp **chỉ sai dấu** (cùng skeleton) → tin **tần suất** thay vì khoảng cách

### 4.4. Lỗi dấu cách
- **Dính từ** (`spacing_merge`): quy hoạch động trên Trie để tách 1 token thành chuỗi âm tiết
  hợp lệ (vd "nhiệmvụ" → "nhiệm vụ"), không tách mảnh 1 ký tự.
- **Tách từ** (`spacing_split`): ghép token với token kế (kể cả khi còn lẫn OCR qua fold),
  vd "ng ành" → "ngành", "rn ột" → "một".

### 4.5. Gợi ý cụm từ ghép
- Ghép token với hàng xóm (trái/phải) và **chỉ nhận cụm là từ ghép có thật** trong từ điển
  (vd "hop dong" → "hợp đồng", "phoi hop" → "phối hợp", "cật chất" → "vật chất").
- Ghép trái chỉ được đổi **dấu** của token bên trái (không đổi chữ gốc đã đúng).

### 4.6. Viết hoa
- **Đầu câu phải viết hoa**: đầu đoạn hoặc sau `. ! ? …`.
- **Viết hoa sai giữa từ** (mẫu thường→HOA kiểu OCR): "nGười" → "người/Người".
- An toàn với từ viết tắt toàn HOA (UBND, TW) và danh từ riêng viết hoa giữa câu (Đảng).

### 4.7. Loại trừ (bỏ qua)
Số, ngày tháng, phần trăm, mã văn bản (chứa `/`), URL/email; token chữ + số chỉ được sửa khi "fold" ra **đúng** một âm tiết thật (vd "54u"→"sau", còn "A80" giữ nguyên).

---

## 5. Mức độ hoàn thiện

| Tính năng | Trạng thái | Ghi chú |
|---|---|---|
| Lẫn ký tự OCR| ✅ | `54u → sau`, `kh1 → khi` |
| Mất / sai dấu | ✅ | xếp hạng theo freq |
| Gợi ý cụm từ ghép (2 từ) | ✅ | chỉ cụm có thật trong từ điển |
| Kiểm tra viết hoa | ✅ | đầu câu + viết hoa giữa từ |
| Danh từ riêng thiếu hoa | ❌ |  |
| Lỗi "từ đúng nhưng sai ngữ cảnh" | ❌ |  |


---

## 6. Các trường hợp chưa kiểm tra được

1. **Danh từ riêng thiếu viết hoa**
2. **Lỗi real-word error** 
3. **OCR mất nguyên âm**
4. **Từ bị OCR nhầm kí tự chữ thành kí tự số (trên 2 kí tự)** 
5. **Cụm từ > 2 âm tiết** 
---

## 7. Kế hoạch cải tiến

- **Tạo từ điển tên riêng**: bổ sung danh sách tỉnh/thành/họ tên thông dụng để phát hiện danh từ riêng thiếu hoa.
- **Mở rộng từ điển**
- **Sửa chính tả cụm 3+ âm tiết**
- **Khôi phục nguyên âm bị mất**


---

