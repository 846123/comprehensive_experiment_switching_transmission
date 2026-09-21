# -*- coding: utf-8 -*-
# @FileName : send_progress.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:33
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import QTimer


class FileSendProgressDialog(QDialog):
    def __init__(self, parent, filename):
        super().__init__(parent)
        self.setWindowTitle("发送文件")
        self.setFixedSize(360, 120)
        self.setModal(False)

        layout = QVBoxLayout()
        self.label = QLabel(f"正在发送：{filename}")
        layout.addWidget(self.label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("准备中...")
        self.status_label.setStyleSheet("color:#666;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def update_progress(self, sent, total):
        percent = int(sent * 100 / total) if total > 0 else 0
        self.progress.setValue(percent)
        self.status_label.setText(f"{sent / 1024:.1f} KB / {total / 1024:.1f} KB")

    def finish_success(self):
        self.progress.setValue(100)
        self.status_label.setText("发送完成")
        QTimer.singleShot(800, self.close)

    def finish_error(self, msg):
        self.status_label.setText(f"发送失败：{msg}")
        self.status_label.setStyleSheet("color:red;")
