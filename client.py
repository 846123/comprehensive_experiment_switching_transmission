import asyncio
import sys
import os
import cv2
import numpy as np
import threading
import time
from collections import deque
import sounddevice as sd
import random

# ===================== 全局音视频状态变量 =====================
# 是否处于音视频通话状态
in_video = False
# 摄像头捕获对象
cap = None
# 视频采集线程停止事件
video_stop_event = threading.Event()
# 画面渲染线程停止事件
render_stop_event = threading.Event()
# 音频播放线程停止事件
audio_stop_event = threading.Event()
# 多线程互斥锁，保护音视频全局状态，防止多线程竞争访问
video_lock = threading.Lock()

# 远端对方画面帧队列，最大长度1，自动丢弃旧帧，降低画面延迟
frame_queue_remote = deque(maxlen=1)
# 本地摄像头预览画面帧队列，最大长度1
frame_queue_local = deque(maxlen=1)
# 远端音频数据缓冲区，缓存对方音频片段，上限8防止音频堆积
audio_queue_remote = deque(maxlen=8)

# 网络连接对象，供子线程调用
global_writer = None
# asyncio事件循环对象，供子线程提交协程任务
global_loop = None
# 视频窗口名称
window_name = "VideoCall"

# 音频固定配置参数
CHUNK = 1024        # 单次音频采样块大小
CHANNELS = 1        # 单声道
RATE = 16000        # 音频采样率 16000Hz

# ==================== 扫雷全局状态 ====================
in_minesweeper = False
mine_stop_event = threading.Event()
mine_lock = threading.Lock()

# 扫雷配置
MINE_ROW = 16
MINE_COL = 20
MINE_COUNT = 40

# 格子状态常量
CELL_UNOPEN = 0
CELL_OPENED = 1
CELL_FLAG = 2

