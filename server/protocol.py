# -*- coding: utf-8 -*-
# @FileName : protocol.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:18
import struct
import uuid

# 消息类型常量
MSG_TYPE_CHAT = 0
MSG_TYPE_MINESWEEPER = 4
MSG_TYPE_FILE_INFO = 5
MSG_TYPE_FILE_CHUNK = 6
MSG_TYPE_FILE_END = 7

# 文件传输常量
FILE_CHUNK_SIZE = 4096
FILE_ID_LEN = 32

# ========== 音视频通话常量 ==========
MSG_TYPE_VIDEO_INVITE = 8       # 通话邀请指令
MSG_TYPE_VIDEO_REPLY = 9        # 通话应答
MSG_TYPE_VIDEO_STATUS = 10      # 通话状态同步

VIDEO_PORT_UDP = 8081
VIDEO_TYPE_AV = "av"

# 房间状态
VIDEO_STATE_IDLE = "idle"
VIDEO_STATE_INVITING = "inviting"
VIDEO_STATE_CHATTING = "chatting"

# 玩家响应状态
RESPONSE_PENDING = "pending"
RESPONSE_ACCEPT = "accept"
RESPONSE_REJECT = "reject"

# 邀请配置
VIDEO_INVITE_TIMEOUT = 30  # 邀请倒计时30秒
VIDEO_MAX_PLAYERS = 6     # 最大6人
VIDEO_MIN_PLAYERS = 2     # 最少2人

# UDP媒体帧常量
VIDEO_FRAME_AUDIO = 0    # 音频帧
VIDEO_FRAME_VIDEO = 1    # 视频帧
VIDEO_NICK_BYTES = 16   # 昵称固定占16字节


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


def gen_file_id():
    return uuid.uuid4().hex


def pack_file_chunk(file_id, offset, data):
    fid = file_id.ljust(FILE_ID_LEN, '\0').encode('utf-8')
    off = struct.pack('>I', offset)
    return fid + off + data


def unpack_file_chunk(payload):
    file_id = payload[:FILE_ID_LEN].decode('utf-8').rstrip('\0')
    offset = struct.unpack('>I', payload[FILE_ID_LEN:FILE_ID_LEN + 4])[0]
    data = payload[FILE_ID_LEN + 4:]
    return file_id, offset, data
