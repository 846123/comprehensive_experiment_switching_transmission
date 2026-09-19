import sys
import os
import json
import asyncio
import hashlib
import struct
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QDialog, QMessageBox, QFileDialog, QSizePolicy, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload

def unpack_header(h):
    return struct.unpack(">HIH", h)


# ========== 聊天气泡 ==========
class MsgBubbleWidget(QWidget):
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
            bw = QWidget()
            bl = QHBoxLayout(bw)
            bl.setContentsMargins(8, 6, 8, 6)
            lab = QLabel(content)
            lab.setWordWrap(True)
            lab.setFont(font)
            lab.setStyleSheet("background:transparent; border:none;")
            bl.addWidget(lab)
            bw.setStyleSheet("QWidget{background:#fff;border-radius:10px;border:1px solid #ccc;} QWidget QLabel{border:none;}")
            layout.addWidget(bw)

        elif msg_type == "other":
            bw = QWidget()
            bl = QHBoxLayout(bw)
            bl.setContentsMargins(8, 6, 8, 6)
            bl.setSpacing(4)
            nick = QLabel(f"【{nickname}】:")
            nick.setFont(font)
            nick.setStyleSheet("background:transparent; border:none;")
            nick.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            cnt = QLabel(content)
            cnt.setWordWrap(True)
            cnt.setFont(font)
            cnt.setStyleSheet("background:transparent; border:none;")
            bl.addWidget(nick)
            bl.addWidget(cnt)
            bw.setStyleSheet("QWidget{background:#f1f1f1;border-radius:10px;border:1px solid #ddd;} QWidget QLabel{border:none;}")
            layout.addWidget(bw)
            layout.addStretch(1)

        elif msg_type == "system":
            layout.addStretch(1)
            lab = QLabel(content)
            lab.setFont(font)
            lab.setStyleSheet("color:#666; background:transparent; border:none;")
            layout.addWidget(lab)
            layout.addStretch(1)


# ========== 网络线程 ==========
class TcpClientThread(QThread):
    msg_signal = pyqtSignal(str)
    file_info_signal = pyqtSignal(dict)
    file_finish_signal = pyqtSignal(bool, str)
    ms_signal = pyqtSignal(dict)
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
        self.recv_file = None
        self.recv_filename = ""
        self.recv_total = 0
        self.recv_md5 = ""
        self.recv_got = 0
        self.recv_path = ""

    def reset_file(self):
        if self.recv_file:
            self.recv_file.close()
        self.recv_file = None
        self.recv_filename = ""
        self.recv_total = 0
        self.recv_md5 = ""
        self.recv_got = 0
        self.recv_path = ""

    async def tcp_task(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.writer.write((self.nickname + "\n").encode())
            await self.writer.drain()
            self.connect_ok_signal.emit()
            buf = b""
            while self.running:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    mt, pl, _ = unpack_header(buf[:8])
                    total = 8 + pl
                    if len(buf) < total:
                        break
                    pkt = buf[:total]
                    buf = buf[total:]
                    payload = pkt[8:]
                    if mt == 0:
                        self.msg_signal.emit(payload.decode("utf-8"))
                    elif mt == 1:
                        meta = json.loads(payload.decode("utf-8"))
                        self.reset_file()
                        self.recv_filename = meta["filename"]
                        self.recv_total = meta["size"]
                        self.recv_md5 = meta["md5"]
                        os.makedirs(f"recv_files/{self.nickname}", exist_ok=True)
                        self.recv_path = f"recv_files/{self.nickname}/received_{self.recv_filename}"
                        self.recv_file = open(self.recv_path, "wb")
                        self.file_info_signal.emit(meta)
                    elif mt == 2:
                        if self.recv_file is None:
                            continue
                        self.recv_file.write(payload)
                        self.recv_got += len(payload)
                        if self.recv_got >= self.recv_total:
                            self.recv_file.close()
                            self.recv_file = None
                            h = hashlib.md5()
                            with open(self.recv_path, "rb") as f:
                                h.update(f.read())
                            ok = h.hexdigest() == self.recv_md5
                            self.file_finish_signal.emit(ok, self.recv_path)
                            self.reset_file()
                    elif mt == 4:
                        try:
                            self.ms_signal.emit(json.loads(payload.decode("utf-8")))
                        except Exception:
                            pass
        except Exception as e:
            self.connect_fail_signal.emit(str(e))
        finally:
            self.reset_file()
            self.disconnected_signal.emit()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.tcp_task())

    async def _send_raw(self, data):
        self.writer.write(data)
        await self.writer.drain()

    def send_text(self, text):
        if self.writer:
            pkt = pack_msg(0, f"{self.nickname}|{text}".encode("utf-8"))
            asyncio.run_coroutine_threadsafe(self._send_raw(pkt), self.loop)

    def send_file(self, path):
        if not self.writer or not os.path.exists(path):
            return
        fname = os.path.basename(path)
        size = os.path.getsize(path)
        h = hashlib.md5()
        with open(path, "rb") as f:
            while c := f.read(4096):
                h.update(c)
        meta = {"filename": fname, "size": size, "md5": h.hexdigest()}
        mp = pack_msg(1, json.dumps(meta).encode("utf-8"))
        asyncio.run_coroutine_threadsafe(self._send_file(mp, path), self.loop)

    async def _send_file(self, mp, path):
        await self._send_raw(mp)
        with open(path, "rb") as f:
            while chunk := f.read(4096):
                await self._send_raw(pack_msg(2, chunk))

    def send_ms(self, cmd_dict):
        if self.writer:
            pkt = pack_msg(4, json.dumps(cmd_dict).encode("utf-8"))
            asyncio.run_coroutine_threadsafe(self._send_raw(pkt), self.loop)

    def close_conn(self):
        self.running = False
        if self.writer:
            asyncio.run_coroutine_threadsafe(self.writer.close(), self.loop)


