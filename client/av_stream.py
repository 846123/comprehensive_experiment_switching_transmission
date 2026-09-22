# -*- coding: utf-8 -*-
# @FileName : av_stream.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/22 18:37
import socket
import struct
import time
import threading
import cv2
import numpy as np
import sounddevice as sd
from .protocol import (
    VIDEO_PORT_UDP,
    VIDEO_FRAME_AUDIO,
    VIDEO_FRAME_VIDEO,
    VIDEO_NICK_BYTES
)


class AVStream:
    def __init__(self, server_host, nickname):
        self.server_host = server_host
        # 昵称补全到固定16字节
        self.nick_bytes = nickname.encode("utf-8").ljust(VIDEO_NICK_BYTES, b"\x00")
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = False

        # 视频参数
        self.cap = None
        self.video_thread = None
        self.fps = 30

        # 音频参数
        self.audio_stream = None
        self.sample_rate = 16000
        self.channels = 1

    def _pack_frame(self, frame_type, data):
        """打包UDP帧：昵称 + 帧类型 + 时间戳 + 数据"""
        timestamp = struct.pack(">I", int(time.time() * 1000))
        return self.nick_bytes + struct.pack("B", frame_type) + timestamp + data

    def _video_loop(self):
        """视频采集线程"""
        self.cap = cv2.VideoCapture(0)
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                break
            # JPEG压缩，质量50，降低带宽
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

    def _audio_callback(self, indata, frames, time_info, status):
        """音频采集回调"""
        if not self.running:
            return
        pkt = self._pack_frame(VIDEO_FRAME_AUDIO, indata.tobytes())
        try:
            self.udp_sock.sendto(pkt, (self.server_host, VIDEO_PORT_UDP))
        except Exception:
            pass

    def start(self):
        """启动采集和发送"""
        if self.running:
            return
        self.running = True

        # 启动视频采集线程
        self.video_thread = threading.Thread(target=self._video_loop, daemon=True)
        self.video_thread.start()

        # 启动音频采集流
        self.audio_stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._audio_callback
        )
        self.audio_stream.start()

    def stop(self):
        """停止所有采集并释放资源"""
        self.running = False
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None
        if self.video_thread:
            self.video_thread.join()
            self.video_thread = None
        self.udp_sock.close()
