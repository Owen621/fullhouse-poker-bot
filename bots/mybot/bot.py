import random

try:
    import eval7 as _ev7
    _USE_EVAL7 = True
except ImportError:
    from treys import Card as _TC, Evaluator as _TE
    _USE_EVAL7 = False
    _tev = _TE()

BOT_NAME = "Freelo"
RANK_ORDER = "23456789TJQKA"

PREMIUM = {("A","A"),("K","K"),("Q","Q"),("J","J"),("A","K")}
STRONG  = {("T","T"),("9","9"),("8","8"),("A","Q"),("A","J"),("A","T"),
           ("K","Q"),("K","J"),("Q","J")}
PLAYABLE= {("7","7"),("6","6"),("5","5"),("4","4"),("3","3"),("2","2"),
           ("A","9"),("A","8"),("A","7"),("A","6"),("A","5"),("A","4"),("A","3"),("A","2"),
           ("K","T"),("K","9"),("Q","T"),("J","T"),("T","9"),("9","8"),("8","7"),("7","6")}

# ---------------------------------------------------------------------------
# Opponent model
# ---------------------------------------------------------------------------
_fc={}; _bo={}; _ac={}; _rc={}; _seen=set(); _mid=[None]

def _reset():
    for d in [_fc,_bo,_ac,_rc]: d.clear()
    _seen.clear()

def _upd(log, seat, hid):
    mid=hid[:13] if len(hid)>=13 else hid
    if _mid[0]!=mid: _reset(); _mid[0]=mid
    for i,e in enumerate(log):
        k=(i,e.get("seat"),e.get("action"))
        if k in _seen: continue
        _seen.add(k)
        s=e.get("seat"); a=e.get("action","")
        if s is None or s==seat: continue
        for d in [_fc,_bo,_ac,_rc]: d.setdefault(s,0)
        if a in ("call","raise","all_in","check"): _ac[s]+=1
        if a in ("raise","all_in"): _rc[s]+=1
        if a=="fold": _fc[s]+=1
        if a in ("fold","call","raise","all_in"): _bo[s]+=1

def _ff(s):  o=_bo.get(s,0); return _fc.get(s,0)/o if o>=8 else 0.35
def _af(s):  a=_ac.get(s,0); return _rc.get(s,0)/a if a>=8 else 0.25
def _maniac(s): return _af(s)>0.55
def _fish(s):   return _af(s)<0.15 and _ff(s)<0.30
def _nit(s):    return _ff(s)>0.65

# ---------------------------------------------------------------------------
# Equity
# ---------------------------------------------------------------------------
_DECK=[r+s for r in RANK_ORDER for s in "shdc"]

def _eq(mc, comm, n_opp, sims=500):
    try:
        if _USE_EVAL7: return _eq7(mc,comm,n_opp,sims)
        return _eqt(mc,comm,n_opp,min(sims,250))
    except: return 0.5

def _eq7(mc,comm,n_opp,sims):
    deck=_ev7.Deck()
    known=[_ev7.Card(c) for c in mc+comm]
    deck.cards=[c for c in deck.cards if c not in known]
    m=[_ev7.Card(c) for c in mc]; b=[_ev7.Card(c) for c in comm]
    need=5-len(b); wins=0
    for _ in range(sims):
        random.shuffle(deck.cards); idx=0; opp=[]
        for _ in range(n_opp): opp.append(deck.cards[idx:idx+2]); idx+=2
        full=b+deck.cards[idx:idx+need]
        if _ev7.evaluate(m+full)>=max(_ev7.evaluate(o+full) for o in opp): wins+=1
    return wins/sims

