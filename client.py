import sys
import json
import struct
import socket
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QDialog, QMessageBox, QFileDialog,
    QGridLayout, QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


# ========== 聊天气泡组件 ==========
class MsgBubbleWidget(QWidget):
    def __init__(self, msg_type, nick, text, initial_max_w=0):
        super().__init__()
        self.msg_type = msg_type
        self.nick = nick
        self.raw_text = text
        self.max_bubble_width = initial_max_w
        self.indent_size = 20

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 2, 0, 2)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        self.font = QFont()
        self.font.setPointSize(10)
        self.text_label = None
        self.bubble_container = None

        if self.msg_type == "self":
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
            bubble_layout.setContentsMargins(0, 0, 0, 0)
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
            outer_vbox = QVBoxLayout()
            outer_vbox.setContentsMargins(0, 0, 0, 0)
            outer_vbox.setSpacing(3)

            nick_label = QLabel(self.nick)
            nick_label.setFont(self.font)
            nick_label.setStyleSheet("color:#444444;")
            outer_vbox.addWidget(nick_label)

            bubble_hbox = QHBoxLayout()
            bubble_hbox.setContentsMargins(0, 0, 0, 0)
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
            bubble_layout.setContentsMargins(0, 0, 0, 0)
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
        self.max_bubble_width = w
        if self.msg_type == "other":
            avail_w = max(w - self.indent_size, 40)
        else:
            avail_w = max(w, 40)

        if self.bubble_container is not None:
            self.bubble_container.setMaximumWidth(avail_w)
            if self.text_label is not None:
                fm = self.fontMetrics()
                text_single_width = fm.horizontalAdvance(self.raw_text)
                label_avail_w = max(avail_w - 12, 20)

                if text_single_width <= label_avail_w:
                    self.text_label.setMinimumWidth(0)
                    self.text_label.setMaximumWidth(16777215)
                else:
                    self.text_label.setFixedWidth(label_avail_w)

                self.text_label.updateGeometry()
            self.bubble_container.adjustSize()
            self.adjustSize()

    def sizeHint(self):
        hint = super().sizeHint()
        if self.text_label:
            label_hint = self.text_label.sizeHint()
            hint.setWidth(label_hint.width())
            hint.setHeight(label_hint.height())
        return hint


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
        self.sock = None
        self.running = True

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(None)
            self.sock.connect((self.host, self.port))
            self.sock.sendall((self.nick + "\n").encode("utf-8"))
            self.connected_signal.emit()
            buf = b""
            while self.running:
                chunk = self.sock.recv(4096)
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
                        text = payload.decode("utf-8", errors="replace")
                        self.msg_signal.emit(text)
                    elif mt == 4:
                        obj = json.loads(payload.decode("utf-8", errors="replace"))
                        self.ms_signal.emit(obj)
            self.sock.close()
        except Exception as e:
            self.fail_signal.emit(str(e))
        finally:
            self.disconnect_signal.emit()

    def send_text(self, text):
        pkt = pack_msg(0, text.encode("utf-8"))
        try:
            if self.sock:
                self.sock.sendall(pkt)
        except Exception as e:
            print("send err", e)

    def send_json(self, obj):
        raw = json.dumps(obj).encode("utf-8")
        pkt = pack_msg(4, raw)
        try:
            if self.sock:
                self.sock.sendall(pkt)
        except Exception as e:
            print("send json err", e)

    def close_conn(self):
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            self.sock.close()


