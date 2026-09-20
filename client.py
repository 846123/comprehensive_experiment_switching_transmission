import sys
import json
import asyncio
import struct
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QDialog, QMessageBox, QFileDialog,
    QGridLayout, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


# ========== 聊天气泡组件【修改版：外层容器限制最大宽度，短文本紧凑包裹】 ==========
class MsgBubbleWidget(QWidget):
    def __init__(self, msg_type, nick, text, initial_max_w=0):
        super().__init__()
        self.msg_type = msg_type
        self.nick = nick
        self.raw_text = text
        self.max_bubble_width = initial_max_w
        self.indent_size = 36

        # 修改：把 MinimumExpanding 改成 Preferred，避免强行拉伸
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 2, 0, 2)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        self.font = QFont()
        self.font.setPointSize(10)
        self.text_label = None
        self.bubble_container = None  # 气泡外层容器，用来设置最大宽度

        if self.msg_type == "self":
            # 自己消息靠右
            self.main_layout.addStretch(1)
            self.bubble_container = QWidget()
            self.bubble_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.bubble_container.setStyleSheet("""
                background-color:#ffffff;
                border:1px solid #cccccc;
                border-radius:8px;
                padding:6px;
            """)
            bubble_layout = QVBoxLayout(self.bubble_container)
            bubble_layout.setContentsMargins(0,0,0,0)
            bubble_layout.setSpacing(0)

            self.text_label = QLabel()
            self.text_label.setFont(self.font)
            self.text_label.setWordWrap(True)
            self.text_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.text_label.setStyleSheet("background:transparent;border:none;")
            bubble_layout.addWidget(self.text_label)
            self.main_layout.addWidget(self.bubble_container)

        elif self.msg_type == "other":
            # 对方消息，昵称在上
            outer_vbox = QVBoxLayout()
            outer_vbox.setContentsMargins(0,0,0,0)
            outer_vbox.setSpacing(3)

            nick_label = QLabel(self.nick)
            nick_label.setFont(self.font)
            nick_label.setStyleSheet("color:#444444;")
            outer_vbox.addWidget(nick_label)

            bubble_hbox = QHBoxLayout()
            bubble_hbox.setContentsMargins(0,0,0,0)
            bubble_hbox.setSpacing(0)
            indent_widget = QWidget()
            indent_widget.setFixedWidth(self.indent_size)
            bubble_hbox.addWidget(indent_widget)

            self.bubble_container = QWidget()
            self.bubble_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.bubble_container.setStyleSheet("""
                background-color:#f1f1f1;
                border:1px solid #dddddd;
                border-radius:8px;
                padding:6px;
            """)
            bubble_layout = QVBoxLayout(self.bubble_container)
            bubble_layout.setContentsMargins(0,0,0,0)
            bubble_layout.setSpacing(0)

            self.text_label = QLabel()
            self.text_label.setFont(self.font)
            self.text_label.setWordWrap(True)
            self.text_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            self.text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.text_label.setStyleSheet("background:transparent;border:none;")
            bubble_layout.addWidget(self.text_label)
            bubble_hbox.addWidget(self.bubble_container)

            outer_vbox.addLayout(bubble_hbox)
            self.main_layout.addLayout(outer_vbox)
            self.main_layout.addStretch(1)

        elif self.msg_type == "sys":
            self.main_layout.addStretch(1)
            label = QLabel(self.raw_text)
            label.setFont(self.font)
            label.setStyleSheet("color:#666666;")
            self.main_layout.addWidget(label)
            self.main_layout.addStretch(1)

        if self.text_label:
            self.text_label.setText(self.raw_text)
        if self.max_bubble_width > 0 and self.bubble_container:
            self.set_bubble_max_width(self.max_bubble_width)

    def set_bubble_max_width(self, w):
        """设置气泡容器最大宽度，窗口resize时调用"""
        self.max_bubble_width = w
        if self.msg_type == "other":
            avail_w = max(w - self.indent_size, 40)
        else:
            avail_w = max(w, 40)
        if self.bubble_container is not None:
            self.bubble_container.setMaximumWidth(avail_w)
            # 核心改动：删掉setText清空重写，改用updateGeometry通知Qt重算布局
            self.bubble_container.updateGeometry()
            self.updateGeometry()


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
                        txt = payload.decode("utf-8").strip()
                        self.msg_signal.emit(txt)
                    elif mt == 4:
                        try:
                            data = json.loads(payload.decode("utf-8"))
                            self.ms_signal.emit(data)
                        except Exception:
                            continue
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
        self.player_list = QLabel("Players:")
        self.status_label = QLabel("Waiting game...")
        left_layout.addWidget(self.player_list)
        left_layout.addWidget(self.status_label)
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.grid_layout.setSpacing(2)
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(grid_widget, 4)
        self.setLayout(main_layout)
        self.setMinimumSize(750, 520)

    def build_grid(self):
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons.clear()
        for x in range(self.rows):
            for y in range(self.cols):
                btn = QPushButton("")
                btn.setFixedSize(32,32)
                f = QFont("Arial",12)
                f.setBold(True)
                btn.setFont(f)
                btn.clicked.connect(lambda ch, xx=x, yy=y: self.on_click(xx, yy, "open"))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(lambda pos, xx=x, yy=y: self.on_click(xx, yy, "flag"))
                self.grid_layout.addWidget(btn, x, y)
                self.buttons[(x,y)] = btn

    def on_click(self, x, y, action):
        self.tcp.send_ms_cmd({"cmd": "click", "x": x, "y": y, "action": action})

    def update_board(self, cells, current, players):
        self.current_player = current
        self.players = players
        self.player_list.setText("Players:\n" + "\n".join([p + (" << YOUR TURN" if p == current else "") for p in players]))
        if current == self.my_nick:
            self.status_label.setText("YOUR TURN, click to open / right click flag")
            self.status_label.setStyleSheet("color:red;")
        else:
            self.status_label.setText(f"Waiting for {current}")
            self.status_label.setStyleSheet("color:#333;")
        for x in range(self.rows):
            for y in range(self.cols):
                val = cells[x][y]
                btn = self.buttons[(x,y)]
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


