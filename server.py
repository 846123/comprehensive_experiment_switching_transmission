import asyncio
import struct
import json
import random
import uuid

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
MS_WAIT_SEC = 30

ms_room = {
    "state": "idle",
    "inviter": None,
    "inviter_writer": None,
    "players": [],
    "countdown_task": None,
    "mine_map": None,
    "cell_number": None,
    "cell_state": None,
    "current_idx": 0,
    "invite_responses": {},
    "rematch_responses": {},
    "first_click": True,
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
    print("[MS] 房间已重置")


async def broadcast_packet(packet, exclude=None):
    for writer in list(clients.keys()):
        if writer is not exclude:
            try:
                writer.write(packet)
                await writer.drain()
            except Exception as e:
                print(f"[广播] 发送失败: {e}")


async def broadcast_text(text, exclude=None):
    payload = text.encode("utf-8")
    pkt = pack_msg(0, payload)
    await broadcast_packet(pkt, exclude)


# 全局广播（邀请相关用，所有人都能收到）
async def ms_broadcast(payload_dict, exclude=None):
    payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    pkt = pack_msg(4, payload)
    await broadcast_packet(pkt, exclude)


# 仅游戏内玩家广播（棋盘/结算用，未参与者收不到）
async def ms_broadcast_to_players(payload_dict, exclude=None):
    payload = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    pkt = pack_msg(4, payload)
    for player in ms_room["players"]:
        writer = player["writer"]
        if writer is exclude:
            continue
        try:
            writer.write(pkt)
            await writer.drain()
        except Exception as e:
            print(f"[游戏广播] 发送失败: {e}")


async def ms_broadcast_invite_status():
    await ms_broadcast({
        "cmd": "invite_status",
        "responses": ms_room["invite_responses"]
    })


async def ms_broadcast_rematch_status():
    await ms_broadcast_to_players({
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
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < r and 0 <= ny < c and mm[nx][ny]:
                        cnt += 1
            num[x][y] = cnt
    ms_room["mine_map"] = mm
    ms_room["cell_number"] = num
    ms_room["cell_state"] = [[0] * c for _ in range(r)]
    print(f"[MS] 地图生成完成，雷数：{MS_MINES}")


def ms_expand(sx, sy):
    r, c = MS_ROWS, MS_COLS
    stack = [(sx, sy)]
    visited = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        if ms_room["cell_state"][x][y] != 0:
            continue
        ms_room["cell_state"][x][y] = 1
        if ms_room["cell_number"][x][y] == 0:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < r and 0 <= ny < c and not ms_room["mine_map"][nx][ny]:
                        stack.append((nx, ny))


def ms_check_win():
    r, c = MS_ROWS, MS_COLS
    for x in range(r):
        for y in range(c):
            if not ms_room["mine_map"][x][y] and ms_room["cell_state"][x][y] != 1:
                return False
    return True


def ms_get_alive_count():
    return sum(1 for p in ms_room["players"] if p["alive"])


def ms_next_player():
    n = len(ms_room["players"])
    if n == 0:
        return
    start = ms_room["current_idx"]
    for i in range(1, n + 1):
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
            elif s == 2:
                row.append("f")
            elif s == 3:
                row.append("m")
            else:
                row.append(str(ms_room["cell_number"][x][y]))
        cells.append(row)
    players_info = [{"nick": p["nick"], "alive": p["alive"]} for p in ms_room["players"]]
    cur = ms_room["players"][ms_room["current_idx"]]["nick"] if ms_room["players"] else None
    return {
        "cmd": "update",
        "cells": cells,
        "current": cur,
        "players": players_info
    }


async def ms_try_start_game():
    accept_players = [n for n, s in ms_room["invite_responses"].items() if s == "accept"]
    print(f"[MS] 当前接受人数：{len(accept_players)}")
    if len(accept_players) < MS_MIN_PLAYER:
        await ms_broadcast({"cmd": "cancel", "msg": "人数不足，游戏取消"})
        ms_reset()
        return False
    for p in ms_room["players"]:
        p["alive"] = True
        p["score"] = 0
    ms_room["state"] = "gaming"
    ms_room["first_click"] = True
    ms_room["current_idx"] = 0
    await ms_broadcast_to_players({
        "cmd": "start",
        "rows": MS_ROWS,
        "cols": MS_COLS,
        "mine_count": MS_MINES,
        "players": [p["nick"] for p in ms_room["players"]],
        "current": ms_room["players"][0]["nick"]
    })
    print("[MS] 游戏开始")
    return True


async def ms_countdown():
    print(f"[MS] 邀请倒计时开始：{MS_WAIT_SEC}秒")
    await asyncio.sleep(MS_WAIT_SEC)
    if ms_room["state"] != "waiting":
        return
    print("[MS] 邀请倒计时结束")
    if ms_room["countdown_task"]:
        ms_room["countdown_task"] = None
    await ms_try_start_game()


async def ms_end_game():
    ms_room["state"] = "resulting"
    ranked = sorted(ms_room["players"], key=lambda p: p["score"], reverse=True)
    result = [{"nick": p["nick"], "score": p["score"]} for p in ranked]
    await ms_broadcast_to_players({
        "cmd": "game_end",
        "result": result
    })
    ms_room["rematch_responses"] = {p["nick"]: "pending" for p in ms_room["players"]}
    ms_room["countdown_task"] = asyncio.create_task(ms_rematch_countdown())
    print("[MS] 游戏结束，进入结算")


async def ms_rematch_countdown():
    await asyncio.sleep(MS_WAIT_SEC)
    if ms_room["state"] != "resulting":
        return
    if ms_room["countdown_task"]:
        ms_room["countdown_task"] = None
    await ms_try_rematch()


async def ms_try_rematch():
    accept_nicks = [nick for nick, status in ms_room["rematch_responses"].items() if status == "accept"]
    if len(accept_nicks) < MS_MIN_PLAYER:
        await ms_broadcast_to_players({"cmd": "rematch_cancel", "msg": "人数不足，取消再来一局"})
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
    await ms_broadcast_to_players({
        "cmd": "start",
        "rows": MS_ROWS,
        "cols": MS_COLS,
        "mine_count": MS_MINES,
        "players": [p["nick"] for p in ms_room["players"]],
        "current": ms_room["players"][0]["nick"]
    })


async def handle_ms_cmd(data, nick, writer):
    cmd = data.get("cmd")
    print(f"[MS] 收到指令：{cmd} 来自：{nick}")

    if cmd == "invite":
        if ms_room["state"] != "idle":
            await ms_broadcast({"cmd": "busy"})
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
            "cmd": "invite",
            "inviter": nick,
            "max": MS_MAX_PLAYER,
            "min": MS_MIN_PLAYER,
            "players": all_nicks
        })
        print(f"[MS] {nick} 发起了扫雷邀请")

    elif cmd == "accept":
        if ms_room["state"] != "waiting":
            return
        if ms_room["invite_responses"].get(nick) != "pending":
            return
        if len(ms_room["players"]) >= MS_MAX_PLAYER:
            await ms_broadcast({"cmd": "full"})
            return
        ms_room["invite_responses"][nick] = "accept"
        ms_room["players"].append({"nick": nick, "writer": writer, "alive": False, "score": 0})
        await ms_broadcast_invite_status()

        if all(s != "pending" for s in ms_room["invite_responses"].values()):
            print("[MS] 全员响应，提前开局")
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            await ms_try_start_game()

    elif cmd == "reject":
        if ms_room["state"] != "waiting":
            return
        if ms_room["invite_responses"].get(nick) != "pending":
            return
        ms_room["invite_responses"][nick] = "reject"
        await ms_broadcast_invite_status()

        if all(s != "pending" for s in ms_room["invite_responses"].values()):
            print("[MS] 全员响应，尝试开局")
            if ms_room["countdown_task"]:
                ms_room["countdown_task"].cancel()
                ms_room["countdown_task"] = None
            await ms_try_start_game()

    elif cmd == "cancel":
        if ms_room["state"] == "waiting" and ms_room["inviter_writer"] == writer:
            await ms_broadcast({"cmd": "cancel", "msg": "发起人取消了邀请"})
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
        if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < MS_ROWS and 0 <= y < MS_COLS):
            return

        if ms_room["first_click"]:
            ms_gen_map(x, y)
            ms_room["first_click"] = False

        if action == "flag":
            if ms_room["cell_state"][x][y] != 0:
                return
            ms_room["cell_state"][x][y] = 2
            if ms_room["mine_map"][x][y]:
                cur_player["score"] += 1
            else:
                cur_player["score"] -= 1
            ms_next_player()

        elif action == "open":
            if ms_room["cell_state"][x][y] in (1, 2, 3):
                return
            if ms_room["mine_map"][x][y]:
                ms_room["cell_state"][x][y] = 3
                cur_player["alive"] = False
                if ms_get_alive_count() < MS_MIN_PLAYER:
                    await ms_broadcast_to_players(ms_build_update())
                    await ms_end_game()
                    return
                ms_next_player()
            else:
                ms_expand(x, y)
                if ms_check_win():
                    await ms_broadcast_to_players(ms_build_update())
                    await ms_end_game()
                    return
                ms_next_player()

        await ms_broadcast_to_players(ms_build_update())

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
            await ms_try_rematch()

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
            await ms_try_rematch()


