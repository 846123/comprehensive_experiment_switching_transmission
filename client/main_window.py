import os
import threading
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QScrollArea, QMessageBox, QDialog,
    QFileDialog
)

from .widgets.msg_bubble import MsgBubbleWidget
from .widgets.minesweeper.invite_dialog import MinesweeperInviteDialog
from .widgets.minesweeper.result_dialog import GameResultDialog
from .widgets.minesweeper.game_window import MinesweeperWindow
from .widgets.file_transfer.send_progress import FileSendProgressDialog
from .widgets.file_transfer.receive_dialog import FileReceiveDialog
from .widgets.file_transfer.receive_progress import FileReceiveProgressDialog
from .widgets.video_chat.invite_dialog import VideoInviteDialog
from .widgets.video_chat.chat_window import VideoChatWindow
from .protocol import MSG_TYPE_VIDEO_INVITE


class ChatMainWindow(QMainWindow):
    def __init__(self, _host, nick, tcp):
        super().__init__()
        self.resize_timer = None
        self.setWindowTitle(f"聊天室 - {nick}")
        self.setGeometry(100, 100, 680, 520)
        self.nick = nick
        self.tcp = tcp
        self.ms_window = None
        self.invite_dialog = None
        self.result_dialog = None
        self.send_progress_dlg = None
        self.receive_dialog = None
        self.receive_progress_dlg = None
        self.current_recv_file_id = ""
        self.current_recv_file_size = 0
        self.current_recv_filename = ""
        self.video_invite_dlg = None
        self.video_chat_window = None

        self.tcp.video_signal.connect(self.on_video_event)

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
        self.tcp.file_info_signal.connect(self.on_file_info)
        self.tcp.file_chunk_signal.connect(self.on_file_chunk)
        self.tcp.file_end_signal.connect(self.on_file_end)
        self.tcp.send_progress_signal.connect(self.on_send_progress)
        self.tcp.send_error_signal.connect(self.on_send_error)

        self.btn_send.clicked.connect(self.send_msg)
        self.msg_input.returnPressed.connect(self.send_msg)
        self.btn_ms.clicked.connect(self.open_minesweeper)
        self.btn_video.clicked.connect(self.open_video_chat)
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
            for child in self.scroll_container.findChildren(QWidget):
                if isinstance(child, MsgBubbleWidget):
                    child.set_bubble_max_width(max_w)
            self.scroll_container.adjustSize()

    def add_bubble(self, bubble_widget):
        view_width = self.scroll_area.viewport().width()
        max_w = int(view_width * 0.8)
        bubble_widget.set_bubble_max_width(max_w)
        self.msg_layout.insertWidget(self.msg_layout.count() - 1, bubble_widget)
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

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
            self.result_dialog = GameResultDialog(
                self, d["result"], self.nick, self.tcp
            )
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

    # ========== 文件传输功能 ==========
    def send_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if not path:
            return
        filename = os.path.basename(path)
        self.send_progress_dlg = FileSendProgressDialog(self, filename)
        self.send_progress_dlg.show()

        def do_send():
            success, msg = self.tcp.send_file(path)
            if not success:
                self.tcp.send_error_signal.emit(msg)

        threading.Thread(target=do_send, daemon=True).start()

    def on_send_progress(self, sent, total):
        if self.send_progress_dlg and self.send_progress_dlg.isVisible():
            if sent == total and total > 0:
                self.send_progress_dlg.finish_success()
            else:
                self.send_progress_dlg.update_progress(sent, total)

    def on_send_error(self, msg):
        if self.send_progress_dlg and self.send_progress_dlg.isVisible():
            self.send_progress_dlg.finish_error(msg)

    def on_file_info(self, file_id, sender, filename, file_size):
        if sender == self.nick:
            return
        self.current_recv_file_id = file_id
        self.current_recv_filename = filename
        self.current_recv_file_size = file_size

        self.receive_dialog = FileReceiveDialog(self, sender, filename, file_size)
        if self.receive_dialog.exec() == QDialog.DialogCode.Accepted:
            save_path = self.receive_dialog.save_path
            success, status = self.tcp.start_receive_file(file_id, save_path)
            if not success:
                QMessageBox.critical(self, "错误", f"无法创建文件：{status}")
                return

            self.receive_progress_dlg = FileReceiveProgressDialog(self, filename)
            self.receive_progress_dlg.show()

            received = self.tcp.get_received_size(file_id)
            self.receive_progress_dlg.update_progress(received, file_size)

            if status == "finished":
                self.receive_progress_dlg.finish_success()
                self.current_recv_file_id = ""
                self.current_recv_file_size = 0

    def on_file_chunk(self, file_id, _offset, _data):
        if not self.current_recv_file_id or file_id != self.current_recv_file_id:
            return
        received = self.tcp.get_received_size(file_id)
        if self.receive_progress_dlg and self.receive_progress_dlg.isVisible():
            self.receive_progress_dlg.update_progress(
                received, self.current_recv_file_size
            )

    def on_file_end(self, file_id, status, msg):
        if not self.current_recv_file_id or file_id != self.current_recv_file_id:
            return
        if not self.receive_progress_dlg or not self.receive_progress_dlg.isVisible():
            return

        self.tcp.finish_receive_file(self.current_recv_file_id)
        if status == "success":
            self.receive_progress_dlg.finish_success()
        else:
            self.receive_progress_dlg.finish_error(msg)
        self.current_recv_file_id = ""
        self.current_recv_file_size = 0

    def on_disconnect(self):
        bubble = MsgBubbleWidget("sys", "", "与服务器断开连接")
        self.add_bubble(bubble)

    def closeEvent(self, event):
        self.tcp.close_conn()
        event.accept()

    # ========== 音视频通话功能 ==========
    def open_video_chat(self):
        self.tcp.send_json({"cmd": "invite"}, MSG_TYPE_VIDEO_INVITE)

    def on_video_event(self, d):
        cmd = d.get("cmd")

        if cmd == "invite":
            # 收到邀请
            if self.video_invite_dlg and self.video_invite_dlg.isVisible():
                return
            if self.video_chat_window and self.video_chat_window.isVisible():
                # 已在通话中，忽略新邀请
                return

            self.video_invite_dlg = VideoInviteDialog(
                self, d["inviter"], d["players"], self.nick, self.tcp
            )
            self.video_invite_dlg.show()

        elif cmd == "invite_status":
            # 状态更新
            if self.video_invite_dlg and self.video_invite_dlg.isVisible():
                self.video_invite_dlg.update_status(d["responses"])

        elif cmd == "cancel":
            # 邀请取消
            if self.video_invite_dlg and self.video_invite_dlg.isVisible():
                self.video_invite_dlg.close()
            QMessageBox.information(self, "提示", d.get("msg", "邀请已取消"))
            self.video_invite_dlg = None

        elif cmd == "busy":
            QMessageBox.warning(self, "提示", d.get("msg", "当前已有视频通话进行中"))

        elif cmd == "start":
            # 通话开始
            if self.video_invite_dlg and self.video_invite_dlg.isVisible():
                self.video_invite_dlg.close()
            self.video_invite_dlg = None

            self.video_chat_window = VideoChatWindow(
                self, self.tcp, self.nick, self.tcp.host
            )
            self.video_chat_window.update_members(d["players"])
            self.video_chat_window.show()
            self.video_chat_window.start_stream()

        elif cmd == "member_leave":
            # 成员离开
            if self.video_chat_window and self.video_chat_window.isVisible():
                self.video_chat_window.update_members(d["players"])

        elif cmd == "call_end":
            # 通话结束
            if self.video_chat_window and self.video_chat_window.isVisible():
                self.video_chat_window.close()
            self.video_chat_window = None
            self.video_invite_dlg = None
            QMessageBox.information(self, "提示", d.get("msg", "通话已结束"))
