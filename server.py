import asyncio
import os
import struct

# 保存所有在线客户端连接对象，key为客户端连接writer，value为用户昵称
clients = {}
# 参与视频通话的客户端连接集合，仅集合内用户可以收到视频帧数据
video_participants = set()
# 参与音频通话的客户端连接集合，仅集合内用户可以收到音频帧数据
audio_participants = set()

# ========== 数据包打包解包工具 ==========
def pack_msg(msg_type: int, payload: bytes) -> bytes:
    # 包头 8字节: >HIH 大端: 2字节类型,4字节长度,2字节预留
    header = struct.pack(">HIH", msg_type, len(payload), 0)
    return header + payload

def unpack_header(header_bytes: bytes):
    return struct.unpack(">HIH", header_bytes)
# ======================================

async def broadcast_text(text, exclude_writer=None):
    """广播文本消息，打包成数据包发送"""
    payload = text.encode("utf-8")
    data_packet = pack_msg(0, payload)
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                writer.write(data_packet)
                await writer.drain()
            except Exception:
                pass

async def forward_file(reader, file_size, exclude_writer):
    """转发文件给其他客户端【旧逻辑保留，暂时不使用】"""
    remaining = file_size
    chunk_size = 4096
    while remaining > 0:
        chunk = await reader.read(min(chunk_size, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        for writer in list(clients.keys()):
            if writer is not exclude_writer:
                try:
                    writer.write(chunk)
                    await writer.drain()
                except Exception:
                    pass

async def handle_client(reader, writer):
    # 登录阶段：仍然使用readline读取昵称（旧换行协议）
    nickname_raw = await reader.readline()
    if not nickname_raw:
        writer.close()
        await writer.wait_closed()
        return
    nickname = nickname_raw.decode().strip()
    clients[writer] = nickname
    # 获取客户端真实IP与端口
    client_ip, client_port = writer.transport.get_extra_info('peername')
    await broadcast_text(f"用户('{client_ip}', {client_port}) {nickname} joined the chatroom")

    buffer = b""
    try:
        while True:
            # 持续读取字节放入缓冲区
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer += chunk

            # 优先解析包头数据包（新协议）
            while len(buffer) >= 8:
                header_buf = buffer[:8]
                msg_type, payload_len, reserved = unpack_header(header_buf)
                total_packet_len = 8 + payload_len
                if len(buffer) < total_packet_len:
                    # 数据体还没收够，退出内层循环继续读
                    break
                # 取出完整包
                full_packet = buffer[:total_packet_len]
                buffer = buffer[total_packet_len:]
                payload_data = full_packet[8:]

                if msg_type == 0:
                    # 文本消息
                    msg_str = payload_data.decode("utf-8")
                    await broadcast_text(msg_str, exclude_writer=writer)
                else:
                    # 其他类型暂时忽略
                    pass

            # ========= 【临时兼容旧文件协议，测试文本请不要发文件】 =========
            # 警告：新包头协议和旧FILE裸流会冲突，仅保留用于后续迁移，测试文本时禁用文件
            # 这段旧协议解析仅保留，本次调试文本聊天不要使用发送文件功能
            if buffer.find(b"FILE|") == 0:
                line_end = buffer.find(b"\n")
                if line_end != -1:
                    line_bytes = buffer[:line_end+1]
                    buffer = buffer[line_end+1:]
                    msg = line_bytes.decode().strip()
                    if msg.startswith("FILE|"):
                        parts = msg.split("|")
                        _, filename, sz_str = parts
                        file_size = int(sz_str)
                        await broadcast_text(msg, exclude_writer=writer)
                        await forward_file(reader, file_size, exclude_writer=writer)
    except Exception:
        pass
    finally:
        del clients[writer]
        writer.close()
        await writer.wait_closed()
        await broadcast_text(f"用户离开: {nickname}")

async def main():
    # 服务端监听 0.0.0.0:8080
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
