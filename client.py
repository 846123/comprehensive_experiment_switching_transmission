import asyncio
import sys
import os


async def receive_loop(reader):
    """接收循环：自动区分文本消息和文件"""
    try:
        while True:
            # 先读一行
            line = await reader.readline()
            if not line:
                print("\n服务端已断开连接")
                break
            line = line.decode().rstrip('\n')

            # ========== 处理接收文件 ==========
            if line.startswith("FILE:"):
                _, sender, filename, file_size_str = line.split(":", 3)
                file_size = int(file_size_str)
                save_name = f"received_{filename}"
                print(f"\n📥 正在接收文件: {filename} (大小: {file_size / 1024:.1f}KB)")
                print(f"💾 将保存为: {save_name}")

                # 接收二进制写入文件
                received = 0
                with open(save_name, 'wb') as f:
                    while received < file_size:
                        chunk_size = min(4096, file_size - received)
                        chunk = await reader.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        # 显示进度
                        progress = received / file_size * 100
                        print(f"\r⏳ 接收进度: {progress:.1f}%", end="", flush=True)

                print(f"\n✅ 文件 {save_name} 接收完成!")
                print("> ", end="", flush=True)
                continue

            # ========== 普通文本消息 ==========
            print(f"\n{line}")
            print("> ", end="", flush=True)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收出错: {e}")


async def send_file(writer, file_path):
    """发送本地文件给所有人"""
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)

    # 先发文件头
    header = f"FILE:{filename}:{file_size}\n".encode()
    writer.write(header)
    await writer.drain()

    # 再分块发二进制
    sent = 0
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            writer.write(chunk)
            sent += len(chunk)
            progress = sent / file_size * 100
            print(f"\r📤 发送进度: {progress:.1f}%", end="", flush=True)
    await writer.drain()
    print(f"\n✅ 文件 {filename} 发送完成!")


async def tcp_client(server_ip, port):
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(f"已连接到 {server_ip}:{port}")

        # 输入昵称
        prompt = await reader.readline()
        print(prompt.decode(), end="", flush=True)
        nickname = await asyncio.get_event_loop().run_in_executor(None, input)
        nickname = nickname.strip() or "匿名"
        writer.write((nickname + '\n').encode())
        await writer.drain()

        print("\n💬 直接输入文字发送消息")
        print("📁 输入 /send <文件路径> 发送文件")
        print("❌ 输入 quit 退出")
        print("-" * 40)

        # 启动后台接收协程
        recv_task = asyncio.create_task(receive_loop(reader))

        # 主发送循环
        while True:
            msg = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
            if msg.lower() == 'quit':
                break

            # 处理发文件命令
            if msg.startswith("/send "):
                file_path = msg[6:].strip()
                # 自动去掉首尾的引号（支持 " " 和 ' '）
                if file_path.startswith(('"', "'")) and file_path.endswith(('"', "'")):
                    file_path = file_path[1:-1]
                await send_file(writer, file_path)
                continue

            # 普通文本消息
            if msg.strip():
                writer.write((msg + '\n').encode())
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
