# -*- coding: utf-8 -*-
# @FileName : result_dialog.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:33
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QWidget, QScrollArea, QHBoxLayout, QPushButton
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont


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
            widget = item.widget()
            if widget:
                widget.deleteLater()

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