# ========== 扫雷格子按钮 ==========
class CellButton(QPushButton):
    left_clicked = pyqtSignal(int, int)
    right_clicked = pyqtSignal(int, int)

    def __init__(self, x, y):
        super().__init__("")
        self.x = x
        self.y = y
        self.setFixedSize(32, 32)
        self.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.setStyleSheet("QPushButton{background:#cfcfcf; border:1px solid #999;}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(self.x, self.y)
        else:
            super().mousePressEvent(e)
            self.left_clicked.emit(self.x, self.y)


# ========== 扫雷等待窗口（发起人） ==========
class MSWaitingDialog(QDialog):
    def __init__(self, parent, inviter, tcp_client):
        super().__init__(parent)
        self.setWindowTitle("Waiting for players...")
        self.setFixedSize(320, 260)
        self.tcp = tcp_client
        lay = QVBoxLayout(self)
        self.info = QLabel(f"Inviter: {inviter}\nMax 6 players, min 2.")
        self.player_list = QListWidget()
        self.count_label = QLabel("Players: 1/6")
        self.timer_label = QLabel("Countdown: 15s")
        cancel_btn = QPushButton("Cancel Invite")
        cancel_btn.clicked.connect(self.on_cancel)
        lay.addWidget(self.info)
        lay.addWidget(self.player_list)
        lay.addWidget(self.count_label)
        lay.addWidget(self.timer_label)
        lay.addWidget(cancel_btn)

        self.remain = 15
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        self.remain -= 1
        self.timer_label.setText(f"Countdown: {self.remain}s")
        if self.remain <= 0:
            self.timer.stop()

    def update_players(self, players):
        self.player_list.clear()
        for p in players:
            self.player_list.addItem(p)
        self.count_label.setText(f"Players: {len(players)}/6")

    def on_cancel(self):
        self.tcp.send_ms({"cmd": "cancel"})
        self.close()


# ========== 扫雷邀请弹窗（被邀请人） ==========
class MSInviteDialog(QDialog):
    def __init__(self, parent, inviter, tcp_client):
        super().__init__(parent)
        self.setWindowTitle("Game Invite")
        self.setFixedSize(280, 160)
        self.tcp = tcp_client
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"{inviter} invites you to Minesweeper!"))
        self.timer_label = QLabel("15s to join")
        lay.addWidget(self.timer_label)
        btn_lay = QHBoxLayout()
        join_btn = QPushButton("Join Game")
        decl_btn = QPushButton("Decline")
        join_btn.clicked.connect(self.on_join)
        decl_btn.clicked.connect(self.on_decline)
        btn_lay.addWidget(join_btn)
        btn_lay.addWidget(decl_btn)
        lay.addLayout(btn_lay)

        self.remain = 15
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)

    def tick(self):
        self.remain -= 1
        self.timer_label.setText(f"{self.remain}s to join")
        if self.remain <= 0:
            self.timer.stop()
            self.reject()

    def on_join(self):
        self.tcp.send_ms({"cmd": "accept"})
        self.accept()

    def on_decline(self):
        self.tcp.send_ms({"cmd": "reject"})
        self.reject()


