import sys
import json
import asyncio
import struct
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QDialog, QMessageBox, QFileDialog, QGridLayout, QSizePolicy,
    QListView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


# ========== 聊天气泡组件 ==========
class MsgBubbleWidget(QWidget):
    def __init__(self, msg_type, nick, text):
        super().__init__()
        # 外层控件：水平撑满列表项，高度随内容自适应
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout()
        # 【修改点】左侧margin缩小，右侧保持不变，实现左侧削减
        layout.setContentsMargins(2, 4, 6, 4)
        layout.setSpacing(8)

        font = QFont()
        font.setPointSize(10)

        if msg_type == "self":
            # 自己消息：左边占位拉伸，气泡靠右
            layout.addStretch(1)
            self.bubble = QLabel(text)
            self.bubble.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            self.bubble.setWordWrap(True)
            self.bubble.setFont(font)
            self.bubble.setStyleSheet(
                "background-color:#ffffff; border:1px solid #cccccc; border-radius:8px; padding:6px;"
            )
            layout.addWidget(self.bubble)

        elif msg_type == "other":
            # 别人消息：气泡靠左，右边占位拉伸
            self.bubble = QWidget()
            self.bubble.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            # 【关键修复】修改sizePolicy为Expanding，允许气泡在maxWidth限制内自动拓宽
            self.bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            self.bubble.setStyleSheet(
                "background-color:#f1f1f1; border:1px solid #dddddd; border-radius:8px; padding:6px;"
            )

            # 内部布局：昵称+文本
            bubble_layout = QHBoxLayout(self.bubble)
            bubble_layout.setContentsMargins(0, 0, 0, 0)
            # 【修改点】昵称和文本间距缩小
            bubble_layout.setSpacing(0)

            nick_label = QLabel(f"【{nick}】：")
            nick_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            nick_label.setFont(font)
            nick_label.setStyleSheet("background:transparent; border:none;")

            content_label = QLabel(text)
            content_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            content_label.setWordWrap(True)
            content_label.setFont(font)
            content_label.setStyleSheet("background:transparent; border:none;")

            bubble_layout.addWidget(nick_label)
            bubble_layout.addWidget(content_label, 1)

            layout.addWidget(self.bubble)
            layout.addStretch(1)

        else:
            # 系统消息：左右拉伸居中
            self.bubble = QLabel(text)
            self.bubble.setWordWrap(False)
            self.bubble.setFont(font)
            self.bubble.setStyleSheet("color:#666666; background:transparent;")
            layout.addStretch(1)
            layout.addWidget(self.bubble)
            layout.addStretch(1)

        self.setLayout(layout)

    # 动态设置气泡最大宽度
    def set_bubble_max_width(self, max_width):
        if hasattr(self, 'bubble'):
            self.bubble.setMaximumWidth(max_width)
        self.adjustSize()


