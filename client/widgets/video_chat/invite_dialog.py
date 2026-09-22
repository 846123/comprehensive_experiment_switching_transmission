from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from ...protocol import (
    RESPONSE_PENDING,
    RESPONSE_ACCEPT,
    RESPONSE_REJECT,
    MSG_TYPE_VIDEO_INVITE
)


class VideoInviteDialog(QDialog):
    def __init__(self, parent, inviter_nick, players_dict, my_nick, tcp):
        super().__init__(parent)
        self.setWindowTitle("音视频通话邀请")
        self.setFixedSize(320, 380)
        self.my_nick = my_nick
        self.tcp = tcp
        self.has_answered = False
        self.time_left = 30

        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)

        # 标题
        title = QLabel(f"{inviter_nick} 邀请你进行音视频通话")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        title.setFont(f)
        main_layout.addWidget(title)

        # 倒计时
        self.countdown_label = QLabel(f"剩余时间：{self.time_left} 秒")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_label.setStyleSheet("color:#d00;")
        main_layout.addWidget(self.countdown_label)

        # 玩家列表
        list_title = QLabel("在线玩家：")
        main_layout.addWidget(list_title)

        self.player_list_layout = QVBoxLayout()
        self.player_list_layout.setSpacing(4)
        main_layout.addLayout(self.player_list_layout)

        # 初始渲染玩家列表
        self.update_status(players_dict)

        main_layout.addStretch(1)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_reject = QPushButton("拒绝")
        self.btn_accept = QPushButton("接受")
        self.btn_accept.setStyleSheet("background-color:#07c160; color:white;")

        self.btn_reject.clicked.connect(self.on_reject)
        self.btn_accept.clicked.connect(self.on_accept)

        btn_layout.addWidget(self.btn_reject)
        btn_layout.addWidget(self.btn_accept)
        main_layout.addLayout(btn_layout)

        self.setLayout(main_layout)

        # 发起人特殊处理：默认接受，仅可取消
        if my_nick == inviter_nick:
            title.setText("已发起视频通话邀请")
            self.btn_accept.setEnabled(False)
            self.btn_reject.setText("取消")

        # 启动倒计时
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(1000)

    def update_status(self, players_dict):
        """更新所有玩家的响应状态"""
        # 清空现有列表
        while self.player_list_layout.count():
            item = self.player_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for nick, status in players_dict.items():
            status_text = "未响应"
            status_color = "#999"
            if status == RESPONSE_ACCEPT:
                status_text = "已接受 ✓"
                status_color = "#07c160"
            elif status == RESPONSE_REJECT:
                status_text = "已拒绝 ✕"
                status_color = "#d00"

            label = QLabel(f"  {nick}  —  {status_text}")
            label.setStyleSheet(f"color:{status_color};")
            self.player_list_layout.addWidget(label)

    def _on_tick(self):
        self.time_left -= 1
        self.countdown_label.setText(f"剩余时间：{self.time_left} 秒")
        if self.time_left <= 0:
            self.timer.stop()
            # 超时未操作默认拒绝
            if not self.has_answered:
                self.on_reject()

    def on_accept(self):
        if self.has_answered:
            return
        self.has_answered = True
        self.tcp.send_json({"cmd": "accept"}, MSG_TYPE_VIDEO_INVITE)
        # 不立即关闭，等待服务端start信号再关

    def on_reject(self):
        if self.has_answered:
            return
        self.has_answered = True
        # 发起人就是取消
        if self.btn_reject.text() == "取消":
            self.tcp.send_json({"cmd": "cancel"}, MSG_TYPE_VIDEO_INVITE)
        else:
            self.tcp.send_json({"cmd": "reject"}, MSG_TYPE_VIDEO_INVITE)
        self.reject()

    def closeEvent(self, event):
        if self.timer.isActive():
            self.timer.stop()
        super().closeEvent(event)
