# Quy ước chung – LAN Chat & File Sharing (CLI)

> Thỏa thuận chung của nhóm 3 người. Mọi thay đổi phải được cả nhóm đồng ý và cập nhật tại đây.

---

## 1. Thông tin chung

| Mục | Thống nhất |
|---|---|
| Ngôn ngữ | Python |
| Phiên bản | **Python 3.14.5** (bắt buộc) |
| Số thành viên | 3 (Thành viên 1, Thành viên 2, Thành viên 3) |
| Giao diện | Console (command-line) |
| Hệ điều hành | **Windows** |
| Hình thức nộp | Live demo trên lớp. Báo cáo chỉ nộp khi kết thúc: **PDF** kèm **mã nguồn LaTeX** |
| Deadline | Ngày 29 (**giả định 29/12/2026**, xem mục 8) |

---

## 2. Ngôn ngữ và thư viện

- **Chỉ dùng thư viện gốc (native) của Python**, không dùng module bên ngoài.
- Không `pip install`, không `requirements.txt`.
- Không dùng `dataclasses`. Các lớp dữ liệu viết bằng `class` thường với `__init__`.
- Không dùng `prompt_toolkit`, `asyncio`, framework mạng hay thư viện bọc socket.

| Nhóm | Module |
|---|---|
| Mạng | `socket` |
| Đa luồng | `threading`, `queue` |
| Hệ thống | `os`, `sys`, `time`, `argparse`, `pathlib`, `shutil`, `signal`, `struct` |
| Bàn phím | `msvcrt` |

Chạy chương trình:

```bash
python lanchat.py --name Quan --port 5000
```

---

## 3. Cấu trúc thư mục

Mỗi thành viên làm trong **folder riêng** của mình để giảm xung đột khi đẩy code.

```
lan-chat/
├── lanchat.py              # Điểm vào chương trình
├── README.md               # Cách cài đặt và chạy
├── .gitignore              # __pycache__/, *.pyc, downloads/
├── core/                   # Luồng chính, lệnh, state, console
│   ├── app.py
│   ├── commands.py
│   ├── console.py
│   ├── models.py           # Lớp Peer (class thường)
│   └── state.py            # Danh sách online, lịch sử chat, unread (có lock)
├── discovery/              # UDP: broadcast, online list, status
│   └── udp.py
├── transport/              # TCP: protocol, chat, truyền file
│   ├── protocol.py
│   ├── tcp.py
│   └── filetransfer.py
├── report/                 # Báo cáo LaTeX (chỉ làm khi nộp)
└── downloads/              # Tự tạo khi chạy, không commit
```

---

## 4. Quy trình Git

- Làm việc trực tiếp trên nhánh `main`, **push thẳng**, không tạo nhánh và không Pull Request.
- Mỗi người chỉ sửa file trong folder của mình. Muốn sửa file của người khác thì báo nhóm trước.
- `lanchat.py`, `README.md`, `.gitignore` do Thành viên 1 quản lý.
- Khi nộp bài, gắn tag `v1.0` trên commit cuối.

---

## 5. Thống nhất kỹ thuật

### 5.1 Cổng và địa chỉ

| Mục | Giá trị |
|---|---|
| UDP discovery | Port **9999** cố định |
| TCP chat và nhận file | Port mặc định **5000**, đổi bằng `--port` |
| Broadcast LAN | `255.255.255.255` (mặc định) |
| Broadcast khi chạy nhiều instance trên 1 máy | `--broadcast 127.255.255.255` |
| Mã hóa | UTF-8 cho mọi chuỗi |

### 5.2 Tên người dùng (`--name`)

- Không chứa khoảng trắng và ký tự `|`.
- Độ dài 1 đến 20 ký tự. Sai thì báo lỗi và thoát khi khởi động.

### 5.3 Định danh peer

- Một peer được xác định bằng cặp **(IP, TCP port)**.

### 5.4 Giao thức UDP (discovery)

Mỗi peer gửi một datagram text mỗi **3 giây**:

```
HELLO|<name>|<tcp_port>|<status>
```

- `status` chỉ nhận `online` hoặc `away`.
- Peer không có HELLO trong **10 giây** thì bị xóa khỏi danh sách, console hiện thông báo.
- Bỏ qua gói do chính mình gửi (cùng `name` và `tcp_port`).

### 5.5 Giao thức TCP (chat và file)

TCP là luồng byte, nên mọi frame có **header ASCII kết thúc bằng `\n`**. Header tối đa 512 byte.

| Frame | Cấu trúc | Ý nghĩa |
|---|---|---|
| Mở chat | `CHAT\|<name>\n` | Người khởi tạo kết nối gửi ngay sau khi connect |
| Tin nhắn | `MSG\|<length>\n` + `<length>` byte UTF-8 | `length` tính bằng byte |
| Đóng chat | `BYE\n` | Báo trước khi đóng kết nối chat |
| Gửi file | `FILE\|<filename>\|<size>\n` + `<size>` byte thô | Mỗi file dùng **một kết nối TCP riêng** |

