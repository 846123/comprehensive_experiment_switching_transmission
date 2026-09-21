# -*- coding: utf-8 -*-
# @FileName : file_transfer.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:19
import asyncio
import json
from .protocol import (
    pack_msg, pack_file_chunk, unpack_file_chunk,
    MSG_TYPE_FILE_INFO, MSG_TYPE_FILE_CHUNK, MSG_TYPE_FILE_END,
    gen_file_id
)
from .connection import ClientManager
import struct


class FileTransferManager:
    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager
        self.transfer_queue = []
        self.current_transfer = None
        self.transfer_lock = None

    async def init_lock(self):
        self.transfer_lock = asyncio.Lock()

    async def broadcast_file_packet(self, pkt, exclude_writer=None):
        await self.client_manager.broadcast_all(pkt, exclude=exclude_writer)

    async def process_next(self):
        async with self.transfer_lock:
            if self.current_transfer is not None:
                return
            if not self.transfer_queue:
                return
            task = self.transfer_queue.pop(0)
            self.current_transfer = task
            print(f"[FILE] 开始传输文件：{task['filename']} 发送者：{task['sender']}")

        meta_payload = json.dumps({
            "file_id": task["file_id"],
            "sender": task["sender"],
            "filename": task["filename"],
            "file_size": task["file_size"]
        }, ensure_ascii=False).encode('utf-8')
        pkt = pack_msg(MSG_TYPE_FILE_INFO, meta_payload)
        await self.broadcast_file_packet(pkt, exclude_writer=task["sender_writer"])

    async def handle_info(self, payload, sender_nick, sender_writer):
        try:
            info = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            print(f"[文件] 元信息解析失败: {e}")
            return

        file_id = info["file_id"]
        filename = info["filename"]
        file_size = info["file_size"]

        task = {
            "file_id": file_id,
            "sender": sender_nick,
            "sender_writer": sender_writer,
            "filename": filename,
            "file_size": file_size,
            "received_offset": 0
        }
        self.transfer_queue.append(task)
        print(f"[FILE] {sender_nick} 发起文件传输：{filename} ({file_size}字节)，已入队")
        await self.process_next()

    async def handle_chunk(self, payload, sender_writer):
        if self.current_transfer is None:
            print("[文件] 收到分片但无当前传输，丢弃")
            return
        if self.current_transfer["sender_writer"] != sender_writer:
            print("[文件] 分片发送者不匹配，丢弃")
            return

        try:
            file_id, offset, data = unpack_file_chunk(payload)
        except struct.error as e:
            print(f"[文件] 分片解析失败: {e}")
            return
        if file_id != self.current_transfer["file_id"]:
            print("[文件] 分片文件ID不匹配，丢弃")
            return

        self.current_transfer["received_offset"] = offset + len(data)
        pkt = pack_msg(MSG_TYPE_FILE_CHUNK, payload)
        await self.broadcast_file_packet(pkt, exclude_writer=sender_writer)

    async def handle_end(self, payload, sender_writer):
        if self.current_transfer is None:
            return
        if self.current_transfer["sender_writer"] != sender_writer:
            return

        try:
            info = json.loads(payload.decode('utf-8'))
        except json.JSONDecodeError as e:
            print(f"[文件] 结束包解析失败: {e}")
            return
        if info["file_id"] != self.current_transfer["file_id"]:
            return

        print(f"[FILE] 文件传输完成：{self.current_transfer['filename']}")
        pkt = pack_msg(MSG_TYPE_FILE_END, payload)
        await self.broadcast_file_packet(pkt, exclude_writer=sender_writer)

        async with self.transfer_lock:
            self.current_transfer = None
        asyncio.create_task(self.process_next())

    async def abort_current(self, reason="发送方断开连接"):
        if self.current_transfer is None:
            return
        end_payload = json.dumps({
            "file_id": self.current_transfer["file_id"],
            "status": "error",
            "msg": reason
        }, ensure_ascii=False).encode('utf-8')
        pkt = pack_msg(MSG_TYPE_FILE_END, end_payload)
        await self.broadcast_file_packet(pkt, exclude_writer=self.current_transfer["sender_writer"])
        print(f"[FILE] 传输中断：{self.current_transfer['filename']} - {reason}")

        async with self.transfer_lock:
            self.current_transfer = None
        asyncio.create_task(self.process_next())

    def is_sender(self, writer):
        if self.current_transfer is None:
            return False
        return self.current_transfer["sender_writer"] == writer
