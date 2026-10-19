# BreatheWell

A local-first asthma self-management workspace. It records symptoms, reliever inhaler use, peak-flow readings, possible triggers, notes, and the date of an observation. Its interactive 3D lung view can be rotated and played across a 30-day timeline, so the selected day and its readings change during playback.

Python serves the app, stores entries in SQLite, builds daily aggregates and descriptive summaries, counts logged trigger days, compares earlier and later observations when enough data exists, and exports the full record as CSV. The summaries describe user-entered data; they do not establish causes or make medical recommendations.

This is a personal record-keeping tool, not a diagnostic or treatment system. It does not interpret readings or recommend medication changes. Users should follow their own clinician-provided asthma action plan and seek emergency help for severe breathing trouble.

## Run it

Requires Python 3.10 or later; no Python packages are needed.

```bash
python main.py
```

Open <http://127.0.0.1:8001>. Entries are stored in `breathewell.db` in this folder. The 3D lungs use the browser's built-in WebGL support, so the core app does not need a remote JavaScript library. To use another port, set the `BREATHEWELL_PORT` environment variable before starting the server.

## API

- `GET /api/health` — service status
- `GET /api/entries` — recent check-ins
- `GET /api/analytics?days=30` — daily timeline and descriptive aggregates (7–90 days)
- `GET /api/export.csv` — download the full record
- `POST /api/entries` — save a check-in
- `DELETE /api/entries/{id}` — delete a check-in

The development server binds to localhost only. Before making this a public or multi-user service, add authentication, HTTPS, access controls, backup/retention choices, and a security review.
