import asyncio
import sys
import os
import cv2
import numpy as np
import threading

# ========== 全局视频状态 ==========
in_video = False
cap = None
video_stop_event = threading.Event()
video_lock = threading.Lock()  # 线程锁，保护全局状态


async def receive_loop(reader, writer):
    global in_video
    try:
        while True:
            line = await reader.readline()
            if not line:
                print("\n服务端已断开连接")
                break

            # 修复：增加解码异常捕获，解决utf-8解码0xff报错
            try:
                line = line.decode().rstrip('\n')
            except UnicodeDecodeError:
                continue

            # 文件接收
            if line.startswith("FILE:"):
                _, sender, filename, file_size_str = line.split(":", 3)
                file_size = int(file_size_str)
                save_name = f"received_{filename}"
                print(f"\n📥 正在接收 {sender} 传输的文件: {filename} (大小: {file_size / 1024:.1f}KB)")
                print(f"💾 将保存为: {save_name}")
                received = 0
                with open(save_name, 'wb') as f:
                    while received < file_size:
                        chunk_size = min(4096, file_size - received)
                        chunk = await reader.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        progress = received / file_size * 100
                        print(f"\r⏳ 接收进度: {progress:.1f}%", end="", flush=True)
                print(f"\n✅ 文件 {save_name} 接收完成!")
                print("> ", end="", flush=True)
                continue

            # 视频邀请/控制消息
            if line.startswith("CALL_INVITE:"):
                _, inviter = line.split(":", 1)
                print(f"\n📹 {inviter} 发起视频通话邀请，输入 y 接受 / n 拒绝：")
                print("> ", end="", flush=True)
                continue

            if line.startswith("CALL_ACCEPT:"):
                _, user = line.split(":", 1)
                print(f"\n✅ {user} 加入了视频通话")
                print("> ", end="", flush=True)
                continue

            if line.startswith("CALL_REJECT:"):
                _, user = line.split(":", 1)
                print(f"\n❌ {user} 拒绝了视频邀请")
                print("> ", end="", flush=True)
                continue

            if line.startswith("CALL_HANGUP:"):
                _, user = line.split(":", 1)
                print(f"\n👋 {user} 挂断了视频通话")
                print("> ", end="", flush=True)
                continue

            # 接收并显示视频帧
            if line.startswith("VIDEO_FRAME:"):
                with video_lock:
                    if not in_video:
                        # 不在视频中则丢弃对应字节，避免污染后续消息
                        _, frame_size_str = line.split(":", 1)
                        frame_size = int(frame_size_str)
                        await reader.readexactly(frame_size)
                        continue

                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)

                # 精准读取完整帧
                try:
                    frame_data = await reader.readexactly(frame_size)
                except asyncio.IncompleteReadError:
                    continue

                # 解码显示
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.imshow("视频通话", frame)
                    # 修复：按q真正触发挂断
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        print("\n⌨️ 按q挂断视频")
                        asyncio.get_running_loop().create_task(stop_video(writer))
                print("> ", end="", flush=True)
                continue

            # 普通文本消息
            print(f"\n{line}")
            print("> ", end="", flush=True)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收出错: {e}")
    finally:
        # 接收结束，确保视频资源释放
        with video_lock:
            if in_video:
                video_stop_event.set()
                in_video = False
        cv2.destroyAllWindows()


async def send_file(writer, file_path):
    """发送本地文件给所有人"""
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return
    file_size = os.path.getsize(file_path)
    filename = os.path.basename(file_path)
    header = f"FILE:{filename}:{file_size}\n".encode()
    writer.write(header)
    await writer.drain()
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