# ========== 扫雷邀请弹窗 ==========
class MinesweeperInviteDialog(QDialog):
    def __init__(self, parent, inviter, players, my_nick, tcp):
        super().__init__(parent)
        self.setWindowTitle("扫雷邀请")
        self.setFixedSize(320, 380)
        self.my_nick = my_nick
        self.tcp = tcp
        self.time_left = 30
        self.responses = {n: "pending" for n in players}
        self.responses[inviter] = "accept"
        self.has_responded = (my_nick == inviter)

        main_layout = QVBoxLayout()
        title = QLabel(f"{inviter} 邀请你玩扫雷")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        title.setFont(f)
        main_layout.addWidget(title)

        self.time_label = QLabel(f"剩余时间: {self.time_left}s")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.time_label)

        self.player_list_widget = QWidget()
        self.player_layout = QVBoxLayout(self.player_list_widget)
        self.player_layout.setContentsMargins(0, 0, 0, 0)
        self.player_layout.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.player_list_widget)
        main_layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        self.btn_accept = QPushButton("接受")
        self.btn_reject = QPushButton("拒绝")
        self.btn_accept.clicked.connect(self.on_accept)
        self.btn_reject.clicked.connect(self.on_reject)
        btn_layout.addWidget(self.btn_accept)
        btn_layout.addWidget(self.btn_reject)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.update_player_list()

        if self.has_responded:
            self.btn_accept.setEnabled(False)
            self.btn_reject.setEnabled(False)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(1000)

    def update_player_list(self):
        for i in reversed(range(self.player_layout.count())):
            item = self.player_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        for nick, status in self.responses.items():
            row = QHBoxLayout()
            nick_label = QLabel(nick)
            status_label = QLabel()
            if status == "accept":
                status_label.setText("✅ 接受")
                status_label.setStyleSheet("color: green;")
            elif status == "reject":
                status_label.setText("❌ 拒绝")
                status_label.setStyleSheet("color: red;")
            else:
                status_label.setText("⏳ 等待中")
                status_label.setStyleSheet("color: gray;")
            row.addWidget(nick_label)
            row.addStretch(1)
            row.addWidget(status_label)
            widget = QWidget()
            widget.setLayout(row)
            self.player_layout.addWidget(widget)

    def on_tick(self):
        self.time_left -= 1
        self.time_label.setText(f"剩余时间: {self.time_left}s")
        if self.time_left <= 0:
            self.timer.stop()
            if not self.has_responded:
                self.on_reject()

    def on_accept(self):
        if self.has_responded:
            return
        self.has_responded = True
        self.btn_accept.setEnabled(False)
        self.btn_reject.setEnabled(False)
        self.tcp.send_json({"cmd": "accept"})

    def on_reject(self):
        if self.has_responded:
            return
        self.has_responded = True
        self.btn_accept.setEnabled(False)
        self.btn_reject.setEnabled(False)
        self.tcp.send_json({"cmd": "reject"})

    def update_status(self, responses):
        self.responses = responses
        self.update_player_list()
        if self.my_nick in responses and responses[self.my_nick] != "pending":
            self.has_responded = True
            self.btn_accept.setEnabled(False)
            self.btn_reject.setEnabled(False)


