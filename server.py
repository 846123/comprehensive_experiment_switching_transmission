import asyncio
import os
import struct
import json
import random

clients = {}

# ========== 包头工具 ==========
def pack_msg(msg_type, payload):
    return struct.pack(">HIH", msg_type, len(payload), 0) + payload

def unpack_header(h):
    return struct.unpack(">HIH", h)

# ========== 扫雷房间全局状态 ==========
MS_ROWS, MS_COLS, MS_MINES = 16, 16, 40
MS_MAX_PLAYER = 6
MS_MIN_PLAYER = 2
MS_WAIT_SEC = 30  # 倒计时统一30秒

ms_room = {
    "state": "idle",          # idle / waiting / gaming / resulting
    "inviter": None,
    "inviter_writer": None,
    "players": [],            # [{"nick":xxx, "writer":writer, "alive":bool, "score":int}]
    "countdown_task": None,
    "mine_map": None,
    "cell_number": None,
    "cell_state": None,       # 0 closed /1 open /2 flag /3 mine opened
    "current_idx": 0,
    "invite_responses": {},   # nick -> "pending"/"accept"/"reject"
    "rematch_responses": {},  # nick -> "pending"/"accept"/"reject"
    "first_click": True,      # 首次点击标记，用于首点不踩雷
}

def ms_reset():
    if ms_room["countdown_task"]:
        ms_room["countdown_task"].cancel()
        ms_room["countdown_task"] = None
    ms_room["state"] = "idle"
    ms_room["inviter"] = None
    ms_room["inviter_writer"] = None
    ms_room["players"] = []
    ms_room["mine_map"] = None
    ms_room["cell_number"] = None
    ms_room["cell_state"] = None
    ms_room["current_idx"] = 0
    ms_room["invite_responses"] = {}
    ms_room["rematch_responses"] = {}
    ms_room["first_click"] = True

async def broadcast_packet(packet, exclude=None):
    for w in list(clients.keys()):
        if w is not exclude:
            try:
                w.write(packet)
                await w.drain()
            except Exception:
                pass

# 【修复】去掉末尾\n，不再自带换行，解决joined消息自动换行问题
async def broadcast_text(text, exclude=None):
    payload = text.encode("utf-8")
    pkt = pack_msg(0, payload)
    await broadcast_packet(pkt, exclude)

async def ms_broadcast(payload_dict, exclude=None):
    payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    pkt = pack_msg(4, payload)
    await broadcast_packet(pkt, exclude)

# 广播邀请响应状态
async def ms_broadcast_invite_status():
    await ms_broadcast({
        "cmd": "invite_status",
        "responses": ms_room["invite_responses"]
    })

# 广播再来一局响应状态
async def ms_broadcast_rematch_status():
    await ms_broadcast({
        "cmd": "rematch_status",
        "responses": ms_room["rematch_responses"]
    })

def ms_gen_map(sx=None, sy=None):
    r, c = MS_ROWS, MS_COLS
    mines = set()
    while len(mines) < MS_MINES:
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
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < r and 0 <= ny < c and mm[nx][ny]:
                        cnt +=1
            num[x][y] = cnt
    ms_room["mine_map"] = mm
    ms_room["cell_number"] = num
    ms_room["cell_state"] = [[0]*c for _ in range(r)]

def ms_expand(sx, sy):
    r, c = MS_ROWS, MS_COLS
    stack = [(sx, sy)]
    visited = set()
    while stack:
        x,y = stack.pop()
        if (x,y) in visited:
            continue
        visited.add((x,y))
        if ms_room["cell_state"][x][y] != 0:
            continue
        ms_room["cell_state"][x][y] = 1
        if ms_room["cell_number"][x][y] == 0:
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    nx, ny = x+dx, y+dy
                    if 0 <= nx < r and 0 <= ny < c and not ms_room["mine_map"][nx][ny]:
                        stack.append((nx, ny))

def ms_check_win():
    r,c = MS_ROWS, MS_COLS
    for x in range(r):
        for y in range(c):
            if not ms_room["mine_map"][x][y] and ms_room["cell_state"][x][y] !=1:
                return False
    return True

# 检查是否所有玩家都死亡
def ms_check_all_dead():
    for p in ms_room["players"]:
        if p["alive"]:
            return False
    return True

# 切换到下一个存活玩家
def ms_next_player():
    n = len(ms_room["players"])
    start = ms_room["current_idx"]
    for i in range(1, n+1):
        idx = (start + i) % n
        if ms_room["players"][idx]["alive"]:
            ms_room["current_idx"] = idx
            return
    ms_room["current_idx"] = 0