def _eqt(mc,comm,n_opp,sims):
    known=set(mc+comm); deck=[c for c in _DECK if c not in known]
    need=5-len(comm); wins=0
    for _ in range(sims):
        random.shuffle(deck); idx=0; opp=[]
        for _ in range(n_opp): opp.append(deck[idx:idx+2]); idx+=2
        full=comm+deck[idx:idx+need]
        bt=[_TC.new(c) for c in full]
        ms=_tev.evaluate(bt,[_TC.new(c) for c in mc])
        best=min(_tev.evaluate(bt,[_TC.new(c) for c in o]) for o in opp)
        if ms<=best: wins+=1
    return wins/sims

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _pf_str(cards):
    r1,r2=cards[0][0],cards[1][0]; suited=cards[0][1]==cards[1][1]
    hi=r1 if RANK_ORDER.index(r1)>=RANK_ORDER.index(r2) else r2
    lo=r2 if hi==r1 else r1; k=(hi,lo)
    if k in PREMIUM: return "premium"
    if k in STRONG:  return "strong"
    if k in PLAYABLE: return "playable"
    if suited and abs(RANK_ORDER.index(r1)-RANK_ORDER.index(r2))<=2: return "sc"
    return "trash"

def _pos(seat,players):
    active=[p["seat"] for p in players if p["state"]!="busted"]
    n=len(active)
    if n<=1: return 1.0
    try: return active.index(seat)/(n-1)
    except: return 0.5

def _nopp(players,seat):
    return sum(1 for p in players
               if p["seat"]!=seat and p["state"] not in ("folded","busted"))

def _blinds(log):
    sb=bb=None
    for e in log:
        if e.get("action")=="small_blind": sb=e.get("seat")
        if e.get("action")=="big_blind": bb=e.get("seat")
        if sb and bb: break
    return sb,bb

def _sz(pot,stack,mb,minr,mult=3.0):
    return min(max(int(pot*mult),minr),stack+mb)
def _bt(pot,stack,mb,minr,frac=0.65):
    return min(max(int(pot*frac),minr),stack+mb)

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def decide(state):
    try:    return _go(state)
    except: return {"action":"check"} if state.get("can_check") else {"action":"fold"}

def _go(state):
    street=state["street"]; mc=state["your_cards"]; comm=state["community_cards"]
    pot=state["pot"]; stack=state["your_stack"]; owed=state["amount_owed"]
    chk=state["can_check"]; minr=state["min_raise_to"]; mb=state["your_bet_this_street"]
    players=state["players"]; log=state["action_log"]; seat=state["seat_to_act"]
    hid=state.get("hand_id","")

    _upd(log,seat,hid)

    n_opp=_nopp(players,seat)
    pos=_pos(seat,players)
    in_pos=pos>=0.5
    mw=n_opp>=3
    opps=[p for p in players if p["seat"]!=seat and p["state"]=="active"]
    oseat=[p["seat"] for p in opps]
    vs_maniac=any(_maniac(s) for s in oseat) or owed>2000
    vs_fish=any(_fish(s) for s in oseat)
    vs_nit=any(_nit(s) for s in oseat)
    sb,bb=_blinds(log)
    in_bb=(seat==bb)

    if street=="preflop":
        return _pre(mc,pot,stack,owed,chk,minr,mb,pos,in_pos,
                    players,seat,log,oseat,vs_maniac,vs_nit,n_opp,mw,in_bb)

    sims=500 if _USE_EVAL7 else 250
    eq=_eq(mc,comm,max(n_opp,1),sims=sims)
    return _post(eq,pot,stack,owed,chk,minr,mb,in_pos,street,
                 oseat,vs_maniac,vs_fish,vs_nit,mw,log,seat,n_opp)

