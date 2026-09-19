import sys
import asyncio
import os
import struct
import hashlib
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QDialog, QMessageBox, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# ========== 数据包打包解包工具 ==========
def pack_msg(msg_type: int, payload: bytes) -> bytes:
    header = struct.pack(">HIH", msg_type, len(payload), 0)
    return header + payload

def unpack_header(header_bytes: bytes):
    return struct.unpack(">HIH", header_bytes)
# ======================================

class MsgBubbleWidget(QWidget):
    """单个气泡控件，区分 自己(右白色) / 他人(左浅灰) / 系统提示(居中灰色)"""
    def __init__(self, msg_type, nickname, content):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent;")

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        self.setLayout(layout)

        font = QFont()
        font.setPointSize(10)

        if msg_type == "self":
            layout.addStretch(1)
            bubble_widget = QWidget()
            bubble_layout = QHBoxLayout()
            bubble_layout.setContentsMargins(8, 6, 8, 6)
            bubble_layout.setSpacing(0)
            bubble_widget.setLayout(bubble_layout)
            label = QLabel(content)
            label.setWordWrap(True)
            label.setFont(font)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            label.setStyleSheet("background:transparent; border:none;")
            bubble_layout.addWidget(label)
            bubble_widget.setStyleSheet("""
                QWidget{background-color:#ffffff;border-radius:10px;border:1px solid #cccccc;}
                QWidget QLabel{border:none;}
            """)
            layout.addWidget(bubble_widget)

        elif msg_type == "other":
            bubble_widget = QWidget()
            bubble_layout = QHBoxLayout()
            bubble_layout.setContentsMargins(8, 6, 8, 6)
            bubble_layout.setSpacing(4)
            bubble_widget.setLayout(bubble_layout)
            nick_label = QLabel(f"【{nickname}】:")
            nick_label.setFont(font)
            nick_label.setStyleSheet("background:transparent; border:none;")
            nick_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            content_label = QLabel(content)
            content_label.setFont(font)
            content_label.setWordWrap(True)
            content_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            content_label.setStyleSheet("background:transparent; border:none;")
            bubble_layout.addWidget(nick_label)
            bubble_layout.addWidget(content_label)
            bubble_widget.setStyleSheet("""
                QWidget{background-color:#f1f1f1;border-radius:10px;border:1px solid #dddddd;}
                QWidget QLabel{border:none;}
            """)
            layout.addWidget(bubble_widget)
            layout.addStretch(1)

        elif msg_type == "system":
            layout.addStretch(1)
            label = QLabel()
            label.setWordWrap(False)
            label.setFont(font)
            label.setText(content)
            label.setStyleSheet("color:#666666; background:transparent; border:none;")
            layout.addWidget(label)
            layout.addStretch(1)

