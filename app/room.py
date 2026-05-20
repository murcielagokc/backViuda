import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from fastapi import WebSocket
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.game import Game


class Phase(str, Enum):
    IDLE = "idle"
    IN_GAME = "in_game"


class Role(str, Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    SPECTATOR = "spectator"


@dataclass
class Connection:
    websocket: WebSocket
    nickname: str
    role: Role


class GameRoom:
    MAX_PLAYERS = 9

    def __init__(self):
        self._connections: dict[str, Connection] = {}
        self._disconnected: set[str] = set()   # playing players without an active socket
        self.phase: Phase = Phase.IDLE
        self._hands: dict[str, list[dict]] = {}
        self._leftover: list[dict] = []
        self.game: "Game | None" = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def waiting(self) -> list[str]:
        return [n for n, c in self._connections.items() if c.role == Role.WAITING]

    @property
    def playing(self) -> list[str]:
        """Connected playing players."""
        return [n for n, c in self._connections.items() if c.role == Role.PLAYING]

    @property
    def playing_all(self) -> list[str]:
        """All playing players, connected or not (preserves game order)."""
        connected = {n for n, c in self._connections.items() if c.role == Role.PLAYING}
        return list(connected | self._disconnected)

    @property
    def spectators(self) -> list[str]:
        return [n for n, c in self._connections.items() if c.role == Role.SPECTATOR]

    @property
    def disconnected(self) -> list[str]:
        return list(self._disconnected)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self, websocket: WebSocket, nickname: str) -> tuple[bool, str]:
        """Register a new connection. Returns (ok, error, is_reconnect)."""
        if nickname in self._connections:
            return False, "El nickname ya está en uso."

        if nickname in self._disconnected:
            # Reconnecting a player who was in an active game
            self._disconnected.discard(nickname)
            self._connections[nickname] = Connection(websocket, nickname, Role.PLAYING)
            return True, ""

        self._connections[nickname] = Connection(websocket, nickname, Role.SPECTATOR)
        return True, ""

    def disconnect(self, nickname: str) -> None:
        conn = self._connections.pop(nickname, None)
        if conn and conn.role == Role.PLAYING and self.phase == Phase.IN_GAME:
            # Keep the nick reserved so they can reconnect
            self._disconnected.add(nickname)

    def is_reconnect(self, nickname: str) -> bool:
        """True if this nick just came back from a disconnected-playing state."""
        conn = self._connections.get(nickname)
        return conn is not None and conn.role == Role.PLAYING and self.phase == Phase.IN_GAME

    # ------------------------------------------------------------------
    # Lobby actions
    # ------------------------------------------------------------------

    def join(self, nickname: str) -> tuple[bool, str]:
        conn = self._connections.get(nickname)
        if conn is None:
            return False, "Conexión no encontrada."
        if self.phase == Phase.IN_GAME:
            return False, "La partida ya está en curso."
        if len(self.waiting) >= self.MAX_PLAYERS:
            return False, "La sala de espera está llena (máx 9 jugadores)."
        if conn.role == Role.WAITING:
            return False, "Ya estás en la lista de espera."
        conn.role = Role.WAITING
        return True, ""

    def leave_waiting(self, nickname: str) -> tuple[bool, str]:
        conn = self._connections.get(nickname)
        if conn is None or conn.role != Role.WAITING:
            return False, "No estás en la lista de espera."
        conn.role = Role.SPECTATOR
        return True, ""

    # ------------------------------------------------------------------
    # Game control
    # ------------------------------------------------------------------

    def start_game(self, initiator: str) -> tuple[bool, str]:
        conn = self._connections.get(initiator)
        if conn is None or conn.role != Role.WAITING:
            return False, "Solo un jugador en espera puede iniciar la partida."
        if len(self.waiting) < 2:
            return False, "Se necesitan al menos 2 jugadores para iniciar."
        if self.phase == Phase.IN_GAME:
            return False, "La partida ya está en curso."
        for nickname in self.waiting:
            self._connections[nickname].role = Role.PLAYING
        self.phase = Phase.IN_GAME
        return True, ""

    def end_game(self) -> None:
        for nickname in self.playing:
            self._connections[nickname].role = Role.SPECTATOR
        self._disconnected.clear()
        self.phase = Phase.IDLE
        self._hands = {}
        self._leftover = []
        self.game = None

    # ------------------------------------------------------------------
    # Hand management
    # ------------------------------------------------------------------

    def set_hands(self, hands: dict[str, list[dict]], leftover: list[dict]) -> None:
        self._hands = hands
        self._leftover = leftover

    def get_hand(self, nickname: str) -> list[dict]:
        return self._hands.get(nickname, [])

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def room_state_payload(self) -> str:
        return json.dumps({
            "type":         "room_state",
            "waiting":      self.waiting,
            "playing":      self.playing,
            "spectators":   self.spectators,
            "disconnected": self.disconnected,
            "phase":        self.phase.value,
        })

    async def broadcast_room_state(self) -> None:
        payload = self.room_state_payload()
        await asyncio.gather(
            *(c.websocket.send_text(payload) for c in self._connections.values()),
            return_exceptions=True,
        )

    async def send_to(self, nickname: str, payload: dict) -> None:
        conn = self._connections.get(nickname)
        if conn:
            await conn.websocket.send_text(json.dumps(payload))

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_text(json.dumps({"type": "error", "message": message}))


room = GameRoom()
