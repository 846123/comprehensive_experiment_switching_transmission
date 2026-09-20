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
from PyQt6.QtGui import QFont, QTextDocument, QTextOption


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


# ========== 聊天气泡组件【已修改，方案A QLabel+setWordWrap】 ==========
class MsgBubbleWidget(QWidget):
    def __init__(self, msg_type, nick, text):
        super().__init__()
        self.msg_type = msg_type
        self.nick = nick
        self.raw_text = text
        self.bubble_max_width = 0
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        self.font = QFont()
        self.font.setPointSize(10)
        self.init_ui()

    def init_ui(self):
        if self.msg_type == "self":
            self.layout = QHBoxLayout()
            self.layout.setContentsMargins(0, 2, 0, 2)
            self.layout.setSpacing(0)
            self.layout.addStretch(1)
            self.text_container = QWidget()
            self.text_layout = QVBoxLayout(self.text_container)
            self.text_layout.setContentsMargins(6,6,6,6)
            self.text_layout.setSpacing(0)
            self.bubble_label = QLabel()
            self.bubble_label.setFont(self.font)
            self.bubble_label.setWordWrap(True)
            self.bubble_label.setTextFormat(Qt.TextFormat.PlainText)
            self.bubble_label.setStyleSheet("background-color:#ffffff; border:1px solid #cccccc; border-radius:8px;")
            self.text_layout.addWidget(self.bubble_label)
            self.layout.addWidget(self.text_container)
            self.setLayout(self.layout)

        elif self.msg_type == "other":
            self.layout = QVBoxLayout()
            self.layout.setContentsMargins(0, 2, 0, 2)
            self.layout.setSpacing(3)
            lb_nick = QLabel(self.nick)
            lb_nick.setFont(self.font)
            lb_nick.setStyleSheet("background:transparent; border:none;")
            lb_nick.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.text_container = QWidget()
            self.text_layout = QVBoxLayout(self.text_container)
            self.text_layout.setContentsMargins(6,6,6,6)
            self.text_layout.setSpacing(0)
            self.bubble_label = QLabel()
            self.bubble_label.setFont(self.font)
            self.bubble_label.setWordWrap(True)
            self.bubble_label.setTextFormat(Qt.TextFormat.PlainText)
            self.bubble_label.setStyleSheet("background-color:#f1f1f1; border:1px solid #dddddd; border-radius:8px;")
            self.text_layout.addWidget(self.bubble_label)
            self.layout.addWidget(lb_nick)
            self.layout.addWidget(self.text_container)
            self.setLayout(self.layout)
        else:
            self.layout = QHBoxLayout()
            self.layout.setContentsMargins(0, 2, 0, 2)
            self.bubble_label = QLabel()
            self.bubble_label.setFont(self.font)
            self.bubble_label.setWordWrap(True)
            self.bubble_label.setTextFormat(Qt.TextFormat.PlainText)
            self.bubble_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bubble_label.setStyleSheet("color:#666; background:transparent; border:none;")
            self.layout.addWidget(self.bubble_label)
            self.setLayout(self.layout)

    def set_bubble_max_width(self, w):
        self.bubble_max_width = w
        self.bubble_label.setMaximumWidth(w)
        doc = QTextDocument()
        doc.setDefaultFont(self.font)
        opt = QTextOption()
        # 中文任意字符换行
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        doc.setPlainText(self.raw_text)
        doc.setTextWidth(w)
        raw_text_width = doc.size().width()

        if raw_text_width <= w:
            final_width = raw_text_width
        else:
            final_width = w
        text_size = doc.size()
        label_w = int(final_width)
        label_h = int(text_size.height())
        if label_w < 20:
            label_w = 20
        self.bubble_label.setFixedSize(label_w, label_h)
        self.bubble_label.setText(self.raw_text)
        self.adjustSize()
        self.updateGeometry()

# ========== 网络线程【完全原样保留】 ==========
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

