# -*- coding: utf-8 -*-
# @FileName : msg_bubble.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:29
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt


class MsgBubbleWidget(QWidget):
    def __init__(self, msg_type, nick, text, initial_max_w=0):
        super().__init__()
        self.msg_type = msg_type
        self.nick = nick
        self.raw_text = text
        self.max_bubble_width = initial_max_w
        self.indent_size = 20

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 2, 0, 2)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        self.font = QFont()
        self.font.setPointSize(10)
        self.text_label = None
        self.bubble_container = None

        if self.msg_type == "self":
            self.main_layout.addStretch(1)
            self.bubble_container = QWidget()
            self.bubble_container.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self.bubble_container.setStyleSheet("""
                background-color:#ffffff;
                border:1px solid #cccccc;
                border-radius:8px;
                padding:6px;
            """)
            bubble_layout = QVBoxLayout(self.bubble_container)
            bubble_layout.setContentsMargins(0, 0, 0, 0)
            bubble_layout.setSpacing(0)

            self.text_label = QLabel()
            self.text_label.setFont(self.font)
            self.text_label.setWordWrap(True)
            self.text_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self.text_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self.text_label.setStyleSheet("background:transparent;border:none;")
            bubble_layout.addWidget(self.text_label)
            self.main_layout.addWidget(self.bubble_container)

        elif self.msg_type == "other":
            outer_vbox = QVBoxLayout()
            outer_vbox.setContentsMargins(0, 0, 0, 0)
            outer_vbox.setSpacing(3)

            nick_label = QLabel(self.nick)
            nick_label.setFont(self.font)
            nick_label.setStyleSheet("color:#444444;")
            outer_vbox.addWidget(nick_label)

            bubble_hbox = QHBoxLayout()
            bubble_hbox.setContentsMargins(0, 0, 0, 0)
            bubble_hbox.setSpacing(0)
            indent_widget = QWidget()
            indent_widget.setFixedWidth(self.indent_size)
            bubble_hbox.addWidget(indent_widget)

            self.bubble_container = QWidget()
            self.bubble_container.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self.bubble_container.setStyleSheet("""
                background-color:#f1f1f1;
                border:1px solid #dddddd;
                border-radius:8px;
                padding:6px;
            """)
            bubble_layout = QVBoxLayout(self.bubble_container)
            bubble_layout.setContentsMargins(0, 0, 0, 0)
            bubble_layout.setSpacing(0)

            self.text_label = QLabel()
            self.text_label.setFont(self.font)
            self.text_label.setWordWrap(True)
            self.text_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
            )
            self.text_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self.text_label.setStyleSheet("background:transparent;border:none;")
            bubble_layout.addWidget(self.text_label)
            bubble_hbox.addWidget(self.bubble_container)

            outer_vbox.addLayout(bubble_hbox)
            self.main_layout.addLayout(outer_vbox)
            self.main_layout.addStretch(1)

        elif self.msg_type == "sys":
            self.main_layout.addStretch(1)
            label = QLabel(self.raw_text)
            label.setFont(self.font)
            label.setStyleSheet("color:#666666;")
            self.main_layout.addWidget(label)
            self.main_layout.addStretch(1)

        if self.text_label:
            self.text_label.setText(self.raw_text)
        if self.max_bubble_width > 0 and self.bubble_container:
            self.set_bubble_max_width(self.max_bubble_width)

    def set_bubble_max_width(self, w):
        self.max_bubble_width = w
        if self.msg_type == "other":
            avail_w = max(w - self.indent_size, 40)
        else:
            avail_w = max(w, 40)

        if self.bubble_container is not None:
            self.bubble_container.setMaximumWidth(avail_w)
            if self.text_label is not None:
                fm = self.fontMetrics()
                text_single_width = fm.horizontalAdvance(self.raw_text)
                label_avail_w = max(avail_w - 12, 20)

                if text_single_width <= label_avail_w:
                    self.text_label.setMinimumWidth(0)
                    self.text_label.setMaximumWidth(16777215)
                else:
                    self.text_label.setFixedWidth(label_avail_w)

                self.text_label.updateGeometry()
            self.bubble_container.adjustSize()
            self.adjustSize()

    def sizeHint(self):
        hint = super().sizeHint()
        if self.text_label:
            label_hint = self.text_label.sizeHint()
            hint.setWidth(label_hint.width())
            hint.setHeight(label_hint.height())
        return hint
