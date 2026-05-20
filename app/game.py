"""
Game state machine for "viuda".

Phases:
  ORDER_DETERMINATION → PLAYING → SHOWDOWN → FINISHED
"""
import random
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, IntEnum

from app.deck import Card, RANKS, RANK_VALUES, SUITS, BLACK_SUITS, RED_SUITS, shuffle_deck, build_deck_no_jokers, build_deck


# ══════════════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════════════

class GamePhase(str, Enum):
    ORDER_DETERMINATION = "order_determination"
    PLAYING             = "playing"
    SHOWDOWN            = "showdown"
    FINISHED            = "finished"


class HandRank(IntEnum):
    HIGH_CARD       = 1
    ONE_PAIR        = 2
    TWO_PAIR        = 3
    THREE_OF_A_KIND = 4
    STRAIGHT        = 5
    FLUSH           = 6
    FULL_HOUSE      = 7
    FOUR_OF_A_KIND  = 8
    STRAIGHT_FLUSH  = 9
    ROYAL_FLUSH     = 10


# ══════════════════════════════════════════════════════════════════════
# Poker evaluation (no jokers)
# ══════════════════════════════════════════════════════════════════════

def _ranks_of(cards: list[Card]) -> list[int]:
    return sorted([c.high_value for c in cards], reverse=True)


def _evaluate_5(cards: list[Card]) -> tuple[HandRank, list[int]]:
    """Evaluate exactly 5 non-joker cards. Returns (HandRank, tiebreakers)."""
    assert len(cards) == 5, f"Expected 5 cards, got {len(cards)}"

    ranks  = _ranks_of(cards)
    suits  = [c.suit for c in cards]

    is_flush = len(set(suits)) == 1

    uniq = sorted(set(ranks))
    is_straight_high = len(uniq) == 5 and uniq[-1] - uniq[0] == 4
    is_wheel = set(ranks) == {14, 2, 3, 4, 5}   # A plays low
    is_straight = is_straight_high or is_wheel
    straight_ranks = [5, 4, 3, 2, 1] if is_wheel else ranks

    rc     = Counter(ranks)
    counts = sorted(rc.values(), reverse=True)

    if is_flush and is_straight:
        if is_straight_high and min(ranks) == 10:
            return HandRank.ROYAL_FLUSH, ranks
        return HandRank.STRAIGHT_FLUSH, straight_ranks

    if counts[0] == 4:
        quad   = next(r for r, c in rc.items() if c == 4)
        kicker = next(r for r, c in rc.items() if c == 1)
        return HandRank.FOUR_OF_A_KIND, [quad, kicker]

    if counts[0] == 3 and counts[1] == 2:
        trip = next(r for r, c in rc.items() if c == 3)
        pair = next(r for r, c in rc.items() if c == 2)
        return HandRank.FULL_HOUSE, [trip, pair]

    if is_flush:
        return HandRank.FLUSH, ranks

    if is_straight:
        return HandRank.STRAIGHT, straight_ranks

    if counts[0] == 3:
        trip    = next(r for r, c in rc.items() if c == 3)
        kickers = sorted([r for r, c in rc.items() if c == 1], reverse=True)
        return HandRank.THREE_OF_A_KIND, [trip] + kickers

    pairs = sorted([r for r, c in rc.items() if c == 2], reverse=True)
    if len(pairs) == 2:
        kicker = next(r for r, c in rc.items() if c == 1)
        return HandRank.TWO_PAIR, pairs + [kicker]

    if counts[0] == 2:
        kickers = sorted([r for r, c in rc.items() if c == 1], reverse=True)
        return HandRank.ONE_PAIR, pairs + kickers

    return HandRank.HIGH_CARD, ranks


def _joker_candidates(joker: Card, base_cards: list[Card]) -> list[Card]:
    """All valid substitutes for a joker given the other cards in hand."""
    taken_ids = {c.id for c in base_cards}
    color_suits = list(BLACK_SUITS) if joker.suit == "joker_black" else list(RED_SUITS)
    candidates: list[Card] = []
    for suit in color_suits:
        for rank in RANKS:
            cid = f"{rank}_{suit}"
            if cid not in taken_ids:
                candidates.append(Card(
                    id=cid, suit=suit, rank=rank,
                    values=tuple(RANK_VALUES[rank]),
                ))
    return candidates


