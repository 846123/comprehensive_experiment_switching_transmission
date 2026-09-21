# -*- coding: utf-8 -*-
# @FileName : invite_dialog.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:32
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QScrollArea, QHBoxLayout, QPushButton
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont


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
            widget = item.widget()
            if widget:
                widget.deleteLater()

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
