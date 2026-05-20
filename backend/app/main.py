import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.room import room, Role
from app.game import Game, GamePhase
from app.protocol import (
    parse_incoming,
    JoinGameMsg, LeaveGameMsg, StartGameMsg, PingMsg,
    SwapAllMsg, SwapOneMsg, PassTurnMsg, StandMsg, NewGameMsg,
    PongMsg, ErrorMsg,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ────────────────────────────────────────────────────────────

async def _broadcast_game(include_showdown: bool = False) -> None:
    """Broadcast public game state and send each player their private hand."""
    g = room.game
    if g is None:
        return

    public = g.public_state()
    pub_json = json.dumps(public)

    for conn in room._connections.values():
        # Add personal valid_actions to the public payload before sending
        personal = {**public, "valid_actions": g.valid_actions(conn.nickname)}
        await conn.websocket.send_text(json.dumps(personal))

    # Send private hands to playing players
    for nick in room.playing:
        hand = g.get_hand(nick)
        await room.send_to(nick, {"type": "hand", "cards": [c.to_dict() for c in hand]})

    # If showdown just triggered, broadcast the result
    if include_showdown and g.phase == GamePhase.SHOWDOWN:
        showdown_json = json.dumps(g.showdown_result())
        for conn in room._connections.values():
            await conn.websocket.send_text(showdown_json)


# ── Lobby handlers ─────────────────────────────────────────────────────

async def handle_join_game(nickname: str, _msg: JoinGameMsg, ws: WebSocket) -> None:
    ok, error = room.join(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await room.broadcast_room_state()


async def handle_leave_game(nickname: str, _msg: LeaveGameMsg, ws: WebSocket) -> None:
    ok, error = room.leave_waiting(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await room.broadcast_room_state()


async def handle_start_game(nickname: str, _msg: StartGameMsg, ws: WebSocket) -> None:
    ok, error = room.start_game(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
        return

    # Create game and run order determination + deal
    g = Game(room.playing)
    g.determine_order()
    g.deal()
    room.game = g

    # Broadcast order result to all
    order_json = json.dumps(g.order_result())
    for conn in room._connections.values():
        await conn.websocket.send_text(order_json)

    # Broadcast room state + game state + private hands
    await room.broadcast_room_state()
    await _broadcast_game()


async def handle_ping(_nickname: str, _msg: PingMsg, ws: WebSocket) -> None:
    await ws.send_text(PongMsg().model_dump_json())


# ── Game action handlers ───────────────────────────────────────────────

async def handle_swap_all(nickname: str, _msg: SwapAllMsg, ws: WebSocket) -> None:
    g = room.game
    if g is None:
        await ws.send_text(ErrorMsg(message="No hay partida en curso.").model_dump_json())
        return
    ok, error = g.apply_swap_all(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await _broadcast_game(include_showdown=True)


async def handle_swap_one(nickname: str, msg: SwapOneMsg, ws: WebSocket) -> None:
    g = room.game
    if g is None:
        await ws.send_text(ErrorMsg(message="No hay partida en curso.").model_dump_json())
        return
    ok, error = g.apply_swap_one(nickname, msg.hand_card_id, msg.table_card_id)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await _broadcast_game(include_showdown=True)


async def handle_pass_turn(nickname: str, _msg: PassTurnMsg, ws: WebSocket) -> None:
    g = room.game
    if g is None:
        await ws.send_text(ErrorMsg(message="No hay partida en curso.").model_dump_json())
        return
    ok, error = g.apply_pass(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await _broadcast_game(include_showdown=True)


async def handle_stand(nickname: str, _msg: StandMsg, ws: WebSocket) -> None:
    g = room.game
    if g is None:
        await ws.send_text(ErrorMsg(message="No hay partida en curso.").model_dump_json())
        return
    ok, error = g.apply_stand(nickname)
    if not ok:
        await ws.send_text(ErrorMsg(message=error).model_dump_json())
    else:
        await _broadcast_game(include_showdown=True)


async def handle_new_game(nickname: str, _msg: NewGameMsg, ws: WebSocket) -> None:
    g = room.game
    if g is None or g.phase != GamePhase.SHOWDOWN:
        await ws.send_text(ErrorMsg(message="Solo se puede reiniciar tras el showdown.").model_dump_json())
        return
    conn = room._connections.get(nickname)
    if conn is None or conn.role not in (Role.PLAYING, Role.WAITING):
        await ws.send_text(ErrorMsg(message="Solo los jugadores pueden reiniciar la partida.").model_dump_json())
        return
    room.end_game()
    await room.broadcast_room_state()


# ── Handler registry ───────────────────────────────────────────────────

HANDLERS = {
    "join_game":  handle_join_game,
    "leave_game": handle_leave_game,
    "start_game": handle_start_game,
    "ping":       handle_ping,
    "swap_all":   handle_swap_all,
    "swap_one":   handle_swap_one,
    "pass_turn":  handle_pass_turn,
    "stand":      handle_stand,
    "new_game":   handle_new_game,
}


# ── WebSocket endpoint ─────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    # First message must be a valid "join"
    try:
        raw = await websocket.receive_text()
        msg = parse_incoming(raw)
    except ValueError as exc:
        await websocket.send_text(ErrorMsg(message=str(exc)).model_dump_json())
        await websocket.close()
        return

    if msg.type != "join" or not msg.nickname.strip():
        await websocket.send_text(
            ErrorMsg(message="El primer mensaje debe ser {type:'join', nickname:'...'}.").model_dump_json()
        )
        await websocket.close()
        return

    nickname = msg.nickname.strip()
    ok, error = room.connect(websocket, nickname)
    if not ok:
        await websocket.send_text(ErrorMsg(message=error).model_dump_json())
        await websocket.close()
        return

    await room.broadcast_room_state()

    # Send current game state to anyone joining mid-game
    if room.game is not None:
        personal = {**room.game.public_state(), "valid_actions": room.game.valid_actions(nickname)}
        await websocket.send_text(json.dumps(personal))
        # If reconnecting as a player, also send their private hand
        if room.is_reconnect(nickname):
            hand = room.game.get_hand(nickname)
            await websocket.send_text(json.dumps({"type": "hand", "cards": [c.to_dict() for c in hand]}))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                incoming = parse_incoming(raw)
            except ValueError as exc:
                await websocket.send_text(ErrorMsg(message=str(exc)).model_dump_json())
                continue

            if incoming.type == "join":
                await websocket.send_text(ErrorMsg(message="Ya estás conectado.").model_dump_json())
                continue

            handler = HANDLERS.get(incoming.type)
            if handler:
                await handler(nickname, incoming, websocket)

    except WebSocketDisconnect:
        room.disconnect(nickname)
        await room.broadcast_room_state()
    except Exception:
        room.disconnect(nickname)
        await room.broadcast_room_state()