def evaluate_best_hand(cards: list[Card]) -> tuple[HandRank, list[int]]:
    """Evaluate a 5-card hand that may contain 0, 1, or 2 jokers."""
    jokers     = [c for c in cards if c.is_joker]
    non_jokers = [c for c in cards if not c.is_joker]

    if not jokers:
        return _evaluate_5(non_jokers)

    best: tuple[HandRank, list[int]] | None = None

    def _update(candidate_hand: list[Card]) -> None:
        nonlocal best
        result = _evaluate_5(candidate_hand)
        if best is None or result > best:
            best = result

    if len(jokers) == 1:
        for sub in _joker_candidates(jokers[0], non_jokers):
            _update(non_jokers + [sub])

    elif len(jokers) == 2:
        cands0 = _joker_candidates(jokers[0], non_jokers)
        cands1 = _joker_candidates(jokers[1], non_jokers)
        for s0 in cands0:
            for s1 in cands1:
                if s0.id != s1.id:
                    _update(non_jokers + [s0, s1])

    return best or _evaluate_5(non_jokers)


# ══════════════════════════════════════════════════════════════════════
# Player state
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PlayerState:
    nickname: str
    hand: list[Card] = field(default_factory=list)
    consecutive_passes: int = 0
    is_standing: bool = False


# ══════════════════════════════════════════════════════════════════════
# Game
# ══════════════════════════════════════════════════════════════════════