# ========== 网络线程 ==========
class TcpClientThread(QThread):
    msg_signal = pyqtSignal(str)
    ms_signal = pyqtSignal(dict)
    connected_signal = pyqtSignal()
    fail_signal = pyqtSignal(str)
    disconnect_signal = pyqtSignal()

    def __init__(self, host, port, nick):
        super().__init__()
        self.host = host
        self.port = port
        self.nick = nick
        self.reader = None
        self.writer = None
        self.loop = None
        self.running = True

    async def tcp_task(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.writer.write((self.nick + "\n").encode("utf-8"))
            await self.writer.drain()
            self.connected_signal.emit()
            buf = b""
            while self.running:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    hdr = buf[:8]
                    mt, pl, _ = unpack_header(hdr)
                    if len(buf) < 8 + pl:
                        break
                    payload = buf[8:8 + pl]
                    buf = buf[8 + pl:]
                    if mt == 0:
                        text = payload.decode("utf-8").strip()
                        self.msg_signal.emit(text)
                    elif mt == 4:
                        try:
                            data = json.loads(payload.decode("utf-8"))
                        except:
                            continue
                        self.ms_signal.emit(data)
        except Exception as e:
            self.fail_signal.emit(str(e))
        finally:
            self.disconnect_signal.emit()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.tcp_task())

    async def _send_raw(self, data):
        if self.writer:
            self.writer.write(data)
            await self.writer.drain()

    def send_text(self, text):
        pkt = pack_msg(0, text.encode("utf-8"))
        asyncio.run_coroutine_threadsafe(self._send_raw(pkt), self.loop)

    def send_ms_cmd(self, cmd_dict):
        payload = json.dumps(cmd_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(4, payload)
        asyncio.run_coroutine_threadsafe(self._send_raw(pkt), self.loop)

    def close_conn(self):
        self.running = False
        if self.writer:
            asyncio.run_coroutine_threadsafe(self.writer.close(), self.loop)


# ========== 扫雷窗口 ==========
class MinesweeperWindow(QDialog):
    def __init__(self, parent, tcp, my_nick):
        super().__init__(parent)
        self.setWindowTitle("Minesweeper")
        self.tcp = tcp
        self.my_nick = my_nick
        self.rows = 16
        self.cols = 16
        self.buttons = {}
        self.current_player = None
        self.players = []
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        self.player_list = QListWidget()
        self.status_label = QLabel("Waiting game...")
        left_layout.addWidget(QLabel("Players:"))
        left_layout.addWidget(self.player_list)
        left_layout.addWidget(self.status_label)
        right_layout = QVBoxLayout()
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.grid_layout.setSpacing(2)
        right_layout.addWidget(grid_widget)
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 4)
        self.setLayout(main_layout)
        self.setMinimumSize(750, 620)

    def build_grid(self):
        for b in self.buttons.values():
            b.deleteLater()
        self.buttons.clear()
        for x in range(self.rows):
            for y in range(self.cols):
                btn = QPushButton("")
                btn.setFixedSize(32, 32)
                btn.setFont(QFont("Arial", 12, QFont.Weight.Bold))
                btn.clicked.connect(lambda checked, xx=x, yy=y: self.on_click(xx, yy, "open"))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(lambda pos, xx=x, yy=y: self.on_click(xx, yy, "flag"))
                self.grid_layout.addWidget(btn, x, y)
                self.buttons[(x, y)] = btn

    def on_click(self, x, y, action):
        self.tcp.send_ms_cmd({"cmd": "click", "x": x, "y": y, "action": action})

    def update_board(self, cells, current, players):
        self.current_player = current
        self.players = players
        self.player_list.clear()
        for p in players:
            item = QListWidgetItem(p + (" << YOUR TURN" if p == current else ""))
            if p == current:
                item.setForeground(Qt.GlobalColor.red)
            self.player_list.addItem(item)
        if current == self.my_nick:
            self.status_label.setText("YOUR TURN, click to open / right click flag")
            self.status_label.setStyleSheet("color:red;")
        else:
            self.status_label.setText(f"Waiting for {current}")
            self.status_label.setStyleSheet("color:#333;")
        for x in range(self.rows):
            for y in range(self.cols):
                val = cells[x][y]
                btn = self.buttons[(x, y)]
                if val == "c":
                    btn.setText("")
                    btn.setStyleSheet("background:#cfcfcf; border:1px solid #bbb;")
                    btn.setEnabled(True)
                elif val == "f":
                    btn.setText("F")
                    btn.setStyleSheet("background:#ffdddd; color:red; border:1px solid #bbb;")
                    btn.setEnabled(True)
                else:
                    btn.setText(val)
                    btn.setStyleSheet("background:#ffffff; border:1px solid #bbb;")
                    btn.setEnabled(False)


# ========== 视频通话弹窗 ==========
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - 300, 120)
        lay = QVBoxLayout()
        lay.addWidget(QLabel("Incoming Video Call Invite"))
        hlay = QHBoxLayout()
        btn_acc = QPushButton("Accept")
        btn_rej = QPushButton("Reject")
        btn_acc.clicked.connect(self.accept)
        btn_rej.clicked.connect(self.reject)
        hlay.addWidget(btn_acc)
        hlay.addWidget(btn_rej)
        lay.addLayout(hlay)
        self.setLayout(lay)


# ========== 登录弹窗 ==========
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login")
        self.setFixedSize(320, 160)
        lay = QVBoxLayout()
        lay.addWidget(QLabel("Server IP"))
        self.ip_edit = QLineEdit("127.0.0.1")
        lay.addWidget(self.ip_edit)
        lay.addWidget(QLabel("Nickname"))
        self.nick_edit = QLineEdit()
        lay.addWidget(self.nick_edit)
        self.status_label = QLabel("")
        lay.addWidget(self.status_label)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.on_connect)
        lay.addWidget(self.connect_btn)
        self.setLayout(lay)
        self.nickname = None
        self.host = None
        self.tcp_thread = None

    def on_connect(self):
        ip = self.ip_edit.text().strip()
        nick = self.nick_edit.text().strip()
        if not ip or not nick:
            QMessageBox.warning(self, "Warning", "IP and nickname cannot be empty!")
            return
        self.status_label.setText("Connecting...")
        self.connect_btn.setEnabled(False)
        self.tcp_thread = TcpClientThread(ip, 8080, nick)
        self.tcp_thread.connected_signal.connect(self.on_connected)
        self.tcp_thread.fail_signal.connect(self.on_fail)
        self.tcp_thread.start()

    def on_connected(self):
        self.nickname = self.nick_edit.text().strip()
        self.host = self.ip_edit.text().strip()
        self.accept()

    def on_fail(self, err):
        self.status_label.setText("Connect failed!")
        QMessageBox.critical(self, "Error", f"Connection error: {err}")
        self.connect_btn.setEnabled(True)