class TcpClientThread(QThread):
    msg_signal = pyqtSignal(str)
    file_info_signal = pyqtSignal(dict)
    file_finish_signal = pyqtSignal(bool, str)
    disconnected_signal = pyqtSignal()
    connect_ok_signal = pyqtSignal()
    connect_fail_signal = pyqtSignal(str)

    def __init__(self, host, nickname):
        super().__init__()
        self.host = host
        self.port = 8080
        self.nickname = nickname
        self.reader = None
        self.writer = None
        self.loop = None
        self.running = True

        # 文件接收状态
        self.recv_file = None
        self.recv_filename = ""
        self.recv_total_size = 0
        self.recv_md5 = ""
        self.recv_received = 0
        self.recv_file_path = ""

    def reset_file_recv_state(self):
        if self.recv_file:
            self.recv_file.close()
            self.recv_file = None
        self.recv_filename = ""
        self.recv_total_size = 0
        self.recv_md5 = ""
        self.recv_received = 0
        self.recv_file_path = ""

    async def tcp_task(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            # 登录握手：发送昵称
            self.writer.write((self.nickname + "\n").encode())
            await self.writer.drain()
            self.connect_ok_signal.emit()

            buffer = b""
            while self.running:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                buffer += chunk

                while len(buffer) >= 8:
                    header_buf = buffer[:8]
                    msg_type, payload_len, reserved = unpack_header(header_buf)
                    total_packet_len = 8 + payload_len
                    if len(buffer) < total_packet_len:
                        break
                    full_packet = buffer[:total_packet_len]
                    buffer = buffer[total_packet_len:]
                    payload_data = full_packet[8:]

                    if msg_type == 0:
                        # 文本消息
                        text = payload_data.decode("utf-8")
                        self.msg_signal.emit(text)
                    elif msg_type == 1:
                        # 文件元信息包
                        meta = json.loads(payload_data.decode("utf-8"))
                        self.reset_file_recv_state()
                        self.recv_filename = meta["filename"]
                        self.recv_total_size = meta["size"]
                        self.recv_md5 = meta["md5"]
                        # 保存到当前目录 received_xxx
                        self.recv_file_path = f"received_{self.recv_filename}"
                        self.recv_file = open(self.recv_file_path, "wb")
                        self.file_info_signal.emit(meta)
                    elif msg_type == 2:
                        # 文件分片
                        if self.recv_file is None:
                            continue
                        self.recv_file.write(payload_data)
                        self.recv_received += len(payload_data)
                        # 判断是否接收完毕
                        if self.recv_received >= self.recv_total_size:
                            self.recv_file.close()
                            self.recv_file = None
                            # md5校验
                            h = hashlib.md5()
                            with open(self.recv_file_path, "rb") as f:
                                h.update(f.read())
                            digest = h.hexdigest()
                            ok = (digest == self.recv_md5)
                            self.file_finish_signal.emit(ok, self.recv_file_path)
                            self.reset_file_recv_state()
        except Exception as e:
            self.connect_fail_signal.emit(str(e))
        finally:
            self.reset_file_recv_state()
            self.disconnected_signal.emit()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.tcp_task())

    def send_text(self, text):
        if self.writer:
            payload = f"{self.nickname}|{text}".encode("utf-8")
            packet = pack_msg(0, payload)
            asyncio.run_coroutine_threadsafe(self._send_raw(packet), self.loop)

    async def _send_raw(self, data: bytes):
        self.writer.write(data)
        await self.writer.drain()

    def send_file(self, filepath):
        if not self.writer or not os.path.exists(filepath):
            return
        fname = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        # 计算md5
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            while c := f.read(4096):
                h.update(c)
        md5_val = h.hexdigest()
        meta = {"filename": fname, "size": size, "md5": md5_val}
        meta_bytes = json.dumps(meta).encode("utf-8")
        meta_packet = pack_msg(1, meta_bytes)
        asyncio.run_coroutine_threadsafe(self._send_file_packets(meta_packet, filepath), self.loop)

    async def _send_file_packets(self, meta_packet, path):
        await self._send_raw(meta_packet)
        with open(path, "rb") as f:
            while chunk := f.read(4096):
                pkt = pack_msg(2, chunk)
                await self._send_raw(pkt)

    def close_conn(self):
        self.running = False
        if self.writer:
            asyncio.run_coroutine_threadsafe(self.writer.close(), self.loop)

