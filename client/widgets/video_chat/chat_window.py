import cv2
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QScrollArea
)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtCore import Qt
from ...protocol import MSG_TYPE_VIDEO_INVITE
from ...av_stream import AVStream


class VideoChatWindow(QDialog):
    def __init__(self, parent, tcp, my_nick, server_host):
        super().__init__(parent)
        self.setWindowTitle("音视频通话")
        self.resize(960, 700)
        self.tcp = tcp
        self.my_nick = my_nick
        self.server_host = server_host
        self.av_stream = None
        self.remote_widgets = {}  # 存储远程参与者控件

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 上半部分：本地大画面预览
        self.local_video = QLabel("摄像头启动中...")
        self.local_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.local_video.setStyleSheet("background-color:#000; color:#888; font-size:14px;")
        self.local_video.setMinimumHeight(440)
        self.local_video.setScaledContents(True)
        main_layout.addWidget(self.local_video, stretch=3)

        # 下半部分：远程参与者视频列表（横向滚动）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border:none; background:#111;")
        scroll_content = QWidget()
        self.remote_layout = QHBoxLayout(scroll_content)
        self.remote_layout.setSpacing(8)
        self.remote_layout.addStretch(1)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=2)

        # 底部状态栏
        bottom_bar = QHBoxLayout()
        self.member_label = QLabel("成员：0人")
        self.member_label.setStyleSheet("color:#fff;")
        self.btn_hangup = QPushButton("挂断")
        self.btn_hangup.setFixedWidth(100)
        self.btn_hangup.setStyleSheet("background-color:#d00; color:white; padding:6px;")
        self.btn_hangup.clicked.connect(self.on_hangup)

        bottom_bar.addWidget(self.member_label)
        bottom_bar.addStretch(1)
        bottom_bar.addWidget(self.btn_hangup)
        main_layout.addLayout(bottom_bar)

        self.setLayout(main_layout)

    def start_stream(self):
        """启动音视频流并绑定信号"""
        if self.av_stream:
            return
        self.av_stream = AVStream(self.server_host, self.my_nick)
        self.av_stream.local_video_signal.connect(self._on_local_frame)
        self.av_stream.video_frame_signal.connect(self._on_remote_frame)
        self.av_stream.start()

    def _on_local_frame(self, frame):
        """渲染本地大画面（镜像显示，符合自拍习惯）"""
        mirror_frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(mirror_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        q_img = QImage(rgb_frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.local_video.setPixmap(QPixmap.fromImage(q_img))

    def _on_remote_frame(self, sender_nick, frame):
        """渲染指定参与者的远程视频"""
        if sender_nick not in self.remote_widgets:
            return
        video_label = self.remote_widgets[sender_nick]["video"]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        q_img = QImage(rgb_frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
        video_label.setPixmap(QPixmap.fromImage(q_img))

    def update_members(self, members):
        """更新成员列表，动态添加/移除远程视频窗口"""
        self.member_label.setText(f"成员：{len(members)}人")
        remote_nicks = [n for n in members if n != self.my_nick]

        # 移除已离开的参与者
        to_remove = [nick for nick in self.remote_widgets if nick not in remote_nicks]
        for nick in to_remove:
            widget_item = self.remote_widgets.pop(nick)
            widget_item["container"].deleteLater()

        # 添加新加入的参与者
        for nick in remote_nicks:
            if nick in self.remote_widgets:
                continue
            self._add_remote_widget(nick)

    def _add_remote_widget(self, nick):
        """添加一个远程参与者的视频卡片"""
        container = QWidget()
        container.setFixedWidth(150)
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(4)

        # 视频画面
        video_label = QLabel("等待画面...")
        video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        video_label.setStyleSheet("background-color:#000; color:#666; font-size:11px;")
        video_label.setFixedHeight(110)
        video_label.setScaledContents(True)
        v_layout.addWidget(video_label)

        # 底部：昵称 + 静音按钮
        bottom = QHBoxLayout()
        nick_label = QLabel(nick)
        nick_label.setStyleSheet("color:#fff; font-size:12px;")
        mute_btn = QPushButton("静音")
        mute_btn.setFixedHeight(22)
        mute_btn.setStyleSheet("font-size:11px;")
        mute_btn.clicked.connect(lambda: self._toggle_mute(nick, mute_btn))

        bottom.addWidget(nick_label)
        bottom.addStretch(1)
        bottom.addWidget(mute_btn)
        v_layout.addLayout(bottom)

        self.remote_layout.insertWidget(0, container)
        self.remote_widgets[nick] = {
            "container": container,
            "video": video_label,
            "mute_btn": mute_btn,
            "muted": False
        }

    def _toggle_mute(self, nick, btn):
        """切换指定参与者的静音状态"""
        info = self.remote_widgets[nick]
        info["muted"] = not info["muted"]
        self.av_stream.set_mute(nick, info["muted"])
        btn.setText("取消静音" if info["muted"] else "静音")
        btn.setStyleSheet(
            "font-size:11px; background-color:#d00; color:white;"
            if info["muted"] else "font-size:11px;"
        )

    def on_hangup(self):
        """挂断通话"""
        if self.av_stream:
            self.av_stream.stop()
            self.av_stream = None
        self.tcp.send_json({"cmd": "hangup"}, MSG_TYPE_VIDEO_INVITE)
        self.accept()

    def closeEvent(self, event):
        """窗口关闭时释放所有资源"""
        if self.av_stream:
            self.av_stream.stop()
            self.av_stream = None
        super().closeEvent(event)
