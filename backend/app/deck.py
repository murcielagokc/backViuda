import random
from dataclasses import dataclass

SUITS = ["spades", "hearts", "diamonds", "clubs"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

RANK_VALUES: dict[str, list[int]] = {
    "A":  [1, 14],
    "2":  [2],  "3":  [3],  "4":  [4],  "5":  [5],
    "6":  [6],  "7":  [7],  "8":  [8],  "9":  [9],
    "10": [10], "J":  [11], "Q":  [12], "K":  [13],
    "JOKER": [0],
}

BLACK_SUITS = {"spades", "clubs"}
RED_SUITS   = {"hearts", "diamonds"}


@dataclass(frozen=True)
class Card:
    id: str
    suit: str    # "spades"|"hearts"|"diamonds"|"clubs"|"joker_black"|"joker_red"
    rank: str    # "A".."K"|"JOKER"
    values: tuple[int, ...]  # (1,14) for Ace; (0,) for Joker

    def to_dict(self) -> dict:
        return {"id": self.id, "suit": self.suit, "rank": self.rank, "values": list(self.values)}

    @property
    def is_joker(self) -> bool:
        return self.rank == "JOKER"

    @property
    def high_value(self) -> int:
        """Max numeric value (A=14)."""
        return max(self.values) if self.values else 0


def build_deck() -> list[Card]:
    """54-card French deck: 52 standard + 1 black joker + 1 red joker."""
    deck: list[Card] = []
    for suit in SUITS:
        for rank in RANKS:
            deck.append(Card(
                id=f"{rank}_{suit}",
                suit=suit,
                rank=rank,
                values=tuple(RANK_VALUES[rank]),
            ))
    deck.append(Card(id="JOKER_black", suit="joker_black", rank="JOKER", values=(0,)))
    deck.append(Card(id="JOKER_red",   suit="joker_red",   rank="JOKER", values=(0,)))
    return deck


def build_deck_no_jokers() -> list[Card]:
    """52-card deck without jokers (used for order determination)."""
    return [c for c in build_deck() if not c.is_joker]


def shuffle_deck(deck: list[Card]) -> list[Card]:
    result = deck[:]
    random.shuffle(result)
    return result
