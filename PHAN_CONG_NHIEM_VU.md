# Phân công nhiệm vụ – LAN Chat & File Sharing

> Đọc kèm `QUY_UOC_CHUNG.md`. Quy ước về folder, giao thức, chữ ký hàm đều nằm ở đó.

---

## 1. Tổng quan

| Thành viên | Folder phụ trách | Nhiệm vụ chính |
|---|---|---|
| **Thành viên 1** | `core/`, `lanchat.py`, `README.md` | Luồng chính, lệnh, console, state, tích hợp, live demo |
| **Thành viên 2** | `discovery/` | UDP discovery, online list, status, timeout |
| **Thành viên 3** | `transport/` | Protocol, TCP chat, truyền file |

Phân bổ điểm theo rubric:

| Tiêu chí (điểm) | Người phụ trách chính |
|---|---|
| UDP discovery, online list, status (15) | Thành viên 2 |
| TCP chat, nhiều peer (20) | Thành viên 3 |
| File transfer có progress (15) | Thành viên 3 |
| Console UI, không bị vỡ khi nhận tin (15) | Thành viên 1 |
| Protocol và framing (10) | Thành viên 3 |
| Error handling và ổn định (10) | Mỗi người cho module của mình, Thành viên 1 kiểm tra tổng |
| Báo cáo (10) | Cả 3, phân mục ở mục 4 |
| Demo và chất lượng code (5) | Thành viên 1 |

---

## 2. Chi tiết nhiệm vụ

### 2.1 Thành viên 1

**Code:**
- [ ] `lanchat.py`: đọc `--name`, `--port`, `--broadcast`, khởi tạo và chạy app.
- [ ] `core/models.py`: class `Peer`.
- [ ] `core/state.py`: danh sách online, lịch sử chat theo peer, bộ đếm unread, có `Lock`.
- [ ] `core/console.py`: đọc phím bằng `msvcrt`, dòng nhập, in tin đến không làm vỡ dòng nhập, `screen_lock`.
- [ ] `core/commands.py`: `/list`, `/chat`, `/send`, `/leave`, `/status`, `/help`, `/quit`.
- [ ] `core/app.py`: nối các module, nhận callback từ discovery và transport, xử lý Ctrl+C.
- [ ] Thông báo online/offline, và thông báo tin từ người không phải chat partner kèm số unread.
- [ ] Viết stub cho discovery và transport để chạy app sớm.
- [ ] `README.md` và `.gitignore`.

**Live demo:** chuẩn bị kịch bản chạy 2 instance trên máy của mình, demo trực tiếp trên lớp.

**Báo cáo:**
- [ ] Phần 1: Giới thiệu, mục tiêu, phạm vi.
- [ ] Phần 2: Kiến trúc tổng thể và sơ đồ.
- [ ] Phần 3: Thread model.
- [ ] Phần 8: Vấn đề gặp phải và cách giải quyết (tổng hợp từ cả nhóm).
- [ ] Phần 9: Kết luận và hướng phát triển.

---

### 2.2 Thành viên 2 – UDP Discovery và Status

**Code (`discovery/udp.py`):**
- [ ] Socket UDP, bind port 9999, bật `SO_REUSEADDR`.
- [ ] Luồng broadcaster: gửi `HELLO|<name>|<tcp_port>|<status>` mỗi 3 giây.
- [ ] Luồng listener: nhận HELLO, parse, bỏ qua gói của chính mình, cập nhật `last_seen`.
- [ ] Phát sự kiện `online` khi có peer mới, `status` khi trạng thái đổi, `offline` khi bị xóa.
- [ ] Kiểm tra timeout mỗi giây, xóa peer không phản hồi sau 10 giây.
- [ ] Hỗ trợ `/status`: đổi trạng thái và gửi HELLO ngay.
- [ ] `stop()` dừng các luồng sạch sẽ.
- [ ] Gói HELLO sai định dạng: bỏ qua, không crash.

**Báo cáo:**
- [ ] Phần 4: Giao thức UDP (HELLO, timeout, cơ chế broadcast).
- [ ] Phần 6: Wireshark UDP broadcast, chụp hình và giải thích ngắn.
- [ ] Phần 8: Vấn đề gặp phải với UDP (ví dụ broadcast không đến, nhiều socket cùng port).

**Wireshark:** chụp gói UDP broadcast khi chạy chương trình, lưu hình cho báo cáo.

---

### 2.3 Thành viên 3 – TCP Chat, Protocol và File Transfer

**Code:**

`transport/protocol.py`
- [ ] Đọc header: đọc từng byte đến `\n`, giới hạn 512 byte.
- [ ] `recv_exact(sock, n)`: lặp `recv()` cho đến khi đủ n byte, đứt kết nối thì báo lỗi.
- [ ] Encode và decode các frame `CHAT`, `MSG`, `BYE`, `FILE` theo mục 5.5 của quy ước.
- [ ] Làm sạch tên file (lấy basename, bỏ `|` và xuống dòng).

