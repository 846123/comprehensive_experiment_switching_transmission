# -*- coding: utf-8 -*-
# @FileName : client.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/14 11:29
import asyncio
import sys


async def tcp_client(server_ip, port):
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(f"已连接到 {server_ip}:{port}")
        print("输入消息并按回车发送（输入 'quit' 退出）：")

        # 启动接收协程
        recv_task = asyncio.create_task(receive_messages(reader))

        # 主循环：发送用户输入
        while True:
            message = input("> ")
            if message.lower() == 'quit':
                break
            writer.write(message.encode())
            await writer.drain()

        writer.close()
        await writer.wait_closed()
        recv_task.cancel()

    except ConnectionRefusedError:
        print("连接失败：服务端未启动或地址错误。")
    except Exception as e:
        print(f"客户端异常: {e}")


async def receive_messages(reader):
    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            response = data.decode().strip()
            print(f"\n收到响应: {response}")
            print("> ", end="", flush=True)  # 重新显示输入提示
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收异常: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python client.py <服务器IP> <端口>")
        sys.exit(1)

    server_ip = sys.argv
    port = int(sys.argv)
    asyncio.run(tcp_client(server_ip, port))
