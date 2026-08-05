# Member Role Report — Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Đào Kiều Thịnh Quang |
| MSSV | 2A202601014 |
| Khóa/Lớp | K4 / D305 |
| Vai trò chính | Coordinator, Policy & Verifier, tích hợp end-to-end |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| A2A orchestration | `ecommerce_agents/coordinator.py` | 50 input JSON và domain-agent facts | 50 output JSON, A2A trace | Hoàn thành |
| EC_POLICY_V2 | `agents/policy.py` | Order/customer/payment/delivery facts | Issue, responsibility, refund, actions | Hoàn thành |
| Independent verification | `agents/verifier.py` | Raw CSV, input và output tổng hợp | Danh sách lỗi hoặc verification pass | Hoàn thành |
| Runtime/model audit | `llm.py`, `config.py`, `tracing.py` | Output đã pass deterministic verifier | 50 read-only model audits và metadata | Hoàn thành |
| Submission workflow | `cli.py`, tests, architecture | Source và generated artifacts | Validation command, ZIP guard, tài liệu | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Kiểm tra data integrity | Toàn pipeline | Xác minh các khóa order/customer/item/payment/product/seller không bị orphan |
| Debug kết nối provider | LLM audit | Chạy lại ngoài network sandbox; 50/50 audit approved |
| Security review | Git/submission | `.env` ignored, quyền 600, không có secret trong source/log/output |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Điều phối 7 agent role | `ecommerce_agents/` | Handoff có sender/recipient/digest rõ ràng | Kiểm tra `logging/trace.jsonl` |
| Áp dụng policy cho 50 case | `output/EC_*.json` | Đủ cả 6 primary issue, 34 action-required và 16 no-action | `python3 scripts/inspect_cases.py` |
| Kiểm tra output độc lập | `VerifierAgent` | 50/50 case pass, không có false evidence ID | `python3 -m ecommerce_agents.cli validate` |
| Model audit ≤10B | `logging/metadata.json` | Qwen3-8B 8,2B; 50/50 audit approved | Lọc event `llm_read_only_audit` trong trace |
| Regression test | `tests/test_pipeline.py` | 4/4 test pass | `python3 -m unittest discover -s tests -v` |

Output cụ thể của phần việc là 50 JSON hợp lệ trong `output/`, tổng refund đề xuất 3.437,76 BRL. Trace mới nhất có 802 event, gồm 50 model-audit event với 50 request ID khác nhau và không có `case_failed` hoặc `verification_failed`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Một khiếu nại phải được đối soát qua nhiều quan hệ one-to-many: order–item, order–payment và customer–history. Kết quả cần đúng policy priority, số tiền, timestamp, null handling, stable ordering và giới hạn mảng. LLM không phù hợp để trực tiếp tính các trường này vì có thể làm sai số hoặc tạo evidence không tồn tại.

### Cách triển khai

Coordinator kiểm tra input rồi giao order ID cho các domain agent. Order & Product Agent dựng order/item/seller/product facts. Customer Agent tìm lịch sử bằng `customer_unique_id`. Payment Agent dùng `Decimal` để cộng từng payment row và đối soát với item + freight. Delivery Agent tính variance từ timestamp gốc và deadline sớm nhất theo từng seller. Policy Agent nhận facts qua handoff, áp dụng sáu primary rule đúng thứ tự rồi thêm secondary issues/actions.

Verifier không tin output của Policy Agent một cách mặc định. Nó đọc lại raw CSV và độc lập dựng expected value cho toàn bộ JSON, sau đó kiểm tra evidence, enum, strict JSON và array limits. Chỉ output đã pass mới được gửi sang Qwen3-8B để audit consistency chỉ đọc. Phản hồi model được ghi trace nhưng không có quyền thay đổi số liệu.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `input/EC_001.json`–`EC_050.json`, 9 Olist CSV |
| Output | `output/EC_001.json`–`EC_050.json` theo schema README |
| Module phụ thuộc | `repository.py`, các domain agent, `utils.py` |
| Module sử dụng output | Verifier, LLM audit, CLI validator/packager |
| Điều kiện lỗi cần xử lý | Thiếu case, order không tồn tại, policy không match, null item, sai evidence/limit/schema, thiếu API key hoặc provider lỗi |