# ========== 视频弹窗 ==========
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280,140)
        scr = QApplication.primaryScreen().geometry()
        self.move(scr.width()-300, 120)
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
        self.setFixedSize(320,160)
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
        QMessageBox.critical(self, "Error", f"{err}")
        self.connect_btn.setEnabled(True)


# ========== 主窗口（ScrollArea + VBoxLayout 方案） ==========
class ChatMainWindow(QMainWindow):
    def __init__(self, host, nick, tcp):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nick}")
        self.setGeometry(100,100,680,520)
        self.nick = nick
        self.tcp = tcp
        self.ms_window = None

        central = QWidget()
        self.setCentralWidget(central)
        vl_main = QVBoxLayout(central)
        vl_main.setContentsMargins(6,6,6,6)
        vl_main.setSpacing(6)

        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border:none;")
        self.scroll_container = QWidget()
        self.msg_layout = QVBoxLayout(self.scroll_container)
        self.msg_layout.setContentsMargins(0,0,0,0)
        self.msg_layout.setSpacing(4)
        # 末尾拉伸，消息向上堆叠
        self.msg_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_container)
        vl_main.addWidget(self.scroll_area)

        # 按钮行
        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_vid = QPushButton("Start Video Call")
        self.btn_ms = QPushButton("Minesweeper")
        btn_layout.addWidget(self.btn_file)
        btn_layout.addWidget(self.btn_vid)
        btn_layout.addWidget(self.btn_ms)
        vl_main.addLayout(btn_layout)

        # 输入行
        input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Input message...")
        self.btn_send = QPushButton("Send")
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(self.btn_send)
        vl_main.addLayout(input_layout)

        # 信号绑定
        self.tcp.msg_signal.connect(self.on_recv_msg)
        self.tcp.ms_signal.connect(self.on_ms_event)
        self.tcp.disconnect_signal.connect(self.on_disconnect)
        self.btn_send.clicked.connect(self.send_msg)
        self.msg_input.returnPressed.connect(self.send_msg)
        self.btn_ms.clicked.connect(self.invite_minesweeper)
        self.btn_vid.clicked.connect(self.video_invite)
        self.btn_file.clicked.connect(self.send_file)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        view_width = self.scroll_area.viewport().width()
        max_w = int(view_width * 0.7)
        # 遍历全部气泡，更新上限并刷新
        for bubble in self.scroll_container.findChildren(MsgBubbleWidget):
            bubble.set_bubble_max_width(max_w)
        self.scroll_container.adjustSize()

    def add_bubble(self, bubble_widget):
        view_width = self.scroll_area.viewport().width()
        max_w = int(view_width * 0.7)
        bubble_widget.set_bubble_max_width(max_w)
        self.msg_layout.insertWidget(self.msg_layout.count()-1, bubble_widget)
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def send_msg(self):
        txt = self.msg_input.text().strip()
        if not txt:
            return
        bubble = MsgBubbleWidget("self", self.nick, txt)
        self.add_bubble(bubble)
        self.tcp.send_text(txt)
        self.msg_input.clear()

    def on_recv_msg(self, txt):
        if "joined" in txt or "left" in txt:
            bubble = MsgBubbleWidget("sys", "", txt)
            self.add_bubble(bubble)
        else:
            if txt.startswith("【") and "】：" in txt:
                idx = txt.index("】：")
                sender_nick = txt[1:idx]
                content = txt[idx+2:]
            else:
                sender_nick = ""
                content = txt
            bubble = MsgBubbleWidget("other", sender_nick, content)
            self.add_bubble(bubble)

    def invite_minesweeper(self):
        self.tcp.send_ms_cmd({"cmd": "invite"})

    def on_ms_event(self, d):
        cmd = d.get("cmd")
        if cmd == "invite":
            ret = QMessageBox.question(self, "Minesweeper Invite", f"{d['inviter']} invites you to minesweeper?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
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
            QMessageBox.information(self, "Win", "All mines cleared, you win!")
            if self.ms_window:
                self.ms_window.close()
                self.ms_window = None
        elif cmd == "cancel":
            QMessageBox.information(self, "Game cancelled", d.get("msg", ""))
        elif cmd == "abort":
            QMessageBox.information(self, "Game aborted", d.get("msg", ""))
        elif cmd == "busy":
            QMessageBox.warning(self, "Warning", "Room busy")
        elif cmd == "full":
            QMessageBox.warning(self, "Warning", "Room full")

    def video_invite(self):
        dlg = VideoInvitePopup(self)
        dlg.exec()

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            QMessageBox.information(self, "Tip", "File transfer function not implemented yet")

    def on_disconnect(self):
        bubble = MsgBubbleWidget("sys", "", "Disconnected from server")
        self.add_bubble(bubble)

    def closeEvent(self, event):
        self.tcp.close_conn()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        win = ChatMainWindow(login.host, login.nickname, login.tcp_thread)
        win.show()
        sys.exit(app.exec())