# ========== 主聊天窗口 ==========
class ChatMainWindow(QMainWindow):
    def __init__(self, host, nick, tcp):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nick}")
        self.setGeometry(100, 100, 680, 520)
        self.nick = nick
        self.tcp = tcp
        self.ms_window = None

        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)

        self.msg_list = QListWidget()
        self.msg_list.setSpacing(4)
        self.msg_list.setStyleSheet("""
            QListWidget{background:transparent;border:none;}
            QListWidget::item{background:transparent;}
            QListWidget::item:selected{background:transparent;}
        """)
        self.msg_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.msg_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        vl.addWidget(self.msg_list)

        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_vid = QPushButton("Start Video Call")
        self.btn_ms = QPushButton("Minesweeper")
        btn_layout.addWidget(self.btn_file)
        btn_layout.addWidget(self.btn_vid)
        btn_layout.addWidget(self.btn_ms)
        vl.addLayout(btn_layout)

        input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Input message...")
        self.btn_send = QPushButton("Send")
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(self.btn_send)
        vl.addLayout(input_layout)

        # 信号绑定
        self.tcp.msg_signal.connect(self.on_recv_msg)
        self.tcp.ms_signal.connect(self.on_ms_event)
        self.tcp.disconnect_signal.connect(self.on_disconnect)
        self.btn_send.clicked.connect(self.send_message)
        self.msg_input.returnPressed.connect(self.send_message)
        self.btn_ms.clicked.connect(self.invite_minesweeper)
        self.btn_vid.clicked.connect(self.video_invite)
        self.btn_file.clicked.connect(self.send_file)

    def add_bubble(self, widget):
        item = QListWidgetItem()
        self.msg_list.addItem(item)
        self.msg_list.setItemWidget(item, widget)
        self.update_bubbles_width()
        self.msg_list.scrollToBottom()

    def update_bubbles_width(self):
        viewport_width = self.msg_list.viewport().width()
        max_width = int(viewport_width * 0.7)
        max_width = max(120, max_width)
        for i in range(self.msg_list.count()):
            item = self.msg_list.item(i)
            widget = self.msg_list.itemWidget(item)
            if isinstance(widget, MsgBubbleWidget):
                widget.set_bubble_max_width(max_width)
                item.setSizeHint(QSize(viewport_width, widget.sizeHint().height()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_bubbles_width()

    def send_message(self):
        txt = self.msg_input.text().strip()
        if not txt:
            return
        self.add_bubble(MsgBubbleWidget("self", self.nick, txt))
        self.tcp.send_text(txt)
        self.msg_input.clear()

    def on_recv_msg(self, txt):
        if "joined" in txt or "left" in txt:
            self.add_bubble(MsgBubbleWidget("system", "", txt))
        else:
            if txt.startswith("【") and "】：" in txt:
                end_pos = txt.index("】：")
                nick = txt[1:end_pos]
                content = txt[end_pos + 2:]
            else:
                nick = ""
                content = txt
            self.add_bubble(MsgBubbleWidget("other", nick, content))

    def invite_minesweeper(self):
        self.tcp.send_ms_cmd({"cmd": "invite"})

    def on_ms_event(self, d):
        cmd = d.get("cmd")
        if cmd == "invite":
            ret = QMessageBox.question(
                self, "Minesweeper Invite",
                f"{d['inviter']} invite you to minesweeper, accept?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self.tcp.send_ms_cmd({"cmd": "accept"})
        elif cmd == "start":
            self.ms_window = MinesweeperWindow(self, self.tcp, self.nick)
            self.ms_window.build_grid()
            self.ms_window.show()
        elif cmd == "update":
            if self.ms_window:
                self.ms_window.update_board(d["cells"], d["current"], d["players"])
        elif cmd == "gameover":
            QMessageBox.information(self, "Game Over", f"{d['loser']} stepped on mine!")
            if self.ms_window:
                self.ms_window.close()
                self.ms_window = None
        elif cmd == "win":
            QMessageBox.information(self, "Win", "All mines cleared!")
            if self.ms_window:
                self.ms_window.close()
                self.ms_window = None
        elif cmd == "cancel":
            QMessageBox.information(self, "Game cancelled", d.get("msg", ""))
        elif cmd == "abort":
            QMessageBox.information(self, "Game aborted", d.get("msg", ""))
        elif cmd == "busy":
            QMessageBox.warning(self, "Warning", "Minesweeper room busy!")
        elif cmd == "full":
            QMessageBox.warning(self, "Warning", "Room full")

    def video_invite(self):
        dlg = VideoInvitePopup(self)
        dlg.exec()

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            QMessageBox.information(self, "Tip", "File transfer function not implemented yet")

    def on_disconnect(self):
        self.add_bubble(MsgBubbleWidget("system", "", "Disconnected from server"))

    def closeEvent(self, event):
        self.tcp.close_conn()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        w = ChatMainWindow(login.host, login.nickname, login.tcp_thread)
        w.show()
        sys.exit(app.exec())
