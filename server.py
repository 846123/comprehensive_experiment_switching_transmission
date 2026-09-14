import asyncio

clients = {}

def broadcast(msg, exclude_writer=None):
    """广播消息给所有客户端"""
    for writer in clients:
        if writer is not exclude_writer:
            try:
                writer.write(msg.encode())
                asyncio.create_task(writer.drain())
            except Exception:
                pass

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"新连接: {addr}")

    try:
        # 1. 请求昵称
        writer.write("请输入你的昵称: ".encode())
        await writer.drain()
        data = await reader.read(1024)
        nickname = data.decode().strip()
        if not nickname:
            nickname = f"用户{addr}"

        clients[writer] = nickname
        print(f"用户 {nickname} 已加入")
        broadcast(f"\n📢 {nickname} 加入了聊天室\n", writer)

        # 2. 接收消息循环
        while True:
            data = await reader.read(1024)
            if not data:
                break
            message = data.decode().strip()
            if not message:
                continue
            print(f"[{nickname}] {message}")
            broadcast(f"[{nickname}]: {message}\n", writer)

    except Exception as e:
        print(f"客户端异常: {e}")
    finally:
        if writer in clients:
            nickname = clients[writer]
            del clients[writer]
            broadcast(f"\n📢 {nickname} 离开了聊天室\n")
            print(f"{nickname} 已断开")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8080)
    print("=" * 40)
    print("聊天室服务端已启动!")
    print("监听地址: 0.0.0.0:8080")
    print("按 Ctrl+C 停止服务")
    print("=" * 40)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务端已停止。")