# ========== 文件传输模块 ==========
FILE_CHUNK_SIZE = 4096
FILE_ID_LEN = 32

file_transfer_queue = []
current_file_transfer = None
file_transfer_lock = None


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


async def broadcast_file_packet(pkt, exclude_writer=None):
    for writer in list(clients.keys()):
        if writer == exclude_writer:
            continue
        try:
            writer.write(pkt)
            await writer.drain()
        except Exception as e:
            print(f"[文件广播] 发送失败: {e}")


async def process_next_file_transfer():
    global current_file_transfer
    async with file_transfer_lock:
        if current_file_transfer is not None:
            return
        if not file_transfer_queue:
            return
        task = file_transfer_queue.pop(0)
        current_file_transfer = task
        print(f"[FILE] 开始传输文件：{task['filename']} 发送者：{task['sender']}")

    meta_payload = json.dumps({
        "file_id": task["file_id"],
        "sender": task["sender"],
        "filename": task["filename"],
        "file_size": task["file_size"]
    }, ensure_ascii=False).encode('utf-8')
    pkt = pack_msg(5, meta_payload)
    await broadcast_file_packet(pkt, exclude_writer=task["sender_writer"])


async def handle_file_info(payload, sender_nick, sender_writer):
    try:
        info = json.loads(payload.decode('utf-8'))
    except json.JSONDecodeError as e:
        print(f"[文件] 元信息解析失败: {e}")
        return

    file_id = info["file_id"]
    filename = info["filename"]
    file_size = info["file_size"]

    task = {
        "file_id": file_id,
        "sender": sender_nick,
        "sender_writer": sender_writer,
        "filename": filename,
        "file_size": file_size,
        "received_offset": 0
    }
    file_transfer_queue.append(task)
    print(f"[FILE] {sender_nick} 发起文件传输：{filename} ({file_size}字节)，已入队")
    await process_next_file_transfer()


