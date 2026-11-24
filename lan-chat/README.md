# LAN Chat & File Sharing (CLI)

Chương trình chat và gửi file trong mạng LAN, chạy trên console. Mỗi máy chạy cùng một chương trình. Chương trình tự tìm người khác trong mạng, hiển thị ai đang online và cho phép chat hoặc gửi file.

- UDP: phát hiện người dùng và trạng thái (port 9999).
- TCP: chat và truyền file (port mặc định 5000).

## Yêu cầu

- Windows
- Python **3.14.5**
- Không cần cài thêm thư viện nào. Chỉ dùng thư viện chuẩn của Python.

## Cài đặt

```bash
git clone <địa chỉ repo>
cd lan-chat
```

## Chạy

```bash
python lanchat.py --name Quan --port 5000
```

Tham số:

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--name` | (bắt buộc) | Tên hiển thị, 1–20 ký tự, không có khoảng trắng và `\|` |
| `--port` | 5000 | Port TCP để chat và nhận file |
| `--broadcast` | 255.255.255.255 | Địa chỉ broadcast |

## Chạy nhiều instance trên một máy

Dùng port TCP khác nhau và broadcast về loopback:

```bash
python lanchat.py --name Quan --port 5001 --broadcast 127.255.255.255
python lanchat.py --name Minh --port 5002 --broadcast 127.255.255.255
```

## Chạy trên nhiều máy trong cùng LAN / Wi-Fi

1. Đảm bảo các máy cùng mạng.
2. Khi Windows hỏi, cho phép Python qua Windows Firewall (cả mạng riêng). Nếu không cho phép, broadcast sẽ không nhận được.
3. Chạy `python lanchat.py --name <tên> --port 5000` trên từng máy.

## Lệnh

| Lệnh | Mô tả |
|---|---|
| `/list` | Hiện danh sách online: số thứ tự, tên, IP, trạng thái |
| `/chat <name\|number>` | Mở chat với người đó |
| `<text>` | Gửi tin nhắn cho chat partner hiện tại |
| `/send <file>` | Gửi file cho chat partner (phải `/chat` trước) |
| `/leave` | Đóng chat hiện tại |
| `/status <online\|away>` | Đổi trạng thái |
| `/help` | Hiện danh sách lệnh |
| `/quit` | Thoát chương trình |

Tin nhắn từ người không phải chat partner hiện tại sẽ được lưu lại và hiển thị kèm số tin chưa đọc. Dùng `/chat <name>` để xem.

## Cấu trúc thư mục

```
lanchat.py        điểm vào chương trình
core/             luồng chính, lệnh, state, console
discovery/        UDP: phát hiện người dùng, trạng thái
transport/        TCP: chat, truyền file
report/           báo cáo LaTeX (làm khi nộp bài)
```
