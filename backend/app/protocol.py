import json
from typing import Literal, Union, Annotated
from pydantic import BaseModel, Field, ValidationError, TypeAdapter


# ── Incoming messages (client → server) ───────────────────────────────

class JoinMsg(BaseModel):
    type: Literal["join"]
    nickname: str

class JoinGameMsg(BaseModel):
    type: Literal["join_game"]

class LeaveGameMsg(BaseModel):
    type: Literal["leave_game"]

class StartGameMsg(BaseModel):
    type: Literal["start_game"]

class PingMsg(BaseModel):
    type: Literal["ping"]

class SwapAllMsg(BaseModel):
    type: Literal["swap_all"]

class SwapOneMsg(BaseModel):
    type: Literal["swap_one"]
    hand_card_id:  str
    table_card_id: str

class PassTurnMsg(BaseModel):
    type: Literal["pass_turn"]

class StandMsg(BaseModel):
    type: Literal["stand"]

class NewGameMsg(BaseModel):
    type: Literal["new_game"]


IncomingMessage = Annotated[
    Union[
        JoinMsg, JoinGameMsg, LeaveGameMsg, StartGameMsg, PingMsg,
        SwapAllMsg, SwapOneMsg, PassTurnMsg, StandMsg, NewGameMsg,
    ],
    Field(discriminator="type"),
]

_KNOWN_TYPES = {
    "join", "join_game", "leave_game", "start_game", "ping",
    "swap_all", "swap_one", "pass_turn", "stand", "new_game",
}

_adapter: TypeAdapter[IncomingMessage] = TypeAdapter(IncomingMessage)


# ── Outgoing messages (server → client) ───────────────────────────────

class PongMsg(BaseModel):
    type: Literal["pong"] = "pong"

class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    message: str


# ── Parser ─────────────────────────────────────────────────────────────

def parse_incoming(raw: str) -> IncomingMessage:
    """Parse a raw JSON string into a typed message. Raises ValueError on failure."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc}") from exc

    msg_type = data.get("type")
    if msg_type is None:
        raise ValueError("El mensaje no tiene campo 'type'.")
    if msg_type not in _KNOWN_TYPES:
        raise ValueError(f"Tipo de mensaje desconocido: '{msg_type}'.")

    try:
        return _adapter.validate_python(data)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