def ms_build_update():
    cells = []
    for x in range(MS_ROWS):
        row = []
        for y in range(MS_COLS):
            s = ms_room["cell_state"][x][y]
            if s == 0:
                row.append("c")
            elif s ==2:
                row.append("f")
            elif s == 3:
                row.append("m")  # 翻开的地雷
            else:
                row.append(str(ms_room["cell_number"][x][y]))
        cells.append(row)
    players_info = [{"nick": p["nick"], "alive": p["alive"]} for p in ms_room["players"]]
    cur = ms_room["players"][ms_room["current_idx"]]["nick"] if ms_room["players"] else None
    return {
        "cmd":"update",
        "cells":cells,
        "current":cur,
        "players":players_info
    }

# 邀请倒计时
async def ms_countdown():
    await asyncio.sleep(MS_WAIT_SEC)
    if ms_room["state"] != "waiting":
        return
    accept_players = [nick for nick, status in ms_room["invite_responses"].items() if status == "accept"]
    if len(accept_players) < MS_MIN_PLAYER:
        await ms_broadcast({"cmd":"cancel","msg":"Not enough players"})
        ms_reset()
        return
    # 初始化玩家状态
    for p in ms_room["players"]:
        p["alive"] = True
        p["score"] = 0
    ms_room["state"] = "gaming"
    ms_room["first_click"] = True
    ms_room["current_idx"] = 0
    await ms_broadcast({
        "cmd":"start",
        "rows":MS_ROWS,
        "cols":MS_COLS,
        "mine_count":MS_MINES,
        "players":[p["nick"] for p in ms_room["players"]],
        "current":ms_room["players"][0]["nick"]
    })

# 游戏结束进入结算
async def ms_end_game():
    ms_room["state"] = "resulting"
    ranked = sorted(ms_room["players"], key=lambda p: p["score"], reverse=True)
    result = [{"nick": p["nick"], "score": p["score"]} for p in ranked]
    await ms_broadcast({
        "cmd": "game_end",
        "result": result
    })
    ms_room["rematch_responses"] = {p["nick"]: "pending" for p in ms_room["players"]}
    ms_room["countdown_task"] = asyncio.create_task(ms_rematch_countdown())

# 再来一局倒计时
async def ms_rematch_countdown():
    await asyncio.sleep(MS_WAIT_SEC)
    if ms_room["state"] != "resulting":
        return
    accept_nicks = [nick for nick, status in ms_room["rematch_responses"].items() if status == "accept"]
    if len(accept_nicks) < MS_MIN_PLAYER:
        await ms_broadcast({"cmd": "rematch_cancel", "msg": "Not enough players for rematch"})
        ms_reset()
        return
    # 按上一局得分排名排序
    ranked = sorted(ms_room["players"], key=lambda p: p["score"], reverse=True)
    new_players = []
    for p in ranked:
        if p["nick"] in accept_nicks:
            new_players.append({
                "nick": p["nick"],
                "writer": p["writer"],
                "alive": True,
                "score": 0
            })
    ms_room["players"] = new_players
    ms_room["state"] = "gaming"
    ms_room["first_click"] = True
    ms_room["current_idx"] = 0
    ms_room["mine_map"] = None
    ms_room["cell_number"] = None
    ms_room["cell_state"] = None
    await ms_broadcast({
        "cmd":"start",
        "rows":MS_ROWS,
        "cols":MS_COLS,
        "mine_count":MS_MINES,
        "players":[p["nick"] for p in ms_room["players"]],
        "current":ms_room["players"][0]["nick"]
    })

