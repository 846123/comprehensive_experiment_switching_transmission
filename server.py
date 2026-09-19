import asyncio
import os

# 保存所有在线客户端连接对象，key为客户端连接writer，value为用户昵称
clients = {}
# 参与视频通话的客户端连接集合，仅集合内用户可以收到视频帧数据
video_participants = set()
# 参与音频通话的客户端连接集合，仅集合内用户可以收到音频帧数据
audio_participants = set()


async def broadcast_text(text, exclude_writer=None):
    """广播文本消息，发送给全部在线客户端"""
    data = (text + '\n').encode()
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                pass


async def forward_file(reader, file_size, filename, exclude_writer=None):
    """转发文件给所有在线客户端"""
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                writer.write(f"FILE|{filename}|{file_size}\n".encode())
                await writer.drain()
                remain = file_size
                while remain > 0:
                    chunk = await reader.read(min(4096, remain))
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
                    remain -= len(chunk)
            except Exception:
                pass


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    nickname = None
    try:
        # 第一步读取客户端发来的昵称
        nick_raw = await reader.readline()
        nickname = nick_raw.decode().strip()
        if not nickname:
            return

        clients[writer] = nickname
        await broadcast_text(f"📢 用户('{addr[0]}', {addr[1]}) {nickname} joined the chatroom")

        buffer = b""
        while True:
            data = await reader.read(4096)
            if not data:
                break
            buffer += data
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                msg = line.decode().strip()
                if msg.startswith("FILE|"):
                    parts = msg.split("|")
                    _, fname, fsize_str = parts
                    fsize = int(fsize_str)
                    await forward_file(reader, fsize, fname, writer)
                    await broadcast_text(f"📁 File received: {fname}", writer)
                else:
                    await broadcast_text(f"[{nickname}]: {msg}", writer)
    except Exception:
        pass
    finally:
        # 连接断开，清理全部容器
        if writer in clients:
            del clients[writer]
        video_participants.discard(writer)
        audio_participants.discard(writer)
        writer.close()
        await writer.wait_closed()
        if nickname:
            await broadcast_text(f"📢 User('{addr[0]}', {addr[1]}) {nickname} left the chatroom")


async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8888)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
    print(f"Server running on {addrs}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
