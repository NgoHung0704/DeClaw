# Phase 7 — Plugin Host: Hướng dẫn review cho người mới

> Branch: `feat/phase-7-plugin-host` (tách từ `main` sau khi Phase 6 merge)
> Tickets: DCL-090..097
> Spec: `docs/superpowers/specs/2026-08-23-phase-7-plugin-host-design.md`
> Roadmap 3 phase: `docs/superpowers/specs/2026-08-23-phase-7-9-roadmap.md`

## Mục lục

1. [TL;DR — 30 giây](#1-tldr--30-giây)
2. [Phase 7 làm gì, và KHÔNG làm gì](#2-phase-7-làm-gì-và-không-làm-gì)
3. [Kiến trúc: hai package, mười module](#3-kiến-trúc-hai-package-mười-module)
4. [SDK — thứ plugin được viết dựa trên](#4-sdk--thứ-plugin-được-viết-dựa-trên)
5. [Host — thứ chạy và kiểm soát plugin](#5-host--thứ-chạy-và-kiểm-soát-plugin)
6. [Auto-grant: quyết định gây tranh cãi nhất](#6-auto-grant-quyết-định-gây-tranh-cãi-nhất)
7. [Ba lỗi thiết kế do CHẠY spec mới lộ ra](#7-ba-lỗi-thiết-kế-do-chạy-spec-mới-lộ-ra)
8. [Giới hạn trung thực — đọc phần này](#8-giới-hạn-trung-thực--đọc-phần-này)
9. [Con số](#9-con-số)
10. [Tiếp theo](#10-tiếp-theo)

---

## 1. TL;DR — 30 giây

Phase 7 làm cho locked decision **"plugin-first — mọi capability là một plugin
trong process riêng"** trở thành thật, cho đúng một plugin mà v0.1 sẽ ship
(doc-intel, Phase 8), mà **không** xây app store.

Cụ thể: core có thể tìm plugin ship kèm ứng dụng, chạy nó trong một process
cách ly, hỏi nó làm được gì, gọi nó, sống sót khi nó crash, tắt nó, và phơi bày
một số capability cho brain dưới dạng tool typed bình thường.

```
declaw chat
   |
   v
PluginHost.start()  ->  discover  ->  spawn  ->  describe  ->  validate
                                                                  |
                            model_tools()  <---------------------- +
                                  |
                                  v
                          ToolRegistry  ->  bind_tools  ->  brain
```

Ba thứ đáng chú ý nhất với người review:

- **`exposed_to_model`** — không phải capability nào cũng là tool cho model.
  `doc-intel.parse` là hạ tầng cho indexer, model không bao giờ được thấy.
- **Auto-grant cho builtin plugin** — có audit, có `declaw plugins list`, có
  revoke vĩnh viễn. Lý do và giới hạn ở [mục 6](#6-auto-grant-quyết-định-gây-tranh-cãi-nhất).
- **Subprocess KHÔNG phải sandbox bảo mật.** Đọc [mục 8](#8-giới-hạn-trung-thực--đọc-phần-này)
  trước khi trích dẫn Phase 7 như một lớp phòng thủ.

---

## 2. Phase 7 làm gì, và KHÔNG làm gì

### Làm

| Ticket | Nội dung |
| --- | --- |
| DCL-090 | Discovery + validate capability lúc load |
| DCL-091 | Enable / disable / quarantine (KHÔNG có install/uninstall/update) |
| DCL-092 | Subprocess với env dựng từ đầu, import blocker, stdout hygiene |
| DCL-093 | Protocol NDJSON giới hạn 32 MiB + codec + JSON Schema → pydantic |
| DCL-094 | Package `declaw_plugin_sdk` |
| DCL-095 | `plugin_state.json` (JSON phẳng, KHÔNG phải SQLite) |
| DCL-096 | Backoff, đếm crash, quarantine, timeout |
| DCL-097 | Vi phạm quyền chặn lúc load; vi phạm protocol giết process |

### Không làm (hoãn có chủ đích, không phải bỏ quên)

- **Cài plugin bên thứ ba.** v0.1 chỉ quét `plugins/builtin/` nằm trong thư mục
  ứng dụng — nghiêm ngặt hơn cả kiểm chữ ký. `signing.py` (DCL-083) không bị
  đụng tới, chờ luồng install.
- **DCL-071/072/073 (credential API cho plugin).** `CLAUDE.md` từng định gộp
  vào Phase 7. Quyết định "doc-intel là plugin mỏng" xoá lý do đó: một plugin
  chỉ parse tài liệu thì không cần secret nào. Permission `credentials` vẫn nằm
  trong enum, chưa ai dùng.
- **Nhiều request song song trên một plugin.** Một request tại một thời điểm.
  Frame vẫn mang `id`, nên thêm process pool sau này không phá tương thích.

### 5 điểm lệch so với `TICKETS.md` gốc

| Ticket | Lệch chỗ nào |
| --- | --- |
| DCL-091 | Thu hẹp còn enable/disable/quarantine |
| DCL-092 | Acceptance viết lại trung thực: import hook là ranh giới kiến trúc, không phải bảo mật |
| DCL-094 | SDK là package top-level `declaw_plugin_sdk/`, không nằm trong `declaw/` |
| DCL-095 | `plugin_state.json` thay cho `installed.db` |
| DCL-097 | Vi phạm quyền bắt lúc load; trigger runtime là vi phạm protocol |

---

## 3. Kiến trúc: hai package, mười module

### `declaw_plugin_sdk/` — plugin viết dựa trên cái này

| File | Nhiệm vụ |
| --- | --- |
| `protocol.py` | Frame models, error codes, version. **Dùng chung**: host cũng import |
| `declaration.py` | `BasePlugin`, decorator `@capability` |
| `_isolation.py` | Chặn import `declaw.*` |
| `runtime.py` | Vòng lặp dispatch đồng bộ |
| `bootstrap.py` | Entry `python -m`: dup stdout, cài blocker, import entrypoint, chạy |

**Vì sao protocol nằm ở SDK chứ không ở host?** SDK không được import `declaw`.
Nếu định nghĩa frame nằm ở host thì plugin phải có bản sao riêng, và hai bên sẽ
trôi lệch nhau. `declaw` import `declaw_plugin_sdk` là hoàn toàn ổn — blocker
chỉ chặn chiều ngược lại.

### `declaw/plugin_host/` — core chạy plugin

| File | Nhiệm vụ |
| --- | --- |
| `errors.py` | Toàn bộ taxonomy lỗi, một chỗ |
| `ipc.py` | Encode/decode NDJSON có giới hạn kích thước |
| `schema.py` | JSON Schema → pydantic model (tập con hạn chế) |
| `process.py` | Spawn, env sạch, drain stderr, thang shutdown |
| `state.py` | `plugin_state.json` |
| `loader.py` | Discovery + validate capability đối chiếu manifest |
| `supervisor.py` | Backoff, đếm crash/vi phạm, quarantine, timeout |
| `tools.py` | `PluginTool` proxy |
| `host.py` | Facade `PluginHost` — thứ duy nhất phần còn lại của app chạm vào |
| `grants_helper.py` | Đường dẫn file grants/state, một chỗ duy nhất |

Cộng với `manifest.py`, `permissions.py`, `signing.py` đã có từ Phase 6.

---

## 4. SDK — thứ plugin được viết dựa trên

### Một plugin trông như thế nào

```python
# tests/fixtures/plugins/echo-plugin/main.py
class EchoArgs(BaseModel):
    message: str
    times: int = 1


class EchoPlugin(BasePlugin):
    name = "echo-plugin"
    version = "1.0.0"

    @capability(
        name="echo",
        description_en="Repeat a message back.",
        description_fr="Renvoie un message.",
        exposed_to_model=True,
        classification="read",
    )
    async def echo(self, args: EchoArgs) -> str:
        return " ".join([args.message] * args.times)
```

Cộng một `plugin.yaml` khai báo tên, version, entrypoint, và **permission mà
plugin xin**. Hết. Tác giả plugin không bao giờ parse input thô: model pydantic
là hợp đồng, JSON Schema của nó bay sang host, host dựng lại và validate mọi
lời gọi **trước khi** plugin được hỏi.

### Mọi default đều fail-safe

| Flag | Default | Quên khai báo thì sao |
| --- | --- | --- |
| `exposed_to_model` | `False` | Model không thấy capability |
| `classification` | `"write"` | Bị chặn sau confirmation gate |
| `produces_external_content` | `False` | (an toàn: không claim là nội dung ngoài) |
| `requires` | `()` | Không xin quyền nào |
| `timeout_s` | `120` | |

Sai sót làm hệ thống **im hơn và chặt hơn**, không bao giờ ồn hơn và lỏng hơn.

### Vì sao vòng lặp SDK là ĐỒNG BỘ

Trên Windows, Proactor event loop **không** `connect_read_pipe` được vào stdin
trong tiến trình con. Mà chỉ có một request tại một thời điểm, nên một vòng lặp
đọc blocking với `asyncio.run()` mỗi request vừa đơn giản hơn vừa chạy được trên
mọi nền tảng. Capability vẫn viết bằng `async def`.

### stdout hygiene

Một `print()` lỡ tay trong plugin sẽ phá stream protocol. `bootstrap.py` xử lý
trước khi bất kỳ dòng code plugin nào chạy:

```python
protocol_fd = os.dup(1)   # giữ stdout thật cho frame
os.dup2(2, 1)             # mọi thứ ghi ra stdout từ giờ đi vào stderr
```

Có capability `noisy` trong echo fixture cố tình `print()` để test điều này.
Kiểm bằng tay:

```bash
printf '%s\n%s\n' \
  '{"v":1,"id":"1","method":"invoke","params":{"capability":"noisy","args":{"message":"ok"}}}' \
  '{"v":1,"id":"2","method":"describe","params":{}}' \
  | uv run python -m declaw_plugin_sdk.bootstrap tests/fixtures/plugins/echo-plugin main.py 2>/dev/null
```

Hai frame JSON sạch. Dòng `print` đi vào stderr.

### Import blocker — đọc kỹ chỗ này

```python
if fullname == "declaw" or fullname.startswith("declaw."):
    raise ImportError(...)
```

Chú ý điều kiện: `declaw_plugin_sdk` **bắt đầu bằng** `"declaw"` nhưng không
phải `"declaw."`, nên nó qua được. Một prefix check ngây thơ sẽ chặn chính SDK
mà plugin cần. Có test riêng cho đúng cái bẫy này.

**Đây là ranh giới kiến trúc, không phải bảo mật.** Xem [mục 8](#8-giới-hạn-trung-thực--đọc-phần-này).

---

## 5. Host — thứ chạy và kiểm soát plugin

### Protocol

NDJSON, một object mỗi dòng, tối đa **32 MiB**. Chọn NDJSON thay vì length-prefix
vì JSON tự escape newline nên một-object-một-dòng là không nhập nhằng, và stream
hỏng vẫn đọc được bằng mắt trong log.

```
Request : {"v":1,"id":"<uuid>","method":"describe|invoke|shutdown","params":{}}
Response: {"v":1,"id":"<uuid>","ok":true,"result":...}
          {"v":1,"id":"<uuid>","ok":false,"error":{"code":"...","message":"..."}}
```

Giới hạn kích thước ép ở **cả hai chiều**: `encode_frame` từ chối phát frame quá
cỡ, nên ta không bao giờ ghi thứ mà đầu kia buộc phải từ chối.

### Env được DỰNG, không phải lọc

```python
env = {
    "PATH": os.environ.get("PATH", ""),
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
    "DECLAW_PLUGIN_NAME": plugin_name,
}
for name in ("SystemRoot", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME"):
    ...
```

Lọc thì quên biến, dựng thì không thể quên. Không một `DECLAW_*` nào (ngoài tên
plugin), không `OLLAMA_*`, không keyring, không biến môi trường của user.
`tests/security/` chứng minh bằng cách hỏi chính plugin xem nó thấy gì.

### stderr PHẢI được drain

Một pipe stderr không ai đọc sẽ đầy buffer của OS rồi **chặn plugin giữa chừng
khi ghi** — nhìn y hệt như treo. Một task nền drain nó suốt vòng đời process.
Nếu integration test bị treo, đây là nghi phạm số một.

### JSON Schema → pydantic: chi tiết dễ chết người

pydantic render `int | None` thành:

```json
{"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null}
```

Đó chính là schema mà SDK phát ra cho một tham số optional. Nếu host từ chối
`anyOf` chung chung thì **mọi plugin có tham số optional đều không load được**.
`_unwrap_nullable` chấp nhận đúng dạng hai-nhánh này và vẫn từ chối `anyOf`
tổng quát. Điều này được kiểm bằng cách chạy `model_json_schema()` thật, không
phải đoán.

### Một tổ hợp bị từ chối thẳng lúc load

Capability vừa `exposed_to_model`, vừa non-READ, vừa `produces_external_content`.

Lý do: `ToolRegistry.langchain_tools` bọc sanitizer cho tool READ có external
content, và bọc confirmation cho tool non-READ — **không bao giờ ghép cả hai**.
Nên tổ hợp đó sẽ tới model mà chưa qua sanitizer. Không plugin nào cần hình
dạng này, nên chặn thẳng thay vì để một cái hố chờ plugin tương lai rơi vào.

### Supervisor: hai bộ đếm, hai ý nghĩa

| | Ngưỡng | Có cửa sổ thời gian? | Vì sao |
| --- | --- | --- | --- |
| Crash | 3 | Có, 300s | Crash có thể do môi trường, nhất thời → tha thứ cái cũ |
| Vi phạm protocol | 3 | Không, cộng dồn | Frame sai không nhất thời: plugin hoặc nói đúng protocol hoặc không |

Backoff: `1, 2, 4, 8, 16, 32, 60, 60...` giây. `clock` và `sleep` được inject nên
toàn bộ chính sách được test mà không tốn một giây thật nào.

**Sau timeout, process BẮT BUỘC bị giết, không tái sử dụng** — câu trả lời chưa
đọc vẫn nằm trong pipe và sẽ bị nhầm là phản hồi của request kế tiếp.

### `plugin_state.json` — vì sao không phải SQLite

File này là **chính sách của người dùng**. Mở ra đọc được, diff được, là một
tính năng minh bạch chứ không phải chi tiết cài đặt. Bốn trường mỗi plugin không
đáng để thêm một database thứ hai với chuỗi migration riêng.

Bộ đếm crash **không** được lưu: khởi động lại DeClaw cho plugin hỏng một cơ hội
mới; nếu vẫn hỏng thì bị quarantine lại trong chưa tới một phút. Còn quarantine
thì được lưu, vì gỡ nó phải là hành động có chủ ý của người dùng.

---

## 6. Auto-grant: quyết định gây tranh cãi nhất

### Vấn đề

`plugin_grants.json` rỗng khi mới cài. Nếu không làm gì, `doc-intel` sẽ có
`filesystem.read` ở trạng thái *đã xin nhưng chưa được cấp*, và **mọi lời gọi
đều thất bại** — mà dialog cấp quyền thì tận Phase 9 mới có.

### Quyết định

**Builtin plugin được tự động cấp đúng những quyền manifest của nó xin, một
lần, minh bạch.**

Lập luận hẹp và không được suy rộng: một builtin plugin nằm trong chính binary
của ứng dụng, nên người dùng không tin nó thì cũng không thể tin DeClaw — không
có quyết định tin cậy riêng nào để hỏi. Hỏi chỉ tập cho người ta thói quen bấm
qua loa.

Thứ làm cho việc này chấp nhận được là **minh bạch + đảo ngược được**:

- mỗi lần auto-grant phát một `PluginPermissionEvent` `action="granted"` → vào
  audit trail và daily report
- `declaw plugins list` hiện mọi quyền và trạng thái cấp của nó
- `declaw plugins revoke <plugin> <permission>` có tác dụng, và **quyền đã bị
  revoke sẽ không bao giờ được auto-grant lại** — nhờ trường `auto_granted`
  trong `plugin_state.json` ghi nhớ "đã từng đề nghị một lần"

### Điều BẮT BUỘC phải làm khi mở luồng install bên thứ ba

Đóng đường auto-grant lại, trong chính change đó. Lập luận trên không sống sót
qua khỏi biên giới builtin dù chỉ một bước. Đã ghi vào danh sách deferred của
roadmap.

---

## 7. Ba lỗi thiết kế do CHẠY spec mới lộ ra

Ghi lại vì đây là bằng chứng cụ thể rằng đọc spec không thay được chạy spec.

### 7.1 `VIOLATION_LIMIT` không bao giờ với tới được

Spec viết: đếm vi phạm protocol "trong một vòng đời process", reset khi restart.

Nhưng **vi phạm đầu tiên đã giết process rồi**. Nên một bộ đếm per-process không
bao giờ vượt quá 1, và ngưỡng 3 là bất khả thi. Quy tắc quarantine đó lẽ ra đã
ship dưới dạng một luật không bao giờ kích hoạt.

Sửa: vi phạm được đếm cộng dồn. Sự bất đối xứng với crash giờ được ghi rõ trong
docstring và có test riêng.

### 7.2 `unknown_method` là code chết

`RequestFrame` khai `method` là `Literal`, nên một method lạ bị validation gộp
vào lỗi parse chung chung. Error code `unknown_method` trong protocol không bao
giờ phát ra — một lời nói dối nhỏ mà người đọc sau này sẽ vấp phải.

Sửa: kiểm method **trước** khi model-validate. Version skew với host mới hơn giờ
báo đúng `unknown_method` và echo lại `id`, thay vì trông như frame rác.

### 7.3 `CapabilitySpec.func` khai sai kiểu

Khai `Awaitable`, nhưng `asyncio.run()` không nhận `Awaitable` trần. mypy bắt
được. Sửa thành `Coroutine`, và decorator được làm generic để method giữ nguyên
signature cho người gọi.

### Ngoài ra, plan cũng sai một chỗ

Plan ghi chữ ký `resolve_in_workspace(raw_path, workspace)`. Code thật là
`_resolve_in_workspace(raw_path)` — nó tự đọc workspace từ settings. Move là
move nguyên văn; code thắng plan.

---

## 8. Giới hạn trung thực — đọc phần này

Viết ra vì văn hoá dự án này là ghi lại thực tế đo được chứ không phải ý định,
và vì nếu không viết thì người ta sẽ đọc chúng như những bảo đảm.

### 8.1 Plugin độc hại KHÔNG bị ngăn chặn

Nó chạy với **toàn bộ quyền của người dùng**. Nó đọc được mọi file người dùng
đọc được, mở được socket, và gỡ được import blocker bằng một dòng.

Cái ranh giới process thật sự cho ta:

- crash isolation (plugin chết không kéo core theo)
- không chung memory
- không có handle keyring
- environment sạch
- một process có thể giết được

Ngăn chặn thật cần **OS-level sandboxing** — đúng bài toán Phase 3 đang bị hoãn.

### 8.2 Permission chỉ được cưỡng chế phía host

Nó quản việc **core sẽ làm gì THAY MẶT plugin** — path nào core validate,
capability nào core dispatch. Nó không ngăn được plugin tự hành động.

### 8.3 Code builtin plugin không được verify chữ ký trong v0.1

Nó nằm trong ứng dụng; nếu ứng dụng bị sửa đổi thì core cũng đã bị xâm phạm rồi.
Và nhắc lại từ roadmap: DCL-083 ký `plugin.yaml`, **không ký code**. Khi luồng
install quay lại, manifest phải có thêm map `files:` path → sha256.

### 8.4 Một request mỗi lần cho mỗi plugin

Một lần parse dài sẽ chặn các lời gọi khác tới cùng plugin đó. Chấp nhận được vì
core mới là bên điều phối indexing, và đường chat (RAG search) không chạm plugin.

### 8.5 Giết process không giết process con (Windows)

Không plugin v0.1 nào sinh process con, và loader không có cách nào ngăn một
plugin làm vậy. Ghi nhận là giới hạn đã biết chứ không che đi.

---

## 9. Con số

```
pytest        606 passed, 1 skipped   (chạy 2 lần, cùng kết quả)
mypy          Success: no issues found in 84 source files   (strict)
ruff          All checks passed!
```

Phân bố test mới của Phase 7:

| Nhóm | Số test | Chạy subprocess thật? |
| --- | --- | --- |
| `test_plugin_protocol.py` | 8 | không |
| `test_plugin_ipc.py` | 10 | không |
| `test_plugin_schema.py` | 15 | không |
| `test_plugin_declaration.py` | 8 | không |
| `test_plugin_runtime.py` | 13 | không |
| `test_plugin_env.py` | 5 | không |
| `test_plugin_state.py` | 9 | không |
| `test_plugin_loader.py` | 16 | không |
| `test_plugin_supervisor.py` | 12 | không |
| `test_plugin_tools.py` | 10 | không |
| `test_cli_plugins.py` | 6 | không |
| `integration/test_plugin_process.py` | 7 | **có** |
| `integration/test_plugin_supervision.py` | 3 | **có** |
| `integration/test_plugin_host.py` | 10 | **có** |
| `security/test_plugin_isolation.py` | 7 | **có** |

Toàn bộ đều **tất định**: không cần Ollama, không cần Docker, không cần mạng.
Test có sleep đều inject `sleep` giả. Test hang-plugin xong trong ~1 giây chứ
không phải một giờ.

Năm plugin fixture dưới `tests/fixtures/plugins/`: `echo-plugin` (tham chiếu),
`crash-plugin` (`os._exit` giữa request), `hang-plugin` (không bao giờ trả lời),
`probe-plugin` (báo cáo sandbox của chính nó), `overreach-plugin` (xin nhiều hơn
manifest).

### Kiểm bằng tay

```bash
uv run declaw plugins list      # hiện "No plugins found." — plugins/builtin trống
uv run declaw chat              # banner + "plugins: none", /exit thoát sạch
```

`plugins: none` là **đúng**: `plugins/builtin/` chỉ có `.gitkeep` cho tới khi
doc-intel xuất hiện ở Phase 8.

---

## 10. Tiếp theo

**Phase 8 — doc-intel**, trên branch tách từ branch này.

Ranh giới đã chốt (roadmap decision 3): **plugin mỏng**.

- *Trong plugin*: parser PDF/DOCX/XLSX/TXT+MD và chunker. Đây là code đọc file
  nhị phân thù địch do người lạ gửi tới, và mang các dependency nặng
  (`pypdf`, `unstructured`, `openpyxl`). Chính xác là thứ đáng bỏ một ranh giới
  process ra để bọc.
- *Trong core* (`declaw/documents/`): embedding, mã hoá Fernet, collection
  Chroma `declaw_documents`, incremental theo hash, watcher, search, citations,
  actions.

Hai điều đã quyết trước, đừng mở lại nếu không có dữ liệu mới:

- **Citation là cấu trúc, không do model sinh** — tool trả về chunk kèm metadata
  nguồn, UI hiển thị nguồn thực sự được retrieve, bất kể model có trích dẫn
  inline hay không. Cùng lý do đã khiến DCL-062 dùng template tất định.
- **Sanitize chunk ở thời điểm retrieval, chỉ top-k, cache theo SHA-256.** Cách
  làm trong ticket gốc (sanitize mọi chunk lúc index) tốn 10-20 phút cho một PDF
  100 trang ở p50 4.19s của `qwen2.5:7b`.

Khi bắt đầu Phase 8, nhớ đọc lại `docs/superpowers/specs/2026-08-23-phase-7-9-roadmap.md`
mục "Deferred to v0.2 or later" — nhất là dòng về install-time permission dialog.
