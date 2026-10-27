"""
Engineers... window: choose which board each engineer shows on, hide
engineers, and add / remove / reorder boards.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from boardsettings import UNASSIGNED


class EngineersDialog(tk.Toplevel):
    def __init__(self, master, settings, engineers, default_board_of, on_save, note=""):
        """
        engineers        : names to list (DB + already-known)
        default_board_of : name -> board they'd show on if left unassigned (or None)
        on_save          : called after settings are saved
        """
        super().__init__(master)
        self.title("Engineers & boards")
        self.geometry("820x560")
        self.transient(master)
        self.settings = settings
        self.default_board_of = default_board_of
        self.on_save = on_save
        self.names = sorted(set(engineers) | set(settings.known_engineers()))

        # work on a copy; only written back on Save
        self.boards = list(settings.boards)
        self.assign = {n: settings.board_of(n) for n in self.names}
        self.hidden = {n: settings.is_hidden(n) for n in self.names}

        self.filter_var = tk.StringVar()
        self.show_var = tk.StringVar(value="All boards")
        self.board_var = tk.StringVar()

        self._build(note)
        self._refresh_boards()
        self._refresh_list()
        self.filter_var.trace_add("write", lambda *a: self._refresh_list())
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    # -- layout
    def _build(self, note):
        top = ttk.Frame(self, padding=(10, 10, 10, 0)); top.pack(fill="x")
        ttk.Label(top, text="Search:").pack(side="left")
        e = ttk.Entry(top, textvariable=self.filter_var, width=24); e.pack(side="left", padx=(4, 12))
        e.focus_set()
        ttk.Label(top, text="Show:").pack(side="left")
        self.show_combo = ttk.Combobox(top, textvariable=self.show_var, state="readonly", width=16)
        self.show_combo.pack(side="left", padx=4)
        self.show_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_list())
        if note:
            ttk.Label(top, text=note, foreground="#a33").pack(side="left", padx=10)

        mid = ttk.Frame(self, padding=10); mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=1); mid.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(mid, columns=("board", "shown"), selectmode="extended")
        self.tree.heading("#0", text="Engineer")
        self.tree.heading("board", text="Board")
        self.tree.heading("shown", text="Shown")
        self.tree.column("#0", width=230)
        self.tree.column("board", width=170)
        self.tree.column("shown", width=60, anchor="center")
        self.tree.tag_configure("hidden", foreground="#999")
        self.tree.tag_configure("auto", foreground="#555")
        vs = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self.board_combo.focus_set())

        side = ttk.Frame(mid, padding=(12, 0, 0, 0)); side.grid(row=0, column=2, sticky="ns")

        box = ttk.LabelFrame(side, text="Selected engineers", padding=8); box.pack(fill="x")
        ttk.Label(box, text="Put on board:").pack(anchor="w")
        self.board_combo = ttk.Combobox(box, textvariable=self.board_var, state="readonly", width=18)
        self.board_combo.pack(fill="x", pady=(2, 4))
        self.board_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_board())
        ttk.Button(box, text="Hide from boards", command=lambda: self._set_hidden(True)).pack(fill="x", pady=2)
        ttk.Button(box, text="Show on boards", command=lambda: self._set_hidden(False)).pack(fill="x", pady=2)
        ttk.Label(box, text="Tip: Ctrl/Shift-click to\nselect several at once.",
                  foreground="#666").pack(anchor="w", pady=(6, 0))

        bbox = ttk.LabelFrame(side, text="Boards (tab order)", padding=8); bbox.pack(fill="both", expand=True, pady=(10, 0))
        self.board_list = tk.Listbox(bbox, height=8, exportselection=False)
        self.board_list.pack(fill="both", expand=True)
        row = ttk.Frame(bbox); row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Add…", width=6, command=self._add_board).pack(side="left")
        ttk.Button(row, text="Remove", width=7, command=self._remove_board).pack(side="left", padx=2)
        ttk.Button(row, text="▲", width=3, command=lambda: self._move_board(-1)).pack(side="left")
        ttk.Button(row, text="▼", width=3, command=lambda: self._move_board(1)).pack(side="left")

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10)); bottom.pack(fill="x")
        ttk.Label(bottom, text="Board in (brackets) = not set yet, picked from the booking's OfficeID.",
                  foreground="#666").pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Save", command=self._save).pack(side="right", padx=6)

    # -- refresh
    def _refresh_boards(self):
        self.board_list.delete(0, "end")
        for b in self.boards:
            self.board_list.insert("end", b)
        self.board_combo["values"] = self.boards + [UNASSIGNED]
        self.show_combo["values"] = ["All boards"] + self.boards + [UNASSIGNED, "Hidden"]
        if self.show_var.get() not in self.show_combo["values"]:
            self.show_var.set("All boards")

    def _effective(self, n):
        b = self.assign.get(n)
        if b in self.boards:
            return b, False
        d = self.default_board_of(n)
        return (d, True) if d in self.boards else (UNASSIGNED, False)

    def _refresh_list(self):
        sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        q = self.filter_var.get().strip().upper()
        show = self.show_var.get()
        for n in self.names:
            board, auto = self._effective(n)
            hidden = self.hidden.get(n, False)
            if q and q not in n:
                continue
            if show == "Hidden" and not hidden:
                continue
            if show not in ("All boards", "Hidden") and board != show:
                continue
            self.tree.insert("", "end", iid=n, text=n,
                             values=(f"({board})" if auto else board, "no" if hidden else "yes"),
                             tags=("hidden",) if hidden else ("auto",) if auto else ())
        self.tree.selection_set([n for n in sel if self.tree.exists(n)])

    # -- actions
    def _selected(self):
        names = list(self.tree.selection())
        if not names:
            messagebox.showinfo("Engineers", "Select one or more engineers first.", parent=self)
        return names

    def _apply_board(self):
        board = self.board_var.get()
        for n in self._selected():
            self.assign[n] = None if board == UNASSIGNED else board
        self._refresh_list()

    def _set_hidden(self, hidden):
        for n in self._selected():
            self.hidden[n] = hidden
        self._refresh_list()

    def _add_board(self):
        name = simpledialog.askstring("Add board", "Board name:", parent=self)
        name = (name or "").strip()
        if name and name != UNASSIGNED and name not in self.boards:
            self.boards.append(name)
            self._refresh_boards(); self._refresh_list()

    def _remove_board(self):
        sel = self.board_list.curselection()
        if not sel:
            return
        board = self.boards[sel[0]]
        count = sum(1 for n in self.names if self.assign.get(n) == board)
        if not messagebox.askyesno("Remove board",
                                   f"Remove the '{board}' tab?\n{count} engineer(s) on it become Unassigned.",
                                   parent=self):
            return
        self.boards.remove(board)
        for n in self.names:
            if self.assign.get(n) == board:
                self.assign[n] = None
        self._refresh_boards(); self._refresh_list()

    def _move_board(self, step):
        sel = self.board_list.curselection()
        if not sel:
            return
        i = sel[0]; j = max(0, min(len(self.boards) - 1, i + step))
        self.boards[i], self.boards[j] = self.boards[j], self.boards[i]
        self._refresh_boards()
        self.board_list.selection_set(j)

    def _save(self):
        s = self.settings
        s["boards"] = list(self.boards)
        for n in self.names:
            s.set_board(n, self.assign.get(n))
            s.set_hidden(n, self.hidden.get(n, False))
        try:
            s.save()
        except OSError as e:
            messagebox.showerror("Save", f"Could not save settings:\n{e}", parent=self)
            return
        self.destroy()
        self.on_save()
