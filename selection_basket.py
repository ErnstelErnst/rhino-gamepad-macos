"""Selection basket with reversible, per-element mutations. No Rhino imports.

A basket is intentionally separate from Rhino's document-wide selection.
``apply(entry, state)`` and ``is_selected(entry)`` are supplied by the Rhino
adapter. The initial selection state is retained for each touched element so
removing it from the basket does not erase a prior manual Rhino selection.
"""

from copy import copy

KINDS = ('object', 'curve', 'face', 'edge')


def identity(entry):
    if not isinstance(entry, dict):
        return None
    kind = str(entry.get('kind', ''))
    if kind not in KINDS or not entry.get('id'):
        return None
    index = int(entry.get('index', -1))
    if kind in ('face', 'edge') and index < 0:
        return None
    return (str(entry['id']), kind, index)


class SelectionBasket:
    def __init__(self):
        self._entries = {}  # identity -> entry; insertion order is selection order
        self._baseline = {}  # identity -> Rhino selected before first basket action
        self._history = []  # (identity, entry, action): action is 'add' or 'remove'

    def __len__(self):
        return len(self._entries)

    def entries(self):
        return [copy(e) for e in self._entries.values()]

    def contains(self, entry):
        return identity(entry) in self._entries

    def counts(self):
        result = {}
        for e in self._entries.values():
            kind = e['kind']
            result[kind] = result.get(kind, 0) + 1
        return result

    def toggle(self, entry, is_selected, apply):
        """Change basket iff associated Rhino selection mutation succeeds.

        On REMOVE the element returns to its state before basket management,
        preserving any independently selected geometry.
        """
        ident = identity(entry)
        if ident is None:
            return None
        if ident not in self._baseline:
            self._baseline[ident] = bool(is_selected(entry))
        old_state = self._baseline[ident]
        if ident in self._entries:
            if not old_state and not apply(entry, False):
                return None
            previous = self._entries.pop(ident)
            self._history.append((ident, previous, 'remove'))
            return 'removed'
        if not old_state and not apply(entry, True):
            return None
        self._entries[ident] = copy(entry)
        self._history.append((ident, copy(entry), 'add'))
        return 'added'

    def undo(self, apply):
        """Undo the most recent basket action; do not pop on failed mutation."""
        if not self._history:
            return None
        ident, entry, action = self._history[-1]
        old_state = self._baseline[ident]
        if action == 'add':
            if not old_state and not apply(entry, False):
                return None
            self._entries.pop(ident, None)
            change = 'undid add'
        else:
            if not old_state and not apply(entry, True):
                return None
            self._entries[ident] = copy(entry)
            change = 'undid remove'
        self._history.pop()
        return change

    def reset(self):
        """Forget basket without changing Rhino selection (e.g. on stop)."""
        self._entries.clear()
        self._history.clear()
        self._baseline.clear()
