# Phase 8a — doc-intel: Hướng dẫn review cho người mới

> Branch: `feat/phase-8-doc-intel` (tách từ `feat/phase-7-plugin-host`)
> Tickets: DCL-100..112 (DCL-113..117 là Phase 8b)
> Spec: `docs/superpowers/specs/2026-08-23-phase-8a-doc-intel-design.md`
> Plan: `docs/superpowers/plans/2026-08-23-phase-8a-doc-intel.md`

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Ranh giới: vì sao plugin lại mỏng](#2-ranh-giới-vì-sao-plugin-lại-mỏng)
3. [Năm quyết định](#3-năm-quyết-định)
4. [Số đo thật](#4-số-đo-thật)
5. [Bốn lỗi lộ ra khi CHẠY](#5-bốn-lỗi-lộ-ra-khi-chạy)
6. [Giới hạn trung thực](#6-giới-hạn-trung-thực)
7. [Tiếp theo — Phase 8b](#7-tiếp-theo--phase-8b)

---

## 1. TL;DR — 30 giây

Phase 8a đóng **MVP DoD #2 và #3**: trỏ DeClaw vào thư mục PDF/DOCX/XLSX/TXT,
hỏi bằng tiếng Pháp hoặc tiếng Anh, nhận câu trả lời **có nguồn kiểm chứng được**.

```
declaw index                          declaw chat
     |                                     |
DocumentIndexer                    document_search (tool)
     |                                     |
     |  resolve_in_workspace               v
     v                              search() -> sanitize từng chunk (cache SHA-256)
PluginHost.call("doc-intel","parse")       |
     |                                     v
=== ranh giới process ===           DocumentStore <-> Chroma "declaw_documents"
     |                                            (Fernet at rest)
doc-intel plugin
  parsers/{pdf,docx,xlsx,text} + chunker
```

Ba điều đáng chú ý nhất:

- **Citation là cấu trúc, không do model sinh.** Đã kiểm chứng live với cả ba
  dạng trong một truy vấn: `contrat.pdf p.1-2`, `compte-rendu.docx - Compte rendu
  de reunion`, `budget.xlsx [Budget]`.
- **Chunk được sanitize lúc TRUY VẤN**, chỉ top-k, cache theo SHA-256. Sanitize
  lúc index sẽ tốn 10-20 phút cho một PDF 100 trang.
- **Người dùng được báo khi có passage bị giữ lại.** Giấu đi sẽ làm câu trả lời
  tệ hơn mà họ không hề biết.

---

## 2. Ranh giới: vì sao plugin lại mỏng

`pypdf`, `python-docx`, `openpyxl` đọc **file nhị phân thù địch do người lạ gửi
tới**. Đó chính xác là đoạn code đáng bỏ một ranh giới process ra để bọc — và là
đoạn duy nhất của doc-intel đáng làm vậy.

Mọi thứ phía sau (embedding, khoá mã hoá, vector store) ở lại core. Nhờ đó:

- không khoá Fernet nào đi qua ranh giới process
- chỉ một process ghi vào Chroma
- output của plugin = external content, đi qua sanitizer ở biên core một cách tự nhiên

Plugin khai đúng **một** capability, `parse`, với `exposed_to_model=False`: nó
là hạ tầng cho indexer, model không bao giờ được thấy. Có test riêng khẳng định
`host.model_tools() == []`.

---

## 3. Năm quyết định

### 3.1 Catalog dùng SQLite, không phải JSON

Ngược hẳn với quyết định `plugin_state.json` ở Phase 7 — và có lý do. File kia
giữ bốn trường **chính sách của người dùng**, nơi đọc/diff được là tính năng.
Cái này là index do máy quản lý trên hàng nghìn file, tra theo hash mỗi lần chạy.
Bài toán khác, kho lưu khác.

### 3.2 Bỏ `unstructured`; chỉ dùng pypdf

PDF scan cần OCR, và OCR là một tiểu dự án riêng (model weights, language pack,
tải về lúc chạy — trái với lời hứa offline).

Điều **tuyệt đối không được làm** là index nó thành rỗng: người dùng sau đó sẽ
nhận câu trả lời tự tin về một tài liệu mà DeClaw chưa từng đọc. Nên file như
vậy được báo `doc_type="pdf-scanned"` và indexer nói thẳng ra.

Bỏ `unstructured` còn cắt được một cây phụ thuộc lớn (weasel, wrapt,
webencodings...), có lợi cho MVP DoD #1.

### 3.3 `document_search` để `produces_external_content=False`

Nhìn qua tưởng sai, nên lý do được ghi ngay trong code. Sanitize xảy ra **bên
trong `search()`**, từng chunk, cache theo SHA-256, chạy song song. Nếu bật cờ
đó, registry wrapper sẽ sanitize lần **thứ hai** trên toàn bộ top-k đã nối lại —
một lời gọi lớn mỗi truy vấn, không cache được gì.

Ba test trong `tests/security/test_documents_isolation.py` giữ đúng bảo đảm
thật: không chunk nào tới model mà chưa được phân loại.

### 3.4 DCL-112 được viết lại

Ticket ghi "strict instruction to cite". Citation đã là cấu trúc, nên nửa đó
không ship. Cái ship là **khung dữ liệu** (data-not-instructions, cùng hình dạng
`brain/memory_context.py`) cộng phần nối sanitizer. **Không thêm system prompt** —
open decision từ Phase 1 vẫn còn hiệu lực.

### 3.5 Indexer nhận callback `on_progress`

Thanh tiến trình Rich hôm nay; Phase 9 stream qua WebSocket mà không phải sửa
indexer.

---

## 4. Số đo thật

Đo trên dev hardware (RTX 3050 Laptop 4GB), không phải ước lượng.

### Test

```
pytest   733 passed, 1 skipped   (chạy 2 lần, kết quả giống hệt)
mypy     Success: no issues found in 95 source files   (strict)
ruff     All checks passed!
```

**123 test mới** cho Phase 8a. Toàn bộ tất định: không cần Ollama, không mạng,
không sleep thật.

### Indexing

| | Thời gian | Kết quả |
| --- | --- | --- |
| Lần đầu (lạnh, gồm nạp model) | **9.6s** | Indexed 5, skipped 0, failed 0 |
| Lần hai (không đổi gì) | **5.5s** | Indexed 0, **skipped 5**, failed 0 |

DCL-108 hoạt động: lần hai không gọi parser lần nào.

### Truy vấn có trích dẫn

Một lượt `declaw chat` hoàn chỉnh (retrieval + sanitize + model suy luận):
**17.7s**, trong đó model reasoning chiếm phần lớn.

Sanitizer mỗi chunk trên `qwen2.5:7b`: **~4-5s ấm**, lần gọi lạnh đầu tiên
**31.1s** vì phải nạp model 7B. Con số ấm khớp với p50 4.19s đã ghi ở Phase 4.

### Citation — kiểm chứng live

Một truy vấn thật trả về đủ cả ba dạng:

```
Sources:
[1] contrat-martin-conseil.pdf p.1-2        <- khoảng trang
[2] compte-rendu.docx - Compte rendu de reunion   <- heading
[3] budget.xlsx [Budget]                    <- tên sheet
```

Không dòng nào do model viết ra.

### Sanitizer FP — đo cụ thể, xác nhận quyết định đã ghi

Lượt chat thật báo *"2 passage(s) were withheld"*. Truy nguyên: hai file
`test.txt`/`text.txt` còn sót từ phase trước, nội dung `my password is 1234`.

| Nội dung | qwen2.5:3b (`.env` máy này) | qwen2.5:7b (mặc định ship) |
| --- | --- | --- |
| `my password is 1234` | **BLOCK** — "Mentions a password" | SAFE |
| `Mon mot de passe est 1234` | SAFE | SAFE |
| Điều khoản hợp đồng tiếng Pháp | SAFE | SAFE |
| Injection thật | BLOCK | BLOCK |

**Đây KHÔNG phải regression.** Nó xác nhận đúng open decision đã ghi trong
`CLAUDE.md`: 3b có FP 7.5-9%, 7b có 0.0%. Bản fix secret-FP (2026-07-25) giữ
vững trên model được ship và hỏng trên bản 3b hạ cấp — giờ có một ca tái hiện
được cụ thể.

Tài liệu tiếng Pháp tự sinh: **0/6 bị giữ lại**. Giả thuyết "văn bản pháp lý
mang tính mệnh lệnh nên dễ bị nhầm là injection" đã được kiểm và **bác bỏ**.

---

## 5. Bốn lỗi lộ ra khi CHẠY

Ghi lại vì đọc plan không thay được chạy plan.

### 5.1 `has_model()` không khớp tag `:latest` — lỗi tệ nhất

`ollama pull nomic-embed-text` lưu model thành `nomic-embed-text:latest`, còn
config mang tên không tag. `has_model()` so khớp chính xác nên **không bao giờ
khớp**.

Hậu quả: người dùng làm theo đúng thông báo của chính chúng ta, tải model về, và
vẫn bị bảo là thiếu — một vòng lặp không lối thoát. Ảnh hưởng y hệt tới model
chat và sanitizer. Đã sửa: tên không tag khớp luôn với `:latest`.

### 5.2 Preflight không kiểm model embedding

Cùng loại lỗi `CLAUDE.md` đã ghi cho sanitizer model. Ollama trả **404 cho model
lạ**, nên `declaw index` báo lỗi HTTP trần trụi, vô nghĩa với người dùng. Đã
thêm check `ollama.embedding_model` và `declaw index` từ chối ngay từ đầu kèm
hướng dẫn.

### 5.3 `PdfError` không tồn tại trong pypdf 6.11

Tên thật là `PyPdfError`, và nó kế thừa `Exception` chứ không phải `ValueError`,
nên PDF hỏng sẽ **không** bị bắt một cách tình cờ.

### 5.4 Fixture test dùng `get_engine()` nên không cô lập

`get_engine()` là singleton memoize toàn tiến trình, nên mọi test dùng chung một
database và rò dữ liệu sang nhau. Phải dùng `build_engine(path)` — đúng cách
`tests/unit/test_db.py` vẫn làm.

### Ngoài ra

- alembic autogenerate không chạy được với driver async (`MissingGreenlet`);
  migration được viết tay. `env.py` mặc định dựng URL **sync**.
- Rich ngắt dòng ở 80 cột dưới `CliRunner`, nên assert vào một cụm từ có thể bị
  cắt giữa chừng sẽ hỏng — hãy chuẩn hoá khoảng trắng.
- **Trên Windows, đừng bao giờ chẩn đoán vấn đề encoding từ output console.**
  Lúc probe fpdf2, dấu tiếng Pháp trông như bị hỏng; dữ liệu vẫn đúng, chỉ là
  codepage của terminal làm hỏng `print`. Assert vào codepoint, đừng tin màn hình.

---

## 6. Giới hạn trung thực

1. **Không đọc được tài liệu scan.** Được báo rõ ràng chứ không im lặng bỏ qua,
   nhưng vẫn là lỗ hổng thật với thị trường mà rất nhiều hồ sơ là bản scan.
2. **Vector embedding KHÔNG được mã hoá.** Text chunk có Fernet, nhưng Chroma
   phải so sánh vector ở dạng thô, và embedding inversion có thể tái tạo gần
   đúng văn bản gốc. Đây là mục Phase 12 kế thừa từ DCL-051 — nhưng **mức phơi
   nhiễm giờ lớn hơn hẳn**: trước là ký ức của agent, giờ là **chính tài liệu
   của khách hàng**.
3. **Injection đã index được lưu ở dạng chưa phân loại.** Nó bị bắt trước khi
   vào context của model, không phải trước khi vào kho.
4. **Cache verdict nằm trong tiến trình**, nên truy vấn đầu sau mỗi lần khởi
   động lại phải trả giá lại.
5. **Chất lượng retrieval chưa được đo.** Phase 8a chỉ chứng minh bộ máy chạy
   đúng, không chứng minh câu trả lời tốt. Đó là việc của Phase 8b.
6. **Model 3B gọi tool không ổn định với câu hỏi tự nhiên.** Kiểm chứng live:
   *"Utilise l'outil document_search pour trouver le preavis..."* → model hỏi lại
   thay vì gọi tool; *"Use the document_search tool with query '...'"* → gọi đúng.
   Đây là trần năng lực của model đã ghi từ Phase 1, không phải lỗi nối dây.

---

## 7. Tiếp theo — Phase 8b

DCL-113..117: summarize, move, rename, organize, và benchmark chất lượng.

**Luật corpus đã chốt từ spec 8a, đừng mở lại:**

- **Bộ phát triển: tự sinh.** Hợp đồng/hoá đơn/thư từ tiếng Pháp viết cho dự án.
- **Bộ held-out: bên ngoài, giấy phép mở.** Vài tài liệu EUR-Lex/Légifrance,
  commit kèm ghi nguồn.
- **Không bao giờ tinh chỉnh theo từng ca hỏng trong held-out.** Sửa khái niệm
  rồi đo lại — nếu không held-out sẽ âm thầm biến thành tập huấn luyện thứ hai.

Lý do: sanitizer đạt 91.7% trên corpus của chính nó và 53.3% trên dữ liệu ngoài
— chênh 38 điểm.
