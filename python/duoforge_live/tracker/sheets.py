"""What lines.check reads: sheets, abilities and items of the members.

Part of the duoforge_live.tracker package (split by fold family from the former tracker.py, restructure
step 7); the package re-exports every name of the former module.
"""

from .. import lines
from .constants import ITEM_NOW_NONE, MOVE_SLOT_NONE, REVEALED_ITEM_CONSUMED, ROSTER_NONE


class _SheetReads:
    # ------------------------------------------------------------------ what lines.check reads
    def sheet_of(self, ident):
        """The sheet of the member a protocol ident ("p1a: Name") names."""
        return self._member_of(ident).sheet

    def known_sheet(self, ident):
        """The sheet of the member a protocol ident names, or None before its name was seen."""
        side, name = int(ident[1]) - 1, ident.split(": ", 1)[1]
        index = self._names[side].get(name)
        return None if index is None else self._member(side)[index].sheet

    def side_sheets(self, ident):
        """The open sheets of every member of the side a protocol ident names (lines.check: a possible Illusion)."""
        return [m.sheet for m in self._member(int(ident[1]) - 1)]

    def ability_now(self, ident):
        """The current ability + 1 of the member a protocol ident names: the one Trace or Skill Swap gave it while it
        stands at the ident's position, else its own (the sheet's, or its Mega forme's)."""
        member = self._member_of(ident)
        pos = lines.flat_position(ident)
        if pos is not None:
            p = self._at(pos)
            if p.ability_now and p.occupant != ROSTER_NONE and self._member(pos // 2)[p.occupant] is member:
                return p.ability_now
        return member.ability

    def _ability_at(self, pos):
        """The current ability + 1 of the occupant of flat position `pos` (ability_now)."""
        p = self._at(pos)
        return p.ability_now or self._member(pos // 2)[p.occupant].ability

    def item_now(self, ident):
        """The item + 1 the member a protocol ident names holds as far as the lines showed, used up or not (lines.check:
        a line about the holder's own item): the one a move or Symbiosis gave it, 0 after one took it, else the
        sheet's."""
        return self._item_of(self._member_of(ident))

    @staticmethod
    def _item_of(member):
        if member.item_now == ITEM_NOW_NONE:
            return 0
        return member.item_now or member.sheet["item"]

    def _holds(self, member, key):
        """Whether `member` holds the item of ITEM table key `key` now, as far as the lines showed: not seen used up or
        lost (item_used), the sheet's item or the one a move gave it."""
        item = self.data.tables["ITEM"].get(key)
        return item is not None and self._holds_id(member, item)

    def _holds_id(self, member, item):
        """_holds by the item's id (an ITEM id, the engine's: the library's rows are the converter's tables)."""
        return not member.item_used and self._item_of(member) == item + 1

    def _item_received(self, pos, code, public):
        """The occupant of `pos` now holds the item `code` (+ 1) that a move or Symbiosis gave it: its old item is no
        longer gone, and a Choice item ends its lock (the item's onStart; dfi_set_held)."""
        m = self._occupant(pos)
        m.item_now = code
        m.revealed &= ~REVEALED_ITEM_CONSUMED
        m.item_consumed = 0
        if public:
            m.item_used = 0
        if code in self._choice_items:
            self._at(pos).choice_slot = MOVE_SLOT_NONE

    def _member_of(self, ident):
        side, name = int(ident[1]) - 1, ident.split(": ", 1)[1]
        if name not in self._names[side]:
            raise lines.Stop(f"structure:{ident} names no member seen yet")
        return self._member(side)[self._names[side][name]]
