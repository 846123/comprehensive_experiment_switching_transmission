# -*- coding: utf-8 -*-
# @FileName : protocol.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:22
import struct

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
MSG_TYPE_VIDEO_INVITE = 8
MSG_TYPE_VIDEO_REPLY = 9
MSG_TYPE_VIDEO_STATUS = 10

VIDEO_PORT_UDP = 8081
VIDEO_TYPE_AV = "av"

# UDP媒体帧常量
VIDEO_FRAME_AUDIO = 0
VIDEO_FRAME_VIDEO = 1
VIDEO_NICK_BYTES = 16
VIDEO_PORT_UDP = 8081


def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload


def unpack_header(h):
    return struct.unpack(">HIH", h)


def pack_file_chunk(file_id, offset, data):
    fid = file_id.ljust(FILE_ID_LEN, '\0').encode('utf-8')
    off = struct.pack('>I', offset)
    return fid + off + data


def unpack_file_chunk(payload):
    file_id = payload[:FILE_ID_LEN].decode('utf-8').rstrip('\0')
    offset = struct.unpack('>I', payload[FILE_ID_LEN:FILE_ID_LEN + 4])[0]
    data = payload[FILE_ID_LEN + 4:]
    return file_id, offset, data
