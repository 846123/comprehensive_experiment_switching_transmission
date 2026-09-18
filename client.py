import asyncio
import sys
import os
import cv2
import numpy as np
import threading
import time
from collections import deque
import sounddevice as sd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QDialog, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

# ===================== 全局音视频状态变量 =====================
in_video = False
cap = None
video_stop_event = threading.Event()
render_stop_event = threading.Event()
audio_stop_event = threading.Event()
video_lock = threading.Lock()

frame_queue_remote = deque(maxlen=1)
frame_queue_local = deque(maxlen=1)
audio_queue_remote = deque(maxlen=8)

global_writer = None
global_loop = None
window_name = "VideoCall"

CHUNK = 1024
CHANNELS = 1
RATE = 16000

# ==================== 扫雷全局状态 ====================
in_minesweeper = False
mine_stop_event = threading.Event()
mine_lock = threading.Lock()

MINE_ROW = 16
MINE_COL = 20
MINE_COUNT = 40

CELL_UNOPEN = 0
CELL_OPENED = 1
CELL_FLAG = 2


def minesweeper_thread():
    global in_minesweeper
    win_name = "Minesweeper"
    cell_size = 30
    MINE_W = MINE_COL * cell_size
    MINE_H = MINE_ROW * cell_size

    colors = {
        CELL_UNOPEN: (180, 180, 180),
        CELL_OPENED: (220, 220, 220),
        CELL_FLAG: (50, 50, 255)
    }
    num_color = [
        (0, 0, 255), (0, 128, 0), (255, 0, 0), (128, 0, 128),
        (0, 0, 128), (128, 128, 0), (0, 128, 128), (128, 128, 128)
    ]
    dirs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)
    import random
    while not mine_stop_event.is_set():
        board_state = [[CELL_UNOPEN for _ in range(MINE_COL)] for _ in range(MINE_ROW)]
        is_mine = [[False] * MINE_COL for _ in range(MINE_ROW)]
        near_mine_cnt = [[0] * MINE_COL for _ in range(MINE_ROW)]

        mines = set()
        while len(mines) < MINE_COUNT:
            mines.add((random.randint(0, MINE_ROW - 1), random.randint(0, MINE_COL - 1)))
        for r, c in mines:
            is_mine[r][c] = True
        for r in range(MINE_ROW):
            for c in range(MINE_COL):
                if is_mine[r][c]:
                    continue
                cnt = 0
                for dr, dc in dirs:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < MINE_ROW and 0 <= nc < MINE_COL and is_mine[nr][nc]:
                        cnt += 1
                near_mine_cnt[r][c] = cnt

        state_box = {"over": False, "win": False}

        def mouse_callback(event, x, y, flags, param):
            if state_box["over"] or state_box["win"]:
                return
            c = x // cell_size
            r = y // cell_size
            if not (0 <= r < MINE_ROW and 0 <= c < MINE_COL):
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                if board_state[r][c] == CELL_UNOPEN:
                    if is_mine[r][c]:
                        state_box["over"] = True
                        board_state[r][c] = CELL_OPENED
                    else:
                        q = [(r, c)]
                        board_state[r][c] = CELL_OPENED
                        while q:
                            rr, cc = q.pop(0)
                            if near_mine_cnt[rr][cc] == 0:
                                for dr, dc in dirs:
                                    nr, nc = rr + dr, cc + dc
                                    if 0 <= nr < MINE_ROW and 0 <= nc < MINE_COL:
                                        if board_state[nr][nc] == CELL_UNOPEN and not is_mine[nr][nc]:
                                            board_state[nr][nc] = CELL_OPENED
                                            q.append((nr, nc))
                opened = sum(row.count(CELL_OPENED) for row in board_state)
                if opened == MINE_ROW * MINE_COL - MINE_COUNT:
                    state_box["win"] = True
            elif event == cv2.EVENT_RBUTTONDOWN:
                if board_state[r][c] == CELL_UNOPEN:
                    board_state[r][c] = CELL_FLAG
                elif board_state[r][c] == CELL_FLAG:
                    board_state[r][c] = CELL_UNOPEN

        cv2.setMouseCallback(win_name, mouse_callback)

        while not mine_stop_event.is_set():
            img = np.ones((MINE_H, MINE_W, 3), dtype=np.uint8) * 200
            for r in range(MINE_ROW):
                for c in range(MINE_COL):
                    x1, y1 = c * cell_size, r * cell_size
                    x2, y2 = x1 + cell_size, y1 + cell_size
                    st = board_state[r][c]
                    cv2.rectangle(img, (x1, y1), (x2, y2), colors[st], -1)
                    cv2.rectangle(img, (x1, y1), (x2, y2), (50, 50, 50), 1)
                    if st == CELL_OPENED and near_mine_cnt[r][c] > 0:
                        cv2.putText(img, str(near_mine_cnt[r][c]),
                                    (x1 + 8, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    num_color[near_mine_cnt[r][c] - 1], 2)
                    if st == CELL_FLAG:
                        cv2.line(img, (x1 + 8, y1 + 22), (x1 + 8, y1 + 8), (0, 0, 200), 2)
                        cv2.putText(img, "|", (x1 + 6, y1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 200), 2)
                    if state_box["over"] and is_mine[r][c] and st != CELL_FLAG:
                        cv2.circle(img, ((x1 + x2) // 2, (y1 + y2) // 2), 8, (0, 0, 0), -1)

            if state_box["over"]:
                cv2.rectangle(img, (0, MINE_H // 2 - 30), (MINE_W, MINE_H // 2 + 30), (0, 0, 0), -1)
                cv2.putText(img, "GAME OVER  (r:restart  q:quit)",
                            (30, MINE_H // 2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if state_box["win"]:
                cv2.rectangle(img, (0, MINE_H // 2 - 30), (MINE_W, MINE_H // 2 + 30), (0, 100, 0), -1)
                cv2.putText(img, "YOU WIN!  (r:restart  q:quit)",
                            (60, MINE_H // 2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(win_name, img)
            key = cv2.waitKey(20) & 0xFF
            if key == ord('q'):
                mine_stop_event.set()
                break
            if key == ord('r') and (state_box["over"] or state_box["win"]):
                break
    try:
        cv2.destroyWindow(win_name)
    except Exception:
        pass
    with mine_lock:
        global in_minesweeper
        in_minesweeper = False


async def start_minesweeper():
    global in_minesweeper
    with mine_lock:
        if in_minesweeper:
            return False
        if in_video:
            return False
        in_minesweeper = True
        mine_stop_event.clear()
    threading.Thread(target=minesweeper_thread, daemon=True).start()
    return True


async def stop_minesweeper():
    global in_minesweeper
    with mine_lock:
        if not in_minesweeper:
            return
        in_minesweeper = False
        mine_stop_event.set()


def render_thread():
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    blank = np.zeros((320, 480, 3), dtype=np.uint8)
    last_remote = blank
    last_local = blank
    while not render_stop_event.is_set():
        if len(frame_queue_remote) > 0:
            last_remote = frame_queue_remote[-1]
        if len(frame_queue_local) > 0:
            last_local = frame_queue_local[-1]
        remote_frame = cv2.resize(last_remote, (480, 320))
        local_frame = cv2.resize(last_local, (480, 320))
        combined = np.hstack([local_frame, remote_frame])
        cv2.imshow(window_name, combined)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            if global_loop and global_writer:
                asyncio.run_coroutine_threadsafe(stop_video(global_writer), global_loop)
    cv2.destroyWindow(window_name)


def audio_play_thread():
    def audio_out_callback(outdata, frames, time_info, status):
        if status:
            pass
        if len(audio_queue_remote) > 0:
            audio_bytes = audio_queue_remote.popleft()
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            outdata[:] = audio_np.reshape(-1, CHANNELS)
        else:
            outdata[:] = np.zeros((frames, CHANNELS), dtype=np.int16)

    stream = sd.OutputStream(
        samplerate=RATE,
        blocksize=CHUNK,
        channels=CHANNELS,
        dtype='int16',
        callback=audio_out_callback
    )
    stream.start()
    while not audio_stop_event.is_set():
        time.sleep(0.01)
    stream.stop()
    stream.close()


def audio_capture_thread(writer, loop):
    def audio_in_callback(indata, frames, time_info, status):
        if status:
            pass
        with video_lock:
            if not in_video:
                return
        audio_bytes = indata.tobytes()
        header = f"AUDIO_FRAME:{len(audio_bytes)}\n".encode()

        async def send_audio():
            try:
                writer.write(header + audio_bytes)
                await writer.drain()
            except Exception:
                video_stop_event.set()
                render_stop_event.set()
                audio_stop_event.set()
                with video_lock:
                    global in_video
                    in_video = False

        asyncio.run_coroutine_threadsafe(send_audio(), loop)

    stream = sd.InputStream(
        samplerate=RATE,
        blocksize=CHUNK,
        channels=CHANNELS,
        dtype='int16',
        callback=audio_in_callback
    )
    stream.start()
    while not audio_stop_event.is_set():
        time.sleep(0.01)
    stream.stop()
    stream.close()


def video_capture_thread(writer, loop):
    global cap, in_video, video_stop_event
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        with video_lock:
            in_video = False
        return
    try:
        while not video_stop_event.is_set():
            with video_lock:
                if not in_video:
                    break
            ret, frame = cap.read()
            retry = 0
            while not ret and retry < 3:
                retry += 1
                ret, frame = cap.read()
                time.sleep(0.01)
            if not ret:
                time.sleep(0.15)
                continue
            frame = cv2.flip(frame, 1)
            frame_queue_local.append(frame.copy())
            frame_send = cv2.resize(frame, (480, 320))
            _, jpeg = cv2.imencode('.jpg', frame_send, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frame_bytes = jpeg.tobytes()
            header = f"VIDEO_FRAME:{len(frame_bytes)}\n".encode()

            async def send_frame():
                try:
                    writer.write(header + frame_bytes)
                    await writer.drain()
                except Exception:
                    video_stop_event.set()
                    render_stop_event.set()
                    audio_stop_event.set()
                    with video_lock:
                        global in_video
                        in_video = False

            asyncio.run_coroutine_threadsafe(send_frame(), loop)
            time.sleep(0.06)
    except Exception as e:
        pass
    finally:
        if cap is not None:
            cap.release()
        with video_lock:
            in_video = False


async def start_video(writer, loop):
    global in_video, video_stop_event, render_stop_event, audio_stop_event, global_writer, global_loop
    global_writer = writer
    global_loop = loop
    with video_lock:
        if in_video:
            return False
        in_video = True
        video_stop_event.clear()
        render_stop_event.clear()
        audio_stop_event.clear()
    threading.Thread(target=video_capture_thread, args=(writer, loop), daemon=True).start()
    threading.Thread(target=render_thread, daemon=True).start()
    threading.Thread(target=audio_capture_thread, args=(writer, loop), daemon=True).start()
    threading.Thread(target=audio_play_thread, daemon=True).start()
    return True


async def stop_video(writer):
    global in_video, video_stop_event, render_stop_event, audio_stop_event
    with video_lock:
        if not in_video:
            return
        in_video = False
        video_stop_event.set()
        render_stop_event.set()
        audio_stop_event.set()
    try:
        writer.write(b"CALL_HANGUP:me\n")
        await writer.drain()
    except Exception:
        pass


# ===================== PyQt GUI 部分 =====================
class CallFloatWidget(QWidget):
    """右侧居中、半透明的音视频邀请浮窗"""
    accept_signal = pyqtSignal()
    reject_signal = pyqtSignal()

    def __init__(self, inviter_name):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(420, 90)

        self.setWindowOpacity(0.8)

        container = QWidget()
        container.setStyleSheet("background-color:#f7f7f7;border:1px solid #cfcfcf;border-radius:10px;")

        label = QLabel(f"{inviter_name} 发起音视频通话")
        label.setFont(QFont("SimHei", 12))
        label.setStyleSheet("color:#222;")

        btn_accept = QPushButton("Accept")
        btn_reject = QPushButton("Reject")
        btn_accept.setFixedSize(80, 36)
        btn_reject.setFixedSize(80, 36)
        btn_accept.setStyleSheet(
            "background-color:#2ecc71;color:white;font-size:14px;border-radius:6px;"
        )
        btn_reject.setStyleSheet(
            "background-color:#e74c3c;color:white;font-size:14px;border-radius:6px;"
        )
        btn_accept.clicked.connect(self.accept_signal.emit)
        btn_reject.clicked.connect(self.reject_signal.emit)

        h_layout = QHBoxLayout(container)
        h_layout.setContentsMargins(18, 0, 18, 0)
        h_layout.addWidget(label)
        h_layout.addStretch(1)
        h_layout.addWidget(btn_accept)
        h_layout.addSpacing(10)
        h_layout.addWidget(btn_reject)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)

        # 定位到屏幕右侧垂直居中
        screen = QApplication.desktop().availableGeometry()
        self.move(screen.right() - self.width() - 40, screen.center().y() - self.height() // 2)


class LoginDialog(QDialog):
    """无边框英文登录窗口，空IP/空昵称拦截，错误清空输入框"""
    def __init__(self):
        super().__init__()
        self.resize(720, 520)
        self.setMinimumSize(720, 520)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self._drag_pos = None

        main_widget = QWidget()
        main_widget.setStyleSheet("""
            QWidget#main{
                background-color:#f0f0f0;
                border-radius:12px;
            }
        """)
        main_widget.setObjectName("main")
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.setSpacing(0)

        # 标题栏
        title_bar = QWidget()
        title_bar.setFixedHeight(48)
        title_bar.setStyleSheet("background-color:#f8f4f0; border-top-left-radius:12px;border-top-right-radius:12px;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16,0,16,0)

        title_label = QLabel("Login...")
        title_label.setFont(QFont("Segoe UI",14))

        btn_close = QPushButton("×")
        btn_close.setFixedSize(32,32)
        btn_close.setStyleSheet("""
            QPushButton{border:none;font-size:20px;}
            QPushButton:hover{background-color:#e8e2de;}
        """)
        btn_close.clicked.connect(self.reject)

        title_layout.addWidget(title_label)
        title_layout.addStretch(1)
        title_layout.addWidget(btn_close)

        # 拖动逻辑
        def mousePressEvent_title(event):
            if event.button() == Qt.LeftButton:
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept()
        def mouseMoveEvent_title(event):
            if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
                self.move(event.globalPos() - self._drag_pos)
                event.accept()
        title_bar.mousePressEvent = mousePressEvent_title
        title_bar.mouseMoveEvent = mouseMoveEvent_title

        # 内容区域
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(100, 80, 100, 60)
        content_layout.setSpacing(30)

        title_content = QLabel("Connect to ChatRoom")
        title_content.setFont(QFont("Segoe UI",20))
        title_content.setAlignment(Qt.AlignCenter)

        self.ip_edit = QLineEdit("127.0.0.1")
        self.ip_edit.setPlaceholderText("Server IP Address")
        self.ip_edit.setFixedHeight(48)
        self.ip_edit.setFont(QFont("Segoe UI",12))

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Your Nickname")
        self.name_edit.setFixedHeight(48)
        self.name_edit.setFont(QFont("Segoe UI",12))

        self.btn_conn = QPushButton("Connect")
        self.btn_conn.setFixedHeight(58)
        self.btn_conn.setFont(QFont("Segoe UI",15))
        self.btn_conn.clicked.connect(self.on_connect_click)

        content_layout.addWidget(title_content)
        content_layout.addWidget(QLabel("Server IP"))
        content_layout.addWidget(self.ip_edit)
        content_layout.addWidget(QLabel("User Nickname"))
        content_layout.addWidget(self.name_edit)
        content_layout.addWidget(self.btn_conn)

        main_layout.addWidget(title_bar)
        main_layout.addWidget(content_widget)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0,0,0,0)
        root_layout.addWidget(main_widget)

    def on_connect_click(self):
        ip_text = self.ip_edit.text().strip()
        nick_text = self.name_edit.text().strip()
        if not ip_text:
            QMessageBox.warning(self, "Warning", "Server IP cannot be empty!")
            self.ip_edit.clear()
            return
        if not nick_text:
            QMessageBox.warning(self, "Warning", "Nickname cannot be empty!")
            self.name_edit.clear()
            return
        self.accept()

    def get_info(self):
        return self.ip_edit.text().strip(), self.name_edit.text().strip()


class ChatMainWindow(QMainWindow):
    add_msg_signal = pyqtSignal(str)
    call_invite_signal = pyqtSignal(str)
    conn_fail_signal = pyqtSignal(str)

    def __init__(self, server_ip, nickname):
        super().__init__()
        self.setWindowTitle(f"ChatRoom - {nickname}")
        self.resize(720, 540)
        self.server_ip = server_ip
        self.nickname = nickname
        self.writer = None
        self.loop = None
        self.float_win = None

        central = QWidget()
        self.setCentralWidget(central)
        vlayout = QVBoxLayout(central)
        vlayout.setContentsMargins(12, 12, 12, 12)
        vlayout.setSpacing(10)

        self.msg_area = QTextEdit()
        self.msg_area.setReadOnly(True)
        self.msg_area.setFont(QFont("SimHei", 10))
        vlayout.addWidget(self.msg_area)

        btn_layout = QHBoxLayout()
        self.btn_file = QPushButton("Send File")
        self.btn_call = QPushButton("Start Video Call")
        self.btn_mine = QPushButton("Minesweeper")
        for btn in [self.btn_file, self.btn_call, self.btn_mine]:
            btn.setFixedHeight(38)
            btn.setFont(QFont("SimHei", 10))
        btn_layout.addWidget(self.btn_file)
        btn_layout.addWidget(self.btn_call)
        btn_layout.addWidget(self.btn_mine)
        vlayout.addLayout(btn_layout)

        hlayout_input = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Input message...")
        self.input_edit.setFixedHeight(36)
        self.btn_send = QPushButton("Send")
        self.btn_send.setFixedWidth(90)
        self.btn_send.setFixedHeight(36)
        hlayout_input.addWidget(self.input_edit)
        hlayout_input.addWidget(self.btn_send)
        vlayout.addLayout(hlayout_input)

        self.add_msg_signal.connect(self.on_add_msg)
        self.call_invite_signal.connect(self.show_call_float)
        self.conn_fail_signal.connect(self.on_conn_failed)

        self.btn_send.clicked.connect(self.send_text)
        self.input_edit.returnPressed.connect(self.send_text)
        self.btn_file.clicked.connect(self.on_send_file)
        self.btn_call.clicked.connect(self.on_start_call)
        self.btn_mine.clicked.connect(self.on_open_mine)

        self.client_thread = ClientThread(server_ip, 8080, nickname, self.add_msg_signal, self.call_invite_signal, self.conn_fail_signal)
        self.client_thread.start()

    def on_conn_failed(self, err_msg):
        QMessageBox.critical(self, "Connection Error", err_msg)
        self.close()

    def on_add_msg(self, text):
        self.msg_area.append(text)

    def show_call_float(self, inviter):
        if self.float_win is not None:
            return
        self.float_win = CallFloatWidget(inviter)
        self.float_win.accept_signal.connect(self.on_call_accept)
        self.float_win.reject_signal.connect(self.on_call_reject)
        self.float_win.show()

    def on_call_accept(self):
        if self.float_win:
            self.float_win.close()
            self.float_win = None
        asyncio.run_coroutine_threadsafe(self.client_thread.accept_call(), self.client_thread.loop)

    def on_call_reject(self):
        if self.float_win:
            self.float_win.close()
            self.float_win = None
        asyncio.run_coroutine_threadsafe(self.client_thread.reject_call(), self.client_thread.loop)

    def send_text(self):
        txt = self.input_edit.text().strip()
        if not txt:
            return
        self.input_edit.clear()
        asyncio.run_coroutine_threadsafe(self.client_thread.send_msg(txt), self.client_thread.loop)

    def on_send_file(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Select File")
        if not filepath:
            return
        asyncio.run_coroutine_threadsafe(self.client_thread.send_file(filepath), self.client_thread.loop)

    def on_start_call(self):
        asyncio.run_coroutine_threadsafe(self.client_thread.invite_call(), self.client_thread.loop)

    def on_open_mine(self):
        asyncio.run_coroutine_threadsafe(self.client_thread.open_mine(), self.client_thread.loop)

    def closeEvent(self, event):
        self.client_thread.stop()
        event.accept()


class ClientThread(QThread):
    conn_fail_signal = pyqtSignal(str)
    def __init__(self, ip, port, nick, msg_sig, call_sig, conn_fail_sig):
        super().__init__()
        self.ip = ip
        self.port = port
        self.nick = nick
        self.msg_sig = msg_sig
        self.call_sig = call_sig
        self.conn_fail_sig = conn_fail_sig
        self.loop = None
        self.writer = None
        self.reader = None
        self._stop = False

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.tcp_main())

    async def tcp_main(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.ip, self.port)
            prompt = await self.reader.readline()
            self.writer.write((self.nick + '\n').encode())
            await self.writer.drain()
            recv_task = asyncio.create_task(self.receive_loop())
            while not self._stop:
                await asyncio.sleep(0.1)
            recv_task.cancel()
        except Exception as e:
            self.conn_fail_sig.emit(f"Connect failed: {str(e)}")

    async def receive_loop(self):
        while True:
            line = await self.reader.readline()
            if not line:
                self.msg_sig.emit("Server disconnected")
                break
            try:
                line = line.decode().rstrip('\n')
            except:
                continue
            if line.startswith("FILE:"):
                _, sender, filename, file_size_str = line.split(":", 3)
                file_size = int(file_size_str)
                self.msg_sig.emit(f"📥 {sender} sending file {filename}, receiving...")
                save_name = f"received_{filename}"
                received = 0
                with open(save_name, 'wb') as f:
                    while received < file_size:
                        chunk = await self.reader.read(min(4096, file_size - received))
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                self.msg_sig.emit(f"✅ Saved as {save_name}")
                continue
            if line.startswith("CALL_INVITE:"):
                _, inviter = line.split(":", 1)
                self.call_sig.emit(inviter)
                continue
            if line.startswith("CALL_ACCEPT:"):
                _, user = line.split(":", 1)
                self.msg_sig.emit(f"✅ {user} joined video call")
                continue
            if line.startswith("CALL_REJECT:"):
                _, user = line.split(":", 1)
                self.msg_sig.emit(f"❌ {user} rejected call")
                continue
            if line.startswith("CALL_HANGUP:"):
                _, user = line.split(":", 1)
                self.msg_sig.emit(f"👋 {user} hung up")
                continue
            if line.startswith("VIDEO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                fs = int(frame_size_str)
                with video_lock:
                    if not in_video:
                        await self.reader.readexactly(fs)
                        continue
                try:
                    frame_data = await self.reader.readexactly(fs)
                except:
                    continue
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    frame_queue_remote.append(frame)
                continue
            if line.startswith("AUDIO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                fs = int(frame_size_str)
                with video_lock:
                    if not in_video:
                        await self.reader.readexactly(fs)
                        continue
                try:
                    frame_data = await self.reader.readexactly(fs)
                except:
                    continue
                audio_queue_remote.append(frame_data)
                continue
            self.msg_sig.emit(line)

    async def send_msg(self, txt):
        self.writer.write((txt + '\n').encode())
        await self.writer.drain()

    async def send_file(self, file_path):
        if not os.path.exists(file_path):
            self.msg_sig.emit("File not found")
            return
        file_size = os.path.getsize(file_path)
        filename = os.path.basename(file_path)
        header = f"FILE:{filename}:{file_size}\n".encode()
        self.writer.write(header)
        await self.writer.drain()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                self.writer.write(chunk)
                await self.writer.drain()
        await self.writer.drain()
        self.msg_sig.emit(f"📤 File {filename} sent")

    async def invite_call(self):
        if in_minesweeper:
            self.msg_sig.emit("⚠️ Minesweeper running, cannot start call")
            return
        self.writer.write(b"CALL_INVITE:me\n")
        await self.writer.drain()
        await start_video(self.writer, self.loop)

    async def accept_call(self):
        self.writer.write(b"CALL_ACCEPT:me\n")
        await self.writer.drain()
        await start_video(self.writer, self.loop)

    async def reject_call(self):
        self.writer.write(b"CALL_REJECT:me\n")
        await self.writer.drain()

    async def open_mine(self):
        ret = await start_minesweeper()
        if ret:
            self.msg_sig.emit("💣 Minesweeper started")
        else:
            self.msg_sig.emit("⚠️ Cannot open minesweeper")

    def stop(self):
        self._stop = True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec_():
        ip, name = login.get_info()
        w = ChatMainWindow(ip, name)
        w.show()
        sys.exit(app.exec_())
