# -*- coding: utf-8 -*-
# @FileName : video_invite.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:30
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt


class VideoInvitePopup(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowOpacity(0.75)
        self.setFixedSize(280, 140)
        lay = QVBoxLayout()
        lay.addWidget(QLabel("Incoming Video Call"))
        h_layout = QHBoxLayout()
        btn_accept = QPushButton("Accept")
        btn_reject = QPushButton("Reject")
        btn_accept.clicked.connect(self.accept)
        btn_reject.clicked.connect(self.reject)
        h_layout.addWidget(btn_accept)
        h_layout.addWidget(btn_reject)
        lay.addLayout(h_layout)
        self.setLayout(lay)
