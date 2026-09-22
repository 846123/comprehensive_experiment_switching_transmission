import cv2
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt
from ...av_stream import AVStream


class VideoChatWindow(QDialog):
    def __init__(self, parent, tcp, my_nick, server_host):
        super().__init__(parent)
        self.setWindowTitle("音视频通话")
        self.resize(640, 520)
        self.tcp = tcp
        self.my_nick = my_nick
        self.server_host = server_host
        self.members = []
        self.av_stream = None

        main_layout = QVBoxLayout()

        # 主视频显示区
        self.main_video = QLabel("等待对方接入...")
        self.main_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_video.setStyleSheet("background-color:#000; color:#fff;")
        self.main_video.setMinimumHeight(380)
        self.main_video.setScaledContents(True)
        main_layout.addWidget(self.main_video)

        # 底部控制栏
        control_layout = QHBoxLayout()
        self.member_label = QLabel("成员：")
        self.btn_mute = QPushButton("静音")
        self.btn_camera = QPushButton("关闭摄像头")
        self.btn_hangup = QPushButton("挂断")
        self.btn_hangup.clicked.connect(self.on_hangup)

        control_layout.addWidget(self.member_label)
        control_layout.addStretch(1)
        control_layout.addWidget(self.btn_mute)
        control_layout.addWidget(self.btn_camera)
        control_layout.addWidget(self.btn_hangup)
        main_layout.addLayout(control_layout)

        self.setLayout(main_layout)

    def start_stream(self):
        """启动音视频采集发送"""
        if self.av_stream:
            return
        self.av_stream = AVStream(self.server_host, self.my_nick)
        # 绑定视频帧信号，收到就更新画面
        self.av_stream.video_frame_signal.connect(self._on_video_frame)
        self.av_stream.start()

    def _on_video_frame(self, sender_nick, frame):
        """渲染视频帧到界面"""
        # OpenCV默认BGR格式，转成RGB给Qt显示
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.main_video.setPixmap(QPixmap.fromImage(q_img))

    def update_members(self, members):
        self.members = members
        self.member_label.setText(f"成员：{', '.join(members)}")

    def on_hangup(self):
        if self.av_stream:
            self.av_stream.stop()
        self.tcp.send_json({"cmd": "hangup"})
        self.reject()

    def closeEvent(self, event):
        if self.av_stream:
            self.av_stream.stop()
        super().closeEvent(event)
