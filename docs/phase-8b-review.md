# Phase 8b — actions, reconciliation, benchmark: Hướng dẫn review

> Branch: `feat/phase-8b-actions-benchmark` (tách từ `feat/phase-7-plugin-host`)
> Tickets: DCL-113..117, cộng một defect không có ticket nhưng quan trọng hơn cả
> Spec: `docs/superpowers/specs/2026-08-26-phase-8b-actions-benchmark.md`
> Plan: `docs/superpowers/plans/2026-08-26-phase-8b-actions-benchmark.md`

## Mục lục

1. [TL;DR](#1-tldr)
2. [Defect quan trọng nhất: index không bao giờ quên](#2-defect-quan-trọng-nhất-index-không-bao-giờ-quên)
3. [Vì sao DCL-114/115 không viết tool mới](#3-vì-sao-dcl-114115-không-viết-tool-mới)
4. [Vì sao summarize được phép dùng LLM](#4-vì-sao-summarize-được-phép-dùng-llm)
5. [Con số benchmark — và nó nói gì](#5-con-số-benchmark--và-nó-nói-gì)
6. [Giới hạn trung thực](#6-giới-hạn-trung-thực)

---

## 1. TL;DR

Phase 8b đóng **MVP DoD #4** (move / rename / summarize bằng ngôn ngữ tự nhiên,
có xác nhận), sửa một defect đã ship ở 8a, và lần đầu tiên đặt một con số **không
tự chấm** lên chất lượng retrieval.

```
pytest   784 passed, 1 skipped   (chạy 2 lần, giống hệt)
mypy     Success: no issues found in 100 source files   (strict)
ruff     All checks passed!
```

41 test mới. Con số quan trọng nhất của phase này:

```
development  recall@1 0.58  recall@5 0.92  MRR 0.75  (n=12)
held-out     recall@1 0.50  recall@5 0.50  MRR 0.50  (n=10)
```

**Chênh 42 điểm.** Xem [mục 5](#5-con-số-benchmark--và-nó-nói-gì) trước khi trích
dẫn bất kỳ con số nào trong đó.

---

## 2. Defect quan trọng nhất: index không bao giờ quên

Phase 8a ship một index không bao giờ quên. Đo được, không phải suy đoán:

```
                     TRƯỚC khi sửa                          SAU khi sửa
after index:   chunks=1 catalog=['contrat.txt']        chunks=1 ['contrat.txt']
after RENAME:  chunks=2 ['archive.txt','contrat.txt']  chunks=1 ['archive.txt']
after DELETE:  chunks=2 (vẫn còn nguyên)               chunks=0 []
search cites:  2 file KHÔNG TỒN TẠI                    []
files on disk: []                                       []
```

`DocumentIndexer.index()` duyệt các file **đang tồn tại**. File bị đổi tên hoặc
bị xoá không bao giờ được ghé qua, nên `store.delete_document()` và
`catalog.forget()` không bao giờ được gọi.

Ba hệ quả, tăng dần mức nghiêm trọng:

1. Đổi tên **nhân đôi** tài liệu thay vì di chuyển nó.
2. Trích dẫn trỏ tới đường dẫn không tồn tại — phá huỷ đúng cái tính chất mà cả
   Phase 8a được xây để bảo đảm.
3. **Tài liệu đã xoá vẫn tiếp tục bị trích dẫn.** Với sản phẩm bán cho giới
   chuyên môn EU dựa trên lập luận GDPR, việc giữ lại và hiển thị nội dung một
   file người dùng đã xoá là vấn đề **quyền được xoá**, không phải vấn đề dữ
   liệu cũ.

### Chi tiết dễ làm sai: phạm vi prune

`declaw index dossier/` chỉ duyệt một thư mục con. Nếu so sánh với **toàn bộ**
catalog, nó sẽ xoá index của mọi tài liệu ngoài thư mục đó.

Quy tắc: **phạm vi prune phải bằng phạm vi duyệt.** Cả hai nửa đều có test riêng
— `test_indexing_a_subfolder_does_not_prune_outside_it` tồn tại chính vì làm sai
chỗ này sẽ xoá index của người dùng.

---

## 3. Vì sao DCL-114/115 không viết tool mới

`FilesystemMoveTool` (DCL-023) **đã** làm move **và** rename, **đã** là
WRITE-class nên registry **đã** bọc nó sau cổng xác nhận, **đã** từ chối ghi đè
nếu không có cờ tường minh, và **đã** được nối vào `declaw chat`. Cả hai ticket
đều ghi dependency là DCL-023.

Viết tool move thứ hai sẽ là trùng lặp — và tệ hơn: hai tool tên na ná nhau đúng
là thứ mà probe Phase 1 cho thấy model 3B xử lý rất tệ.

Cái **thiếu** không phải là tool, mà là bằng chứng rằng **index đi theo file**.
Đó là thứ `tests/integration/test_document_actions_e2e.py` bổ sung: rename qua
cổng xác nhận, move bị từ chối thì không có gì thay đổi, và `organize_files` +
reindex để lại đúng một entry cho mỗi file thay vì hai.

---

## 4. Vì sao summarize được phép dùng LLM

DCL-062 đã chốt: audit summary phải dùng template **tất định**, vì không được
phép hallucinate. Vậy tại sao DCL-113 lại để model viết văn?

Vì hai thứ đó là **hai loại đối tượng khác nhau**:

- Audit summary là **bằng chứng** — người đọc là người đang kiểm tra tuân thủ.
  Một câu nghe hợp lý nhưng sai còn tệ hơn không có gì.
- Document summary là **tiện ích phái sinh** người dùng chủ động yêu cầu và đọc
  với ý thức về nguồn gốc của nó.

Cái **sống sót** từ DCL-062 không phải "không bao giờ dùng model", mà là **"không
bao giờ để model bịa trích dẫn"**. Nên:

- model viết prose
- **tool tự chạy lại retrieval** và dựng khối Sources từ metadata thật
- file mang dòng provenance rõ ràng, EN và FR
- WRITE-class, nên không ghi gì trước khi người dùng duyệt

Có test chứng minh: model viết `"According to invented-source.pdf page 99"` —
chuỗi đó nằm trong prose của nó và **không bao giờ** xuất hiện trong khối Sources.

---

## 5. Con số benchmark — và nó nói gì

```
development  recall@1 0.58  recall@5 0.92  MRR 0.75  (n=12)
held-out     recall@1 0.50  recall@5 0.50  MRR 0.50  (n=10)
```

### Đọc đúng con số này

**Chỉ có con số held-out là có ý nghĩa.** Lý do phải nói thẳng:

Bộ development chỉ có 4 tài liệu sinh ra **4 chunk**. Bộ held-out có 4 tài liệu
sinh ra **1071 chunk**. Với 4 chunk, top-5 trả về gần như toàn bộ corpus — nên
0.92 gần như không đo cái gì cả. Nó là artefact của corpus quá nhỏ, không phải
bằng chứng retrieval tốt.

**Con số thật: recall@5 = 0.50 trên văn bản pháp lý EU thật.** Một nửa số câu
hỏi không lấy được đúng đoạn văn.

### Nó lặp lại đúng bài học của sanitizer

| | corpus tự viết | dữ liệu ngoài | chênh |
| --- | --- | --- | --- |
| Sanitizer (Phase 4) | 91.7% | 53.3% | 38 điểm |
| Retrieval (Phase 8b) | 92% | 50% | **42 điểm** |

Hai hệ thống khác nhau, cùng một hình dạng thất bại. Đây chính là lý do luật
held-out tồn tại, và là lý do nó phải được áp dụng **từ đầu** chứ không phải khi
đã muộn.

### 5 câu hỏi bị trượt (đều thuộc held-out)

Bốn trong năm câu trượt thuộc RGPD — tài liệu dài nhất (407k ký tự). Giả thuyết
đáng thử ở phase sau: chunk ~512 token quá nhỏ so với văn bản pháp lý, nơi một
điều khoản trải dài nhiều đoạn; hoặc `nomic-embed-text` yếu với tiếng Pháp pháp
lý. **Chưa kiểm chứng** — đừng ghi như thể đã biết nguyên nhân.

**Tuyệt đối không tinh chỉnh theo từng câu trượt trong held-out.** Sửa khái
niệm, rồi đo lại. Nếu không, held-out âm thầm trở thành tập huấn luyện thứ hai —
đúng cách sanitizer đã tự lừa mình 38 điểm.

---

## 6. Giới hạn trung thực

1. **Reconciliation chỉ chạy khi `declaw index`.** Giữa hai lần chạy, index vẫn
   có thể trích dẫn file người dùng vừa xoá một phút trước. Reconciliation liên
   tục cần gateway Phase 9 (component watcher đã xây sẵn từ 8a).
2. **`summary.md` ghi vào workspace nên sẽ bị index ở lần sau.** Dòng provenance
   giảm nhẹ chuyện này, không xoá bỏ được sự kỳ cục khi corpus chứa văn của
   chính trợ lý.
3. **`organize_files` validate-rồi-thực-thi, không nguyên tử.** Lỗi giữa chừng
   (đĩa lỗi, quyền thay đổi giữa validate và execute) để lại việc sắp xếp dở
   dang. Kết quả trả về liệt kê chính xác những move đã thành công.
4. **Benchmark đo retrieval, không đo câu trả lời.** recall@5 tốt mà model đọc
   sai đoạn văn vẫn cho trải nghiệm tệ, và con số này không bắt được điều đó.
5. **Vector embedding vẫn chưa mã hoá** (Phase 12), và reconciliation xoá chunk
   là xoá **logic** — Chroma không lập tức chà sạch segment trên đĩa. Cần nói rõ
   điều này trước khi tuyên bố bất cứ điều gì về quyền được xoá.
6. **`DocumentIndexer` nhận tham số `workspace` nhưng resolve path qua settings
   toàn cục.** Trong production hai thứ luôn trùng nhau nên không ai thấy; với
   thư mục tạm thì tham số đó là một lời nói dối. Script benchmark phải set env
   var để đi vòng. Đây là mùi thiết kế còn nợ lại từ 8a, chưa sửa vì
   `resolve_in_workspace` là ranh giới bảo mật, đáng có một change riêng.
