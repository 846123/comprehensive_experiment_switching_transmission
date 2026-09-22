from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class VideoInviteDialog(QDialog):
    def __init__(self, parent, caller_nick, my_nick, tcp):
        super().__init__(parent)
        self.setWindowTitle("音视频通话")
        self.setFixedSize(300, 180)
        self.my_nick = my_nick
        self.tcp = tcp
        self.has_answered = False

        main_layout = QVBoxLayout()
        main_layout.addStretch(1)

        title = QLabel(f"{caller_nick} 邀请你进行音视频通话")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = QFont()
        f.setPointSize(12)
        f.setBold(True)
        title.setFont(f)
        main_layout.addWidget(title)

        tip = QLabel("接通后将开启摄像头和麦克风")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet("color:#666;")
        main_layout.addWidget(tip)
        main_layout.addStretch(1)

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

        # 自己是发起人则显示等待界面
        if my_nick == caller_nick:
            title.setText("等待对方接听...")
            tip.setText("已向所有在线用户发起呼叫")
            self.btn_accept.setEnabled(False)
            self.btn_reject.setText("取消")

    def on_accept(self):
        if self.has_answered:
            return
        self.has_answered = True
        self.tcp.send_json({"cmd": "accept"})
        self.accept()

    def on_reject(self):
        if self.has_answered:
            return
        self.has_answered = True
        self.tcp.send_json({"cmd": "reject"})
        self.reject()
