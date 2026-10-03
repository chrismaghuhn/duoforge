"""Pure protocol-log inference shared by openings and the spectator replay pipeline."""
from duoforge_live import lines

BROUGHT = 4  # The open-sheet VGC formats bring four Pokemon from a six-Pokemon team.


def hindsight(log, side, data, sheets):
    """Return roster indices of the two leads and the set of other members seen switching in."""
    roster = [data.base_forme(data.forme(member["species"])) for member in sheets[side]]
    leads, seen, started, turn = [None, None], set(), False, False
    for line in log:
        kind = lines.line_kind(line)
        if kind == "start":
            started = True
        elif kind == "turn":
            turn = True
        elif kind == "switch" and started and line.split("|")[2][:2] == f"p{side + 1}":
            parts = line.split("|")
            try:
                base = data.base_forme(data.forme(parts[3].split(",")[0]))
            except ValueError:
                continue  # A forme changed on the bench; the member entered earlier in its own forme.
            if roster.count(base) != 1:
                raise lines.Stop(f"structure:{parts[2]} is not one member of its sheet")
            member = roster.index(base)
            if not turn:
                leads["ab".index(parts[2][2])] = member
            seen.add(member)
    if None in leads:
        raise lines.Stop("structure:no two leads at |start|")
    return tuple(leads), seen - set(leads)


def hindsight_picks(log, side, data, sheets):
    """Return the leads and the two visible back Pokemon, or None when the back is not observable."""
    leads, back = hindsight(log, side, data, sheets)
    if len(back) != BROUGHT - 2:
        return None
    return leads + tuple(sorted(back))
