# -*- coding: utf-8 -*-
# @FileName : connection.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:18
import json
from .protocol import (
    pack_msg, unpack_header,
    MSG_TYPE_CHAT, MSG_TYPE_MINESWEEPER,
    MSG_TYPE_FILE_INFO, MSG_TYPE_FILE_CHUNK, MSG_TYPE_FILE_END
)


class ClientManager:
    def __init__(self):
        self.clients = {}

    def add_client(self, writer, nickname):
        self.clients[writer] = nickname

    def remove_client(self, writer):
        if writer in self.clients:
            del self.clients[writer]

    def get_nick(self, writer):
        return self.clients.get(writer)

    def all_writers(self):
        return list(self.clients.keys())

    def all_nicks(self):
        return list(self.clients.values())

    async def broadcast_all(self, packet, exclude=None):
        for writer in self.all_writers():
            if writer is exclude:
                continue
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e:
                print(f"[广播] 发送失败: {e}")

    async def broadcast_to(self, writers, packet, exclude=None):
        for writer in writers:
            if writer is exclude:
                continue
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e:
                print(f"[定向广播] 发送失败: {e}")


async def handle_client(
    reader, writer,
    client_manager,
    chat_handler,
    minesweeper_handler,
    file_info_handler,
    file_chunk_handler,
    file_end_handler
):
    addr = writer.get_extra_info('peername')
    ip, port = addr
    nickname_raw = await reader.readline()
    if not nickname_raw:
        writer.close()
        await writer.wait_closed()
        return

    nickname = nickname_raw.decode("utf-8").strip()
    if not nickname:
        writer.close()
        await writer.wait_closed()
        return

    client_manager.add_client(writer, nickname)
    print(f"[连接] {nickname}({ip}:{port}) 已加入")

    join_msg = f"User('{ip}',{port}) {nickname} joined"
    await chat_handler(join_msg, exclude=writer)

    buffer = b""
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer += chunk
            while len(buffer) >= 8:
                hdr = buffer[:8]
                mt, pl, _ = unpack_header(hdr)
                if len(buffer) < 8 + pl:
                    break
                payload = buffer[8:8 + pl]
                buffer = buffer[8 + pl:]

                if mt == MSG_TYPE_CHAT:
                    content = payload.decode("utf-8").strip()
                    await chat_handler(content, nickname, writer)
                elif mt == MSG_TYPE_MINESWEEPER:
                    try:
                        data = json.loads(payload.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    await minesweeper_handler(data, nickname, writer)
                elif mt == MSG_TYPE_FILE_INFO:
                    await file_info_handler(payload, nickname, writer)
                elif mt == MSG_TYPE_FILE_CHUNK:
                    await file_chunk_handler(payload, writer)
                elif mt == MSG_TYPE_FILE_END:
                    await file_end_handler(payload, writer)
    except Exception as e:
        print(f"[错误] {nickname} 连接异常：{e}")
    finally:
        client_manager.remove_client(writer)
        leave_msg = f"User('{ip}',{port}) {nickname} left"
        await chat_handler(leave_msg, exclude=writer)
        print(f"[连接] {nickname} 已离开")
        writer.close()
        await writer.wait_closed()