class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(screen_geo.width() - 300, 120)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Incoming Video Call Invite"))
        btn_layout = QHBoxLayout()
        accept_btn = QPushButton("Accept")
        reject_btn = QPushButton("Reject")
        accept_btn.clicked.connect(self.accept)
        reject_btn.clicked.connect(self.reject)
        btn_layout.addWidget(accept_btn)
        btn_layout.addWidget(reject_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login")
        self.setFixedSize(320, 160)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Server IP"))
        self.ip_edit = QLineEdit("127.0.0.1")
        layout.addWidget(self.ip_edit)
        layout.addWidget(QLabel("Nickname"))
        self.nick_edit = QLineEdit()
        layout.addWidget(self.nick_edit)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        self.ok_btn = QPushButton("Connect")
        self.ok_btn.clicked.connect(self.on_ok)
        layout.addWidget(self.ok_btn)
        self.setLayout(layout)
        self.nickname = None
        self.host = None
        self.tcp_client = None

    def on_ok(self):
        ip = self.ip_edit.text().strip()
        nick = self.nick_edit.text().strip()
        if not ip or not nick:
            QMessageBox.warning(self, "Warning", "IP and nickname cannot be empty!")
            self.ip_edit.clear()
            self.nick_edit.clear()
            return
        self.status_label.setText("Trying to connect...")
        self.ok_btn.setEnabled(False)
        self.tcp_client = TcpClientThread(ip, nick)
        self.tcp_client.connect_ok_signal.connect(self.on_connect_success)
        self.tcp_client.connect_fail_signal.connect(self.on_connect_fail)
        self.tcp_client.start()

    def on_connect_success(self):
        self.nickname = self.nick_edit.text().strip()
        self.host = self.ip_edit.text().strip()
        self.accept()

    def on_connect_fail(self, err_msg):
        self.status_label.setText("Connection failed!")
        QMessageBox.critical(self, "Error", f"Connect failed:\n{err_msg}")
        self.tcp_client.quit()
        self.tcp_client.wait()
        self.tcp_client = None
        self.ok_btn.setEnabled(True)
        self.ip_edit.clear()
        self.nick_edit.clear()

class ChatMainWindow(QMainWindow):
    def __init__(self, host, nickname, tcp_client):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nickname}")
        self.setGeometry(100, 100, 650, 480)
        self.nickname = nickname
        self.tcp_client = tcp_client

        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)

        self.msg_list = QListWidget()
        self.msg_list.setSpacing(4)
        self.msg_list.setStyleSheet("""
        QListWidget {background:transparent;border:none;}
        QListWidget::item {border:none;background:transparent;}
        QListWidget::item:selected {background:transparent;}
        QListWidget::item:hover {background:transparent;}
        """)
        vl.addWidget(self.msg_list)

        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_file.clicked.connect(self.select_file)
        self.btn_video = QPushButton("Start Video Call")
        self.btn_video.clicked.connect(self.btn_video_click)
        self.btn_mines = QPushButton("Minesweeper")
        btn_layout.addWidget(self.btn_file)
        btn_layout.addWidget(self.btn_video)
        btn_layout.addWidget(self.btn_mines)
        vl.addLayout(btn_layout)

        input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Input message...")
        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self.send_msg)
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(self.btn_send)
        vl.addLayout(input_layout)

        self.tcp_client.msg_signal.connect(self.on_recv_msg)
        self.tcp_client.file_info_signal.connect(self.on_file_info)
        self.tcp_client.file_finish_signal.connect(self.on_file_finish)
        self.tcp_client.disconnected_signal.connect(self.on_disconnect)

    def add_msg_item(self, bubble_widget):
        item = QListWidgetItem()
        item.setSizeHint(bubble_widget.sizeHint())
        self.msg_list.addItem(item)
        self.msg_list.setItemWidget(item, bubble_widget)
        self.msg_list.scrollToBottom()

    def on_recv_msg(self, txt):
        if "joined the chatroom" in txt or "用户离开" in txt:
            w = MsgBubbleWidget("system", "", txt)
            self.add_msg_item(w)
        elif "|" in txt:
            send_nick, content = txt.split("|", 1)
            w = MsgBubbleWidget("other", send_nick, content)
            self.add_msg_item(w)
        else:
            w = MsgBubbleWidget("system", "", txt)
            self.add_msg_item(w)

    def on_file_info(self, meta):
        fname = meta["filename"]
        size = meta["size"]
        w = MsgBubbleWidget("system", "", f"Receiving file: {fname}, size={size} bytes")
        self.add_msg_item(w)

    def on_file_finish(self, ok, path):
        if ok:
            w = MsgBubbleWidget("system", "", f"File saved successfully! Path: {path}")
        else:
            w = MsgBubbleWidget("system", "", f"File MD5 check failed, file may be corrupted!")
        self.add_msg_item(w)

    def send_msg(self):
        text = self.msg_input.text().strip()
        if not text:
            return
        w = MsgBubbleWidget("self", self.nickname, text)
        self.add_msg_item(w)
        self.tcp_client.send_text(text)
        self.msg_input.clear()

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self.tcp_client.send_file(path)
            w = MsgBubbleWidget("self", self.nickname, f"Sending file: {os.path.basename(path)}")
            self.add_msg_item(w)

    def btn_video_click(self):
        popup = VideoInvitePopup(self)
        popup.exec()

    def on_disconnect(self):
        w = MsgBubbleWidget("system", "", "⚠️ Disconnected from server")
        self.add_msg_item(w)

    def closeEvent(self, event):
        self.tcp_client.close_conn()
        self.tcp_client.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        win = ChatMainWindow(login.host, login.nickname, login.tcp_client)
        win.show()
        sys.exit(app.exec())
