"""
Your own BoardView settings (which board each engineer sits on, your
initials, zoom...).  Kept in boardview_settings.json next to this file -
never in the Access database.
"""
import json, os

from boarddata import name_key

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boardview_settings.json")
UNASSIGNED = "Unassigned"

DEFAULT_BOARDS = ["London", "Surge", "East", "West", "South"]

# First run only: these start on the London board.
SEED = {"London": [
    "ACQUAYE, ISAAC", "ALBERTELLI, JADEN", "DUNN, KALLAM", "FAULKNER, JASON",
    "GRAY, BILLY", "HUMPHREYS, CONNOR", "HUMPHREYS, STEPHEN",
    "JANES, DANIEL", "JANES, PETER", "JOYCE, ADAM", "MCKEOWN, ELLIOT",
    "RODELL, WILLIAM", "SMITH, JAKE", "WELCH, LEE", "YIANNOPOULOS, MARCO",
]}


class Settings:
    def __init__(self, path=SETTINGS_PATH):
        self.path = path
        self.load_error = None
        self.data = {
            "boards": list(DEFAULT_BOARDS),
            "engineers": {},          # NAME -> {"board": str|None, "hidden": bool}
            "my_initials": "",
            "mine_only": False,
            "zoom": 1.0,
            "last_board": None,
        }
        self.load()

    # -- file
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except FileNotFoundError:
            for board, names in SEED.items():
                for n in names:
                    self.set_board(n, board)
        except (OSError, ValueError) as e:
            # keep the broken file for inspection; carry on with defaults
            self.load_error = f"{self.path} could not be read ({e}); started with defaults."
            try: os.replace(self.path, self.path + ".bad")
            except OSError: pass

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # -- simple values
    def __getitem__(self, k): return self.data[k]
    def __setitem__(self, k, v): self.data[k] = v

    @property
    def boards(self): return self.data["boards"]

    def my_initials(self):
        raw = self.data.get("my_initials", "").replace(",", " ").upper().split()
        return set(raw)

    # -- engineers
    def _eng(self, name):
        return self.data["engineers"].setdefault(name_key(name), {"board": None, "hidden": False})

    def known_engineers(self):
        return sorted(self.data["engineers"])

    def board_of(self, name):
        e = self.data["engineers"].get(name_key(name))
        b = e and e.get("board")
        return b if b in self.boards else None

    def is_hidden(self, name):
        e = self.data["engineers"].get(name_key(name))
        return bool(e and e.get("hidden"))

    def set_board(self, name, board):
        self._eng(name)["board"] = None if board in (None, UNASSIGNED) else board

    def set_hidden(self, name, hidden):
        self._eng(name)["hidden"] = bool(hidden)

    def pinned_to(self, board):
        """Engineers assigned to this board (shown even with no bookings)."""
        return [n for n, e in self.data["engineers"].items()
                if e.get("board") == board and not e.get("hidden")]
