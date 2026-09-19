import sys
import asyncio
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QDialog, QMessageBox, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont


class MsgBubbleWidget(QWidget):
    """单个气泡控件，区分 自己(右白色) / 他人(左浅灰) / 系统提示(居中灰色)"""

    def __init__(self, msg_type, nickname, content):
        super().__init__()

        # 消除控件自身默认灰色背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background:transparent;")

        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        self.setLayout(layout)

        font = QFont()
        font.setPointSize(10)

        if msg_type == "self":
            # 自己消息：靠右，白色气泡，去掉昵称后缀
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
                QWidget{
                    background-color:#ffffff;
                    border-radius:10px;
                    border:1px solid #cccccc;
                }
                QWidget QLabel{
                    border:none;
                }
            """)

            layout.addWidget(bubble_widget)

        elif msg_type == "other":
            # 别人消息：靠左，浅灰气泡，昵称单独label，正文单独label，换行缩进对齐
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
                QWidget{
                    background-color:#f1f1f1;
                    border-radius:10px;
                    border:1px solid #dddddd;
                }
                QWidget QLabel{
                    border:none;
                }
            """)

            layout.addWidget(bubble_widget)
            layout.addStretch(1)

        elif msg_type == "system":
            # 系统上下线提示，居中无气泡
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
    file_signal = pyqtSignal(str, int)
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

    async def tcp_task(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.writer.write((self.nickname + "\n").encode())
            await self.writer.drain()
            self.connect_ok_signal.emit()
            while self.running:
                line = await self.reader.readline()
                if not line:
                    break
                text = line.decode().strip()
                if text.startswith("FILE|"):
                    parts = text.split("|")
                    _, fname, sz = parts
                    self.file_signal.emit(fname, int(sz))
                else:
                    self.msg_signal.emit(text)
        except Exception as e:
            self.connect_fail_signal.emit(str(e))
        finally:
            self.disconnected_signal.emit()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.tcp_task())

    def send_text(self, text):
        if self.writer:
            payload = f"{self.nickname}|{text}\n"
            asyncio.run_coroutine_threadsafe(self._send(payload), self.loop)

    async def _send(self, data):
        self.writer.write(data.encode())
        await self.writer.drain()

    def send_file(self, filepath):
        if not self.writer or not os.path.exists(filepath):
            return
        fname = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        header = f"FILE|{fname}|{size}\n"
        asyncio.run_coroutine_threadsafe(self._send_file(header, filepath), self.loop)

    async def _send_file(self, header, path):
        self.writer.write(header.encode())
        await self.writer.drain()
        with open(path, "rb") as f:
            while chunk := f.read(4096):
                self.writer.write(chunk)
                await self.writer.drain()

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
        QListWidget {
            background:transparent;
            border:none;
        }
        QListWidget::item {
            border:none;
            background:transparent;
        }
        QListWidget::item:selected {
            background:transparent;
        }
        QListWidget::item:hover {
            background:transparent;
        }
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
        self.tcp_client.file_signal.connect(self.on_file_recv)
        self.tcp_client.disconnected_signal.connect(self.on_disconnect)

    def add_msg_item(self, bubble_widget):
        item = QListWidgetItem()
        item.setSizeHint(bubble_widget.sizeHint())
        self.msg_list.addItem(item)
        self.msg_list.setItemWidget(item, bubble_widget)
        self.msg_list.scrollToBottom()

    def on_recv_msg(self, txt):
        if "joined the chatroom" in txt or "User left" in txt:
            w = MsgBubbleWidget("system", "", txt)
            self.add_msg_item(w)
        elif "|" in txt:
            send_nick, content = txt.split("|", 1)
            w = MsgBubbleWidget("other", send_nick, content)
            self.add_msg_item(w)
        else:
            w = MsgBubbleWidget("system", "", txt)
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

    def on_file_recv(self, fname, size):
        w = MsgBubbleWidget("other", "System", f"Receive file: {fname}, size: {size} bytes")
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
