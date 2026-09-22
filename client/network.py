# -*- coding: utf-8 -*-
# @FileName : network.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:22
import socket
import os
import json
import uuid
from PyQt6.QtCore import QThread, pyqtSignal
from .protocol import (
    pack_msg, unpack_header,
    pack_file_chunk, unpack_file_chunk,
    MSG_TYPE_CHAT, MSG_TYPE_MINESWEEPER,
    MSG_TYPE_FILE_INFO, MSG_TYPE_FILE_CHUNK, MSG_TYPE_FILE_END,
    FILE_CHUNK_SIZE,
    MSG_TYPE_VIDEO_INVITE, MSG_TYPE_VIDEO_STATUS
)


class TcpClientThread(QThread):
    msg_signal = pyqtSignal(str)
    ms_signal = pyqtSignal(dict)
    connected_signal = pyqtSignal()
    fail_signal = pyqtSignal(str)
    disconnect_signal = pyqtSignal()
    video_signal = pyqtSignal(dict)

    file_info_signal = pyqtSignal(str, str, str, int)  # file_id, sender, filename, file_size
    file_chunk_signal = pyqtSignal(str, int, bytes)  # file_id, offset, data
    file_end_signal = pyqtSignal(str, str, str)  # file_id, status, msg
    send_progress_signal = pyqtSignal(int, int)  # sent, total
    send_error_signal = pyqtSignal(str)

    def __init__(self, host, port, nick):
        super().__init__()
        self.host = host
        self.port = port
        self.nick = nick
        self.sock = None
        self.running = True
        self.receiving_files = {}
        self.chunk_buffer = {}  # file_id -> {offset: bytes}
        self.pending_end = set()  # 已收到结束包但未完成接收的文件

    def run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(None)
            self.sock.connect((self.host, self.port))
            self.sock.sendall((self.nick + "\n").encode("utf-8"))
            self.connected_signal.emit()

            buf = b""
            while self.running:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 8:
                    hdr = buf[:8]
                    mt, pl, _ = unpack_header(hdr)
                    if len(buf) < 8 + pl:
                        break
                    payload = buf[8:8 + pl]
                    buf = buf[8 + pl:]

                    if mt == MSG_TYPE_CHAT:
                        text = payload.decode("utf-8", errors="replace")
                        self.msg_signal.emit(text)
                    elif mt == MSG_TYPE_MINESWEEPER:
                        obj = json.loads(payload.decode("utf-8", errors="replace"))
                        self.ms_signal.emit(obj)
                    elif mt == MSG_TYPE_FILE_INFO:
                        info = json.loads(payload.decode("utf-8"))
                        self.file_info_signal.emit(
                            info["file_id"], info["sender"],
                            info["filename"], info["file_size"]
                        )
                    elif mt == MSG_TYPE_FILE_CHUNK:
                        file_id, offset, data = unpack_file_chunk(payload)
                        self._handle_file_chunk(file_id, offset, data)
                        self.file_chunk_signal.emit(file_id, offset, data)
                    elif mt == MSG_TYPE_FILE_END:
                        info = json.loads(payload.decode("utf-8"))
                        self._handle_file_end(info["file_id"])
                        self.file_end_signal.emit(
                            info["file_id"], info["status"],
                            info.get("msg", "")
                        )
                    elif mt == MSG_TYPE_VIDEO_STATUS:
                        obj = json.loads(payload.decode("utf-8"))
                        self.video_signal.emit(obj)
            self.sock.close()
        except socket.error as e:
            self.fail_signal.emit(str(e))
        finally:
            self.disconnect_signal.emit()

    def _handle_file_chunk(self, file_id, offset, data):
        if file_id in self.receiving_files:
            info = self.receiving_files[file_id]
            info["handle"].seek(offset)
            info["handle"].write(data)
            info["received"] += len(data)
        else:
            if file_id not in self.chunk_buffer:
                self.chunk_buffer[file_id] = {}
            self.chunk_buffer[file_id][offset] = data

    def _handle_file_end(self, file_id):
        if file_id in self.receiving_files:
            info = self.receiving_files[file_id]
            info["handle"].close()
            del self.receiving_files[file_id]
            if file_id in self.chunk_buffer:
                del self.chunk_buffer[file_id]
        else:
            self.pending_end.add(file_id)

    def send_text(self, text):
        pkt = pack_msg(MSG_TYPE_CHAT, text.encode("utf-8"))
        try:
            if self.sock:
                self.sock.sendall(pkt)
        except socket.error as e:
            print("send err", e)

    def send_json(self, obj, msg_type=MSG_TYPE_MINESWEEPER):
        raw = json.dumps(obj).encode("utf-8")
        pkt = pack_msg(msg_type, raw)
        try:
            if self.sock:
                self.sock.sendall(pkt)
        except socket.error as e:
            print("send json err", e)

    def send_file(self, file_path):
        try:
            file_size = os.path.getsize(file_path)
            filename = os.path.basename(file_path)
            file_id = uuid.uuid4().hex

            meta = json.dumps({
                "file_id": file_id,
                "filename": filename,
                "file_size": file_size
            }, ensure_ascii=False).encode("utf-8")
            self.sock.sendall(pack_msg(MSG_TYPE_FILE_INFO, meta))

            sent = 0
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(FILE_CHUNK_SIZE)
                    if not chunk:
                        break
                    pkt_data = pack_file_chunk(file_id, sent, chunk)
                    self.sock.sendall(pack_msg(MSG_TYPE_FILE_CHUNK, pkt_data))
                    sent += len(chunk)
                    self.send_progress_signal.emit(sent, file_size)

            end = json.dumps({
                "file_id": file_id,
                "status": "success",
                "msg": ""
            }, ensure_ascii=False).encode("utf-8")
            self.sock.sendall(pack_msg(MSG_TYPE_FILE_END, end))
            return True, ""
        except (socket.error, OSError, IOError) as e:
            return False, str(e)

    def start_receive_file(self, file_id, save_path):
        try:
            f = open(save_path, 'wb')
            self.receiving_files[file_id] = {
                "path": save_path,
                "handle": f,
                "size": 0,
                "received": 0
            }
            if file_id in self.chunk_buffer:
                for offset in sorted(self.chunk_buffer[file_id].keys()):
                    data = self.chunk_buffer[file_id][offset]
                    f.seek(offset)
                    f.write(data)
                    self.receiving_files[file_id]["received"] += len(data)
                del self.chunk_buffer[file_id]

            if file_id in self.pending_end:
                self.pending_end.remove(file_id)
                info = self.receiving_files[file_id]
                info["handle"].close()
                del self.receiving_files[file_id]
                return True, "finished"
            return True, ""
        except OSError as e:
            return False, str(e)

    def get_received_size(self, file_id):
        if file_id in self.receiving_files:
            return self.receiving_files[file_id]["received"]
        if file_id in self.chunk_buffer:
            return sum(len(d) for d in self.chunk_buffer[file_id].values())
        return 0

    def finish_receive_file(self, file_id):
        if file_id in self.receiving_files:
            info = self.receiving_files[file_id]
            info["handle"].close()
            del self.receiving_files[file_id]
        if file_id in self.chunk_buffer:
            del self.chunk_buffer[file_id]
        if file_id in self.pending_end:
            self.pending_end.remove(file_id)

    def close_conn(self):
        self.running = False
        for info in self.receiving_files.values():
            try:
                info["handle"].close()
            except OSError:
                pass
        self.receiving_files.clear()
        self.chunk_buffer.clear()
        self.pending_end.clear()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            self.sock.close()