async def handle_ms_cmd(data, nick, writer):
    cmd = data.get("cmd")
    if cmd == "invite":
        if ms_room["state"] != "idle":
            await ms_broadcast({"cmd":"busy"})
            return
        ms_room["state"] = "waiting"
        ms_room["inviter"] = nick
        ms_room["inviter_writer"] = writer
        all_nicks = list(clients.values())
        ms_room["invite_responses"] = {n: "pending" for n in all_nicks}
        ms_room["invite_responses"][nick] = "accept"
        ms_room["players"] = [{"nick": nick, "writer": writer, "alive": False, "score": 0}]
        ms_room["countdown_task"] = asyncio.create_task(ms_countdown())
        await ms_broadcast({
            "cmd":"invite",
            "inviter":nick,
            "max":MS_MAX_PLAYER,
            "min":MS_MIN_PLAYER,
            "players": all_nicks
        })

    elif cmd == "accept":
        if ms_room["state"] != "waiting":
            return
        if ms_room["invite_responses"].get(nick) != "pending":
            return
        if len(ms_room["players"]) >= MS_MAX_PLAYER:
            await ms_broadcast({"cmd":"full"})
            return
        ms_room["invite_responses"][nick] = "accept"
        ms_room["players"].append({"nick": nick, "writer": writer, "alive": False, "score": 0})
        await ms_broadcast_invite_status()
        # 全员响应则提前结束倒计时
        if all(s != "pending" for s in ms_room["invite_responses"].values()):
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            accept_players = [n for n, s in ms_room["invite_responses"].items() if s == "accept"]
            if len(accept_players) < MS_MIN_PLAYER:
                await ms_broadcast({"cmd":"cancel","msg":"Not enough players"})
                ms_reset()
                return
            for p in ms_room["players"]:
                p["alive"] = True
                p["score"] = 0
            ms_room["state"] = "gaming"
            ms_room["first_click"] = True
            ms_room["current_idx"] = 0
            await ms_broadcast({
                "cmd":"start",
                "rows":MS_ROWS,
                "cols":MS_COLS,
                "mine_count":MS_MINES,
                "players":[p["nick"] for p in ms_room["players"]],
                "current":ms_room["players"][0]["nick"]
            })

    elif cmd == "reject":
        if ms_room["state"] != "waiting":
            return
        if ms_room["invite_responses"].get(nick) != "pending":
            return
        ms_room["invite_responses"][nick] = "reject"
        await ms_broadcast_invite_status()
        if all(s != "pending" for s in ms_room["invite_responses"].values()):
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            accept_players = [n for n, s in ms_room["invite_responses"].items() if s == "accept"]
            if len(accept_players) < MS_MIN_PLAYER:
                await ms_broadcast({"cmd":"cancel","msg":"Not enough players"})
                ms_reset()
                return
            for p in ms_room["players"]:
                p["alive"] = True
                p["score"] = 0
            ms_room["state"] = "gaming"
            ms_room["first_click"] = True
            ms_room["current_idx"] = 0
            await ms_broadcast({
                "cmd":"start",
                "rows":MS_ROWS,
                "cols":MS_COLS,
                "mine_count":MS_MINES,
                "players":[p["nick"] for p in ms_room["players"]],
                "current":ms_room["players"][0]["nick"]
            })

    elif cmd == "cancel":
        if ms_room["state"] == "waiting" and ms_room["inviter_writer"] == writer:
            await ms_broadcast({"cmd":"cancel","msg":"Inviter cancelled"})
            ms_reset()

    elif cmd == "click":
        if ms_room["state"] != "gaming":
            return
        cur_player = ms_room["players"][ms_room["current_idx"]]
        if cur_player["nick"] != nick:
            return
        x = data.get("x")
        y = data.get("y")
        action = data.get("action")
        if not (isinstance(x,int) and isinstance(y,int) and 0<=x<MS_ROWS and 0<=y<MS_COLS):
            return

        # 首次操作生成地图，首点及周围无雷
        if ms_room["first_click"]:
            ms_gen_map(x, y)
            ms_room["first_click"] = False

        if action == "flag":
            # 仅未翻开未插旗可插，不可取消
            if ms_room["cell_state"][x][y] != 0:
                return
            ms_room["cell_state"][x][y] = 2
            # 计分：正确+1，错误-1
            if ms_room["mine_map"][x][y]:
                cur_player["score"] += 1
            else:
                cur_player["score"] -= 1
            ms_next_player()

        elif action == "open":
            if ms_room["cell_state"][x][y] in (1, 2, 3):
                return
            # 踩雷：仅当前雷显示，玩家死亡
            if ms_room["mine_map"][x][y]:
                ms_room["cell_state"][x][y] = 3
                cur_player["alive"] = False
                if ms_check_all_dead():
                    await ms_broadcast(ms_build_update())
                    await ms_end_game()
                    return
                ms_next_player()
            else:
                ms_expand(x, y)
                if ms_check_win():
                    await ms_broadcast(ms_build_update())
                    await ms_end_game()
                    return
                ms_next_player()

        await ms_broadcast(ms_build_update())

    elif cmd == "rematch_accept":
        if ms_room["state"] != "resulting":
            return
        if ms_room["rematch_responses"].get(nick) != "pending":
            return
        ms_room["rematch_responses"][nick] = "accept"
        await ms_broadcast_rematch_status()
        if all(s != "pending" for s in ms_room["rematch_responses"].values()):
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            accept_nicks = [n for n, s in ms_room["rematch_responses"].items() if s == "accept"]
            if len(accept_nicks) < MS_MIN_PLAYER:
                await ms_broadcast({"cmd": "rematch_cancel", "msg": "Not enough players for rematch"})
                ms_reset()
                return
            ranked = sorted(ms_room["players"], key=lambda p: p["score"], reverse=True)
            new_players = []
            for p in ranked:
                if p["nick"] in accept_nicks:
                    new_players.append({
                        "nick": p["nick"],
                        "writer": p["writer"],
                        "alive": True,
                        "score": 0
                    })
            ms_room["players"] = new_players
            ms_room["state"] = "gaming"
            ms_room["first_click"] = True
            ms_room["current_idx"] = 0
            ms_room["mine_map"] = None
            ms_room["cell_number"] = None
            ms_room["cell_state"] = None
            await ms_broadcast({
                "cmd":"start",
                "rows":MS_ROWS,
                "cols":MS_COLS,
                "mine_count":MS_MINES,
                "players":[p["nick"] for p in ms_room["players"]],
                "current":ms_room["players"][0]["nick"]
            })

    elif cmd == "rematch_reject":
        if ms_room["state"] != "resulting":
            return
        if ms_room["rematch_responses"].get(nick) != "pending":
            return
        ms_room["rematch_responses"][nick] = "reject"
        await ms_broadcast_rematch_status()
        if all(s != "pending" for s in ms_room["rematch_responses"].values()):
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            accept_nicks = [n for n, s in ms_room["rematch_responses"].items() if s == "accept"]
            if len(accept_nicks) < MS_MIN_PLAYER:
                await ms_broadcast({"cmd": "rematch_cancel", "msg": "Not enough players for rematch"})
                ms_reset()
                return
            ranked = sorted(ms_room["players"], key=lambda p: p["score"], reverse=True)
            new_players = []
            for p in ranked:
                if p["nick"] in accept_nicks:
                    new_players.append({
                        "nick": p["nick"],
                        "writer": p["writer"],
                        "alive": True,
                        "score": 0
                    })
            ms_room["players"] = new_players
            ms_room["state"] = "gaming"
            ms_room["first_click"] = True
            ms_room["current_idx"] = 0
            ms_room["mine_map"] = None
            ms_room["cell_number"] = None
            ms_room["cell_state"] = None
            await ms_broadcast({
                "cmd":"start",
                "rows":MS_ROWS,
                "cols":MS_COLS,
                "mine_count":MS_MINES,
                "players":[p["nick"] for p in ms_room["players"]],
                "current":ms_room["players"][0]["nick"]
            })

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    ip, port = addr
    nickname_raw = await reader.readline()
    if not nickname_raw:
        writer.close()
        await writer.wait_closed()
        return
    nickname = nickname_raw.decode("utf-8").strip()
    if not nickname:
        writer.close()
        await writer.wait_closed()
        return
    clients[writer] = nickname
    join_msg = f"User('{ip}',{port}) {nickname} joined"
    await broadcast_text(join_msg)
    buffer = b""
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer += chunk
            while len(buffer) >= 8:
                hdr = buffer[:8]
                mt, pl, _ = unpack_header(hdr)
                if len(buffer) < 8 + pl:
                    break
                payload = buffer[8:8+pl]
                buffer = buffer[8+pl:]
                if mt == 0:
                    # 文本聊天，exclude=writer，消息不发给发送者本人
                    content = payload.decode("utf-8").strip()
                    chat_msg = f"【{nickname}】：{content}"
                    await broadcast_text(chat_msg, exclude=writer)
                elif mt == 4:
                    try:
                        data = json.loads(payload.decode("utf-8"))
                    except:
                        continue
                    await handle_ms_cmd(data, nickname, writer)
    except Exception:
        pass
    finally:
        del clients[writer]
        leave_msg = f"User('{ip}',{port}) {nickname} left"
        await broadcast_text(leave_msg)
        # 扫雷房间用户下线处理
        if ms_room["state"] in ("waiting", "gaming", "resulting"):
            if ms_room["state"] == "waiting":
                if nickname in ms_room["invite_responses"]:
                    ms_room["invite_responses"][nickname] = "reject"
                    await ms_broadcast_invite_status()
                before_len = len(ms_room["players"])
                ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]
                after_len = len(ms_room["players"])
                if before_len != after_len:
                    await ms_broadcast({
                        "cmd":"leave_wait",
                        "players":[p["nick"] for p in ms_room["players"]],
                        "count":len(ms_room["players"])
                    })
                if ms_room["inviter_writer"] == writer:
                    await ms_broadcast({"cmd":"cancel","msg":"Inviter left"})
                    ms_reset()

            elif ms_room["state"] == "gaming":
                player_left = None
                for p in ms_room["players"]:
                    if p["writer"] == writer:
                        p["alive"] = False
                        player_left = p
                        break
                if player_left:
                    ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]
                    if len(ms_room["players"]) < MS_MIN_PLAYER:
                        await ms_broadcast({"cmd":"abort","msg":"Player left, game aborted"})
                        ms_reset()
                    else:
                        if ms_room["current_idx"] >= len(ms_room["players"]):
                            ms_room["current_idx"] = 0
                        elif ms_room["players"][ms_room["current_idx"]]["writer"] == writer:
                            ms_next_player()
                        await ms_broadcast(ms_build_update())

            elif ms_room["state"] == "resulting":
                if nickname in ms_room["rematch_responses"]:
                    ms_room["rematch_responses"][nickname] = "reject"
                    await ms_broadcast_rematch_status()
                ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]

        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
