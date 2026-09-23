import asyncio
import json
import socket
from .protocol import (
    pack_msg,
    MSG_TYPE_VIDEO_STATUS,
    VIDEO_STATE_IDLE,
    VIDEO_STATE_INVITING,
    VIDEO_STATE_CHATTING,
    RESPONSE_PENDING,
    RESPONSE_ACCEPT,
    RESPONSE_REJECT,
    VIDEO_INVITE_TIMEOUT,
    VIDEO_MIN_PLAYERS,
    VIDEO_MAX_PLAYERS,
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
        self.caller = ""
        self.players = {}
        self.chat_members = []
        self.chat_nick_set = set()  # 预存昵称集合，快速查找
        self.udp_addresses = {}
        self.udp_socket = None
        self.countdown_task = None

    async def broadcast_all(self, payload_dict, exclude=None):
        """全员广播信令"""
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_VIDEO_STATUS, payload)
        await self.client_manager.broadcast_all(pkt, exclude)

    async def broadcast_to_chat(self, payload_dict, exclude=None):
        """仅通话内成员广播"""
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_VIDEO_STATUS, payload)
        writers = [m["writer"] for m in self.chat_members]
        await self.client_manager.broadcast_to(writers, pkt, exclude)

    def reset(self):
        """重置房间状态"""
        self.state = VIDEO_STATE_IDLE
        self.caller = ""
        self.players.clear()
        self.chat_members.clear()
        self.chat_nick_set.clear()
        self.udp_addresses.clear()
        if self.countdown_task:
            self.countdown_task.cancel()
            self.countdown_task = None
        print("[视频] 房间已重置")

    def _get_all_players(self):
        """获取当前所有在线玩家列表"""
        return self.client_manager.all_nicks()

    async def _start_countdown(self):
        """启动倒计时协程"""
        try:
            await asyncio.sleep(VIDEO_INVITE_TIMEOUT)
            await self._settle_invite()
        except asyncio.CancelledError:
            pass

    async def _settle_invite(self):
        """结算邀请：统计接受人数，决定是否开启通话"""
        if self.state != VIDEO_STATE_INVITING:
            return

        accept_players = [nick for nick, status in self.players.items() if status == RESPONSE_ACCEPT]
        accept_count = len(accept_players)

        if VIDEO_MIN_PLAYERS <= accept_count <= VIDEO_MAX_PLAYERS:
            # 满足人数要求，进入通话
            self.state = VIDEO_STATE_CHATTING
            self.chat_members = []
            self.chat_nick_set = set(accept_players)
            all_clients = self.client_manager.clients
            for nick in accept_players:
                for writer, name in all_clients.items():
                    if name == nick:
                        self.chat_members.append({"nick": nick, "writer": writer})
                        break
            # 广播开始通话
            await self.broadcast_all({
                "cmd": "start",
                "players": accept_players
            })
            print(f"[视频] 通话开始，成员：{accept_players}")
        else:
            # 人数不足，取消邀请
            await self.broadcast_all({
                "cmd": "cancel",
                "msg": f"接受人数不足{VIDEO_MIN_PLAYERS}人，邀请已取消"
            })
            print(f"[视频] 邀请取消，接受人数：{accept_count}")
            self.reset()

    async def udp_relay(self, port):
        """UDP媒体流中继（批量转发优化版）"""
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

            # 非通话状态直接丢弃
            if self.state != VIDEO_STATE_CHATTING:
                continue
            if sender_nick not in self.chat_nick_set:
                continue

            # 预构建目标列表，批量转发
            targets = []
            for nick in self.chat_nick_set:
                if nick == sender_nick:
                    continue
                target_addr = self.udp_addresses.get(nick)
                if target_addr:
                    targets.append(target_addr)

            # 批量发送，减少循环开销
            for target in targets:
                try:
                    await loop.sock_sendto(self.udp_socket, data, target)
                except Exception:
                    continue

    async def handle_command(self, data, nick, writer):
        cmd = data.get("cmd")
        print(f"[视频] 收到指令：{cmd} 来自：{nick}")

        if cmd == "invite":
            # 发起邀请
            if self.state != VIDEO_STATE_IDLE:
                pkt = pack_msg(MSG_TYPE_VIDEO_STATUS, json.dumps({
                    "cmd": "busy",
                    "msg": "当前已有视频通话进行中"
                }).encode("utf-8"))
                try:
                    writer.write(pkt)
                    await writer.drain()
                except Exception:
                    pass
                return

            self.state = VIDEO_STATE_INVITING
            self.caller = nick
            all_nicks = self._get_all_players()
            self.players = {n: RESPONSE_PENDING for n in all_nicks}
            self.players[nick] = RESPONSE_ACCEPT

            self.countdown_task = asyncio.create_task(self._start_countdown())

            await self.broadcast_all({
                "cmd": "invite",
                "inviter": nick,
                "players": self.players,
                "time_left": VIDEO_INVITE_TIMEOUT
            })
            print(f"[视频] {nick} 发起视频邀请，在线人数：{len(all_nicks)}")

        elif cmd == "accept":
            if self.state != VIDEO_STATE_INVITING:
                return
            if nick not in self.players:
                return
            if self.players[nick] != RESPONSE_PENDING:
                return

            self.players[nick] = RESPONSE_ACCEPT
            await self.broadcast_all({
                "cmd": "invite_status",
                "responses": self.players
            })

            if all(s != RESPONSE_PENDING for s in self.players.values()):
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self._settle_invite()

        elif cmd == "reject":
            if self.state != VIDEO_STATE_INVITING:
                return
            if nick not in self.players:
                return
            if self.players[nick] != RESPONSE_PENDING:
                return

            self.players[nick] = RESPONSE_REJECT
            await self.broadcast_all({
                "cmd": "invite_status",
                "responses": self.players
            })

            if all(s != RESPONSE_PENDING for s in self.players.values()):
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self._settle_invite()

        elif cmd == "cancel":
            if self.state != VIDEO_STATE_INVITING:
                return
            if nick != self.caller:
                return

            await self.broadcast_all({
                "cmd": "cancel",
                "msg": "发起人已取消邀请"
            })
            print(f"[视频] {nick} 取消了视频邀请")
            self.reset()

        elif cmd == "mute":
            # 麦克风静音
            if self.state != VIDEO_STATE_CHATTING:
                return
            if nick not in self.chat_nick_set:
                return
            await self.broadcast_to_chat({
                "cmd": "mute_status",
                "nick": nick,
                "muted": True
            })

        elif cmd == "unmute":
            # 取消麦克风静音
            if self.state != VIDEO_STATE_CHATTING:
                return
            if nick not in self.chat_nick_set:
                return
            await self.broadcast_to_chat({
                "cmd": "mute_status",
                "nick": nick,
                "muted": False
            })

        elif cmd == "speaker_mute":
            # 听筒静音
            if self.state != VIDEO_STATE_CHATTING:
                return
            if nick not in self.chat_nick_set:
                return
            await self.broadcast_to_chat({
                "cmd": "speaker_mute_status",
                "nick": nick,
                "muted": True
            })

        elif cmd == "speaker_unmute":
            # 取消听筒静音
            if self.state != VIDEO_STATE_CHATTING:
                return
            if nick not in self.chat_nick_set:
                return
            await self.broadcast_to_chat({
                "cmd": "speaker_mute_status",
                "nick": nick,
                "muted": False
            })

        elif cmd == "hangup":
            if self.state != VIDEO_STATE_CHATTING:
                return

            self.chat_members = [m for m in self.chat_members if m["nick"] != nick]
            self.chat_nick_set.discard(nick)
            if nick in self.udp_addresses:
                del self.udp_addresses[nick]

            if len(self.chat_members) < VIDEO_MIN_PLAYERS:
                await self.broadcast_all({
                    "cmd": "call_end",
                    "msg": "通话人数不足，已结束"
                })
                print("[视频] 通话结束，人数不足")
                self.reset()
            else:
                await self.broadcast_to_chat({
                    "cmd": "member_leave",
                    "nick": nick,
                    "players": list(self.chat_nick_set)
                })


    async def on_client_leave(self, nickname, writer):
        if self.state == VIDEO_STATE_IDLE:
            return

        if self.state == VIDEO_STATE_INVITING:
            if nickname in self.players and self.players[nickname] == RESPONSE_PENDING:
                self.players[nickname] = RESPONSE_REJECT
                await self.broadcast_all({
                    "cmd": "invite_status",
                    "responses": self.players
                })
                if all(s != RESPONSE_PENDING for s in self.players.values()):
                    if self.countdown_task:
                        self.countdown_task.cancel()
                        self.countdown_task = None
                    await self._settle_invite()

        elif self.state == VIDEO_STATE_CHATTING:
            self.chat_members = [m for m in self.chat_members if m["nick"] != nickname]
            self.chat_nick_set.discard(nickname)
            if nickname in self.udp_addresses:
                del self.udp_addresses[nickname]

            if len(self.chat_members) < VIDEO_MIN_PLAYERS:
                await self.broadcast_all({
                    "cmd": "call_end",
                    "msg": "通话人数不足，已结束"
                })
                self.reset()
            else:
                await self.broadcast_to_chat({
                    "cmd": "member_leave",
                    "nick": nickname,
                    "players": list(self.chat_nick_set)
                })
