import sys
import asyncio
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QLineEdit, QPushButton, QDialog, QLabel, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont


class TcpClientThread(QThread):
    msg_signal = pyqtSignal(str)
    file_signal = pyqtSignal(str, int)
    disconnected_signal = pyqtSignal()
    connect_ok_signal = pyqtSignal()
    connect_fail_signal = pyqtSignal(str)

    def __init__(self, host, port, nickname):
        super().__init__()
        self.host = host
        self.port = port
        self.nickname = nickname
        self.reader = None
        self.writer = None
        self.loop = None
        self.running = True

    async def tcp_task(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            # 发送昵称
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
            asyncio.run_coroutine_threadsafe(self._send(text + "\n"), self.loop)

    async def _send(self, data):
        self.writer.write(data.encode())
        await self.writer.drain()

    def send_file(self, filepath):
        if not self.writer or not os.path.exists(filepath):
            return
        fname = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        asyncio.run_coroutine_threadsafe(self._send_file(filepath, fname, size), self.loop)

    async def _send_file(self, path, fname, size):
        self.writer.write(f"FILE|{fname}|{size}\n".encode())
        await self.writer.drain()
        with open(path, "rb") as f:
            while chunk := f.read(4096):
                self.writer.write(chunk)
                await self.writer.drain()

    def close_conn(self):
        self.running = False
        if self.writer:
            asyncio.run_coroutine_threadsafe(self.writer.close(), self.loop)


# 无边框半透明视频邀请浮窗
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280,140)
        # 放在屏幕右侧
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(screen_geo.width()-300, 120)
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


# Login Dialog：登录阶段完成TCP连接校验
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login")
        self.setFixedSize(320, 220)
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
        # 1. 本地校验：空IP、空昵称直接拒绝
        if not ip or not nick:
            QMessageBox.warning(self, "Error", "IP and nickname cannot be empty!")
            self.ip_edit.clear()
            self.nick_edit.clear()
            return
        self.status_label.setText("Trying to connect...")
        self.ok_btn.setEnabled(False)
        # 登录弹窗内启动线程尝试连接
        self.tcp_client = TcpClientThread(ip, 8888, nick)
        self.tcp_client.connect_ok_signal.connect(self.on_connect_success)
        self.tcp_client.connect_fail_signal.connect(self.on_connect_failed)
        self.tcp_client.start()

    def on_connect_success(self):
        self.nickname = self.nick_edit.text().strip()
        self.host = self.ip_edit.text().strip()
        self.accept()

    def on_connect_failed(self, err_msg):
        self.status_label.setText("Connection failed!")
        QMessageBox.critical(self, "Connect Error", f"Can not connect to server:\n{err_msg}")
        self.tcp_client.quit()
        self.tcp_client.wait()
        self.tcp_client = None
        # 清空输入框
        self.ip_edit.clear()
        self.nick_edit.clear()
        self.ok_btn.setEnabled(True)


# Main Chat Window：接收已经建好的tcp客户端，不再新建连接
class ChatMainWindow(QMainWindow):
    def __init__(self, host, nickname, tcp_client):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nickname}")
        self.setGeometry(100, 100, 650, 480)
        self.nickname = nickname
        self.tcp_client = tcp_client
        # 绑定信号
        self.tcp_client.msg_signal.connect(self.append_msg)
        self.tcp_client.file_signal.connect(self.on_file_recv)
        self.tcp_client.disconnected_signal.connect(self.on_disconnect)

        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)
        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        vl.addWidget(self.chat_box)

        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_file.clicked.connect(self.select_file)
        self.btn_video = QPushButton("Start Video Call")
        self.btn_video.clicked.connect(self.show_video_invite)
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

    def append_msg(self, txt):
        self.chat_box.append(txt)

    def send_msg(self):
        text = self.msg_input.text().strip()
        if text:
            self.tcp_client.send_text(text)
            self.msg_input.clear()

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self.tcp_client.send_file(path)

    def on_file_recv(self, fname, size):
        self.append_msg(f"📥 Receiving file {fname}, size:{size}")

    def show_video_invite(self):
        popup = VideoInvitePopup(self)
        popup.exec()

    def on_disconnect(self):
        self.append_msg("⚠️ Disconnected from server")

    def closeEvent(self, event):
        self.tcp_client.close_conn()
        self.tcp_client.wait()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        # 把登录阶段已经建立好的tcp对象传给主窗口，不再新建连接
        win = ChatMainWindow(login.host, login.nickname, login.tcp_client)
        win.show()
        sys.exit(app.exec())