# ========== 结算弹窗 ==========
class GameResultDialog(QDialog):
    def __init__(self, parent, result, my_nick, tcp):
        super().__init__(parent)
        self.setWindowTitle("游戏结束")
        self.setFixedSize(320, 400)
        self.my_nick = my_nick
        self.tcp = tcp
        self.result = result
        self.time_left = 30
        self.responses = {item["nick"]: "pending" for item in result}
        self.has_responded = False

        main_layout = QVBoxLayout()
        title = QLabel("游戏结束")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        title.setFont(f)
        main_layout.addWidget(title)

        self.time_label = QLabel(f"剩余时间: {self.time_left}s")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.time_label)

        self.rank_widget = QWidget()
        self.rank_layout = QVBoxLayout(self.rank_widget)
        self.rank_layout.setContentsMargins(0, 0, 0, 0)
        self.rank_layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rank_widget)
        main_layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        self.btn_rematch = QPushButton("再来一局")
        self.btn_quit = QPushButton("退出")
        self.btn_rematch.clicked.connect(self.on_rematch)
        self.btn_quit.clicked.connect(self.on_quit)
        btn_layout.addWidget(self.btn_rematch)
        btn_layout.addWidget(self.btn_quit)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)
        self.update_rank_list()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(1000)

    def update_rank_list(self):
        for i in reversed(range(self.rank_layout.count())):
            item = self.rank_layout.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        for idx, item in enumerate(self.result, 1):
            nick = item["nick"]
            score = item["score"]
            status = self.responses.get(nick, "pending")

            row = QHBoxLayout()
            rank_label = QLabel(f"{idx}.")
            rank_label.setFixedWidth(20)
            nick_label = QLabel(nick)
            score_label = QLabel(f"{score} 分")
            status_label = QLabel()

            if status == "accept":
                status_label.setText("✅")
            elif status == "reject":
                status_label.setText("❌")
            else:
                status_label.setText("⏳")

            row.addWidget(rank_label)
            row.addWidget(nick_label, 1)
            row.addWidget(score_label)
            row.addWidget(status_label)

            widget = QWidget()
            widget.setLayout(row)
            self.rank_layout.addWidget(widget)

    def on_tick(self):
        self.time_left -= 1
        self.time_label.setText(f"剩余时间: {self.time_left}s")
        if self.time_left <= 0:
            self.timer.stop()
            if not self.has_responded:
                self.on_quit()

    def on_rematch(self):
        if self.has_responded:
            return
        self.has_responded = True
        self.btn_rematch.setEnabled(False)
        self.btn_quit.setEnabled(False)
        self.tcp.send_json({"cmd": "rematch_accept"})

    def on_quit(self):
        if self.has_responded:
            return
        self.has_responded = True
        self.btn_rematch.setEnabled(False)
        self.btn_quit.setEnabled(False)
        self.tcp.send_json({"cmd": "rematch_reject"})

    def update_status(self, responses):
        self.responses = responses
        self.update_rank_list()
        if self.my_nick in responses and responses[self.my_nick] != "pending":
            self.has_responded = True
            self.btn_rematch.setEnabled(False)
            self.btn_quit.setEnabled(False)


# ========== 扫雷窗口 ==========
class MinesweeperWindow(QDialog):
    def __init__(self, parent, tcp, my_nick):
        super().__init__(parent)
        self.setWindowTitle("多人扫雷")
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
        self.player_label = QLabel("等待游戏开始...")
        left_layout.addWidget(self.player_label)
        left_layout.addStretch(1)
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.grid_layout.setSpacing(2)
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(grid_widget, 4)
        self.setLayout(main_layout)
        self.setFixedSize(750, 520)

    def build_grid(self):
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons.clear()
        for x in range(self.rows):
            for y in range(self.cols):
                btn = QPushButton("")
                btn.setFixedSize(32, 32)
                f = QFont("Arial", 12)
                f.setBold(True)
                btn.setFont(f)
                btn.clicked.connect(lambda ch, xx=x, yy=y: self.on_click(xx, yy, "open"))
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(lambda pos, xx=x, yy=y: self.on_click(xx, yy, "flag"))
                self.grid_layout.addWidget(btn, x, y)
                self.buttons[(x, y)] = btn

    def on_click(self, x, y, action):
        if self.current_player != self.my_nick:
            return
        self.tcp.send_json({"cmd": "click", "x": x, "y": y, "action": action})

    def update_board(self, cells, current, players):
        self.current_player = current
        self.players = players
        txt = "玩家列表：\n"
        for p in players:
            nick = p["nick"]
            alive = p["alive"]
            line = f"{nick}"
            if not alive:
                line += " 💀"
            if nick == current:
                line += " ◀ 你的回合"
            txt += line + "\n"
        self.player_label.setText(txt.strip())

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
                    btn.setEnabled(False)
                elif val == "m":
                    btn.setText("💣")
                    btn.setStyleSheet("background:#ff6666; color:white; border:1px solid #bbb;")
                    btn.setEnabled(False)
                else:
                    btn.setText(val)
                    btn.setStyleSheet("background:#ffffff; border:1px solid #bbb;")
                    btn.setEnabled(False)

        is_my_turn = (self.current_player == self.my_nick)
        for btn in self.buttons.values():
            if btn.isEnabled():
                btn.setEnabled(is_my_turn)


