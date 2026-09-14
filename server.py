import asyncio
import os

clients = {}
video_participants = set()
audio_participants = set()  # 音频通话参与者集合


async def broadcast_text(text, exclude_writer=None):
    """广播文本消息（自动加换行符）"""
    data = (text + '\n').encode()
    for writer in list(clients.keys()):
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
        for writer in list(clients.keys()):
            if writer is not exclude_writer:
                try:
                    writer.write(chunk)
                except Exception:
                    pass
        remaining -= len(chunk)
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                await writer.drain()
            except Exception:
                pass


async def forward_video_frame(reader, frame_size, exclude_writer=None):
    """转发一帧视频给所有在通话中的人"""
    frame_data = b''
    while len(frame_data) < frame_size:
        chunk = await reader.read(min(4096, frame_size - len(frame_data)))
        if not chunk:
            break
        frame_data += chunk
    if len(frame_data) != frame_size:
        return
    for writer in list(video_participants):
        if writer is not exclude_writer:
            try:
                header = f"VIDEO_FRAME:{frame_size}\n".encode()
                writer.write(header)
                writer.write(frame_data)
                await writer.drain()
            except Exception:
                pass


async def forward_audio_frame(reader, frame_size, exclude_writer=None):
    """转发音频帧给所有音频参与者"""
    frame_data = b''
    while len(frame_data) < frame_size:
        chunk = await reader.read(min(4096, frame_size - len(frame_data)))
        if not chunk:
            break
        frame_data += chunk
    if len(frame_data) != frame_size:
        return
    for writer in list(audio_participants):
        if writer is not exclude_writer:
            try:
                header = f"AUDIO_FRAME:{frame_size}\n".encode()
                writer.write(header)
                writer.write(frame_data)
                await writer.drain()
            except Exception:
                pass


async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"新连接: {addr}")
    nickname = ""
    try:
        writer.write("请输入你的昵称: ".encode() + b'\n')
        await writer.drain()
        nickname_line = await reader.readline()
        nickname = nickname_line.decode().strip() or f"用户{addr}"
        clients[writer] = nickname
        print(f"用户 {nickname} 已加入")
        await broadcast_text(f"📢 {nickname} 加入了聊天室", writer)

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                line = line.decode().rstrip('\n')
            except UnicodeDecodeError:
                continue
            if not line:
                continue

            # 普通文本消息
            if not (line.startswith("FILE:") or line.startswith("CALL_") or line.startswith(
                    "VIDEO_FRAME:") or line.startswith("AUDIO_FRAME:")):
                print(f"[{nickname}] {line}")
                await broadcast_text(f"[{nickname}]: {line}", writer)
                continue

            # 文件传输
            if line.startswith("FILE:"):
                _, filename, file_size_str = line.split(":", 2)
                file_size = int(file_size_str)
                filename = os.path.basename(filename)
                print(f"[{nickname}] 正在发送文件: {filename} ({file_size}字节)")
                await broadcast_text(f"FILE:{nickname}:{filename}:{file_size}", writer)
                await forward_file(reader, file_size, writer)
                print(f"[{nickname}] 文件 {filename} 传输完成")
                continue

            # 通话控制消息（加入视频+音频集合）
            if line.startswith("CALL_INVITE:"):
                print(f"[{nickname}] 发起音视频通话邀请")
                await broadcast_text(f"CALL_INVITE:{nickname}", writer)
                video_participants.add(writer)
                audio_participants.add(writer)
                continue
            if line.startswith("CALL_ACCEPT:"):
                video_participants.add(writer)
                audio_participants.add(writer)
                print(f"[{nickname}] 接受了音视频邀请")
                await broadcast_text(f"CALL_ACCEPT:{nickname}")
                continue
            if line.startswith("CALL_REJECT:"):
                print(f"[{nickname}] 拒绝了音视频邀请")
                await broadcast_text(f"CALL_REJECT:{nickname}", exclude_writer=writer)
                continue
            if line.startswith("CALL_HANGUP:"):
                if writer in video_participants:
                    video_participants.remove(writer)
                if writer in audio_participants:
                    audio_participants.remove(writer)
                print(f"[{nickname}] 挂断音视频通话")
                await broadcast_text(f"CALL_HANGUP:{nickname}")
                continue

            # 视频帧转发
            if line.startswith("VIDEO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)
                await forward_video_frame(reader, frame_size, writer)
                continue

            # ========== 新增！音频帧处理分支 ==========
            if line.startswith("AUDIO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)
                await forward_audio_frame(reader, frame_size, writer)
                continue

    except Exception as e:
        print(f"客户端异常: {nickname} - {e}")
    finally:
        if writer in video_participants:
            video_participants.remove(writer)
        if writer in audio_participants:
            audio_participants.remove(writer)
        if writer in clients:
            nickname = clients[writer]
            del clients[writer]
            await broadcast_text(f"📢 {nickname} 离开了聊天室")
            if video_participants or audio_participants:
                await broadcast_text(f"CALL_HANGUP:{nickname}")
            print(f"{nickname} 已断开")
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    server = await asyncio.start_server(handle_client, '0.0.0.0', 8080)
    print("=" * 60)
    print("📡 带【视频+音频通话】聊天室服务端已启动!")
    print("📝 文本聊天：直接输入文字发送")
    print("📁 文件传输：/send <文件路径>")
    print("📹 音视频通话：/call 发起邀请 | /hangup 挂断")
    print("监听地址: 0.0.0.0:8080")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n服务端已停止。")
