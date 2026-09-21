# -*- coding: utf-8 -*-
# @FileName : game_window.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:33
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QGridLayout, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class MinesweeperWindow(QDialog):
    def __init__(self, parent, tcp, my_nick):
        super().__init__(parent)
        self.setWindowTitle("多人扫雷")
        self.tcp = tcp
        self.my_nick = my_nick
        self.rows = 16
        self.cols = 16
        self.buttons = {}
        self.current_player = None
        self.players = []
        self.player_label = None
        self.grid_layout = None
        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        self.player_label = QLabel("等待游戏开始...")
        left_layout.addWidget(self.player_label)
        left_layout.addStretch(1)
        grid_widget = QWidget()
        self.grid_layout = QGridLayout(grid_widget)
        self.grid_layout.setSpacing(2)
        main_layout.addLayout(left_layout, 1)
        main_layout.addWidget(grid_widget, 4)
        self.setLayout(main_layout)
        self.setFixedSize(750, 520)

    def build_grid(self):
        for btn in self.buttons.values():
            btn.deleteLater()
        self.buttons.clear()
        for x in range(self.rows):
            for y in range(self.cols):
                btn = QPushButton("")
                btn.setFixedSize(32, 32)
                f = QFont("Arial", 12)
                f.setBold(True)
                btn.setFont(f)
                btn.clicked.connect(
                    lambda ch, xx=x, yy=y: self.on_click(xx, yy, "open")
                )
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, xx=x, yy=y: self.on_click(xx, yy, "flag")
                )
                self.grid_layout.addWidget(btn, x, y)
                self.buttons[(x, y)] = btn

    def on_click(self, x, y, action):
        if self.current_player != self.my_nick:
            return
        self.tcp.send_json({"cmd": "click", "x": x, "y": y, "action": action})

    def update_board(self, cells, current, players):
        self.current_player = current
        self.players = players
        txt = "玩家列表：\n"
        for p in players:
            nick = p["nick"]
            alive = p["alive"]
            line = f"{nick}"
            if not alive:
                line += " 💀"
            if nick == current:
                line += " ◀ 你的回合"
            txt += line + "\n"
        self.player_label.setText(txt.strip())

        for x in range(self.rows):
            for y in range(self.cols):
                val = cells[x][y]
                btn = self.buttons[(x, y)]
                if val == "c":
                    btn.setText("")
                    btn.setStyleSheet("background:#cfcfcf; border:1px solid #bbb;")
                    btn.setEnabled(True)
                elif val == "f":
                    btn.setText("F")
                    btn.setStyleSheet(
                        "background:#ffdddd; color:red; border:1px solid #bbb;"
                    )
                    btn.setEnabled(False)
                elif val == "m":
                    btn.setText("💣")
                    btn.setStyleSheet(
                        "background:#ff6666; color:white; border:1px solid #bbb;"
                    )
                    btn.setEnabled(False)
                else:
                    btn.setText(val)
                    btn.setStyleSheet(
                        "background:#ffffff; border:1px solid #bbb;"
                    )
                    btn.setEnabled(False)

        is_my_turn = (self.current_player == self.my_nick)
        for btn in self.buttons.values():
            if btn.isEnabled():
                btn.setEnabled(is_my_turn)
