# -*- coding: utf-8 -*-
# @FileName : main.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:17
import asyncio
from .connection import ClientManager, handle_client
from .chat import broadcast_text, handle_chat_message
from .minesweeper import MinesweeperRoom
from .file_transfer import FileTransferManager


async def main():
    client_manager = ClientManager()
    ms_room = MinesweeperRoom(client_manager)
    file_manager = FileTransferManager(client_manager)
    await file_manager.init_lock()

    async def chat_handler(*args, **kwargs):
        if len(args) == 1:
            await broadcast_text(client_manager, args[0], **kwargs)
        else:
            await handle_chat_message(args[0], args[1], args[2], client_manager)

    async def ms_handler(data, nick, writer):
        await ms_room.handle_command(data, nick, writer)

    async def file_info_handler(payload, nick, writer):
        await file_manager.handle_info(payload, nick, writer)

    async def file_chunk_handler(payload, writer):
        await file_manager.handle_chunk(payload, writer)

    async def file_end_handler(payload, writer):
        await file_manager.handle_end(payload, writer)

    async def on_client_cleanup(nickname, writer):
        await ms_room.on_client_leave(nickname, writer)
        if file_manager.is_sender(writer):
            await file_manager.abort_current()

    async def wrapped_handle_client(reader, writer):
        try:
            await handle_client(
                reader, writer,
                client_manager,
                chat_handler,
                ms_handler,
                file_info_handler,
                file_chunk_handler,
                file_end_handler
            )
        finally:
            nickname = client_manager.get_nick(writer)
            if nickname:
                await on_client_cleanup(nickname, writer)

    server = await asyncio.start_server(wrapped_handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
