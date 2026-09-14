# -*- coding: utf-8 -*-
# @FileName : server1.py
# @Author   : Tsing Sai
# @Time     : 2026/9/14 12:30
# -*- coding: utf-8 -*-
# @FileName : server.py
# @Author   : Tsing Sai
# @Time     : 2026/9/14 10:55
import asyncio
import struct

clients = set()

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"新连接: {addr}")
    clients.add(writer)

    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            message = data.decode().strip()
            print(f"收到来自 {addr}: {message}")

            # 广播给所有其他客户端
            for client in clients:
                if client != writer:
                    client.write(f"转发: {message}".encode())
                    await client.drain()
    except Exception as e:
        print(f"客户端 {addr} 连接异常: {e}")
    finally:
        clients.remove(writer)
        writer.close()
        await writer.wait_closed()
        print(f"客户端 {addr} 已断开")

async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8080)
    # 修复这一行：取列表第一个socket
    addr = server.sockets[0].getsockname()
    print(f"服务端启动，监听 {addr[0]}:{addr[1]}")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务端已手动停止。")