Quy tắc nhận dữ liệu:
- Lặp `recv()` cho đến khi đủ số byte, không giả định một lần là đủ.
- Frame đầu tiên quyết định loại kết nối: `CHAT` là chat, `FILE` là truyền file.
- `filename` chỉ lấy tên file, bỏ ký tự `|` và xuống dòng.
- Trùng tên trong `downloads/` thì thêm hậu tố `(1)`, `(2)`.
- Nhận file thiếu dữ liệu: báo lỗi và xóa file tạm.

### 5.6 Mô hình luồng

| Luồng | Vai trò |
|---|---|
| Main | Đọc bàn phím, xử lý lệnh, gửi tin nhắn chat |
| UDP broadcaster | Gửi HELLO mỗi 3 giây |
| UDP listener | Nhận HELLO, cập nhật danh sách online, kiểm tra timeout |
| TCP acceptor | Chờ kết nối đến, tạo receiver cho mỗi kết nối |
| TCP receiver | Một luồng cho mỗi kết nối chat, hiển thị tin nhắn |
| File sender | Một luồng cho mỗi lần gửi file, không chặn chat |

Đồng bộ:
- Danh sách online, lịch sử chat, bộ đếm unread: bảo vệ bằng `threading.Lock` trong `core/state.py`.
- Việc in ra màn hình: bảo vệ bằng một **screen lock** để hai luồng không in cùng lúc.

### 5.7 Giao diện console (Windows)

- Không có ô nhập riêng, nên chương trình tự mô phỏng: **dòng cuối luôn là dòng nhập**, phía trên là lịch sử.
- Đọc phím bằng `msvcrt.getwch()`, giữ phần text đang gõ trong một buffer.
- Khi có tin đến lúc đang gõ:
  1. Xóa dòng nhập hiện tại (`\r` + `\033[K`).
  2. In tin nhắn kèm xuống dòng.
  3. Vẽ lại prompt `> ` cùng phần text đang gõ dở.
- Giao diện và thông báo dùng **tiếng Anh**, giống mẫu trong đề bài.

### 5.8 Lệnh

| Lệnh | Mô tả |
|---|---|
| `/list` | Hiện danh sách online: số thứ tự, tên, IP, trạng thái |
| `/chat <name\|number>` | Mở chat với người đó |
| `<text>` | Gửi tin nhắn cho chat partner hiện tại |
| `/send <file>` | Gửi file cho chat partner (phải `/chat` trước) |
| `/leave` | Đóng chat hiện tại |
| `/status <online\|away>` | Đổi trạng thái, gửi ngay qua HELLO |
| `/help` | Hiện danh sách lệnh |
| `/quit` | Thoát chương trình |

Lệnh sai: hiện thông báo ngắn và gợi ý `/help`, không thoát chương trình.

---

## 6. Giao diện giữa các module

Ba thành viên dùng đúng các chữ ký này. Thay đổi phải báo cả nhóm và cập nhật tại đây.

```python
# core/models.py  [Thành viên 1]
class Peer:
    def __init__(self, name, ip, tcp_port, status, last_seen):
        self.name = name
        self.ip = ip
        self.tcp_port = tcp_port
        self.status = status      # "online" | "away"
        self.last_seen = last_seen  # time.monotonic()

# discovery/udp.py  [Thành viên 2]
def start_discovery(name, tcp_port, udp_port, broadcast_addr,
                    get_status, on_event):
    """get_status() trả về "online" | "away".
    on_event(kind, peer) với kind: "online" | "offline" | "status".
    Trả về đối tượng Discovery có phương thức stop()."""

# transport/tcp.py  [Thành viên 3]
def start_server(port, on_chat, on_file, on_error):
    """on_chat(name, session), on_file(from_ip, saved_path, size), on_error(message).
    Trả về đối tượng Server có phương thức stop()."""

class ChatSession:
    def send(self, text):   # raise OSError nếu mất kết nối
        ...
    def close(self):        # gửi BYE rồi đóng
        ...

def open_chat(ip, port, my_name, on_message, on_closed):
    """on_message(text), on_closed(). Raise ConnectionError nếu không kết nối được."""

# transport/filetransfer.py  [Thành viên 3]
def send_file(ip, port, path, on_progress):
    """on_progress(percent) với percent 0..100. Chạy trong luồng riêng, raise lỗi khi thất bại."""
```

---

## 7. Lỗi cần xử lý

| Tình huống | Xử lý |
|---|---|
| Peer đóng kết nối hoặc crash | Hiện thông báo, quay về prompt chính |
| Kết nối tới peer đã offline | Hiện lỗi, không crash |
| File không tồn tại, truyền bị ngắt | Hiện lỗi, xóa file tạm |
| Nhận dữ liệu không đủ | Đọc tiếp đến khi đủ, nếu đứt thì báo lỗi |
| Lệnh không hợp lệ | Hiện gợi ý `/help` |
| Ctrl+C | Đóng socket, dừng luồng, thoát sạch |

---

## 8. Ghi chú

- **Deadline:** đề bài ghi "ngày 29". Tài liệu này giả định là **29/12/2026**. Nếu thực tế là 29/11/2026 thì phạm vi phải cắt giảm, cần cả nhóm bàn ngay.
- Cần cho phép Python qua Windows Firewall, nếu không broadcast sẽ không nhận được.
- Tài liệu tham khảo: *Beej's Guide to Network Programming*, tài liệu Python `socket` và `threading`.
