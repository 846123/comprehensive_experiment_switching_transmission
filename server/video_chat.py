import asyncio
import json
import socket
from .protocol import (
    pack_msg,
    MSG_TYPE_VIDEO_STATUS,
    VIDEO_STATE_IDLE,
    VIDEO_STATE_CALLING,
    VIDEO_STATE_CHATTING,
    VIDEO_TYPE_AV,
    VIDEO_FRAME_AUDIO,
    VIDEO_FRAME_VIDEO,
    VIDEO_NICK_BYTES,
    VIDEO_PORT_UDP
)
from .connection import ClientManager


class VideoChatRoom:
    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager
        self.state = VIDEO_STATE_IDLE
        self.members = []  # 已接通的成员
        self.udp_addresses = {}  # 昵称 -> UDP地址
        self.udp_socket = None

    async def broadcast_all(self, payload_dict, exclude=None):
        """全员广播信令"""
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_VIDEO_STATUS, payload)
        await self.client_manager.broadcast_all(pkt, exclude)

    async def broadcast_to_members(self, payload_dict, exclude=None):
        """仅通话内成员广播"""
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_VIDEO_STATUS, payload)
        writers = [m["writer"] for m in self.members]
        await self.client_manager.broadcast_to(writers, pkt, exclude)

    def reset(self):
        self.state = VIDEO_STATE_IDLE
        self.members.clear()
        self.udp_addresses.clear()
        print("[视频] 通话房间已重置")

    def get_member_nicks(self):
        return [m["nick"] for m in self.members]

    async def udp_relay(self, port):
        """UDP媒体流中继（视频核心功能，和扫雷完全无关）"""
        loop = asyncio.get_running_loop()
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(("0.0.0.0", port))
        self.udp_socket.setblocking(False)
        print(f"[视频] UDP媒体中继启动，端口：{port}")

        while True:
            try:
                data, addr = await loop.sock_recvfrom(self.udp_socket, 65535)
            except Exception:
                continue
            if len(data) < VIDEO_NICK_BYTES:
                continue

            sender_nick = data[:VIDEO_NICK_BYTES].decode("utf-8").rstrip("\x00")
            self.udp_addresses[sender_nick] = addr

            if self.state != VIDEO_STATE_CHATTING:
                continue

            # 转发给通话内其他所有人
            for member in self.members:
                if member["nick"] == sender_nick:
                    continue
                target_addr = self.udp_addresses.get(member["nick"])
                if target_addr:
                    try:
                        await loop.sock_sendto(self.udp_socket, data, target_addr)
                    except Exception:
                        pass

    async def handle_command(self, data, nick, writer):
        cmd = data.get("cmd")
        print(f"[视频] 收到指令：{cmd} 来自：{nick}")

        if cmd == "call":
            # 发起呼叫：全员振铃
            if self.state == VIDEO_STATE_IDLE:
                self.state = VIDEO_STATE_CALLING
                self.members = [{"nick": nick, "writer": writer, "audio_on": True, "video_on": True}]
            elif self.state in (VIDEO_STATE_CALLING, VIDEO_STATE_CHATTING):
                # 已有通话，直接加入呼叫
                if nick not in self.get_member_nicks():
                    self.members.append({"nick": nick, "writer": writer, "audio_on": True, "video_on": True})

            await self.broadcast_all({
                "cmd": "incoming_call",
                "caller": nick,
                "members": self.get_member_nicks()
            })
            print(f"[视频] {nick} 发起音视频呼叫")

        elif cmd == "accept":
            # 接受呼叫：直接加入通话
            if nick in self.get_member_nicks():
                return
            self.members.append({"nick": nick, "writer": writer, "audio_on": True, "video_on": True})
            self.state = VIDEO_STATE_CHATTING

            await self.broadcast_to_members({
                "cmd": "member_join",
                "nick": nick,
                "members": self.get_member_nicks()
            })
            print(f"[视频] {nick} 加入通话，当前成员：{self.get_member_nicks()}")

        elif cmd == "reject":
            # 拒绝呼叫：不影响其他人
            await self.broadcast_to_members({
                "cmd": "member_reject",
                "nick": nick
            })

        elif cmd == "hangup":
            # 挂断：离开房间
            self.members = [m for m in self.members if m["nick"] != nick]
            if nick in self.udp_addresses:
                del self.udp_addresses[nick]

            if len(self.members) == 0:
                self.reset()
                await self.broadcast_all({"cmd": "call_end"})
                print("[视频] 通话结束，房间已重置")
                return

            await self.broadcast_to_members({
                "cmd": "member_leave",
                "nick": nick,
                "members": self.get_member_nicks()
            })
            if len(self.members) < 2:
                self.state = VIDEO_STATE_CALLING

    async def on_client_leave(self, nickname, writer):
        if self.state == VIDEO_STATE_IDLE:
            return
        # 用户离线自动挂断
        self.members = [m for m in self.members if m["nick"] != nickname]
        if nickname in self.udp_addresses:
            del self.udp_addresses[nickname]

        if len(self.members) == 0:
            self.reset()
            await self.broadcast_all({"cmd": "call_end"})
            return

        await self.broadcast_to_members({
            "cmd": "member_leave",
            "nick": nickname,
            "members": self.get_member_nicks()
        })
        if len(self.members) < 2:
            self.state = VIDEO_STATE_CALLING
