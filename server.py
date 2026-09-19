import asyncio
import os
import struct
import hashlib
import json

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

async def broadcast_packet(packet:bytes, exclude_writer=None):
    """广播完整数据包给全部客户端"""
    for writer in list(clients.keys()):
        if writer is not exclude_writer:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception:
                pass

async def broadcast_text(text, exclude_writer=None):
    """广播文本消息，打包成数据包发送"""
    payload = text.encode("utf-8")
    packet = pack_msg(0, payload)
    await broadcast_packet(packet, exclude_writer)

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
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer += chunk

            # 解析包头数据包
            while len(buffer) >= 8:
                header_buf = buffer[:8]
                msg_type, payload_len, reserved = unpack_header(header_buf)
                total_packet_len = 8 + payload_len
                if len(buffer) < total_packet_len:
                    break
                full_packet = buffer[:total_packet_len]
                buffer = buffer[total_packet_len:]
                payload_data = full_packet[8:]

                if msg_type == 0:
                    # 文本消息
                    msg_str = payload_data.decode("utf-8")
                    await broadcast_text(msg_str, exclude_writer=writer)
                elif msg_type == 1:
                    # 文件元数据包，直接广播给所有人
                    await broadcast_packet(full_packet, exclude_writer=writer)
                elif msg_type == 2:
                    # 文件分片包，直接广播给所有人
                    await broadcast_packet(full_packet, exclude_writer=writer)
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
