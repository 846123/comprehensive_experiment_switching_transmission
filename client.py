import asyncio
import sys

async def receive_messages(reader):
    """后台持续接收服务端消息"""
    try:
        while True:
            data = await reader.read(1024)
            if not data:
                print("\n服务端已断开连接")
                break
            msg = data.decode()
            print(msg, end="", flush=True)
            print("> ", end="", flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收出错: {e}")

async def tcp_client(server_ip, port):
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(f"已连接到 {server_ip}:{port}")

        # 1. 输入昵称
        data = await reader.read(1024)
        print(data.decode(), end="", flush=True)
        nickname = await asyncio.get_event_loop().run_in_executor(None, input)
        nickname = nickname.strip() or "匿名"
        writer.write(nickname.encode())
        await writer.drain()

        print("\n输入消息发送 (输入 quit 退出)")
        print("-" * 30)

        # 2. 启动接收协程
        recv_task = asyncio.create_task(receive_messages(reader))

        # 3. 发送消息主循环
        while True:
            msg = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
            if msg.lower() == 'quit':
                break
            if msg.strip():
                writer.write(msg.encode())
                await writer.drain()

        print("正在断开...")
        writer.close()
        await writer.wait_closed()
        recv_task.cancel()

    except ConnectionRefusedError:
        print("❌ 连接失败: 服务端未启动或地址/端口错误")
    except Exception as e:
        print(f"❌ 客户端异常: {e}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python client.py <服务器IP> <端口>")
        print("示例: python client.py 127.0.0.1 8080")
        sys.exit(1)

    server_ip = sys.argv[1]
    port = int(sys.argv[2])
    asyncio.run(tcp_client(server_ip, port))
