import random
from treys import Card, Evaluator

BOT_NAME = "StudentBot"

_evaluator = Evaluator()

RANK_ORDER = "23456789TJQKA"

STRONG_PREFLOP = {
    ("A","A"),("K","K"),("Q","Q"),("J","J"),("T","T"),
    ("A","K"),("A","Q"),("A","J"),("K","Q"),
}
PLAYABLE_PREFLOP = {
    ("9","9"),("8","8"),("7","7"),("6","6"),
    ("A","T"),("A","9"),("K","J"),("K","T"),("Q","J"),
    ("J","T"),("T","9"),("9","8"),
}

def _hand_rank(cards):
    r1, r2 = cards[0][0], cards[1][0]
    hi = r1 if RANK_ORDER.index(r1) >= RANK_ORDER.index(r2) else r2
    lo = r2 if hi == r1 else r1
    return (hi, lo)

def _estimate_equity(my_cards, community, num_opp, sims=200):
    try:
        known = set(my_cards + community)
        ranks = "23456789TJQKA"
        suits = "shdc"
        deck = [r+s for r in ranks for s in suits if r+s not in known]
        board_need = 5 - len(community)
        wins = 0
        for _ in range(sims):
            random.shuffle(deck)
            idx = 0
            opp_hands = []
            for _ in range(num_opp):
                opp_hands.append(deck[idx:idx+2])
                idx += 2
            run_out = deck[idx:idx+board_need]
            full_board = community + run_out
            board_treys = [Card.new(c) for c in full_board]
            my_score = _evaluator.evaluate(board_treys, [Card.new(c) for c in my_cards])
            best_opp = min(
                _evaluator.evaluate(board_treys, [Card.new(c) for c in oh])
                for oh in opp_hands
            )
            if my_score <= best_opp:
                wins += 1
        return wins / sims
    except Exception:
        return 0.5

def decide(state):
    try:
        street      = state["street"]
        my_cards    = state["your_cards"]
        community   = state["community_cards"]
        pot         = state["pot"]
        stack       = state["your_stack"]
        owed        = state["amount_owed"]
        can_check   = state["can_check"]
        min_raise   = state["min_raise_to"]
        my_bet      = state["your_bet_this_street"]
        players     = state["players"]
        seat        = state["seat_to_act"]
        n           = len([p for p in players if p["state"] != "busted"])
        position    = seat / max(n - 1, 1)

        if street == "preflop":
            key = _hand_rank(my_cards)
            suited = my_cards[0][1] == my_cards[1][1]
            if key in STRONG_PREFLOP:
                size = min(max(int(pot * 3), min_raise), stack + my_bet)
                return {"action": "raise", "amount": size}
            if key in PLAYABLE_PREFLOP or suited:
                if owed <= 300 or can_check:
                    return {"action": "call"} if owed > 0 else {"action": "check"}
            if can_check:
                return {"action": "check"}
            if owed <= 100:
                return {"action": "call"}
            return {"action": "fold"}

        # Postflop: equity based
        num_opp = max(sum(1 for p in players
                         if p["seat"] != seat and p["state"] == "active"), 1)
        equity = _estimate_equity(my_cards, community, num_opp, sims=150)

        if equity >= 0.65:
            if can_check:
                bet = min(max(int(pot * 0.6), min_raise), stack + my_bet)
                return {"action": "raise", "amount": bet}
            return {"action": "call"}

        if equity >= 0.45:
            if can_check:
                if position > 0.5:
                    bet = min(max(int(pot * 0.4), min_raise), stack + my_bet)
                    return {"action": "raise", "amount": bet}
                return {"action": "check"}
            pot_odds = owed / (pot + owed) if (pot + owed) > 0 else 1
            if equity > pot_odds * 1.1:
                return {"action": "call"}
            return {"action": "fold"}

        if can_check:
            return {"action": "check"}
        pot_odds = owed / (pot + owed) if (pot + owed) > 0 else 1
        if pot_odds < 0.15:
            return {"action": "call"}
        return {"action": "fold"}

    except Exception:
        if state.get("can_check"):
            return {"action": "check"}
        return {"action": "fold"}