# ========== 视频弹窗 ==========
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        lay = QVBoxLayout()
        lay.addWidget(QLabel("Incoming Video Call"))
        hlay = QHBoxLayout()
        btn_accept = QPushButton("Accept")
        btn_reject = QPushButton("Reject")
        btn_accept.clicked.connect(self.accept)
        btn_reject.clicked.connect(self.reject)
        hlay.addWidget(btn_accept)
        hlay.addWidget(btn_reject)
        lay.addLayout(hlay)
        self.setLayout(lay)


# ========== 登录弹窗 ==========
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("登录")
        self.setFixedSize(320, 160)
        lay = QVBoxLayout()
        lay.addWidget(QLabel("服务器地址"))
        self.ip_edit = QLineEdit("127.0.0.1")
        lay.addWidget(self.ip_edit)
        lay.addWidget(QLabel("昵称"))
        self.nick_edit = QLineEdit()
        lay.addWidget(self.nick_edit)
        self.status_label = QLabel("")
        lay.addWidget(self.status_label)
        self.connect_btn = QPushButton("连接")
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
            QMessageBox.warning(self, "警告", "服务器地址和昵称不能为空！")
            return
        self.status_label.setText("连接中...")
        self.connect_btn.setEnabled(False)
        self.host = ip
        self.nickname = nick
        self.tcp_thread = TcpClientThread(ip, 8080, nick)
        self.tcp_thread.connected_signal.connect(lambda: self.accept())
        self.tcp_thread.fail_signal.connect(lambda e: (self.status_label.setText(e), self.connect_btn.setEnabled(True)))
        self.tcp_thread.start()


