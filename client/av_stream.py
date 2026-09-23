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
        self.fps = 20

        # 音频参数
        self.audio_input = None
        self.audio_output = None
        self.sample_rate = 16000
        self.channels = 1
        self.self_muted = False  # 自身麦克风静音状态

        # 音频队列解耦
        self.audio_send_queue = deque()
        self.audio_send_thread = None
        self.audio_recv_queue = deque()
        self.audio_play_thread = None
        self._buffer_size = 3200  # 约200ms音频缓冲

    def set_self_mute(self, mute):
        """设置自身麦克风是否静音"""
        self.self_muted = mute

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
            self.local_video_signal.emit(frame.copy())

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
        """音频采集回调：静音时直接丢弃，不发送"""
        if not self.running or self.self_muted:
            return
        pkt = self._pack_frame(VIDEO_FRAME_AUDIO, indata.tobytes())
        self.audio_send_queue.append(pkt)

    def _audio_send_loop(self):
        """音频发送独立线程"""
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
        """音频播放独立线程：带缓冲"""
        play_buffer = b""
        while self.running:
            if self.audio_recv_queue:
                payload = self.audio_recv_queue.popleft()
                try:
                    play_buffer += payload
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
                if len(play_buffer) < self._buffer_size:
                    play_buffer += b"\x00\x00" * 160

    def _recv_loop(self):
        """UDP接收线程：音视频分流，所有远程音频正常播放"""
        while self.running:
            try:
                data, _ = self.udp_sock.recvfrom(65535)
            except Exception:
                continue

            if len(data) < VIDEO_NICK_BYTES + 5:
                continue

            sender_nick = data[:VIDEO_NICK_BYTES].decode("utf-8").rstrip("\x00")
            frame_type = data[VIDEO_NICK_BYTES]
            payload = data[VIDEO_NICK_BYTES + 5:]

            if frame_type == VIDEO_FRAME_VIDEO:
                try:
                    img_array = np.frombuffer(payload, dtype=np.uint8)
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if frame is not None:
                        self.video_frame_signal.emit(sender_nick, frame)
                except Exception:
                    pass

            elif frame_type == VIDEO_FRAME_AUDIO:
                # 所有远程音频直接进入播放队列
                self.audio_recv_queue.append(payload)

    def start(self):
        if self.running:
            return
        self.running = True

        self.video_send_thread = threading.Thread(target=self._video_send_loop, daemon=True)
        self.video_send_thread.start()

        self.audio_input = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._audio_input_callback
        )
        self.audio_input.start()

        self.audio_output = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16"
        )
        self.audio_output.start()

        self.audio_send_thread = threading.Thread(target=self._audio_send_loop, daemon=True)
        self.audio_send_thread.start()
        self.audio_play_thread = threading.Thread(target=self._audio_play_loop, daemon=True)
        self.audio_play_thread.start()

        self.video_recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.video_recv_thread.start()

    def stop(self):
        self.running = False
        self.self_muted = False
        self.audio_send_queue.clear()
        self.audio_recv_queue.clear()

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
        if self.audio_send_thread:
            self.audio_send_thread.join(timeout=2)
            self.audio_send_thread = None
        if self.audio_play_thread:
            self.audio_play_thread.join(timeout=2)
            self.audio_play_thread = None