async def handle_file_chunk(payload, sender_writer):
    global current_file_transfer
    if current_file_transfer is None:
        print("[文件] 收到分片但无当前传输，丢弃")
        return

    # 仅校验发送者身份和文件ID
    if current_file_transfer["sender_writer"] != sender_writer:
        print("[文件] 分片发送者不匹配，丢弃")
        return

    try:
        file_id, offset, data = unpack_file_chunk(payload)
    except struct.error as e:
        print(f"[文件] 分片解析失败: {e}")
        return

    if file_id != current_file_transfer["file_id"]:
        print("[文件] 分片文件ID不匹配，丢弃")
        return

    current_file_transfer["received_offset"] = offset + len(data)
    pkt = pack_msg(6, payload)
    await broadcast_file_packet(pkt, exclude_writer=sender_writer)


async def handle_file_end(payload, sender_writer):
    global current_file_transfer
    if current_file_transfer is None:
        return
    if current_file_transfer["sender_writer"] != sender_writer:
        return

    try:
        info = json.loads(payload.decode('utf-8'))
    except json.JSONDecodeError as e:
        print(f"[文件] 结束包解析失败: {e}")
        return
    if info["file_id"] != current_file_transfer["file_id"]:
        return

    print(f"[FILE] 文件传输完成：{current_file_transfer['filename']}")
    pkt = pack_msg(7, payload)
    await broadcast_file_packet(pkt, exclude_writer=sender_writer)

    async with file_transfer_lock:
        current_file_transfer = None
    asyncio.create_task(process_next_file_transfer())


