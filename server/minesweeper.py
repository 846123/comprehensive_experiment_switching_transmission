# -*- coding: utf-8 -*-
# @FileName : minesweeper.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/21 22:19
import asyncio
import json
import random
from .protocol import pack_msg, MSG_TYPE_MINESWEEPER
from .connection import ClientManager


class MinesweeperRoom:
    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager

        # 常量配置
        self.MS_ROWS = 16
        self.MS_COLS = 16
        self.MS_MINES = 40
        self.MS_MAX_PLAYER = 6
        self.MS_MIN_PLAYER = 2
        self.MS_WAIT_SEC = 30

        # 房间状态
        self.state = "idle"
        self.inviter = None
        self.inviter_writer = None
        self.players = []
        self.countdown_task = None
        self.mine_map = None
        self.cell_number = None
        self.cell_state = None
        self.current_idx = 0
        self.invite_responses = {}
        self.rematch_responses = {}
        self.first_click = True

    async def broadcast_all(self, payload_dict, exclude=None):
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_MINESWEEPER, payload)
        await self.client_manager.broadcast_all(pkt, exclude)

    async def broadcast_to_players(self, payload_dict, exclude=None):
        payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        pkt = pack_msg(MSG_TYPE_MINESWEEPER, payload)
        writers = [p["writer"] for p in self.players]
        await self.client_manager.broadcast_to(writers, pkt, exclude)

    async def broadcast_invite_status(self):
        await self.broadcast_all({
            "cmd": "invite_status",
            "responses": self.invite_responses
        })

    async def broadcast_rematch_status(self):
        await self.broadcast_to_players({
            "cmd": "rematch_status",
            "responses": self.rematch_responses
        })

    def reset(self):
        if self.countdown_task:
            self.countdown_task.cancel()
            self.countdown_task = None
        self.state = "idle"
        self.inviter = None
        self.inviter_writer = None
        self.players = []
        self.mine_map = None
        self.cell_number = None
        self.cell_state = None
        self.current_idx = 0
        self.invite_responses = {}
        self.rematch_responses = {}
        self.first_click = True
        print("[MS] 房间已重置")

    def gen_map(self, sx=None, sy=None):
        r, c = self.MS_ROWS, self.MS_COLS
        mines = set()
        while len(mines) < self.MS_MINES:
            x = random.randint(0, r - 1)
            y = random.randint(0, c - 1)
            if sx is not None and abs(x - sx) <= 1 and abs(y - sy) <= 1:
                continue
            mines.add((x, y))

        mm = [[False] * c for _ in range(r)]
        for x, y in mines:
            mm[x][y] = True

        num = [[0] * c for _ in range(r)]
        for x in range(r):
            for y in range(c):
                if mm[x][y]:
                    continue
                cnt = 0
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < r and 0 <= ny < c and mm[nx][ny]:
                            cnt += 1
                num[x][y] = cnt

        self.mine_map = mm
        self.cell_number = num
        self.cell_state = [[0] * c for _ in range(r)]
        print(f"[MS] 地图生成完成，雷数：{self.MS_MINES}")

    def expand(self, sx, sy):
        r, c = self.MS_ROWS, self.MS_COLS
        stack = [(sx, sy)]
        visited = set()
        while stack:
            x, y = stack.pop()
            if (x, y) in visited:
                continue
            visited.add((x, y))
            if self.cell_state[x][y] != 0:
                continue
            self.cell_state[x][y] = 1
            if self.cell_number[x][y] == 0:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < r and 0 <= ny < c and not self.mine_map[nx][ny]:
                            stack.append((nx, ny))

    def check_win(self):
        r, c = self.MS_ROWS, self.MS_COLS
        for x in range(r):
            for y in range(c):
                if not self.mine_map[x][y] and self.cell_state[x][y] != 1:
                    return False
        return True

    def get_alive_count(self):
        return sum(1 for p in self.players if p["alive"])

    def next_player(self):
        n = len(self.players)
        if n == 0:
            return
        start = self.current_idx
        for i in range(1, n + 1):
            idx = (start + i) % n
            if self.players[idx]["alive"]:
                self.current_idx = idx
                return
        self.current_idx = 0

    def build_update(self):
        cells = []
        for x in range(self.MS_ROWS):
            row = []
            for y in range(self.MS_COLS):
                s = self.cell_state[x][y]
                if s == 0:
                    row.append("c")
                elif s == 2:
                    row.append("f")
                elif s == 3:
                    row.append("m")
                else:
                    row.append(str(self.cell_number[x][y]))
            cells.append(row)
        players_info = [{"nick": p["nick"], "alive": p["alive"]} for p in self.players]
        cur = self.players[self.current_idx]["nick"] if self.players else None
        return {
            "cmd": "update",
            "cells": cells,
            "current": cur,
            "players": players_info
        }

    async def try_start_game(self):
        accept_players = [n for n, s in self.invite_responses.items() if s == "accept"]
        print(f"[MS] 当前接受人数：{len(accept_players)}")
        if len(accept_players) < self.MS_MIN_PLAYER:
            await self.broadcast_all({"cmd": "cancel", "msg": "人数不足，游戏取消"})
            self.reset()
            return False

        for p in self.players:
            p["alive"] = True
            p["score"] = 0
        self.state = "gaming"
        self.first_click = True
        self.current_idx = 0

        await self.broadcast_to_players({
            "cmd": "start",
            "rows": self.MS_ROWS,
            "cols": self.MS_COLS,
            "mine_count": self.MS_MINES,
            "players": [p["nick"] for p in self.players],
            "current": self.players[0]["nick"]
        })
        print("[MS] 游戏开始")
        return True

    async def countdown(self):
        print(f"[MS] 邀请倒计时开始：{self.MS_WAIT_SEC}秒")
        await asyncio.sleep(self.MS_WAIT_SEC)
        if self.state != "waiting":
            return
        print("[MS] 邀请倒计时结束")
        if self.countdown_task:
            self.countdown_task = None
        await self.try_start_game()

    async def end_game(self):
        self.state = "resulting"
        ranked = sorted(self.players, key=lambda p: p["score"], reverse=True)
        result = [{"nick": p["nick"], "score": p["score"]} for p in ranked]

        await self.broadcast_to_players({
            "cmd": "game_end",
            "result": result
        })
        self.rematch_responses = {p["nick"]: "pending" for p in self.players}
        self.countdown_task = asyncio.create_task(self.rematch_countdown())
        print("[MS] 游戏结束，进入结算")

    async def rematch_countdown(self):
        await asyncio.sleep(self.MS_WAIT_SEC)
        if self.state != "resulting":
            return
        if self.countdown_task:
            self.countdown_task = None
        await self.try_rematch()

    async def try_rematch(self):
        accept_nicks = [nick for nick, status in self.rematch_responses.items() if status == "accept"]
        if len(accept_nicks) < self.MS_MIN_PLAYER:
            await self.broadcast_to_players({"cmd": "rematch_cancel", "msg": "人数不足，取消再来一局"})
            self.reset()
            return

        ranked = sorted(self.players, key=lambda p: p["score"], reverse=True)
        new_players = []
        for p in ranked:
            if p["nick"] in accept_nicks:
                new_players.append({
                    "nick": p["nick"],
                    "writer": p["writer"],
                    "alive": True,
                    "score": 0
                })
        self.players = new_players
        self.state = "gaming"
        self.first_click = True
        self.current_idx = 0
        self.mine_map = None
        self.cell_number = None
        self.cell_state = None

        await self.broadcast_to_players({
            "cmd": "start",
            "rows": self.MS_ROWS,
            "cols": self.MS_COLS,
            "mine_count": self.MS_MINES,
            "players": [p["nick"] for p in self.players],
            "current": self.players[0]["nick"]
        })

    async def handle_command(self, data, nick, writer):
        cmd = data.get("cmd")
        print(f"[MS] 收到指令：{cmd} 来自：{nick}")

        if cmd == "invite":
            if self.state != "idle":
                await self.broadcast_all({"cmd": "busy"})
                return
            self.state = "waiting"
            self.inviter = nick
            self.inviter_writer = writer
            all_nicks = self.client_manager.all_nicks()
            self.invite_responses = {n: "pending" for n in all_nicks}
            self.invite_responses[nick] = "accept"
            self.players = [{"nick": nick, "writer": writer, "alive": False, "score": 0}]
            self.countdown_task = asyncio.create_task(self.countdown())
            await self.broadcast_all({
                "cmd": "invite",
                "inviter": nick,
                "max": self.MS_MAX_PLAYER,
                "min": self.MS_MIN_PLAYER,
                "players": all_nicks
            })
            print(f"[MS] {nick} 发起了扫雷邀请")

        elif cmd == "accept":
            if self.state != "waiting":
                return
            if self.invite_responses.get(nick) != "pending":
                return
            if len(self.players) >= self.MS_MAX_PLAYER:
                await self.broadcast_all({"cmd": "full"})
                return
            self.invite_responses[nick] = "accept"
            self.players.append({"nick": nick, "writer": writer, "alive": False, "score": 0})
            await self.broadcast_invite_status()

            if all(s != "pending" for s in self.invite_responses.values()):
                print("[MS] 全员响应，提前开局")
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self.try_start_game()

        elif cmd == "reject":
            if self.state != "waiting":
                return
            if self.invite_responses.get(nick) != "pending":
                return
            self.invite_responses[nick] = "reject"
            await self.broadcast_invite_status()

            if all(s != "pending" for s in self.invite_responses.values()):
                print("[MS] 全员响应，尝试开局")
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self.try_start_game()

        elif cmd == "cancel":
            if self.state == "waiting" and self.inviter_writer == writer:
                await self.broadcast_all({"cmd": "cancel", "msg": "发起人取消了邀请"})
                self.reset()

        elif cmd == "click":
            if self.state != "gaming":
                return
            cur_player = self.players[self.current_idx]
            if cur_player["nick"] != nick:
                return
            x = data.get("x")
            y = data.get("y")
            action = data.get("action")
            if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < self.MS_ROWS and 0 <= y < self.MS_COLS):
                return

            if self.first_click:
                self.gen_map(x, y)
                self.first_click = False

            if action == "flag":
                if self.cell_state[x][y] != 0:
                    return
                self.cell_state[x][y] = 2
                if self.mine_map[x][y]:
                    cur_player["score"] += 1
                else:
                    cur_player["score"] -= 1
                self.next_player()

            elif action == "open":
                if self.cell_state[x][y] in (1, 2, 3):
                    return
                if self.mine_map[x][y]:
                    self.cell_state[x][y] = 3
                    cur_player["alive"] = False
                    if self.get_alive_count() < self.MS_MIN_PLAYER:
                        await self.broadcast_to_players(self.build_update())
                        await self.end_game()
                        return
                    self.next_player()
                else:
                    self.expand(x, y)
                    if self.check_win():
                        await self.broadcast_to_players(self.build_update())
                        await self.end_game()
                        return
                    self.next_player()

            await self.broadcast_to_players(self.build_update())

        elif cmd == "rematch_accept":
            if self.state != "resulting":
                return
            if self.rematch_responses.get(nick) != "pending":
                return
            self.rematch_responses[nick] = "accept"
            await self.broadcast_rematch_status()
            if all(s != "pending" for s in self.rematch_responses.values()):
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self.try_rematch()

        elif cmd == "rematch_reject":
            if self.state != "resulting":
                return
            if self.rematch_responses.get(nick) != "pending":
                return
            self.rematch_responses[nick] = "reject"
            await self.broadcast_rematch_status()
            if all(s != "pending" for s in self.rematch_responses.values()):
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self.try_rematch()

    async def on_client_leave(self, nickname, writer):
        if self.state not in ("waiting", "gaming", "resulting"):
            return

        if self.state == "waiting":
            if nickname in self.invite_responses:
                self.invite_responses[nickname] = "reject"
                await self.broadcast_invite_status()
            self.players = [p for p in self.players if p["writer"] != writer]
            if self.inviter_writer == writer:
                await self.broadcast_all({"cmd": "cancel", "msg": "发起人离开，邀请取消"})
                self.reset()
            elif all(s != "pending" for s in self.invite_responses.values()):
                if self.countdown_task:
                    self.countdown_task.cancel()
                    self.countdown_task = None
                await self.try_start_game()

        elif self.state == "gaming":
            player_left = None
            for p in self.players:
                if p["writer"] == writer:
                    p["alive"] = False
                    player_left = p
                    break
            if player_left:
                self.players = [p for p in self.players if p["writer"] != writer]
                if len(self.players) < self.MS_MIN_PLAYER:
                    await self.broadcast_to_players({"cmd": "abort", "msg": "玩家离开，游戏中止"})
                    self.reset()
                else:
                    if self.current_idx >= len(self.players):
                        self.current_idx = 0
                    elif self.players[self.current_idx]["writer"] == writer:
                        self.next_player()
                    await self.broadcast_to_players(self.build_update())

        elif self.state == "resulting":
            if nickname in self.rematch_responses:
                self.rematch_responses[nickname] = "reject"
                await self.broadcast_rematch_status()
            self.players = [p for p in self.players if p["writer"] != writer]
