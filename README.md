# BoardView

Read-only on-screen view of the MainBoard bookings, laid out like the Digital Board Manager.

```
pip install -r requirements.txt
python boardview.py          # live data from the Access DB (edit ACCDB_PATH / BOARDS at the top)
python boardview.py --demo   # fake data, no database needed
```

- Tabs across the top = boards (`BOARDS` maps tab name -> OfficeID)
- Previous / Next (or PageUp / PageDown), Jump To a date, Today, Refresh (F5)
- Click a booking to see job, PM, postcode, hours and flags in the Cell info bar
- Red = provisional, yellow = WRSREQ, red text on yellow = both; HOLS / SICK / BHOL / UNPD in red