async def abort_current_file_transfer(reason="发送方断开连接"):
    global current_file_transfer
    if current_file_transfer is None:
        return
    end_payload = json.dumps({
        "file_id": current_file_transfer["file_id"],
        "status": "error",
        "msg": reason
    }, ensure_ascii=False).encode('utf-8')
    pkt = pack_msg(7, end_payload)
    await broadcast_file_packet(pkt, exclude_writer=current_file_transfer["sender_writer"])
    print(f"[FILE] 传输中断：{current_file_transfer['filename']} - {reason}")

    async with file_transfer_lock:
        current_file_transfer = None
    asyncio.create_task(process_next_file_transfer())


# ========== 客户端连接处理 ==========
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
    print(f"[连接] {nickname}({ip}:{port}) 已加入")
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
                payload = buffer[8:8 + pl]
                buffer = buffer[8 + pl:]
                if mt == 0:
                    content = payload.decode("utf-8").strip()
                    chat_msg = f"【{nickname}】：{content}"
                    await broadcast_text(chat_msg, exclude=writer)
                elif mt == 4:
                    try:
                        data = json.loads(payload.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    await handle_ms_cmd(data, nickname, writer)
                elif mt == 5:
                    await handle_file_info(payload, nickname, writer)
                elif mt == 6:
                    await handle_file_chunk(payload, writer)
                elif mt == 7:
                    await handle_file_end(payload, writer)
    except Exception as e:
        print(f"[错误] {nickname} 连接异常：{e}")
    finally:
        del clients[writer]
        leave_msg = f"User('{ip}',{port}) {nickname} left"
        await broadcast_text(leave_msg)
        print(f"[连接] {nickname} 已离开")

        # 扫雷状态处理
        if ms_room["state"] in ("waiting", "gaming", "resulting"):
            if ms_room["state"] == "waiting":
                if nickname in ms_room["invite_responses"]:
                    ms_room["invite_responses"][nickname] = "reject"
                    await ms_broadcast_invite_status()
                ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]
                if ms_room["inviter_writer"] == writer:
                    await ms_broadcast({"cmd": "cancel", "msg": "发起人离开，邀请取消"})
                    ms_reset()
                elif all(s != "pending" for s in ms_room["invite_responses"].values()):
                    if ms_room["countdown_task"]:
                        ms_room["countdown_task"].cancel()
                        ms_room["countdown_task"] = None
                    await ms_try_start_game()

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
                        await ms_broadcast_to_players({"cmd": "abort", "msg": "玩家离开，游戏中止"})
                        ms_reset()
                    else:
                        if ms_room["current_idx"] >= len(ms_room["players"]):
                            ms_room["current_idx"] = 0
                        elif ms_room["players"][ms_room["current_idx"]]["writer"] == writer:
                            ms_next_player()
                        await ms_broadcast_to_players(ms_build_update())

            elif ms_room["state"] == "resulting":
                if nickname in ms_room["rematch_responses"]:
                    ms_room["rematch_responses"][nickname] = "reject"
                    await ms_broadcast_rematch_status()
                ms_room["players"] = [p for p in ms_room["players"] if p["writer"] != writer]

        # 文件传输处理
        if current_file_transfer and current_file_transfer["sender_writer"] == writer:
            await abort_current_file_transfer()

        writer.close()
        await writer.wait_closed()


async def main():
    global file_transfer_lock
    file_transfer_lock = asyncio.Lock()
    server = await asyncio.start_server(handle_client, "0.0.0.0", 8080)
    print("Server running on 0.0.0.0:8080")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
