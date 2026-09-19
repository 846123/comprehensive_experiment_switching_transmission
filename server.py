import asyncio
import os

# 保存所有在线客户端连接对象，key为客户端连接writer，value为用户昵称
clients = {}
# 参与视频通话的客户端连接集合，仅集合内用户可以收到视频帧数据
video_participants = set()
# 参与音频通话的客户端连接集合，仅集合内用户可以收到音频帧数据
audio_participants = set()


async def broadcast_text(text, exclude_writer=None):
    """
    广播文本消息，发送给全部在线客户端
    :param text: 需要广播的文本内容
    :param exclude_writer: 需要排除的连接对象，一般为消息发送者，不发给自己
    """
    data = (text + '\n').encode()
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                pass


async def forward_file(reader, file_size, exclude_writer):
    """转发文件给其他客户端"""
    remaining = file_size
    chunk_size = 4096
    while remaining > 0:
        chunk = await reader.read(min(chunk_size, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        for writer in list(clients.keys()):
            if writer is not exclude_writer:
                try:
                    writer.write(chunk)
                    await writer.drain()
                except Exception:
                    pass


async def handle_client(reader, writer):
    nickname_raw = await reader.readline()
    if not nickname_raw:
        writer.close()
        await writer.wait_closed()
        return
    nickname = nickname_raw.decode().strip()
    clients[writer] = nickname
    # 获取客户端真实IP与端口
    client_ip, client_port = writer.transport.get_extra_info('peername')
    await broadcast_text(f"用户('{client_ip}', {client_port}) {nickname} joined the chatroom")

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = line.decode().strip()
            if msg.startswith("FILE|"):
                parts = msg.split("|")
                _, filename, sz_str = parts
                file_size = int(sz_str)
                await broadcast_text(msg, exclude_writer=writer)
                await forward_file(reader, file_size, exclude_writer=writer)
            else:
                await broadcast_text(msg, exclude_writer=writer)
    except Exception:
        pass
    finally:
        del clients[writer]
        writer.close()
        await writer.wait_closed()
        await broadcast_text(f"用户离开: {nickname}")


async def main():
    # 服务端监听 0.0.0.0:8080
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