`transport/tcp.py`
- [ ] Acceptor: `listen()` trên port TCP, mỗi kết nối tới tạo một luồng receiver riêng.
- [ ] Receiver đọc frame đầu tiên: `CHAT` thì gọi `on_chat`, `FILE` thì chuyển sang xử lý file.
- [ ] `open_chat()`: connect, gửi `CHAT|<name>`, trả về `ChatSession`.
- [ ] `ChatSession.send()`: gửi `MSG`, có lock để tránh gửi chồng.
- [ ] `ChatSession.close()`: gửi `BYE`, đóng socket.
- [ ] Phát hiện peer đóng kết nối, gọi `on_closed`.
- [ ] Chat với nhiều peer cùng lúc (mỗi peer một luồng).

`transport/filetransfer.py`
- [ ] `send_file()`: mở kết nối TCP mới tới peer, gửi `FILE|<name>|<size>\n`, đọc file theo khối và gửi.
- [ ] Gọi `on_progress` theo phần trăm, không in quá dày.
- [ ] Phía nhận: ghi vào `downloads/`, tránh trùng tên bằng hậu tố `(n)`.
- [ ] Nhận thiếu dữ liệu: đóng và xóa file tạm, báo lỗi.
- [ ] Kiểm tra file tồn tại trước khi kết nối.
- [ ] Chạy trong luồng riêng, không chặn chat.

**Báo cáo:**
- [ ] Phần 5: Giao thức TCP (frame, lý do cần header độ dài, truyền file).
- [ ] Phần 7: Wireshark TCP three-way handshake (SYN, SYN-ACK, ACK), chụp hình và giải thích ngắn.
- [ ] Phần 8: Vấn đề gặp phải với TCP (ví dụ recv không đủ byte, file lớn, dữ liệu bị cắt).

**Wireshark:** chụp TCP three-way handshake khi mở chat, lưu hình cho báo cáo.

> Đây là phần nặng nhất về logic. Nếu thấy chậm tiến độ, báo nhóm ngay để chia lại việc.

---

## 3. Lịch làm việc (giả định deadline 29/12/2026)

Đây là mốc hoàn thành dự kiến, không phải checkpoint kiểm tra.

| Giai đoạn | Thời gian | Nội dung | Phụ trách |
|---|---|---|---|
| Chốt giao diện | 28/11 | Thống nhất chữ ký hàm trong `QUY_UOC_CHUNG.md` mục 6, tạo repo | Thành viên 1 |
| Nền tảng | 26/11 – 02/12 | TCP echo, UDP gửi nhận thử, khung app | Cả 3 |
| Discovery | 03/12 – 09/12 | UDP discovery, `/list`, `/status`, timeout | Thành viên 2 |
| Chat TCP | 10/12 – 16/12 | `/chat`, `/leave`, framing, nhiều peer, thread | Thành viên 3, Thành viên 1 tích hợp |
| Console và file | 17/12 – 23/12 | Console không vỡ khi nhận tin; truyền file có progress | Thành viên 3 (file), Thành viên 1 (console) |
| Hoàn thiện | 24/12 – 26/12 | Xử lý lỗi, Wireshark, tập live demo | Cả nhóm |
| Nộp bài | 27/12 – 29/12 | Viết báo cáo LaTeX, nộp PDF và mã nguồn LaTeX, tag `v1.0` | Cả nhóm |

---

## 4. Báo cáo (chỉ làm khi nộp)

Báo cáo **không viết trong quá trình làm**. Chỉ bắt đầu từ 27/12, dùng LaTeX, nộp cả **PDF** và **mã nguồn LaTeX**. Độ dài 5–10 trang.

| Phần | Người viết |
|---|---|
| 1. Giới thiệu, mục tiêu, phạm vi | Thành viên 1 |
| 2. Kiến trúc tổng thể và sơ đồ | Thành viên 1 |
| 3. Thread model | Thành viên 1 |
| 4. Giao thức UDP (HELLO, timeout) | Thành viên 2 |
| 5. Giao thức TCP (frame, framing, truyền file) | Thành viên 3 |
| 6. Wireshark: UDP broadcast | Thành viên 2 |
| 7. Wireshark: TCP handshake | Thành viên 3 |
| 8. Vấn đề gặp phải và cách giải quyết | Mỗi người viết phần của mình |
| 9. Kết luận và hướng phát triển | Thành viên 1 |

Yêu cầu:
- Thành viên 1 tạo sẵn file LaTeX khung (preamble, các section) để mỗi người điền phần mình trong thư mục `report/`.
- Hình Wireshark đặt kèm chú thích, mỗi người chụp và lưu hình của phần mình.

---

## 5. Checklist nộp bài

- [ ] Code đẩy lên `main`, tag `v1.0`, chạy được theo README.
- [ ] README đủ: cài đặt, chạy, chạy nhiều instance trên 1 máy.
- [ ] Báo cáo 5–10 trang, có Wireshark UDP broadcast và TCP three-way handshake.
- [ ] Nộp PDF và mã nguồn LaTeX.
- [ ] Live demo trên lớp đã chạy thử ít nhất 2 lần.