class Game:
    HAND_SIZE  = 5
    TABLE_SIZE = 5

    def __init__(self, players: list[str]) -> None:
        self._all_players = players
        self._order: list[str] = []          # determined play order
        self._states: dict[str, PlayerState] = {
            p: PlayerState(nickname=p) for p in players
        }
        self._table: list[Card] = []
        self._table_face_up = False

        self._turn_number = 0                # absolute turn index
        self._first_stand_turn: int | None = None

        self.phase = GamePhase.ORDER_DETERMINATION
        self.order_cards: dict[str, Card] = {}

    # ── Phase 0: order determination ──────────────────────────────

    def determine_order(self) -> None:
        """Deal 1 card (no jokers) to each player and compute play order."""
        deck = shuffle_deck(build_deck_no_jokers())
        order_cards: dict[str, Card] = {}
        for i, nick in enumerate(self._all_players):
            order_cards[nick] = deck[i]
        self.order_cards = order_cards

        # Sort descending by high value; ties broken randomly
        self._order = sorted(
            self._all_players,
            key=lambda n: (order_cards[n].high_value, random.random()),
            reverse=True,
        )

    # ── Phase 1: dealing ──────────────────────────────────────────

    def deal(self) -> None:
        """
        Deal 5 cards to each player + 5 to table, intercalado in play order.
        (Table is treated as the last 'player' in each round.)
        """
        deck = shuffle_deck(build_deck())
        idx  = 0
        for _ in range(self.HAND_SIZE):
            for nick in self._order:
                self._states[nick].hand.append(deck[idx])
                idx += 1
            self._table.append(deck[idx])
            idx += 1

        self._table_face_up = False
        self.phase = GamePhase.PLAYING

    # ── Properties ────────────────────────────────────────────────

    @property
    def current_player(self) -> str | None:
        if self.phase != GamePhase.PLAYING or not self._order:
            return None
        return self._order[self._turn_number % len(self._order)]

    @property
    def table_face_up(self) -> bool:
        return self._table_face_up

    def get_hand(self, nickname: str) -> list[Card]:
        return self._states[nickname].hand

    def valid_actions(self, nickname: str) -> list[str]:
        if self.phase != GamePhase.PLAYING:
            return []
        if nickname != self.current_player:
            return []
        if self._states[nickname].is_standing:
            return []
        actions = ["swap_all", "pass_turn", "stand"]
        if self._table_face_up:
            actions.insert(1, "swap_one")
        return actions

    # ── Validation helper ─────────────────────────────────────────

    def _check_turn(self, nickname: str) -> tuple[bool, str]:
        if self.phase != GamePhase.PLAYING:
            return False, "La partida no está en fase de juego."
        if nickname != self.current_player:
            return False, "No es tu turno."
        if self._states[nickname].is_standing:
            return False, "Ya estás plantado."
        return True, ""

    # ── Actions ───────────────────────────────────────────────────

    def apply_swap_all(self, nickname: str) -> tuple[bool, str]:
        ok, err = self._check_turn(nickname)
        if not ok:
            return False, err

        s = self._states[nickname]
        s.hand, self._table = self._table[:], s.hand[:]
        self._table_face_up  = True
        s.consecutive_passes = 0
        self._advance()
        return True, ""

    def apply_swap_one(
        self, nickname: str, hand_card_id: str, table_card_id: str
    ) -> tuple[bool, str]:
        ok, err = self._check_turn(nickname)
        if not ok:
            return False, err

        if not self._table_face_up:
            return False, "La mesa está boca abajo; no puedes cambiar solo una carta."

        s          = self._states[nickname]
        hand_card  = next((c for c in s.hand   if c.id == hand_card_id),  None)
        table_card = next((c for c in self._table if c.id == table_card_id), None)

        if hand_card  is None: return False, "Esa carta no está en tu mano."
        if table_card is None: return False, "Esa carta no está en la mesa."

        s.hand     = [table_card if c.id == hand_card_id  else c for c in s.hand]
        self._table = [hand_card  if c.id == table_card_id else c for c in self._table]
        s.consecutive_passes = 0
        self._advance()
        return True, ""

    def apply_pass(self, nickname: str) -> tuple[bool, str]:
        ok, err = self._check_turn(nickname)
        if not ok:
            return False, err

        s = self._states[nickname]
        s.consecutive_passes += 1

        if s.consecutive_passes >= 2:
            # Auto-stand after 2 consecutive passes
            s.is_standing = True
            if self._first_stand_turn is None:
                self._first_stand_turn = self._turn_number

        self._advance()
        return True, ""

    def apply_stand(self, nickname: str) -> tuple[bool, str]:
        ok, err = self._check_turn(nickname)
        if not ok:
            return False, err

        s = self._states[nickname]
        s.is_standing        = True
        s.consecutive_passes = 0

        if self._first_stand_turn is None:
            self._first_stand_turn = self._turn_number

        self._advance()
        return True, ""

    # ── Turn advancement ──────────────────────────────────────────

    def _advance(self) -> None:
        self._turn_number += 1

        # Skip standing players, check showdown each step
        n = len(self._order)
        for _ in range(n + 1):            # safety cap
            if self._is_showdown():
                self.phase = GamePhase.SHOWDOWN
                return

            cp = self._order[self._turn_number % n]
            if not self._states[cp].is_standing:
                return                    # found active player

            self._turn_number += 1       # skip standee

        # All players standing → showdown
        self.phase = GamePhase.SHOWDOWN

    def _is_showdown(self) -> bool:
        if self._first_stand_turn is None:
            return False
        n = len(self._order)
        first_stander_pos = self._first_stand_turn % n
        return (
            self._turn_number - self._first_stand_turn >= n
            and self._turn_number % n == first_stander_pos
        )

    # ── Showdown evaluation ───────────────────────────────────────

    def evaluate_all(self) -> dict[str, dict]:
        results: dict[str, dict] = {}
        for nick in self._order:
            hand = self._states[nick].hand
            rank, tiebreakers = evaluate_best_hand(hand)
            results[nick] = {
                "nickname":    nick,
                "hand":        [c.to_dict() for c in hand],
                "rank":        rank.name,
                "rank_value":  int(rank),
                "tiebreakers": tiebreakers,
            }
        return results

    def get_winners(self) -> list[str]:
        results = self.evaluate_all()
        best_rank = max(r["rank_value"] for r in results.values())
        top = [n for n, r in results.items() if r["rank_value"] == best_rank]
        if len(top) == 1:
            return top
        best_tb = max(results[n]["tiebreakers"] for n in top)
        return [n for n in top if results[n]["tiebreakers"] == best_tb]

    # ── Serialization ─────────────────────────────────────────────

    def public_state(self) -> dict:
        return {
            "type":           "game_state",
            "phase":          self.phase.value,
            "current_player": self.current_player,
            "order":          self._order,
            "players": [
                {
                    "nickname":          nick,
                    "card_count":        len(self._states[nick].hand),
                    "is_standing":       self._states[nick].is_standing,
                    "consecutive_passes": self._states[nick].consecutive_passes,
                }
                for nick in self._order
            ],
            "table": {
                "face_up": self._table_face_up,
                "count":   len(self._table),
                "cards":   [c.to_dict() for c in self._table] if self._table_face_up else None,
            },
        }

    def order_result(self) -> dict:
        return {
            "type":       "order_result",
            "order_cards": {
                nick: card.to_dict() for nick, card in self.order_cards.items()
            },
            "play_order": self._order,
        }

    def showdown_result(self) -> dict:
        evaluations = self.evaluate_all()
        winners = self.get_winners()
        return {
            "type":        "showdown",
            "evaluations": list(evaluations.values()),
            "winners":     winners,
            "table":       [c.to_dict() for c in self._table],
        }
