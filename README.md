# BoardView

Read-only on-screen view of the MainBoard bookings, laid out like the Digital Board Manager.
Nothing is written to the Access database.

```
pip install -r requirements.txt
python boardview.py          # live data (edit ACCDB_PATH / OFFICE_CODES at the top of boarddata.py)
python boardview.py --demo   # fake data, no database needed
```

## Boards and engineers
Each tab (London, Surge, East, West, South...) shows the engineers **you** put on it, with all
their bookings for the week, whatever office the job is in.

- **Right-click an engineer** -> *Show on West* (etc.) to move them. *Hide this engineer* removes them from every board.
- **Engineers & boards...** (top right) lists every engineer: select one or several, pick a board,
  hide/show them, and add / remove / reorder the board tabs. Press **Save**.
- Engineers you haven't placed yet go on the board matching their bookings' OfficeID
  (`OFFICE_CODES` in `boarddata.py`), otherwise on the orange **Unassigned** tab.
- An engineer you've placed on a board stays on it every week, even with no bookings.

These choices are saved in `boardview_settings.json` next to the script (not in the database).

## Finding your jobs
- Type your initials in **My initials** (e.g. `AR`; several allowed: `AR AT`). Your bookings get a
  green outline, bold text and a green bar, and each engineer shows a green "N mine" badge.
- **Only my jobs** greys out everything else.
- **Find** highlights bookings matching a job number, postcode or initials and greys out the rest.

## Viewing
- Previous / Next (or PageUp / PageDown), This week, Jump to a date, Refresh (F5)
- Zoom: `-` / `+` buttons, Ctrl + / Ctrl -, Ctrl + mouse wheel, Ctrl+0 to reset
- Ctrl+1..9 switches tabs; Ctrl+F jumps to Find
- Hover a booking for details, click to show them in the bottom bar, double-click to copy the job number
- Today's column is green; the engineer names and day headers stay put while you scroll

Colours: red = provisional, yellow = WRSREQ, red text on yellow = both, HOLS / SICK / BHOL / UNPD in red.