def minesweeper_thread():
    """扫雷渲染与游戏逻辑线程，独立OpenCV窗口"""
    global in_minesweeper

    win_name = "Minesweeper"
    cell_size = 30
    MINE_W = MINE_COL * cell_size
    MINE_H = MINE_ROW * cell_size

    colors = {
        CELL_UNOPEN: (180, 180, 180),
        CELL_OPENED: (220, 220, 220),
        CELL_FLAG:   (50, 50, 255)
    }
    num_color = [
        (0, 0, 255), (0, 128, 0), (255, 0, 0), (128, 0, 128),
        (0, 0, 128), (128, 128, 0), (0, 128, 128), (128, 128, 128)
    ]
    dirs = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

    cv2.namedWindow(win_name, cv2.WINDOW_AUTOSIZE)  # 锁定尺寸，禁止拉伸

    while not mine_stop_event.is_set():
        # ---- 一局开始，重置棋盘 ----
        board_state = [[CELL_UNOPEN for _ in range(MINE_COL)] for _ in range(MINE_ROW)]
        is_mine = [[False]*MINE_COL for _ in range(MINE_ROW)]
        near_mine_cnt = [[0]*MINE_COL for _ in range(MINE_ROW)]
        game_over = False
        game_win = False

        mines = set()
        while len(mines) < MINE_COUNT:
            mines.add((random.randint(0, MINE_ROW-1), random.randint(0, MINE_COL-1)))
        for r, c in mines:
            is_mine[r][c] = True
        for r in range(MINE_ROW):
            for c in range(MINE_COL):
                if is_mine[r][c]:
                    continue
                cnt = 0
                for dr, dc in dirs:
                    nr, nc = r+dr, c+dc
                    if 0 <= nr < MINE_ROW and 0 <= nc < MINE_COL and is_mine[nr][nc]:
                        cnt += 1
                near_mine_cnt[r][c] = cnt

        state_box = {"over": False, "win": False}

        def mouse_callback(event, x, y, flags, param):
            if state_box["over"] or state_box["win"]:
                return
            c = x // cell_size
            r = y // cell_size
            if not (0 <= r < MINE_ROW and 0 <= c < MINE_COL):
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                if board_state[r][c] == CELL_UNOPEN:
                    if is_mine[r][c]:
                        state_box["over"] = True
                        board_state[r][c] = CELL_OPENED
                    else:
                        q = [(r, c)]
                        board_state[r][c] = CELL_OPENED
                        while q:
                            rr, cc = q.pop(0)
                            if near_mine_cnt[rr][cc] == 0:
                                for dr, dc in dirs:
                                    nr, nc = rr+dr, cc+dc
                                    if 0 <= nr < MINE_ROW and 0 <= nc < MINE_COL:
                                        if board_state[nr][nc] == CELL_UNOPEN and not is_mine[nr][nc]:
                                            board_state[nr][nc] = CELL_OPENED
                                            q.append((nr, nc))
                # 胜利判定：所有非雷格都被打开
                opened = sum(row.count(CELL_OPENED) for row in board_state)
                if opened == MINE_ROW * MINE_COL - MINE_COUNT:
                    state_box["win"] = True
            elif event == cv2.EVENT_RBUTTONDOWN:
                if board_state[r][c] == CELL_UNOPEN:
                    board_state[r][c] = CELL_FLAG
                elif board_state[r][c] == CELL_FLAG:
                    board_state[r][c] = CELL_UNOPEN

        cv2.setMouseCallback(win_name, mouse_callback)

        while not mine_stop_event.is_set():
            img = np.ones((MINE_H, MINE_W, 3), dtype=np.uint8) * 200
            for r in range(MINE_ROW):
                for c in range(MINE_COL):
                    x1, y1 = c*cell_size, r*cell_size
                    x2, y2 = x1+cell_size, y1+cell_size
                    st = board_state[r][c]
                    cv2.rectangle(img, (x1, y1), (x2, y2), colors[st], -1)
                    cv2.rectangle(img, (x1, y1), (x2, y2), (50, 50, 50), 1)
                    if st == CELL_OPENED and near_mine_cnt[r][c] > 0:
                        cv2.putText(img, str(near_mine_cnt[r][c]),
                                    (x1+8, y1+22), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                                    num_color[near_mine_cnt[r][c]-1], 2)
                    # 插旗
                    if st == CELL_FLAG:
                        cv2.line(img, (x1+8, y1+22), (x1+8, y1+8), (0, 0, 200), 2)
                        cv2.putText(img, "|", (x1+6, y1+22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,200), 2)
                    # 游戏结束：翻开所有雷
                    if state_box["over"] and is_mine[r][c] and st != CELL_FLAG:
                        cv2.circle(img, ((x1+x2)//2, (y1+y2)//2), 8, (0, 0, 0), -1)

            # 结束/胜利文字覆盖层
            if state_box["over"]:
                cv2.rectangle(img, (0, MINE_H//2-30), (MINE_W, MINE_H//2+30), (0, 0, 0), -1)
                cv2.putText(img, "GAME OVER  (r:restart  q:quit)",
                            (30, MINE_H//2+10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if state_box["win"]:
                cv2.rectangle(img, (0, MINE_H//2-30), (MINE_W, MINE_H//2+30), (0, 100, 0), -1)
                cv2.putText(img, "YOU WIN!  (r:restart  q:quit)",
                            (60, MINE_H//2+10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            cv2.imshow(win_name, img)
            key = cv2.waitKey(20) & 0xFF
            if key == ord('q'):
                mine_stop_event.set()
                break
            if key == ord('r') and (state_box["over"] or state_box["win"]):
                break  # 跳出内层循环，外层 while 重新开局

    try:
        cv2.destroyWindow(win_name)
    except Exception:
        pass
    with mine_lock:
        in_minesweeper = False
    print("\n💣 扫雷已关闭")
    print("> ", end="", flush=True)


async def start_minesweeper():
    """启动扫雷，和视频通话互斥"""
    global in_minesweeper
    with mine_lock:
        if in_minesweeper:
            print("⚠️ 扫雷已经打开")
            return
        if in_video:
            print("⚠️ 正在音视频通话，无法打开扫雷！")
            return
        in_minesweeper = True
        mine_stop_event.clear()
    threading.Thread(target=minesweeper_thread, daemon=True).start()

async def stop_minesweeper():
    """关闭扫雷"""
    global in_minesweeper
    with mine_lock:
        if not in_minesweeper:
            return
        in_minesweeper = False
        mine_stop_event.set()

def render_thread():
    """
    画面渲染独立线程
    读取本地预览队列与远端画面队列，左右拼接分屏，创建窗口展示画面
    按下q键触发挂断音视频通话
    """
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    blank = np.zeros((320, 480, 3), dtype=np.uint8)
    last_remote = blank
    last_local = blank
    while not render_stop_event.is_set():
        if len(frame_queue_remote) > 0:
            last_remote = frame_queue_remote[-1]
        if len(frame_queue_local) > 0:
            last_local = frame_queue_local[-1]
        remote_frame = cv2.resize(last_remote, (480, 320))
        local_frame = cv2.resize(last_local, (480, 320))
        combined = np.hstack([local_frame, remote_frame])
        cv2.imshow(window_name, combined)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("\n⌨️ 按q挂断视频音频")
            if global_loop and global_writer:
                asyncio.run_coroutine_threadsafe(stop_video(global_writer), global_loop)
    cv2.destroyWindow(window_name)

def audio_play_thread():
    """
    音频播放线程，负责播放远端传来的对方语音
    内置声卡回调函数，声卡需要音频数据时自动填充队列中的音频采样
    """
    def audio_out_callback(outdata, frames, time_info, status):
        """音频输出回调函数，声卡驱动自动调用，填充扬声器音频缓冲区"""
        if status:
            print(f"Audio out status: {status}")
        if len(audio_queue_remote) > 0:
            audio_bytes = audio_queue_remote.popleft()
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            outdata[:] = audio_np.reshape(-1, CHANNELS)
        else:
            outdata[:] = np.zeros((frames, CHANNELS), dtype=np.int16)

    stream = sd.OutputStream(
        samplerate=RATE,
        blocksize=CHUNK,
        channels=CHANNELS,
        dtype='int16',
        callback=audio_out_callback
    )
    stream.start()
    while not audio_stop_event.is_set():
        time.sleep(0.01)
    stream.stop()
    stream.close()

def audio_capture_thread(writer, loop):
    """
    音频采集线程，读取本机麦克风声音，将音频片段发送至服务端
    :param writer: 网络连接对象
    :param loop: asyncio事件循环
    """
    def audio_in_callback(indata, frames, time_info, status):
        """音频输入回调函数，声卡驱动自动调用，采集麦克风音频"""
        if status:
            print(f"Audio in status: {status}")
        with video_lock:
            if not in_video:
                return
        audio_bytes = indata.tobytes()
        header = f"AUDIO_FRAME:{len(audio_bytes)}\n".encode()

        async def send_audio():
            """协程任务：将采集到的音频数据发送给服务端"""
            try:
                writer.write(header + audio_bytes)
                await writer.drain()
            except Exception:
                video_stop_event.set()
                render_stop_event.set()
                audio_stop_event.set()
                with video_lock:
                    in_video = False

        asyncio.run_coroutine_threadsafe(send_audio(), loop)

    stream = sd.InputStream(
        samplerate=RATE,
        blocksize=CHUNK,
        channels=CHANNELS,
        dtype='int16',
        callback=audio_in_callback
    )
    stream.start()
    while not audio_stop_event.is_set():
        time.sleep(0.01)
    stream.stop()
    stream.close()

async def receive_loop(reader, writer):
    """
    消息接收协程，持续接收服务端转发的所有数据
    解析消息类型：文本、文件、通话指令、视频帧、音频帧，做对应处理
    :param reader: 网络数据读取对象
    :param writer: 网络数据写入对象
    """
    global in_video
    try:
        while True:
            # 读取消息头部一行，作为协议标识
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

            # ========= 文件接收处理 =========
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

            # ========= 通话控制消息处理 =========
            if line.startswith("CALL_INVITE:"):
                _, inviter = line.split(":", 1)
                print(f"\n📹 {inviter} 发起【音视频】通话邀请，输入 y 接受 / n 拒绝：")
                print("> ", end="", flush=True)
                continue
            if line.startswith("CALL_ACCEPT:"):
                _, user = line.split(":", 1)
                print(f"\n✅ {user} 加入音视频通话")
                print("> ", end="", flush=True)
                continue
            if line.startswith("CALL_REJECT:"):
                _, user = line.split(":", 1)
                print(f"\n❌ {user} 拒绝了音视频邀请")
                print("> ", end="", flush=True)
                continue
            if line.startswith("CALL_HANGUP:"):
                _, user = line.split(":", 1)
                print(f"\n👋 {user} 挂断音视频通话")
                print("> ", end="", flush=True)
                continue

            # ========= 视频帧处理：读取指定长度二进制图像数据 =========
            if line.startswith("VIDEO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)
                with video_lock:
                    if not in_video:
                        # 当前未通话，丢弃这一段二进制数据，防止解析错乱
                        await reader.readexactly(frame_size)
                        continue
                try:
                    frame_data = await reader.readexactly(frame_size)
                except asyncio.IncompleteReadError:
                    continue
                frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    frame_queue_remote.append(frame)
                continue

            # ========= 音频帧处理：读取指定长度二进制音频数据 =========
            if line.startswith("AUDIO_FRAME:"):
                _, frame_size_str = line.split(":", 1)
                frame_size = int(frame_size_str)
                with video_lock:
                    if not in_video:
                        # 当前未通话，丢弃这一段二进制数据，防止解析错乱
                        await reader.readexactly(frame_size)
                        continue
                try:
                    frame_data = await reader.readexactly(frame_size)
                except asyncio.IncompleteReadError:
                    continue
                audio_queue_remote.append(frame_data)
                continue

            # ========= 普通文本消息，直接打印在控制台 =========
            print(f"\n{line}")
            print("> ", end="", flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"\n接收出错: {e}")
    finally:
        # 连接异常，关闭音视频相关线程
        with video_lock:
            if in_video:
                video_stop_event.set()
                render_stop_event.set()
                audio_stop_event.set()
                in_video = False

def video_capture_thread(writer, loop):
    """
    视频采集线程
    读取本机摄像头画面，做镜像翻转；画面存入本地预览队列，压缩后发送给服务端
    :param writer: 网络连接对象
    :param loop: asyncio事件循环
    """
    global cap, in_video, video_stop_event
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("\n❌ 无法打开摄像头")
        with video_lock:
            in_video = False
        return
    print("\n📹 音视频通话已连接，按q关闭窗口或输入/hangup挂断")
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
            frame_queue_local.append(frame.copy())
            # 图像缩放并JPEG压缩，减少网络传输流量
            frame_send = cv2.resize(frame, (480, 320))
            _, jpeg = cv2.imencode('.jpg', frame_send, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frame_bytes = jpeg.tobytes()
            header = f"VIDEO_FRAME:{len(frame_bytes)}\n".encode()

            async def send_frame():
                """协程任务：将压缩后的图像帧发送给服务端"""
                try:
                    writer.write(header + frame_bytes)
                    await writer.drain()
                except Exception:
                    video_stop_event.set()
                    render_stop_event.set()
                    audio_stop_event.set()
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
        print("\n📹 音视频通话已结束")
        print("> ", end="", flush=True)

async def start_video(writer, loop):
    """
    开启音视频通话
    修改通话状态，依次启动视频采集、画面渲染、音频采集、音频播放四个子线程
    :param writer: 网络连接对象
    :param loop: asyncio事件循环
    """
    global in_video, video_stop_event, render_stop_event, audio_stop_event, global_writer, global_loop
    global_writer = writer
    global_loop = loop
    with video_lock:
        if in_video:
            print("⚠️ 已经在音视频通话中")
            return
        in_video = True
        video_stop_event.clear()
        render_stop_event.clear()
        audio_stop_event.clear()
    # 启动4个守护子线程，分别负责视频采集、画面渲染、音频采集、音频播放
    threading.Thread(target=video_capture_thread, args=(writer, loop), daemon=True).start()
    threading.Thread(target=render_thread, daemon=True).start()
    threading.Thread(target=audio_capture_thread, args=(writer, loop), daemon=True).start()
    threading.Thread(target=audio_play_thread, daemon=True).start()

async def stop_video(writer):
    """
    挂断音视频通话
    修改通话状态，设置线程停止事件，向服务端发送挂断通知
    :param writer: 网络连接对象
    """
    global in_video, video_stop_event, render_stop_event, audio_stop_event
    with video_lock:
        if not in_video:
            return
        in_video = False
        video_stop_event.set()
        render_stop_event.set()
        audio_stop_event.set()
    try:
        writer.write(b"CALL_HANGUP:me\n")
        await writer.drain()
    except Exception:
        pass

async def tcp_client(server_ip, port):
    """
    客户端主协程
    建立TCP连接，读取用户控制台输入指令，分发处理文本、文件、音视频通话指令
    :param server_ip: 服务端IP地址
    :param port: 服务端端口号
    """
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
        print("📹 输入 /call 发起【音视频】通话")
        print("💣 输入 /mine 打开扫雷 | /exitmine 关闭扫雷")
        print("❌ 输入 /hangup 挂断 | quit 退出程序")
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
                # 扫雷打开时禁止开视频
                if in_minesweeper:
                    print("⚠️ 正在玩扫雷，不能发起音视频通话")
                    continue
                writer.write(b"CALL_INVITE:me\n")
                await writer.drain()
                await start_video(writer, loop)
                continue
            if msg == '/hangup':
                await stop_video(writer)
                continue
            if msg == '/mine':
                await start_minesweeper()
                continue
            if msg == '/exitmine':
                await stop_minesweeper()
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
        # 退出前，如果正在通话，先挂断音视频
        if in_video:
            await stop_video(writer)
        if in_minesweeper:
            await stop_minesweeper()
        print("正在断开...")
        writer.close()
        await writer.wait_closed()
        recv_task.cancel()
    except ConnectionRefusedError:
        print("❌ 连接失败: 服务端未启动或地址/端口错误")
    except Exception as e:
        print(f"❌ 客户端异常: {e}")

async def send_file(writer, file_path):
    """
    读取本地文件，分块发送文件数据到服务端
    :param writer: 网络连接对象
    :param file_path: 本地待发送文件路径
    """
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
    # 读取命令行参数：服务端IP与端口
    if len(sys.argv) != 3:
        print("用法: python client.py <服务器IP> <端口>")
        print("示例: python client.py 127.0.0.1 8080")
        sys.exit(1)
    server_ip = sys.argv[1]
    port = int(sys.argv[2])
    asyncio.run(tcp_client(server_ip, port))