### Cách xác minh

```bash
python3 -m unittest discover -s tests -v
python3 -m ecommerce_agents.cli run --llm-audit
python3 -m ecommerce_agents.cli validate
python3 scripts/inspect_cases.py
```

- **Kết quả mong đợi:** 4 tests pass, 50 case complete, 50 model audit approved, validator không có lỗi.
- **Kết quả thực tế:** 4/4 tests pass; 50/50 JSON pass; 50/50 audit approved; 34 action-required, 16 no-action.
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/metadata.json`; không chứa secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Output chủ yếu là phép join, tính tiền/thời gian và policy classification có đáp án xác định, nhưng bài yêu cầu kiến trúc multi-agent và model ≤10B.
- **Các phương án đã cân nhắc:** (1) để LLM sinh toàn bộ JSON; (2) rule engine đơn khối; (3) domain agents deterministic kết hợp model audit chỉ đọc.
- **Phương án đã chọn:** Domain agents có contract/handoff thật, deterministic policy + independent verifier, Qwen3-8B chỉ audit cuối.
- **Lý do:** Phương án này giữ đúng tinh thần A2A và trace thật, đồng thời tránh hallucination ID/số tiền. Kết quả reproducible khi chạy không model và không thay đổi khi bật audit model.
- **Bằng chứng quyết định phù hợp:** Output digest của lượt chạy cuối là `d5488320646b9ac918c229b0c8225620935eb7ffa7eeaf39b60bcf1a5d500659`; validator pass 50/50 và 50 model audits approved.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`.
- **Lệnh hoặc bước tái hiện:** `python3 -m ecommerce_agents.cli run --llm-audit` trong network sandbox.
- **Nguyên nhân gốc:** Sandbox chặn DNS/outbound network; key đã được cấu hình đúng và không phải nguyên nhân.
- **Cách xử lý:** Chạy lại đúng command với quyền kết nối ngoài sandbox đã được người dùng phê duyệt; không thay đổi hoặc lộ API key.
- **Cách xác minh sau khi sửa:** Run hoàn thành 50 case; trace có 50 request ID, 50 trạng thái `approved`, không có failed event.
- **Điều học được:** Cần phân biệt lỗi credential với lỗi network boundary và giữ deterministic result độc lập khỏi provider availability.

## 7. Hiểu biết về luồng end-to-end

1. Input cung cấp `claimed_order_id`; Coordinator dùng ID này để lấy order, sau đó các agent join customer, items, sellers, products và payments. Customer history chỉ dùng làm context, không đưa related orders vào affected entities.
2. Payment quality được đo bằng chênh lệch giữa tổng payment rows và tổng item + freight trong sai số 0,10 BRL. Delivery responsibility phụ thuộc cả delivery estimate và seller shipping limit, không chỉ lời khiếu nại.
3. Policy Agent áp dụng primary rule theo priority để tránh một order đồng thời bị gán nhiều primary issue. Secondary issues được thêm sau theo thứ tự cố định.
4. Verifier dựng expected JSON độc lập từ raw CSV, kiểm tra evidence và giới hạn trước khi Coordinator ghi output. Vì vậy một model audit sai hoặc provider gián đoạn không thể sửa số liệu.
5. Một run thành công cần đồng thời có 50 JSON pass validator, trace của lượt mới nhất, metadata model/runtime, 50 audit approved và ZIP đúng 50 file dưới 5 MB.

## 8. Cam kết của thành viên

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Đào Kiều Thịnh Quang
**Ngày xác nhận:** 2026-08-05
