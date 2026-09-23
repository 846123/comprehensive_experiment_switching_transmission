import cv2
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QScrollArea, QGridLayout
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

        # 上半部分：本地大画面预览（网格布局叠加静音标识）
        self.local_container = QWidget()
        self.local_container.setStyleSheet("background-color:#000;")
        local_grid = QGridLayout(self.local_container)
        local_grid.setContentsMargins(0, 0, 0, 0)

        self.local_video = QLabel("摄像头启动中...")
        self.local_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.local_video.setStyleSheet("color:#888; font-size:14px;")
        self.local_video.setMinimumHeight(440)
        self.local_video.setScaledContents(True)

        # 本地静音标识（左上角，叠加在画面上层）
        self.local_mute_label = QLabel("麦克风已关闭")
        self.local_mute_label.setStyleSheet("""
            color:white; 
            background-color:rgba(220,0,0,0.85); 
            padding:4px 10px;
            font-size:13px;
            border-radius:4px;
        """)
        self.local_mute_label.hide()

        local_grid.addWidget(self.local_video, 0, 0)
        local_grid.addWidget(self.local_mute_label, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        main_layout.addWidget(self.local_container, stretch=3)

        # 下半部分：远程参与者视频列表（横向滚动）
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border:none; background:#111;")
        scroll_content = QWidget()
        self.remote_layout = QHBoxLayout(scroll_content)
        self.remote_layout.setSpacing(10)
        self.remote_layout.addStretch(1)
        scroll_area.setWidget(scroll_content)
        main_layout.addWidget(scroll_area, stretch=2)

        # 底部状态栏
        bottom_bar = QHBoxLayout()
        self.member_label = QLabel("成员：0人")
        self.member_label.setStyleSheet("color:#fff;")

        self.btn_mute = QPushButton("静音")
        self.btn_mute.setFixedWidth(80)
        self.btn_mute.setStyleSheet("""
            QPushButton {
                background-color:#333;
                color:white;
                padding:6px;
                border:1px solid #555;
                border-radius:3px;
            }
            QPushButton:hover {
                background-color:#444;
            }
        """)
        self.btn_mute.clicked.connect(self._toggle_self_mute)

        self.btn_hangup = QPushButton("挂断")
        self.btn_hangup.setFixedWidth(100)
        self.btn_hangup.setStyleSheet("background-color:#d00; color:white; padding:6px;")
        self.btn_hangup.clicked.connect(self.on_hangup)

        bottom_bar.addWidget(self.member_label)
        bottom_bar.addStretch(1)
        bottom_bar.addWidget(self.btn_mute)
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
        """渲染本地大画面（镜像显示）"""
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
        """更新成员列表，动态增删视频窗口"""
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

    def update_mute_status(self, nick, muted):
        """更新指定参与者的静音标识"""
        if nick == self.my_nick:
            # 更新本地大画面的静音标识
            self.local_mute_label.setVisible(muted)
            return
        if nick in self.remote_widgets:
            self.remote_widgets[nick]["mute_label"].setVisible(muted)

    def _add_remote_widget(self, nick):
        """添加一个远程参与者的视频卡片（网格布局叠加静音标识）"""
        container = QWidget()
        container.setFixedWidth(180)
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(4, 4, 4, 4)
        v_layout.setSpacing(4)

        # 视频画面容器（网格叠加静音标识）
        video_container = QWidget()
        video_container.setStyleSheet("background-color:#000;")
        video_grid = QGridLayout(video_container)
        video_grid.setContentsMargins(0, 0, 0, 0)

        video_label = QLabel("等待画面...")
        video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        video_label.setStyleSheet("color:#666; font-size:11px;")
        video_label.setFixedHeight(120)
        video_label.setScaledContents(True)

        # 远程静音标识（左上角，叠加在画面上层）
        mute_label = QLabel("静音中")
        mute_label.setStyleSheet("""
            color:white;
            background-color:rgba(220,0,0,0.85);
            padding:2px 6px;
            font-size:11px;
            border-radius:3px;
        """)
        mute_label.hide()

        video_grid.addWidget(video_label, 0, 0)
        video_grid.addWidget(mute_label, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        v_layout.addWidget(video_container)

        # 底部昵称
        nick_label = QLabel(nick)
        nick_label.setStyleSheet("color:#fff; font-size:12px;")
        v_layout.addWidget(nick_label)

        self.remote_layout.insertWidget(0, container)
        self.remote_widgets[nick] = {
            "container": container,
            "video": video_label,
            "mute_label": mute_label
        }

    def _toggle_self_mute(self):
        """切换自身麦克风静音状态"""
        if not self.av_stream:
            return
        current_muted = self.av_stream.self_muted
        new_muted = not current_muted
        self.av_stream.set_self_mute(new_muted)

        # 发送状态同步指令
        cmd = "mute" if new_muted else "unmute"
        self.tcp.send_json({"cmd": cmd}, MSG_TYPE_VIDEO_INVITE)

        # 更新按钮样式
        if new_muted:
            self.btn_mute.setText("取消静音")
            self.btn_mute.setStyleSheet("""
                QPushButton {
                    background-color:#d00;
                    color:white;
                    padding:6px;
                    border:1px solid #f00;
                    border-radius:3px;
                }
                QPushButton:hover {
                    background-color:#e00;
                }
            """)
        else:
            self.btn_mute.setText("静音")
            self.btn_mute.setStyleSheet("""
                QPushButton {
                    background-color:#333;
                    color:white;
                    padding:6px;
                    border:1px solid #555;
                    border-radius:3px;
                }
                QPushButton:hover {
                    background-color:#444;
                }
            """)

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
