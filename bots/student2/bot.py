import os, random
import numpy as np
from treys import Card, Evaluator
 
BOT_NAME = "EquityExploiter"
 
# ---------------------------------------------------------------------------
# Load preflop lookup table at import time
# ---------------------------------------------------------------------------
_DATA_DIR = os.environ.get("BOT_DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
_lookup = {}
try:
    _npz = np.load(os.path.join(_DATA_DIR, "preflop_equity.npz"), allow_pickle=True)
    _lookup = dict(zip(_npz['keys'], _npz['values']))
except Exception:
    pass  # fallback to heuristics if file missing
 
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
 
# ---------------------------------------------------------------------------
# Opponent model
# ---------------------------------------------------------------------------
_fold_cnt={}; _bet_opps={}; _act_cnt={}; _raise_cnt={}
_seen=set(); _mid=[None]
 
def _reset():
    for d in [_fold_cnt,_bet_opps,_act_cnt,_raise_cnt]: d.clear()
    _seen.clear()
 
def _update(log, seat, hid):
    mid = hid[:13] if len(hid)>=13 else hid
    if _mid[0] != mid: _reset(); _mid[0] = mid
    for i,e in enumerate(log):
        k = (i, e.get("seat"), e.get("action"))
        if k in _seen: continue
        _seen.add(k)
        s = e.get("seat"); a = e.get("action","")
        if s is None or s == seat: continue
        for d in [_fold_cnt,_bet_opps,_act_cnt,_raise_cnt]: d.setdefault(s,0)
        if a in ("call","raise","all_in","check"): _act_cnt[s] += 1
        if a in ("raise","all_in"): _raise_cnt[s] += 1
        if a == "fold": _fold_cnt[s] += 1
        if a in ("fold","call","raise","all_in"): _bet_opps[s] += 1
 
def _ff(s):
    o = _bet_opps.get(s,0)
    return _fold_cnt.get(s,0)/o if o>=8 else 0.35
def _af(s):
    a = _act_cnt.get(s,0)
    return _raise_cnt.get(s,0)/a if a>=8 else 0.25
def _is_maniac(s): return _af(s) > 0.55
def _is_nit(s):    return _ff(s) > 0.65
def _is_fish(s):   return _af(s) < 0.15 and _ff(s) < 0.30
def _is_passive(s):return _af(s) < 0.20
 
# ---------------------------------------------------------------------------
# Preflop lookup
# ---------------------------------------------------------------------------
def _canonical_key(cards):
    """Convert hole cards to canonical lookup key e.g. 'AKs', 'TT', '72o'."""
    r1, r2 = cards[0][0], cards[1][0]
    s1, s2 = cards[0][1], cards[1][1]
    suited = s1 == s2
    pair = r1 == r2
    hi = r1 if RANK_ORDER.index(r1) >= RANK_ORDER.index(r2) else r2
    lo = r2 if hi == r1 else r1
    if pair:
        return hi + lo
    return hi + lo + ("s" if suited else "o")
 
def _preflop_equity(cards, n_opp):
    """Get preflop equity from lookup table. Returns None if not found."""
    key = f"{_canonical_key(cards)}_{min(n_opp,5)}"
    val = _lookup.get(key)
    if val is None: return None
    return float(val)
 
def _hand_rank(cards):
    r1,r2 = cards[0][0], cards[1][0]
    hi = r1 if RANK_ORDER.index(r1) >= RANK_ORDER.index(r2) else r2
    lo = r2 if hi == r1 else r1
    return (hi, lo)
 
# ---------------------------------------------------------------------------
# Postflop equity (Monte Carlo)
# ---------------------------------------------------------------------------
_DECK = [r+s for r in RANK_ORDER for s in "shdc"]
 
def _postflop_equity(mc, comm, n_opp, sims=200):
    try:
        known = set(mc+comm)
        deck = [c for c in _DECK if c not in known]
        need = 5 - len(comm); wins = 0
        for _ in range(sims):
            random.shuffle(deck)
            idx=0; opp=[]
            for _ in range(n_opp): opp.append(deck[idx:idx+2]); idx+=2
            full = comm + deck[idx:idx+need]
            bt = [Card.new(c) for c in full]
            ms = _evaluator.evaluate(bt, [Card.new(c) for c in mc])
            best = min(_evaluator.evaluate(bt,[Card.new(c) for c in o]) for o in opp)
            if ms <= best: wins += 1
        return wins / sims
    except: return 0.5
 
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pos(seat, players):
    active = [p["seat"] for p in players if p["state"]!="busted"]
    n = len(active)
    if n<=1: return 1.0
    try: return active.index(seat)/(n-1)
    except: return 0.5
 
def _nopp(players, seat):
    return sum(1 for p in players
               if p["seat"]!=seat and p["state"] not in ("folded","busted"))
 
def _get_blinds(log):
    sb=bb=None
    for e in log:
        if e.get("action")=="small_blind": sb=e.get("seat")
        if e.get("action")=="big_blind": bb=e.get("seat")
        if sb is not None and bb is not None: break
    return sb, bb
 
def _size(pot, stack, mb, minr, mult=3.0):
    return min(max(int(pot*mult), minr), stack+mb)
def _bet(pot, stack, mb, minr, frac=0.65):
    return min(max(int(pot*frac), minr), stack+mb)
 
# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def decide(state):
    try:    return _inner(state)
    except: return {"action":"check"} if state.get("can_check") else {"action":"fold"}
 
def _inner(state):
    street  = state["street"]; mc = state["your_cards"]; comm = state["community_cards"]
    pot     = state["pot"]; stack = state["your_stack"]; owed = state["amount_owed"]
    chk     = state["can_check"]; minr = state["min_raise_to"]; mb = state["your_bet_this_street"]
    players = state["players"]; log = state["action_log"]; seat = state["seat_to_act"]
    hid     = state.get("hand_id","")
 
    _update(log, seat, hid)
 
    n_opp   = _nopp(players, seat)
    pos     = _pos(seat, players)
    in_pos  = pos >= 0.5
    multiway = n_opp >= 3
 
    active_opps = [p for p in players if p["seat"]!=seat and p["state"]=="active"]
    opp_seats   = [p["seat"] for p in active_opps]
 
    avg_af  = sum(_af(s) for s in opp_seats)/len(opp_seats) if opp_seats else 0.25
    avg_ff  = sum(_ff(s) for s in opp_seats)/len(opp_seats) if opp_seats else 0.35
    vs_aggro   = avg_af > 0.45
    vs_passive = avg_ff > 0.55
    any_maniac = any(_is_maniac(s) for s in opp_seats) or owed > 2000
 
    sb, bb = _get_blinds(log)
    in_blind = seat in (sb, bb)
 
    if street == "preflop":
        return _preflop(mc, pot, stack, owed, chk, minr, mb, pos, in_pos,
                        players, seat, log, opp_seats, any_maniac,
                        n_opp, vs_aggro, vs_passive, in_blind, sb, bb, multiway)
 
    eq = _postflop_equity(mc, comm, max(n_opp,1), sims=200)
    return _postflop(eq, pot, stack, owed, chk, minr, mb, in_pos, street,
                     opp_seats, any_maniac, multiway, log, seat, n_opp,
                     vs_aggro, vs_passive, in_blind)
 
# ---------------------------------------------------------------------------
# Preflop — uses lookup table for equity-based decisions
# ---------------------------------------------------------------------------
def _preflop(mc, pot, stack, owed, chk, minr, mb, pos, in_pos,
             players, seat, log, opp_seats, any_maniac,
             n_opp, vs_aggro, vs_passive, in_blind, sb, bb, multiway):
 
    key    = _hand_rank(mc)
    suited = mc[0][1] == mc[1][1]
    rby_opp = sum(1 for a in log if a.get("action") in ("raise","all_in")
                  and a.get("seat") != seat)
    is_shove  = owed > stack * 0.7
    facing3   = rby_opp >= 2 and not any_maniac
    num_callers = sum(1 for a in log if a.get("action") == "call")
 
    # Get equity from lookup table
    pf_eq = _preflop_equity(mc, max(n_opp,1))
    # If lookup available, use it for all decisions
    # Otherwise fall back to range-based logic
 
    # vs maniac / shove — very tight
    if any_maniac:
        if is_shove:
            ranks = sorted([mc[0][0],mc[1][0]],
                           key=lambda r: RANK_ORDER.index(r), reverse=True)
            if ranks[0]==ranks[1] and ranks[0] in ("A","K"): return {"action":"call"}
            if set(ranks)=={"A","K"}: return {"action":"call"}
            if key in {("A","A"),("K","K"),("Q","Q"),("J","J")} and \
               any(_is_maniac(s) for s in opp_seats): return {"action":"call"}
            return {"action":"fold"}
        if key in {("A","A"),("K","K"),("Q","Q"),("J","J"),("A","K")}:
            return {"action":"call"} if owed>0 else \
                   {"action":"raise","amount":_size(max(pot,100),stack,mb,minr,2.0)}
        if pf_eq and pf_eq > 0.55 and owed < stack*0.20: return {"action":"call"}
        return {"action":"check"} if chk else {"action":"fold"}
 
    # Use lookup table equity if available
    if pf_eq is not None:
        # Equity-based preflop decisions
        # Thresholds adjust for position and opponent type
        raise_thresh = 0.58 if vs_aggro else (0.52 if vs_passive else 0.55)
        call_thresh  = 0.45 if vs_aggro else (0.40 if vs_passive else 0.42)
 
        # Multiway: tighten thresholds
        if multiway:
            raise_thresh += 0.05
            call_thresh  += 0.05
 
        # Late position: loosen
        if pos >= 0.75 and rby_opp == 0:
            raise_thresh -= 0.05
            call_thresh  -= 0.03
 
        if facing3:
            # Only continue with top hands facing a 3-bet
            if pf_eq > 0.62: return {"action":"call"}
            return {"action":"check"} if chk else {"action":"fold"}
 
        if pf_eq >= raise_thresh:
            mult = 3.5 + num_callers*0.5
            if vs_passive: mult += 0.5  # bet bigger vs passive
            return {"action":"raise","amount":_size(max(pot,100),stack,mb,minr,mult)}
 
        if pf_eq >= call_thresh:
            max_call = 200 if vs_aggro else 350
            if owed <= max_call or chk:
                return {"action":"call"} if owed>0 else {"action":"check"}
            return {"action":"check"} if chk else {"action":"fold"}
 
        # Trash: steal from late position
        if chk: return {"action":"check"}
        if pos >= 0.85 and rby_opp == 0 and owed <= 100:
            opps = [p for p in players if p["seat"]!=seat and p["state"]=="active"]
            if not opps or all(_ff(p["seat"])>0.5 for p in opps):
                return {"action":"raise","amount":_size(max(pot,100),stack,mb,minr,2.2)}
        # BB defence
        if in_blind and seat==bb and rby_opp==1 and owed<=300:
            if suited or "A" in (mc[0][0],mc[1][0]):
                return {"action":"call"}
        return {"action":"fold"}
 
    # Fallback: range-based (if lookup failed to load)
    if key in STRONG_PREFLOP:
        mult = 3.5 if vs_passive else 3.0
        return {"action":"raise","amount":_size(max(pot,100),stack,mb,minr,mult)}
    if key in PLAYABLE_PREFLOP or suited:
        if owed <= (200 if vs_aggro else 300) or chk:
            return {"action":"call"} if owed>0 else {"action":"check"}
    if chk: return {"action":"check"}
    if owed <= 100: return {"action":"call"}
    return {"action":"fold"}
 
# ---------------------------------------------------------------------------
# Postflop
# ---------------------------------------------------------------------------
def _postflop(eq, pot, stack, owed, chk, minr, mb, in_pos, street,
              opp_seats, any_maniac, multiway, log, seat, n_opp,
              vs_aggro, vs_passive, in_blind):
 
    eq_adj   = eq - (n_opp-1)*0.07
    pot_odds = owed/(pot+owed) if (pot+owed)>0 else 1.0
 
    # Adjust thresholds based on opponent profile
    strong_thresh = 0.60 if vs_aggro else (0.55 if vs_passive else 0.62)
    medium_thresh = 0.40 if vs_passive else 0.43
    bet_frac      = 0.80 if vs_passive else 0.65
    call_edge     = 1.15 if vs_aggro else (1.05 if vs_passive else 1.10)
 
    if multiway:
        strong_thresh = max(strong_thresh, 0.70)
        medium_thresh = max(medium_thresh, 0.52)
 
    strong  = eq_adj >= strong_thresh
    medium  = medium_thresh <= eq_adj < strong_thresh
    drawing = eq >= 0.35 and eq_adj < medium_thresh
 
    # ── STRONG ──
    if strong:
        if chk:
            if any_maniac: return {"action":"check"}
            frac = bet_frac if not multiway else 0.55
            return {"action":"raise","amount":_bet(pot,stack,mb,minr,frac)}
        else:
            if multiway: return {"action":"call"}
            if vs_passive and street=="river":
                return {"action":"raise","amount":_size(pot,stack,mb,minr,2.0)}
            if eq_adj >= 0.75:
                return {"action":"raise","amount":_size(pot,stack,mb,minr,1.8)}
            return {"action":"call"}
 
    # ── MEDIUM ──
    if medium:
        if chk:
            if multiway: return {"action":"check"}
            if in_pos:
                frac = 0.70 if vs_passive else 0.50
                return {"action":"raise","amount":_bet(pot,stack,mb,minr,frac)}
            return {"action":"check"}
        else:
            if pot_odds < 0.15: return {"action":"call"}
            if eq > pot_odds * call_edge: return {"action":"call"}
            if multiway and owed > pot*0.3: return {"action":"fold"}
            return {"action":"fold"}
 
    # ── DRAWING ──
    if drawing and street in ("flop","turn"):
        if chk:
            if in_pos and not multiway:
                return {"action":"raise","amount":_bet(pot,stack,mb,minr,0.55)}
            return {"action":"check"}
        else:
            impl = 1.25 if street=="flop" else 1.05
            if eq*impl > pot_odds: return {"action":"call"}
            if pot_odds < 0.12: return {"action":"call"}
            return {"action":"fold"}
 
    # ── WEAK ──
    if chk:
        if not multiway and street=="river" and in_pos:
            checked = [a for a in log[-4:] if a.get("seat")!=seat
                       and a.get("action") in ("raise","all_in","call")]
            if not checked:
                return {"action":"raise","amount":_bet(pot,stack,mb,minr,0.75)}
        return {"action":"check"}
 
    if pot_odds < 0.10 and street != "river": return {"action":"call"}
    return {"action":"fold"}