# ========== 扫雷游戏窗口 ==========
class MSGameWindow(QDialog):
    def __init__(self, parent, my_nick, rows, cols, tcp_client):
        super().__init__(parent)
        self.setWindowTitle("Minesweeper Online")
        self.my_nick = my_nick
        self.rows = rows
        self.cols = cols
        self.tcp = tcp_client
        self.current_player = None
        self.buttons = {}
        self.setMinimumSize(720, 600)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(QLabel("Players:"))
        self.player_list = QListWidget()
        left.addWidget(self.player_list)
        self.status = QLabel("")
        left.addWidget(self.status)
        root.addLayout(left)

        right = QVBoxLayout()
        grid_holder = QWidget()
        self.grid = QGridLayout(grid_holder)
        self.grid.setSpacing(2)
        right.addWidget(grid_holder)
        root.addLayout(right)

        for x in range(rows):
            for y in range(cols):
                b = CellButton(x, y)
                b.left_clicked.connect(self.on_left)
                b.right_clicked.connect(self.on_right)
                self.grid.addWidget(b, x, y)
                self.buttons[(x, y)] = b

    def is_my_turn(self):
        return self.current_player == self.my_nick

    def on_left(self, x, y):
        if not self.is_my_turn():
            return
        self.tcp.send_ms({"cmd": "click", "x": x, "y": y, "action": "open"})

    def on_right(self, x, y):
        if not self.is_my_turn():
            return
        self.tcp.send_ms({"cmd": "click", "x": x, "y": y, "action": "flag"})

    def update_players(self, players):
        self.player_list.clear()
        for p in players:
            text = p + ("  << YOUR TURN" if p == self.current_player else "")
            item = QListWidgetItem(text)
            if p == self.current_player:
                item.setForeground(Qt.GlobalColor.red)
            if p == self.my_nick:
                item.setFont(QFont("", 10, QFont.Weight.Bold))
            self.player_list.addItem(item)
        if self.is_my_turn():
            self.status.setText("YOUR TURN - click to open, right-click to flag")
            self.status.setStyleSheet("color:red;")
        else:
            self.status.setText(f"Waiting for {self.current_player}...")
            self.status.setStyleSheet("color:#666;")

    def update_board(self, cells, current, players):
        self.current_player = current
        for x in range(self.rows):
            for y in range(self.cols):
                v = cells[x][y]
                b = self.buttons[(x, y)]
                if v == "c":
                    b.setText("")
                    b.setEnabled(True)
                    b.setStyleSheet("QPushButton{background:#cfcfcf; border:1px solid #999;}")
                elif v == "f":
                    b.setText("F")
                    b.setStyleSheet("QPushButton{background:#ffd5d5; border:1px solid #999; color:red;}")
                else:
                    b.setText(v)
                    b.setEnabled(False)
                    b.setStyleSheet("QPushButton{background:#fff; border:1px solid #bbb; color:#333;}")
        self.update_players(players)

    def reveal_mines(self, mines, loser):
        for x, y in mines:
            b = self.buttons.get((x, y))
            if b:
                b.setText("*")
                b.setEnabled(False)
                b.setStyleSheet("QPushButton{background:#ff6666; border:1px solid #999; color:#fff;}")
        QMessageBox.information(self, "Game Over", f"{loser} hit a mine!")