# ========== 主聊天窗口 ==========
class ChatMainWindow(QMainWindow):
    def __init__(self, host, nick, tcp):
        super().__init__()
        self.resize_timer = None
        self.setWindowTitle(f"聊天室 - {nick}")
        self.setGeometry(100, 100, 680, 520)
        self.nick = nick
        self.tcp = tcp
        self.ms_window = None
        self.invite_dialog = None
        self.result_dialog = None

        central = QWidget()
        self.setCentralWidget(central)
        vl_main = QVBoxLayout(central)
        vl_main.setContentsMargins(6, 6, 6, 6)
        vl_main.setSpacing(6)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border:none;")
        self.scroll_container = QWidget()
        self.msg_layout = QVBoxLayout(self.scroll_container)
        self.msg_layout.setContentsMargins(0, 0, 0, 0)
        self.msg_layout.setSpacing(4)
        self.msg_layout.addStretch(1)
        self.scroll_area.setWidget(self.scroll_container)
        vl_main.addWidget(self.scroll_area)

        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("发送文件")
        self.btn_video = QPushButton("发起视频")
        self.btn_ms = QPushButton("扫雷游戏")
        btn_layout.addWidget(self.btn_file)
        btn_layout.addWidget(self.btn_video)
        btn_layout.addWidget(self.btn_ms)
        vl_main.addLayout(btn_layout)

        input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("输入消息...")
        self.btn_send = QPushButton("发送")
        input_layout.addWidget(self.msg_input)
        input_layout.addWidget(self.btn_send)
        vl_main.addLayout(input_layout)

        self.tcp.msg_signal.connect(self.on_recv_msg)
        self.tcp.ms_signal.connect(self.on_ms_event)
        self.tcp.disconnect_signal.connect(self.on_disconnect)
        self.btn_send.clicked.connect(self.send_msg)
        self.msg_input.returnPressed.connect(self.send_msg)
        self.btn_ms.clicked.connect(self.open_minesweeper)
        self.btn_video.clicked.connect(self.open_video)
        self.btn_file.clicked.connect(self.send_file)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.resize_timer is not None:
            self.killTimer(self.resize_timer)
        self.resize_timer = self.startTimer(80)

    def timerEvent(self, event):
        if event.timerId() == self.resize_timer:
            self.killTimer(self.resize_timer)
            self.resize_timer = None
            view_width = self.scroll_area.viewport().width()
            max_w = int(view_width * 0.8)
            for bubble in self.scroll_container.findChildren(MsgBubbleWidget):
                bubble.set_bubble_max_width(max_w)
            self.scroll_container.adjustSize()

    def add_bubble(self, bubble_widget):
        view_width = self.scroll_area.viewport().width()
        max_w = int(view_width * 0.8)
        bubble_widget.set_bubble_max_width(max_w)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble_widget)
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
                content = txt[idx + 2:]
            else:
                sender_nick = ""
                content = txt
            bubble = MsgBubbleWidget("other", sender_nick, content)
            self.add_bubble(bubble)

    def open_minesweeper(self):
        self.tcp.send_json({"cmd": "invite"})

    def on_ms_event(self, d):
        cmd = d.get("cmd")
        if cmd == "invite":
            if self.invite_dialog and self.invite_dialog.isVisible():
                self.invite_dialog.close()
            self.invite_dialog = MinesweeperInviteDialog(
                self, d["inviter"], d["players"], self.nick, self.tcp
            )
            self.invite_dialog.show()

        elif cmd == "invite_status":
            if self.invite_dialog and self.invite_dialog.isVisible():
                self.invite_dialog.update_status(d["responses"])

        elif cmd == "cancel":
            if self.invite_dialog and self.invite_dialog.isVisible():
                self.invite_dialog.close()
            QMessageBox.information(self, "提示", d.get("msg", "邀请已取消"))

        elif cmd == "busy":
            QMessageBox.warning(self, "提示", "当前已有游戏进行中")

        elif cmd == "full":
            QMessageBox.warning(self, "提示", "游戏人数已满")

        elif cmd == "start":
            if self.invite_dialog and self.invite_dialog.isVisible():
                self.invite_dialog.close()
            if self.result_dialog and self.result_dialog.isVisible():
                self.result_dialog.close()
            self.ms_window = MinesweeperWindow(self, self.tcp, self.nick)
            self.ms_window.build_grid()
            # 修复：开局初始化棋盘和玩家状态，让第一个玩家可以操作
            init_cells = [["c" for _ in range(16)] for _ in range(16)]
            init_players = [{"nick": p, "alive": True} for p in d["players"]]
            self.ms_window.update_board(init_cells, d["current"], init_players)
            self.ms_window.show()

        elif cmd == "update":
            if self.ms_window and self.ms_window.isVisible():
                self.ms_window.update_board(d["cells"], d["current"], d["players"])

        elif cmd == "game_end":
            if self.ms_window and self.ms_window.isVisible():
                self.ms_window.close()
            self.result_dialog = GameResultDialog(self, d["result"], self.nick, self.tcp)
            self.result_dialog.show()

        elif cmd == "rematch_status":
            if self.result_dialog and self.result_dialog.isVisible():
                self.result_dialog.update_status(d["responses"])

        elif cmd == "rematch_cancel":
            if self.result_dialog and self.result_dialog.isVisible():
                self.result_dialog.close()
            QMessageBox.information(self, "提示", d.get("msg", "再来一局取消"))

        elif cmd == "abort":
            if self.ms_window and self.ms_window.isVisible():
                self.ms_window.close()
            QMessageBox.information(self, "提示", d.get("msg", "游戏中止"))

    def open_video(self):
        dlg = VideoInvitePopup(self)
        dlg.exec()

    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            QMessageBox.information(self, "提示", "文件传输功能暂未实现")

    def on_disconnect(self):
        bubble = MsgBubbleWidget("sys", "", "与服务器断开连接")
        self.add_bubble(bubble)

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