# ---------------------------------------------------------------------------
# Preflop
# ---------------------------------------------------------------------------
def _pre(mc,pot,stack,owed,chk,minr,mb,pos,in_pos,
         players,seat,log,oseat,vs_maniac,vs_nit,n_opp,mw,in_bb):

    strength=_pf_str(mc)
    suited=mc[0][1]==mc[1][1]
    rbo=sum(1 for a in log if a.get("action") in ("raise","all_in")
            and a.get("seat")!=seat)
    # Also count our own raises to detect when we're facing a 3-bet
    our_raises=sum(1 for a in log if a.get("action") in ("raise","all_in")
                   and a.get("seat")==seat)
    shove=owed>stack*0.7
    # f3 = facing 3-bet: either 2 opponents raised, or we raised and 1 opponent re-raised
    f3=(rbo>=2 or (our_raises>=1 and rbo>=1)) and not vs_maniac
    nc=sum(1 for a in log if a.get("action")=="call")

    # vs maniac/shove
    if vs_maniac:
        if shove:
            rnks=sorted([mc[0][0],mc[1][0]],key=lambda r:RANK_ORDER.index(r),reverse=True)
            if rnks[0]==rnks[1] and rnks[0] in ("A","K"): return {"action":"call"}
            if set(rnks)=={"A","K"}: return {"action":"call"}
            if strength=="premium" and any(_maniac(s) for s in oseat):
                return {"action":"call"}
            return {"action":"fold"}
        if strength in ("premium","strong"):
            return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
        if owed<stack*0.10: return {"action":"call"}
        return {"action":"check"} if chk else {"action":"fold"}

    # Premium: always raise
    if strength=="premium":
        return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,3.0+nc*0.5)}

    # Strong: always raise, but fold most to 3-bet
    if strength=="strong":
        if f3:
            # Only 4-bet TT+ and AQ+, fold the rest
            r1i = RANK_ORDER.index(mc[0][0]); r2i = RANK_ORDER.index(mc[1][0])
            pair = mc[0][0]==mc[1][0]
            top_pair = pair and r1i >= RANK_ORDER.index("T")
            top_combo = not pair and max(r1i,r2i)>=RANK_ORDER.index("A") and min(r1i,r2i)>=RANK_ORDER.index("Q")
            if top_pair or top_combo:
                return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
            # AJ/AT/KQ etc: call if cheap, fold otherwise
            if owed < stack * 0.20 and max(r1i,r2i)>=RANK_ORDER.index("A"):
                return {"action":"call"}
            return {"action":"check"} if chk else {"action":"fold"}
        return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5+nc*0.3)}

    # Playable/SC
    if strength in ("playable","sc"):
        if f3: return {"action":"check"} if chk else {"action":"fold"}
        if rbo==1:
            if mc[0][0]==mc[1][0] and owed<=200: return {"action":"call"}
            if in_pos and suited and RANK_ORDER.index(mc[0][0])>=RANK_ORDER.index("J"):
                return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
            return {"action":"check"} if chk else {"action":"fold"}
        if in_pos:
            return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
        if owed<=150: return {"action":"call"}
        if chk: return {"action":"check"}
        return {"action":"fold"}

    # Trash
    if chk: return {"action":"check"}
    
    # STEAL - 34.5% of all hands won preflop (biggest single EV source)
    # Raise any two cards from late position if it's folded to us
    opps_a=[p for p in players if p["seat"]!=seat and p["state"]=="active"]
    if rbo==0 and owed<=100:
        if pos>=0.85:
            # BTN/CO: steal always when folded to us
            return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
        elif pos>=0.70 and (vs_nit or len(opps_a)<=3):
            # HJ/MP: steal vs tight players
            return {"action":"raise","amount":_sz(max(pot,100),stack,mb,minr,2.5)}
    
    # BB defence: call cheap raises with reasonable hands
    if in_bb and rbo==1 and owed<=250:
        r1,r2=mc[0][0],mc[1][0]
        if suited or r1=="A" or r2=="A" or r1==r2:
            return {"action":"call"}
        # Defend any two cards vs steal (pos>=0.7 raiser likely stealing)
        # Get pot odds to defend
        pot_odds_bb = owed/(pot+owed) if pot+owed>0 else 1
        if pot_odds_bb < 0.25:  # cheap enough to defend wide
            return {"action":"call"}
    return {"action":"fold"}