# ========== 视频邀请弹窗（保留占位） ==========
class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        s = QApplication.primaryScreen().geometry()
        self.move(s.width() - 300, 120)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Incoming Video Call Invite"))
        bl = QHBoxLayout()
        a = QPushButton("Accept")
        r = QPushButton("Reject")
        a.clicked.connect(self.accept)
        r.clicked.connect(self.reject)
        bl.addWidget(a)
        bl.addWidget(r)
        lay.addLayout(bl)


# ========== 登录窗口 ==========
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login")
        self.setFixedSize(320, 160)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Server IP"))
        self.ip_edit = QLineEdit("127.0.0.1")
        lay.addWidget(self.ip_edit)
        lay.addWidget(QLabel("Nickname"))
        self.nick_edit = QLineEdit()
        lay.addWidget(self.nick_edit)
        self.status = QLabel("")
        lay.addWidget(self.status)
        self.ok = QPushButton("Connect")
        self.ok.clicked.connect(self.on_ok)
        lay.addWidget(self.ok)
        self.nickname = None
        self.host = None
        self.tcp = None

    def on_ok(self):
        ip = self.ip_edit.text().strip()
        nick = self.nick_edit.text().strip()
        if not ip or not nick:
            QMessageBox.warning(self, "Warning", "IP and nickname cannot be empty!")
            return
        self.status.setText("Connecting...")
        self.ok.setEnabled(False)
        self.tcp = TcpClientThread(ip, nick)
        self.tcp.connect_ok_signal.connect(self.on_ok_conn)
        self.tcp.connect_fail_signal.connect(self.on_fail_conn)
        self.tcp.start()

    def on_ok_conn(self):
        self.nickname = self.nick_edit.text().strip()
        self.host = self.ip_edit.text().strip()
        self.accept()

    def on_fail_conn(self, err):
        self.status.setText("Connect failed!")
        QMessageBox.critical(self, "Error", err)
        self.tcp.quit()
        self.tcp.wait()
        self.tcp = None
        self.ok.setEnabled(True)


