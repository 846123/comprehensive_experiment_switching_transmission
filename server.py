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
MS_WAIT_SEC = 15

ms_room = {
    "state": "idle",          # idle / waiting / gaming
    "inviter": None,
    "inviter_writer": None,
    "players": [],            # [{"nick":xxx, "writer":writer}]
    "countdown_task": None,
    "mine_map": None,
    "cell_number": None,
    "cell_state": None,       # 0 closed /1 open /2 flag
    "current_idx": 0,
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
            else:
                row.append(str(ms_room["cell_number"][x][y]))
        cells.append(row)
    cur = ms_room["players"][ms_room["current_idx"]]["nick"] if ms_room["players"] else None
    return {
        "cmd":"update",
        "cells":cells,
        "current":cur,
        "players":[p["nick"] for p in ms_room["players"]]
    }

async def ms_countdown():
    await asyncio.sleep(MS_WAIT_SEC)
    if ms_room["state"] != "waiting":
        return
    if len(ms_room["players"]) < MS_MIN_PLAYER:
        await ms_broadcast({"cmd":"cancel","msg":"Not enough players"})
        ms_reset()
        return
    ms_room["state"] = "gaming"
    ms_gen_map()
    ms_room["current_idx"] = 0
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
        ms_room["players"] = [{"nick":nick,"writer":writer}]
        ms_room["countdown_task"] = asyncio.create_task(ms_countdown())
        await ms_broadcast({
            "cmd":"invite",
            "inviter":nick,
            "max":MS_MAX_PLAYER,
            "min":MS_MIN_PLAYER
        })
    elif cmd == "accept":
        if ms_room["state"] != "waiting":
            return
        if any(p["nick"] == nick for p in ms_room["players"]):
            return
        if len(ms_room["players"]) >= MS_MAX_PLAYER:
            await ms_broadcast({"cmd":"full"})
            return
        ms_room["players"].append({"nick":nick,"writer":writer})
        await ms_broadcast({
            "cmd":"join",
            "player":nick,
            "players":[p["nick"] for p in ms_room["players"]],
            "count":len(ms_room["players"])
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
        if action == "flag":
            if ms_room["cell_state"][x][y] ==0:
                ms_room["cell_state"][x][y] =2
            elif ms_room["cell_state"][x][y]==2:
                ms_room["cell_state"][x][y]=0
        elif action == "open":
            if ms_room["cell_state"][x][y] in (1,2):
                return
            if ms_room["mine_map"][x][y]:
                mines = [[mx,my] for mx in range(MS_ROWS) for my in range(MS_COLS) if ms_room["mine_map"][mx][my]]
                await ms_broadcast({"cmd":"gameover","loser":nick,"mines":mines})
                ms_reset()
                return
            ms_expand(x,y)
            if ms_check_win():
                await ms_broadcast({"cmd":"win"})
                ms_reset()
                return
            ms_room["current_idx"] = (ms_room["current_idx"]+1) % len(ms_room["players"])
        await ms_broadcast(ms_build_update())

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
        if ms_room["state"] in ("waiting","gaming"):
            before_len = len(ms_room["players"])
            ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]
            after_len = len(ms_room["players"])
            if before_len != after_len:
                if ms_room["state"] == "waiting":
                    await ms_broadcast({
                        "cmd":"leave_wait",
                        "players":[p["nick"] for p in ms_room["players"]],
                        "count":len(ms_room["players"])
                    })
                else:
                    if len(ms_room["players"]) < MS_MIN_PLAYER:
                        await ms_broadcast({"cmd":"abort","msg":"Player left, game aborted"})
                        ms_reset()
                    else:
                        if ms_room["current_idx"] >= len(ms_room["players"]):
                            ms_room["current_idx"] =0
                        await ms_broadcast(ms_build_update())
            if ms_room["inviter_writer"] == writer and ms_room["state"] == "waiting":
                await ms_broadcast({"cmd":"cancel","msg":"Inviter left"})
                ms_reset()
        writer.close()
        await writer.wait_closed()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
