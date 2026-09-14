import asyncio
import sys
import os
import cv2
import numpy as np
import threading
import time
from collections import deque

# ========== 全局视频状态 ==========
in_video = False
cap = None
video_stop_event = threading.Event()
render_stop_event = threading.Event()
video_lock = threading.Lock()

frame_queue_remote = deque(maxlen=1)   # 远端画面（对方）
frame_queue_local = deque(maxlen=1)    # 本地摄像头预览（自己）

global_writer = None
global_loop = None
window_name = "VideoCall"


def render_thread():
    """渲染线程：拼接本地+远端画面，左右分屏（修复闪烁，缓存上一帧）"""
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    blank = np.zeros((320, 480, 3), dtype=np.uint8)
    # 缓存上一帧画面，无新帧持续显示旧画面，避免黑屏闪烁
    last_remote = blank
    last_local = blank

    while not render_stop_event.is_set():
        # 有新帧才更新缓存，只读不删除
        if len(frame_queue_remote) > 0:
            last_remote = frame_queue_remote[-1]
        if len(frame_queue_local) > 0:
            last_local = frame_queue_local[-1]

        remote_frame = cv2.resize(last_remote, (480, 320))
        local_frame = cv2.resize(last_local, (480, 320))
        combined = np.hstack([local_frame, remote_frame])  # 左：自己，右：对方

        cv2.imshow(window_name, combined)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("\n⌨️ 按q挂断视频")
            if global_loop and global_writer:
                asyncio.run_coroutine_threadsafe(stop_video(global_writer), global_loop)
    cv2.destroyWindow(window_name)


async def receive_loop(reader, writer):
    global in_video
    try:
        while True:
            line = await reader.readline()
            if not line:
                print("\n服务端已断开连接")
                break
            try:
                line = line.decode().rstrip('\n')
            except UnicodeDecodeError:
                continue
            if not line:
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

            # 视频控制消息
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

            # 接收远端视频帧，放入远端队列
            if line.startswith("VIDEO_FRAME:"):
                with video_lock:
                    if not in_video:
                        _, frame_size_str = line.split(":", 1)
                        frame_size = int(frame_size_str)
                        await reader.readexactly(frame_size)
                        continue
                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)
                try:
                    frame_data = await reader.readexactly(frame_size)
                except asyncio.IncompleteReadError:
                    continue
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    frame_queue_remote.append(frame)
                continue

            # 普通文本消息
            print(f"\n{line}")
            print("> ", end="", flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收出错: {e}")
    finally:
        with video_lock:
            if in_video:
                video_stop_event.set()
                render_stop_event.set()
                in_video = False


def video_capture_thread(writer, loop):
    """采集：发送到服务端 + 送入本地预览队列，增加自拍镜像"""
    global cap, in_video, video_stop_event
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
            retry = 0
            while not ret and retry < 3:
                retry += 1
                ret, frame = cap.read()
                time.sleep(0.01)
            if not ret:
                print("\n⚠️ 摄像头读取失败，尝试重试...")
                time.sleep(0.15)
                continue

            # 水平翻转，自拍镜像效果
            frame = cv2.flip(frame, 1)
            # 保存原图到本地预览队列
            frame_queue_local.append(frame.copy())

            # 压缩编码发送给对方
            frame_send = cv2.resize(frame, (480, 320))
            _, jpeg = cv2.imencode('.jpg', frame_send, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frame_bytes = jpeg.tobytes()
            header = f"VIDEO_FRAME:{len(frame_bytes)}\n".encode()

            async def send_frame():
                try:
                    writer.write(header + frame_bytes)
                    await writer.drain()
                except Exception:
                    video_stop_event.set()
                    render_stop_event.set()
                    with video_lock:
                        in_video = False
            asyncio.run_coroutine_threadsafe(send_frame(), loop)
            time.sleep(0.06)

    except Exception as e:
        print(f"\n视频采集异常: {e}")
    finally:
        if cap is not None:
            cap.release()
        with video_lock:
            in_video = False
        print("\n📹 视频通话已结束")
        print("> ", end="", flush=True)


async def start_video(writer, loop):
    global in_video, video_stop_event, render_stop_event, global_writer, global_loop
    global_writer = writer
    global_loop = loop
    with video_lock:
        if in_video:
            print("⚠️ 已经在视频通话中")
            return
        in_video = True
        video_stop_event.clear()
        render_stop_event.clear()
    threading.Thread(target=video_capture_thread, args=(writer, loop), daemon=True).start()
    threading.Thread(target=render_thread, daemon=True).start()


async def stop_video(writer):
    global in_video, video_stop_event, render_stop_event
    with video_lock:
        if not in_video:
            return
        in_video = False
        video_stop_event.set()
        render_stop_event.set()
    try:
        writer.write(b"CALL_HANGUP:me\n")
        await writer.drain()
    except Exception:
        pass


async def tcp_client(server_ip, port):
    global in_video
    try:
        reader, writer = await asyncio.open_connection(server_ip, port)
        print(f"已连接到 {server_ip}:{port}")
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

        while True:
            msg = await loop.run_in_executor(None, input, "> ")
            if msg.lower() == 'quit':
                break
            if msg.startswith("/send "):
                file_path = msg[6:].strip()
                if file_path.startswith(('"', "'")) and file_path.endswith(('"', "'")):
                    file_path = file_path[1:-1]
                await send_file(writer, file_path)
                continue
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
            if msg.strip():
                writer.write((msg + '\n').encode())
                await writer.drain()

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


async def send_file(writer, file_path):
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


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python client.py <服务器IP> <端口>")
        print("示例: python client.py 127.0.0.1 8080")
        sys.exit(1)
    server_ip = sys.argv[1]
    port = int(sys.argv[2])
    asyncio.run(tcp_client(server_ip, port))
