import socket
import struct
import time
import threading
import cv2
import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, pyqtSignal
from .protocol import (
    VIDEO_PORT_UDP,
    VIDEO_FRAME_AUDIO,
    VIDEO_FRAME_VIDEO,
    VIDEO_NICK_BYTES
)


class AVStream(QObject):
    # 远程视频帧信号：发送者昵称 + 画面数据
    video_frame_signal = pyqtSignal(str, np.ndarray)
    # 本地预览信号：本地摄像头画面
    local_video_signal = pyqtSignal(np.ndarray)

    def __init__(self, server_host, nickname):
        super().__init__()
        self.server_host = server_host
        self.nick_bytes = nickname.encode("utf-8").ljust(VIDEO_NICK_BYTES, b"\x00")
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False

        # 视频参数
        self.cap = None
        self.video_send_thread = None
        self.video_recv_thread = None
        self.fps = 30

        # 音频参数
        self.audio_input = None
        self.audio_output = None
        self.sample_rate = 16000
        self.channels = 1
        self.muted_nicks = set()  # 本地静音的参与者昵称列表

    def set_mute(self, nick, mute):
        """设置指定参与者是否静音"""
        if mute:
            self.muted_nicks.add(nick)
        else:
            self.muted_nicks.discard(nick)

    def _pack_frame(self, frame_type, data):
        timestamp = struct.pack(">I", int(time.time()))
        return self.nick_bytes + struct.pack("B", frame_type) + timestamp + data

    def _video_send_loop(self):
        """视频采集发送线程，同时输出本地预览"""
        self.cap = cv2.VideoCapture(0)
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                break
            # 发送本地预览信号（拷贝数据，避免多线程冲突）
            self.local_video_signal.emit(frame.copy())

            # 编码并发送
            ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            if not ret:
                continue
            pkt = self._pack_frame(VIDEO_FRAME_VIDEO, buf.tobytes())
            try:
                self.udp_sock.sendto(pkt, (self.server_host, VIDEO_PORT_UDP))
            except Exception:
                pass
            time.sleep(1 / self.fps)
        self.cap.release()

    def _audio_input_callback(self, indata, frames, time_info, status):
        """音频采集回调"""
        if not self.running:
            return
        pkt = self._pack_frame(VIDEO_FRAME_AUDIO, indata.tobytes())
        try:
            self.udp_sock.sendto(pkt, (self.server_host, VIDEO_PORT_UDP))
        except Exception:
            pass

    def _recv_loop(self):
        """UDP接收线程：拆分音视频分别处理"""
        while self.running:
            try:
                data, _ = self.udp_sock.recvfrom(65535)
            except Exception:
                continue

            if len(data) < VIDEO_NICK_BYTES + 5:
                continue

            # 解析包头
            sender_nick = data[:VIDEO_NICK_BYTES].decode("utf-8").rstrip("\x00")
            frame_type = data[VIDEO_NICK_BYTES]
            payload = data[VIDEO_NICK_BYTES + 5:]

            if frame_type == VIDEO_FRAME_VIDEO:
                # 视频：解码后发信号给UI渲染
                try:
                    img_array = np.frombuffer(payload, dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self.video_frame_signal.emit(sender_nick, frame)
                except Exception:
                    pass

            elif frame_type == VIDEO_FRAME_AUDIO:
                # 音频：检查静音列表，静音则跳过播放
                if sender_nick in self.muted_nicks:
                    continue
                if self.audio_output and self.running:
                    try:
                        audio_data = np.frombuffer(payload, dtype=np.int16)
                        self.audio_output.write(audio_data)
                    except Exception:
                        pass

    def start(self):
        if self.running:
            return
        self.running = True

        # 启动发送
        self.video_send_thread = threading.Thread(target=self._video_send_loop, daemon=True)
        self.video_send_thread.start()

        self.audio_input = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._audio_input_callback
        )
        self.audio_input.start()

        # 启动音频播放流
        self.audio_output = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16"
        )
        self.audio_output.start()

        # 启动接收线程
        self.video_recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.video_recv_thread.start()

    def stop(self):
        self.running = False
        self.muted_nicks.clear()
        # 先关闭UDP套接字，强制打断阻塞接收
        try:
            self.udp_sock.close()
        except Exception:
            pass

        if self.audio_input:
            self.audio_input.stop()
            self.audio_input.close()
            self.audio_input = None
        if self.audio_output:
            self.audio_output.stop()
            self.audio_output.close()
            self.audio_output = None
        if self.video_send_thread:
            self.video_send_thread.join(timeout=2)
            self.video_send_thread = None
        if self.video_recv_thread:
            self.video_recv_thread.join(timeout=2)
            self.video_recv_thread = None
