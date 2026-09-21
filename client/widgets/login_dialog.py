# -*- coding: utf-8 -*-
# @FileName : login_dialog.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:30
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from ..network import TcpClientThread


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
        self.tcp_thread.fail_signal.connect(
            lambda e: (self.status_label.setText(e), self.connect_btn.setEnabled(True))
        )
        self.tcp_thread.start()