# ========== 主聊天窗口 ==========
class ChatMainWindow(QMainWindow):
    def __init__(self, host, nickname, tcp):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nickname}")
        self.setGeometry(100, 100, 680, 520)
        self.nickname = nickname
        self.tcp = tcp
        self.ms_wait_dlg = None
        self.ms_game_win = None

        central = QWidget()
        self.setCentralWidget(central)
        vl = QVBoxLayout(central)

        self.msg_list = QListWidget()
        self.msg_list.setSpacing(4)
        self.msg_list.setStyleSheet("""
        QListWidget{background:transparent; border:none;}
        QListWidget::item{border:none; background:transparent;}
        QListWidget::item:selected{background:transparent;}
        QListWidget::item:hover{background:transparent;}
        """)
        vl.addWidget(self.msg_list)

        bl = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_file.clicked.connect(self.select_file)
        self.btn_video = QPushButton("Start Video Call")
        self.btn_video.clicked.connect(lambda: VideoInvitePopup(self).exec())
        self.btn_ms = QPushButton("Minesweeper")
        self.btn_ms.clicked.connect(self.invite_ms)
        bl.addWidget(self.btn_file)
        bl.addWidget(self.btn_video)
        bl.addWidget(self.btn_ms)
        vl.addLayout(bl)

        il = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Input message...")
        send = QPushButton("Send")
        send.clicked.connect(self.send_msg)
        il.addWidget(self.input)
        il.addWidget(send)
        vl.addLayout(il)

        tcp.msg_signal.connect(self.on_recv_msg)
        tcp.file_info_signal.connect(self.on_file_info)
        tcp.file_finish_signal.connect(self.on_file_finish)
        tcp.ms_signal.connect(self.on_ms_msg)
        tcp.disconnected_signal.connect(self.on_disconnect)

    def add_bubble(self, w):
        item = QListWidgetItem()
        item.setSizeHint(w.sizeHint())
        self.msg_list.addItem(item)
        self.msg_list.setItemWidget(item, w)
        self.msg_list.scrollToBottom()

    def on_recv_msg(self, txt):
        if "joined" in txt or "left" in txt:
            self.add_bubble(MsgBubbleWidget("system", "", txt))
        elif "|" in txt:
            nick, content = txt.split("|", 1)
            self.add_bubble(MsgBubbleWidget("other", nick, content))
        else:
            self.add_bubble(MsgBubbleWidget("system", "", txt))

    def on_file_info(self, meta):
        self.add_bubble(MsgBubbleWidget("system", "", f"Receiving: {meta['filename']} ({meta['size']}B)"))

    def on_file_finish(self, ok, path):
        if ok:
            self.add_bubble(MsgBubbleWidget("system", "", f"Saved: {path}"))
        else:
            self.add_bubble(MsgBubbleWidget("system", "", "File corrupted (MD5 mismatch)"))

    def send_msg(self):
        t = self.input.text().strip()
        if not t:
            return
        self.add_bubble(MsgBubbleWidget("self", self.nickname, t))
        self.tcp.send_text(t)
        self.input.clear()

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self.tcp.send_file(path)
            self.add_bubble(MsgBubbleWidget("self", self.nickname, f"Sending: {os.path.basename(path)}"))

    # ---------- 扫雷 ----------
    def invite_ms(self):
        self.tcp.send_ms({"cmd": "invite"})
        self.ms_wait_dlg = MSWaitingDialog(self, self.nickname, self.tcp)
        self.ms_wait_dlg.show()

    def on_ms_msg(self, d):
        cmd = d.get("cmd")
        if cmd == "invite":
            inviter = d["inviter"]
            if inviter == self.nickname:
                return
            dlg = MSInviteDialog(self, inviter, self.tcp)
            dlg.exec()
        elif cmd == "busy":
            QMessageBox.information(self, "Minesweeper", "A game is already in progress.")
        elif cmd == "full":
            QMessageBox.information(self, "Minesweeper", "Game lobby is full.")
        elif cmd == "join":
            if self.ms_wait_dlg:
                self.ms_wait_dlg.update_players(d["players"])
        elif cmd == "leave_wait":
            if self.ms_wait_dlg:
                self.ms_wait_dlg.update_players(d["players"])
        elif cmd == "cancel":
            if self.ms_wait_dlg:
                self.ms_wait_dlg.close()
                self.ms_wait_dlg = None
            QMessageBox.information(self, "Minesweeper", d.get("msg", "Game cancelled"))
        elif cmd == "start":
            if self.ms_wait_dlg:
                self.ms_wait_dlg.close()
                self.ms_wait_dlg = None
            self.ms_game_win = MSGameWindow(self, self.nickname, d["rows"], d["cols"], self.tcp)
            self.ms_game_win.update_players(d["players"])
            self.ms_game_win.current_player = d["current"]
            self.ms_game_win.show()
        elif cmd == "update":
            if self.ms_game_win:
                self.ms_game_win.update_board(d["cells"], d["current"], d["players"])
        elif cmd == "gameover":
            if self.ms_game_win:
                self.ms_game_win.reveal_mines(d["mines"], d["loser"])
        elif cmd == "win":
            if self.ms_game_win:
                QMessageBox.information(self, "Minesweeper", "You win! All safe cells opened.")
        elif cmd == "abort":
            if self.ms_game_win:
                self.ms_game_win.close()
                self.ms_game_win = None
            QMessageBox.information(self, "Minesweeper", d.get("msg", "Game aborted"))

    def on_disconnect(self):
        self.add_bubble(MsgBubbleWidget("system", "", "Disconnected from server"))

    def closeEvent(self, e):
        self.tcp.close_conn()
        self.tcp.wait()
        e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        win = ChatMainWindow(login.host, login.nickname, login.tcp)
        win.show()
        sys.exit(app.exec())