# ---------------------------------------------------------------------------
# Postflop: bet strong, CHECK medium, fold weak to bets
# ---------------------------------------------------------------------------
def _post(eq,pot,stack,owed,chk,minr,mb,in_pos,street,
          oseat,vs_maniac,vs_fish,vs_nit,mw,log,seat,n_opp):

    eq_adj=eq-(n_opp-1)*0.07
    pot_odds=owed/(pot+owed) if (pot+owed)>0 else 1.0

    if mw:
        strong=eq_adj>=0.70; medium=0.53<=eq_adj<0.70; draw=eq>=0.42 and eq_adj<0.53
    else:
        strong=eq_adj>=0.62; medium=0.45<=eq_adj<0.62; draw=eq>=0.36 and eq_adj<0.45

    # STRONG: bet/raise for value
    # SPR (stack to pot ratio) awareness
    spr = stack / pot if pot > 0 else 10
    short_stack = spr < 3  # commit when short

    if strong:
        if chk:
            if vs_maniac and not short_stack: return {"action":"check"}
            frac=0.72 if vs_fish else (0.50 if mw else 0.65)
            # Short stack: bet larger to build pot for commitment
            if short_stack: frac = min(frac * 1.3, 1.0)
            return {"action":"raise","amount":_bt(pot,stack,mb,minr,frac)}
        else:
            if mw:
                if street=="river":
                    return {"action":"raise","amount":_bt(pot,stack,mb,minr,1.4)}
                # Short stack multiway: commit
                if short_stack: return {"action":"raise","amount":_bt(pot,stack,mb,minr,1.5)}
                return {"action":"call"}
            if street=="river" or eq_adj>=0.73 or short_stack:
                return {"action":"raise","amount":_bt(pot,stack,mb,minr,1.6)}
            return {"action":"call"}

    # MEDIUM: CHECK pot control, don't build pots OOP
    # Key insight: ()bot checks 27% - medium hands check, don't bet/call
    if medium:
        if chk:
            if mw: return {"action":"check"}
            # Bet medium in position (c-bet / value thin)
            if in_pos:
                frac=0.55 if not vs_nit else 0.65
                return {"action":"raise","amount":_bt(pot,stack,mb,minr,frac)}
            # Out of position: CHECK medium hands (pot control)
            return {"action":"check"}
        else:
            # Data shows winners call when pot_odds 15-25%, fold to large bets
            # 86.3% of winner calls have pot odds 15-25%
            if pot_odds < 0.15 and eq > pot_odds * 1.1:
                return {"action":"call"}   # small bet, decent equity
            if pot_odds < 0.25 and eq > pot_odds * 1.3 and not mw:
                return {"action":"call"}   # medium bet, strong equity edge HU
            return {"action":"fold"}       # large bet or multiway: fold medium

    # DRAWING: semi-bluff in position
    if draw and street in ("flop","turn"):
        if chk:
            if in_pos and not mw:
                return {"action":"raise","amount":_bt(pot,stack,mb,minr,0.55)}
            return {"action":"check"}
        else:
            if street=="flop" and eq>0.40 and pot_odds<0.22: return {"action":"call"}
            if pot_odds<0.10: return {"action":"call"}
            return {"action":"fold"}

    # WEAK: check, fold to bets, occasional bluff
    if chk:
        if not mw:
            if street=="river" and in_pos and random.random()<0.25:
                recent=[a for a in log[-5:] if a.get("seat")!=seat
                        and a.get("action") in ("raise","all_in","call")]
                if not recent:
                    return {"action":"raise","amount":_bt(pot,stack,mb,minr,0.75)}
            if street=="flop" and in_pos and random.random()<0.30:
                return {"action":"raise","amount":_bt(pot,stack,mb,minr,0.50)}
        return {"action":"check"}

    if pot_odds<0.08 and street!="river": return {"action":"call"}
    return {"action":"fold"}