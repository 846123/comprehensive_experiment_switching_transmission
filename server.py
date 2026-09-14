import asyncio
import os

clients = {}


async def broadcast_text(text, exclude_writer=None):
    """广播文本消息（自动加换行符）"""
    data = (text + '\n').encode()
    for writer in clients:
        if writer is not exclude_writer:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                pass


async def forward_file(reader, file_size, exclude_writer=None):
    """转发文件二进制块给所有其他客户端"""
    remaining = file_size
    while remaining > 0:
        chunk_size = min(4096, remaining)
        chunk = await reader.read(chunk_size)
        if not chunk:
            break
        # 转发给所有其他客户端
        for writer in clients:
            if writer is not exclude_writer:
                try:
                    writer.write(chunk)
                except Exception:
                    pass
        remaining -= len(chunk)
    # 等所有发送完成
    for writer in clients:
        if writer is not exclude_writer:
            try:
                await writer.drain()
            except Exception:
                pass


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"新连接: {addr}")

    try:
        # 1. 昵称设置（完全和之前一样）
        writer.write("请输入你的昵称: ".encode() + b'\n')
        await writer.drain()
        nickname_line = await reader.readline()
        nickname = nickname_line.decode().strip() or f"用户{addr}"

        clients[writer] = nickname
        print(f"用户 {nickname} 已加入")
        await broadcast_text(f"📢 {nickname} 加入了聊天室", writer)

        # 2. 主循环（完全和之前一样）
        while True:
            line = await reader.readline()
            if not line:
                break
            line = line.decode().strip()
            if not line:
                continue

            # ========== 处理文件传输（仅改了这里2行）==========
            if line.startswith("FILE:"):
                _, filename, file_size_str = line.split(":", 2)
                file_size = int(file_size_str)
                filename = os.path.basename(filename)
                print(f"[{nickname}] 正在发送文件: {filename} ({file_size}字节)")

                # 先广播文件头给其他人
                await broadcast_text(f"FILE:{nickname}:{filename}:{file_size}", writer)
                # 再转发二进制内容
                await forward_file(reader, file_size, writer)

                # ===== 以下是唯一改动的地方 =====
                # 1. 只在服务端控制台打印传输完成（你要的效果：接在"正在发送文件"后面）
                print(f"[{nickname}] 文件 {filename} 传输完成")
                # 2. 删掉了原来广播给所有人的"✅ xx发送的文件传输完成"！接收方不会再看到这句突兀的话
                # =================================
                continue

            # ========== 普通文本消息（完全和之前一样）==========
            print(f"[{nickname}] {line}")
            await broadcast_text(f"[{nickname}]: {line}", writer)

    except Exception as e:
        print(f"客户端异常: {e}")
    finally:
        if writer in clients:
            nickname = clients[writer]
            del clients[writer]
            await broadcast_text(f"📢 {nickname} 离开了聊天室")
            print(f"{nickname} 已断开")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8080)
    print("=" * 50)
    print("📁 带文件传输的聊天室服务端已启动!")
    print("监听地址: 0.0.0.0:8080")
    print("发文件命令: /send <本地文件路径>")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务端已停止。")
