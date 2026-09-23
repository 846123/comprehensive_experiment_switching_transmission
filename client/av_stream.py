import socket
import struct
import time
import threading
import cv2
import numpy as np
import sounddevice as sd
from collections import deque
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
        self.fps = 20  # 下调至20fps，视频通话完全够用

        # 音频参数
        self.audio_input = None
        self.audio_output = None
        self.sample_rate = 16000
        self.channels = 1
        self.muted_nicks = set()  # 本地静音的参与者昵称列表

        # 音频队列解耦
        self.audio_send_queue = deque()
        self.audio_send_thread = None
        self.audio_recv_queue = deque()
        self.audio_play_thread = None
        self._buffer_size = 3200  # 约200ms音频缓冲（16kHz单声道int16）

    def set_mute(self, nick, mute):
        """设置指定参与者是否静音，True=静音 False=取消静音"""
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
            # 发送本地预览信号
            self.local_video_signal.emit(frame.copy())

            # 编码并发送，降低画质减少码率
            ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 40])
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
        """音频采集回调：仅写入队列，不阻塞采集线程"""
        if not self.running:
            return
        pkt = self._pack_frame(VIDEO_FRAME_AUDIO, indata.tobytes())
        self.audio_send_queue.append(pkt)

    def _audio_send_loop(self):
        """音频发送独立线程：负责批量UDP发送"""
        while self.running:
            if self.audio_send_queue:
                data = self.audio_send_queue.popleft()
                try:
                    self.udp_sock.sendto(data, (self.server_host, VIDEO_PORT_UDP))
                except Exception:
                    pass
            else:
                time.sleep(0.005)

    def _audio_play_loop(self):
        """音频播放独立线程：带缓冲，平滑网络抖动"""
        play_buffer = b""
        while self.running:
            if self.audio_recv_queue:
                payload = self.audio_recv_queue.popleft()
                try:
                    play_buffer += payload
                    # 达到缓冲阈值后再播放，抗抖动
                    if len(play_buffer) >= self._buffer_size * 2:
                        chunk = play_buffer[:self._buffer_size * 2]
                        play_buffer = play_buffer[self._buffer_size * 2:]
                        if self.audio_output:
                            audio_data = np.frombuffer(chunk, dtype=np.int16)
                            self.audio_output.write(audio_data)
                except Exception:
                    pass
            else:
                time.sleep(0.005)
                # 缓冲不足时补少量静音，避免断音爆音
                if len(play_buffer) < self._buffer_size:
                    play_buffer += b"\x00\x00" * 160

    def _recv_loop(self):
        """UDP接收线程：拆分音视频，音频写入缓冲队列"""
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
                # 音频：检查静音，未静音则写入播放队列
                if sender_nick in self.muted_nicks:
                    continue
                self.audio_recv_queue.append(payload)

    def start(self):
        if self.running:
            return
        self.running = True

        # 启动视频发送
        self.video_send_thread = threading.Thread(target=self._video_send_loop, daemon=True)
        self.video_send_thread.start()

        # 启动音频采集
        self.audio_input = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._audio_input_callback
        )
        self.audio_input.start()

        # 启动音频播放
        self.audio_output = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16"
        )
        self.audio_output.start()

        # 启动音频收发独立线程
        self.audio_send_thread = threading.Thread(target=self._audio_send_loop, daemon=True)
        self.audio_send_thread.start()
        self.audio_play_thread = threading.Thread(target=self._audio_play_loop, daemon=True)
        self.audio_play_thread.start()

        # 启动接收线程
        self.video_recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.video_recv_thread.start()

    def stop(self):
        self.running = False
        self.muted_nicks.clear()
        self.audio_send_queue.clear()
        self.audio_recv_queue.clear()

        # 先关闭UDP套接字，强制打断阻塞接收
        try:
            self.udp_sock.close()
        except Exception:
            pass

        # 释放音频设备
        if self.audio_input:
            self.audio_input.stop()
            self.audio_input.close()
            self.audio_input = None
        if self.audio_output:
            self.audio_output.stop()
            self.audio_output.close()
            self.audio_output = None

        # 等待线程退出
        if self.video_send_thread:
            self.video_send_thread.join(timeout=2)
            self.video_send_thread = None
        if self.video_recv_thread:
            self.video_recv_thread.join(timeout=2)
            self.video_recv_thread = None
        if self.audio_send_thread:
            self.audio_send_thread.join(timeout=2)
            self.audio_send_thread = None
        if self.audio_play_thread:
            self.audio_play_thread.join(timeout=2)
            self.audio_play_thread = None
