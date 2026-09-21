# -*- coding: utf-8 -*-
# @FileName : chat.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:18
from .protocol import pack_msg, MSG_TYPE_CHAT
from .connection import ClientManager


async def broadcast_text(client_manager: ClientManager, text, exclude=None):
    payload = text.encode("utf-8")
    pkt = pack_msg(MSG_TYPE_CHAT, payload)
    await client_manager.broadcast_all(pkt, exclude)


async def handle_chat_message(content, nickname, writer, client_manager: ClientManager):
    chat_msg = f"【{nickname}】：{content}"
    await broadcast_text(client_manager, chat_msg, exclude=writer)