def video_capture_thread(writer, loop):
    """后台线程：采集摄像头帧并发送"""
    global cap, in_video, video_stop_event

    # 修复：Windows下强制指定CAP_DSHOW驱动，解决摄像头打不开/索引越界
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("\n❌ 无法打开摄像头")
        with video_lock:
            in_video = False
        return

    print("\n📹 视频通话已连接，按q关闭窗口或输入/hangup挂断")
    print("> ", end="", flush=True)

    try:
        while not video_stop_event.is_set():
            with video_lock:
                if not in_video:
                    break

            ret, frame = cap.read()
            if not ret:
                print("\n❌ 摄像头读取失败")
                break

            # 缩小分辨率+压缩，降低带宽
            frame = cv2.resize(frame, (480, 320))
            _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frame_bytes = jpeg.tobytes()

            header = f"VIDEO_FRAME:{len(frame_bytes)}\n".encode()

            async def send_frame():
                try:
                    writer.write(header + frame_bytes)
                    await writer.drain()
                except Exception:
                    # 修复：连接断开自动停止，避免反复报WinError 64
                    video_stop_event.set()
                    with video_lock:
                        in_video = False

            asyncio.run_coroutine_threadsafe(send_frame(), loop)

            # 控制帧率 ~15fps
            video_stop_event.wait(0.06)

    except Exception as e:
        print(f"\n视频采集异常: {e}")
    finally:
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        with video_lock:
            in_video = False
        print("\n📹 视频通话已结束")
        print("> ", end="", flush=True)


async def start_video(writer, loop):
    """启动视频通话"""
    global in_video, video_stop_event
    with video_lock:
        if in_video:
            print("⚠️ 已经在视频通话中")
            return
        in_video = True
        video_stop_event.clear()

    threading.Thread(target=video_capture_thread, args=(writer, loop), daemon=True).start()


async def stop_video(writer):
    """挂断视频"""
    global in_video, video_stop_event
    with video_lock:
        if not in_video:
            return
        in_video = False
        video_stop_event.set()

    try:
        writer.write(b"CALL_HANGUP:me\n")
        await writer.drain()
    except Exception:
        pass

    cv2.destroyAllWindows()


async def tcp_client(server_ip, port):
    global in_video
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(f"已连接到 {server_ip}:{port}")

        # 输入昵称
        prompt = await reader.readline()
        print(prompt.decode(), end="", flush=True)
        nickname = await asyncio.get_running_loop().run_in_executor(None, input)
        nickname = nickname.strip() or "匿名"
        writer.write((nickname + '\n').encode())
        await writer.drain()

        print("\n💬 直接输入文字发送消息")
        print("📁 输入 /send <文件路径> 发送文件")
        print("📹 输入 /call 发起视频通话")
        print("❌ 输入 /hangup 挂断视频 | quit 退出程序")
        print("-" * 50)

        recv_task = asyncio.create_task(receive_loop(reader, writer))
        loop = asyncio.get_running_loop()

        # 主发送循环
        while True:
            msg = await loop.run_in_executor(None, input, "> ")
            if msg.lower() == 'quit':
                break

            # 发文件命令
            if msg.startswith("/send "):
                file_path = msg[6:].strip()
                if file_path.startswith(('"', "'")) and file_path.endswith(('"', "'")):
                    file_path = file_path[1:-1]
                await send_file(writer, file_path)
                continue

            # 视频命令
            if msg == '/call':
                writer.write(b"CALL_INVITE:me\n")
                await writer.drain()
                await start_video(writer, loop)
                continue

            if msg == '/hangup':
                await stop_video(writer)
                continue

            if msg.lower() == 'y' and not in_video:
                writer.write(b"CALL_ACCEPT:me\n")
                await writer.drain()
                await start_video(writer, loop)
                continue

            if msg.lower() == 'n':
                writer.write(b"CALL_REJECT:me\n")
                await writer.drain()
                print("✅ 已拒绝邀请")
                continue

            # 普通文本消息
            if msg.strip():
                writer.write((msg + '\n').encode())
                await writer.drain()

        # 退出清理
        if in_video:
            await stop_video(writer)
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