# ========== 扫雷窗口【原样保留】 ==========
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
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(2)
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(grid_widget, 4)
        self.setLayout(main_layout)
        self.setMinimumSize(750, 520)
        self.grid_layout = grid_layout

    def build_grid(self):
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons.clear()
        for x in range(self.rows):
            for y in range(self.cols):
                btn = QPushButton("")
                btn.setFixedSize(32, 32)
                f = QFont("Arial", 12, QFont.Weight.Bold)
                btn.setFont(f)
                btn.clicked.connect(lambda ch, xx=x, yy=y: self.on_click(xx, yy, "open"))
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
            line = p
            if p == current:
                line += " << YOUR TURN"
            item = QListWidgetItem(line)
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

# ========== 视频通话弹窗【原样保留】 ==========
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        scr = QApplication.primaryScreen().geometry()
        self.move(scr.width() - 300, 120)
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

# ========== 登录弹窗【原样保留】 ==========
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
        QMessageBox.critical(self, "Error", f"{err}")
        self.connect_btn.setEnabled(True)

# ========== 主聊天窗口【只删掉 widget.repaint()，其余原样】 ==========
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
        self.btn_send.clicked.connect(self.send_msg)
        self.msg_input.returnPressed.connect(self.send_msg)
        self.btn_ms.clicked.connect(self.invite_minesweeper)
        self.btn_vid.clicked.connect(self.video_invite)
        self.btn_file.clicked.connect(self.send_file)

    def update_bubbles_width(self):
        view_width = self.msg_list.viewport().width()
        max_bubble_w = int(view_width * 0.8)
        for i in range(self.msg_list.count()):
            item = self.msg_list.item(i)
            widget = self.msg_list.itemWidget(item)
            if isinstance(widget, MsgBubbleWidget):
                widget.set_bubble_max_width(max_bubble_w)
                item.setSizeHint(widget.sizeHint())
        self.msg_list.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_bubbles_width()

    def add_bubble(self, widget, max_w):
        widget.set_bubble_max_width(max_w)
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self.msg_list.addItem(item)
        self.msg_list.setItemWidget(item, widget)
        self.msg_list.scrollToBottom()

    def send_msg(self):
        txt = self.msg_input.text().strip()
        if not txt:
            return
        view_width = self.msg_list.viewport().width()
        max_bubble_w = int(view_width * 0.8)
        bubble = MsgBubbleWidget("self", self.nick, txt)
        self.add_bubble(bubble, max_bubble_w)
        self.tcp.send_text(txt)
        self.msg_input.clear()

    def on_recv_msg(self, txt):
        view_width = self.msg_list.viewport().width()
        max_bubble_w = int(view_width * 0.8)
        if "joined" in txt or "left" in txt:
            bubble = MsgBubbleWidget("sys", "", txt)
            self.add_bubble(bubble, max_bubble_w)
        else:
            if txt.startswith("【") and "】：" in txt:
                idx = txt.index("】：")
                sender_nick = txt[1:idx]
                content = txt[idx+2:]
            else:
                sender_nick = ""
                content = txt
            bubble = MsgBubbleWidget("other", sender_nick, content)
            self.add_bubble(bubble, max_bubble_w)

    def invite_minesweeper(self):
        self.tcp.send_ms_cmd({"cmd": "invite"})

    def on_ms_event(self, d):
        cmd = d.get("cmd")
        if cmd == "invite":
            ret = QMessageBox.question(self, "Minesweeper Invite", f"{d['inviter']} invites you to minesweeper, accept?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
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
            QMessageBox.warning(self, "Warning", "Room full!")

    def video_invite(self):
        dlg = VideoInvitePopup(self)
        dlg.exec()

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            QMessageBox.information(self, "Tip", "File transfer function not implemented yet")

    def on_disconnect(self):
        view_width = self.msg_list.viewport().width()
        max_bubble_w = int(view_width * 0.8)
        bubble = MsgBubbleWidget("sys", "", "Disconnected from server")
        self.add_bubble(bubble, max_bubble_w)

    def closeEvent(self, event):
        self.tcp.close_conn()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        win = ChatMainWindow(login.host, login.nickname, login.tcp_thread)
        win.show()
        win.update_bubbles_width()
        sys.exit(app.exec())
