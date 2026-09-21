# -*- coding: utf-8 -*-
# @FileName : receive_dialog.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:34
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QHBoxLayout,
    QLineEdit, QPushButton, QFileDialog, QMessageBox
)


class FileReceiveDialog(QDialog):
    def __init__(self, parent, sender, filename, file_size):
        super().__init__(parent)
        self.setWindowTitle("接收文件")
        self.setFixedSize(420, 180)
        self.sender = sender
        self.filename = filename
        self.file_size = file_size
        self.save_path = ""

        layout = QVBoxLayout()

        info = QLabel(
            f"{sender} 向你发送文件：\n"
            f"文件名：{filename}\n"
            f"大小：{file_size / 1024:.2f} KB"
        )
        layout.addWidget(info)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit, 1)

        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self.on_browse)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self.on_save)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def on_browse(self):
        default_name = self.get_unique_filename(os.path.expanduser("~"), self.filename)
        path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", default_name, "所有文件 (*.*)"
        )
        if path:
            self.path_edit.setText(path)

    @staticmethod
    def get_unique_filename(directory, filename):
        base, ext = os.path.splitext(filename)
        counter = 1
        candidate = os.path.join(directory, filename)
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{base}({counter}){ext}")
            counter += 1
        return candidate

    def on_save(self):
        path = self.path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请选择保存路径")
            return
        self.save_path = path
        self.accept()
