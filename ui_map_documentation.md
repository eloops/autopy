# UI Map Documentation (`ui_map.json`)

This was generated with an LLM (Kagi Quick). All the updates to code.py and ui_map.json were written with help from same.

---

## 1. Global options (top of the file)

These live at the start of `ui_map.json`, before the `"screens"` section.

### `screen`

```json
"screen": { "width": 1920, "height": 720 }
```

The resolution of the infotainment screen, in pixels.

| Option | What it is | What it affects |
|---|---|---|
| `width` | Screen width in pixels | Used by the **zero reset**: the cursor starts each run by moving `-width` and `-height` from wherever it is, guaranteeing it ends up in the top-left corner (0,0). If this is wrong, the zero reset lands somewhere random and every subsequent click is offset. |
| `height` | Screen height in pixels | Same — the vertical half of the zero reset. |

### `units_per_mm`

```json
"units_per_mm": 8
```

**How many mouse units equal one millimetre of cursor travel on the screen.**
This is the *pixel density* figure — it converts real-world measurements (taken
with a ruler on the screen) into the mouse units that the HID protocol actually
sends.

It affects **every single movement**: all target coordinates in the map are
pixels, and the code converts pixels to mouse units using this number. If it's
wrong, every move is proportionally stretched or squeezed — a button at the
right side of the screen will be over- or under-shot. See section 3 for how to
measure it.

### `movement`

All cursor movement timing. These exist because the infotainment applies mouse
acceleration — a long fast move travels further than the sum of its parts — so
long moves are split into small chunks with pauses, which the target can't
accelerate.

| Option | Default | What it is / what it affects |
|---|---|---|
| `max_chunk_units` | `100` | Maximum size of each chunk, in mouse units. Every long move is broken into pieces of at most this size. Bigger = faster but more prone to acceleration distortion. |
| `chunk_pause_ms` | `50` | Pause between chunks. Long enough that the target treats each chunk as a separate small move (no acceleration). |
| `settle_ms` | `200` | Minimum pause after any move, click, or macro step, everywhere. This is the global "give the system time" floor — it can never go below 200 ms even if you set it lower. |
| `screen_load_ms` | `600` | How long to wait **after clicking into a screen, before scrolling it**. The screen needs time to finish loading before a wheel event will register — too short and the scroll silently doesn't happen. |

### `scroll`

| Option | Default | What it is / what it affects |
|---|---|---|
| `ticks` | `800` | How many wheel ticks per scroll command. One scroll = this many ticks at once. Must be enough to get from one end of the list to the other. |
| `settle_ms` | `500` | How long to wait after scrolling, before the next click. The list animates to its new position; clicking mid-animation hits whatever is under the cursor at that moment, not the intended button. |

> **Rule of thumb for all the timing values:** if a click lands on the wrong
> thing, it's almost always one of these three (`settle_ms`, `screen_load_ms`,
> `scroll.settle_ms`) being too short for that situation — and cold boots are
> slower than warm ones, so leave margin.

---

## 2. Building the menu structure

The map describes the infotainment UI as a **tree of screens**. Each screen can
contain:

- **`targets`** — buttons that live on that screen. Each has a name and pixel
  coordinates.
- **`views`** — alternative "states" of the same screen (e.g. a list scrolled to
  the top vs. the bottom, or tabs). Each view has its own `targets`.
- **`enter`** — *only if the screen is reachable by clicking something* — which
  button opens it (`target`) and from which screen (`parent`).

### The mental model

```
main ── applications ── vehicle_settings ── settings_list ── intelligent_driving ── lane_assist
                                                  │
                                                  ├─ in_car (tabs: cabin, driver_seat)
                                                  └─ driving
```

The code walks this tree automatically: to reach any button, it goes **up** to
`main` (via the persistent Home button) if needed, then **down** through each
`enter` click, scrolling or switching tabs to the right view along the way. You
never write the navigation steps yourself — you describe the layout once, and
`go("any_button_name")` figures out the path.

### A short example

```json
"screens": {
  "main": {
    "targets": {
      "home":         { "x": 1850, "y": 88 },
      "applications": { "x": 1850, "y": 208 }
    }
  },

  "applications": {
    "enter": { "target": "applications", "parent": "main" },
    "targets": {
      "vehicle_settings": { "x": 720, "y": 528 }
    }
  },

  "settings_list": {
    "enter": { "target": "settings_list", "parent": "vehicle_settings" },
    "scrollable": true,
    "views": {
      "top": {
        "targets": { "in_car": { "x": 1635, "y": 318 } }
      },
      "bottom": {
        "targets": { "intelligent_driving": { "x": 1635, "y": 513 } }
      }
    }
  },

  "in_car": {
    "enter": { "target": "in_car", "parent": "settings_list", "parent_view": "top" },
    "targets": {
      "cabin_tab": { "x": 635, "y": 168, "sets_view": "cabin" }
    },
    "views": {
      "cabin": {
        "switch": "cabin_tab",
        "targets": { "dms_toggle": { "x": 1371, "y": 268 } }
      }
    }
  }
}
```

### Field reference

| Field | Where | Meaning |
|---|---|---|
| `x`, `y` | any target | Pixel coordinates of the button. `x` is from the left edge, `y` is from the top. |
| `enter.target` | screen | The name of the button (on the parent screen) that opens this screen. |
| `enter.parent` | screen | Which screen that button lives on. `main` is the root of the tree. |
| `enter.parent_view` | screen | Optional: which *view* the parent must be in for the button to be visible/valid (e.g. `settings_list` must be scrolled to `"top"` before the `in_car` entry is clickable). |
| `scrollable: true` | screen | This screen's views are switched by **scrolling**. |
| `views.<name>.switch` | view | For **tabbed** screens: the name of the tab button that activates this view. |
| `sets_view` | target | Clicking this button switches its screen to that view (tab buttons use this). |
| `terminal: true` | target | After clicking this, the UI state becomes unpredictable (e.g. CarPlay takes over). The engine resets to (0,0) and marks its state as unknown. |
| `wait_before` | target | Seconds to wait before clicking this target (e.g. a confirmation dialog that appears after a delay). |

### Rules to keep it consistent

- Every screen except `main` needs an `enter` — otherwise the engine can't build
  a path to it and will log an error.
- A target's name is global and unique; your macros refer to buttons by these
  names.
- Scroll direction mapping is fixed in code: scrolling `up` reaches the
  **bottom** view, `down` reaches the **top** (this matches observed behavior —
  scrolling up means the list content moves up, revealing the bottom).
- Coordinates are always **pixel** values in the map; the `units_per_mm`
  conversion happens inside the code.

---

## 3. How to determine screen pixel density (`units_per_mm`)

The idea: measure, with a physical ruler on the screen, how far the cursor
travels for a known number of mouse units — then divide.

**Method:**

1. Put the cursor on a known starting point — the easiest is the zero reset
   position: top-left corner (0,0). (Run a `zero` step, or just let the macro's
   initial reset do it.)
2. Perform a precise, known move — e.g. send a single `mover` step of
   `dx: 1000, dy: 0` (1000 mouse units right).
3. **Measure with a ruler** how many millimetres the cursor moved on the screen.
4. Compute: `units_per_mm = mouse units sent ÷ mm measured`

**Example:** if 1000 units moved the cursor 125 mm, then
`units_per_mm = 1000 / 125 = 8`.

**Tips for accuracy:**

- Use a large move (1000+ units) — measurement error matters less
  proportionally.
- Do it 2–3 times and average.
- Make sure the move is done as **one chunk** for the measurement (temporarily
  raise `max_chunk_units` above the test distance, e.g. 2000), so you're
  measuring pure 1:1 travel with no pauses involved. Restore the value
  afterwards.
- Your screen resolution divided by `units_per_mm` should roughly equal the
  physical dots-per-mm of the display — a sanity check if you know the screen's
  physical dimensions.

---

## 4. Suggested test configuration for probing coordinates

Add a dedicated **probe section** to `macro.json` (toggled with `active`, just
like the boot delay). It moves the cursor to candidate coordinates in small
steps and pauses, so you can see exactly where each lands and nudge the values
in `ui_map.json` until each click hits its button.

```json
{
  "config": {
    "reset_pointer_at_start": true,
    "delay_between_steps_ms": 200
  },
  "sections": [
    {
      "description": "Boot delay",
      "active": false,
      "steps": [
        { "type": "wait", "seconds": 45 }
      ]
    },
    {
      "description": "PROBE - coordinates test",
      "active": true,
      "steps": [
        { "type": "zero" },
        { "type": "wait", "seconds": 1 },

        { "type": "go", "target": "applications" },
        { "type": "wait", "seconds": 1 },
        { "type": "go", "target": "vehicle_settings" },
        { "type": "wait", "seconds": 1 },
        { "type": "go", "target": "settings_list" },
        { "type": "wait", "seconds": 2 },

        { "type": "go", "target": "in_car" },
        { "type": "wait", "seconds": 1 },
        { "type": "go", "target": "dms_toggle" },
        { "type": "wait", "seconds": 1 },
        { "type": "go", "target": "cabin_tab" }
      ]
    }
  ]
}
```

### How to use it

1. **Set every other section `active: false`** and only the probe section
   `active: true` — this keeps the probe isolated.
2. Plug the board into the car's USB (or a bench setup) and watch where the
   cursor lands at each step.
3. **No clicking needed for pure coordinate probing:** if you only want to see
   where a coordinate lands *without* activating anything, temporarily point
   the `go` steps at harmless targets, or — for a quick eyeball — use legacy
   `mover` steps (`{"tipo": "mover", "dx": ..., "dy": ...}`) to move to the
   candidate position and just look.
4. When a click lands off-center on its button, adjust that target's `x`/`y` in
   `ui_map.json` by the pixel error you observed, and re-run. Iterate until
   each cursor parks dead-center on its button.
5. **Keep the serial console open during bench probes** — the log prints every
   `Enter screen`, `Scroll`, and `Click 'name' at (x,y)` line, so you always
   know where the engine *thinks* it is while you watch where the cursor
   actually is. Any mismatch tells you exactly which target's coordinates to
   fix.

### Probing new buttons — workflow

1. Manually drive to the screen in the car and note roughly where the button is.
2. Add a tentative target entry in `ui_map.json` (rough coordinates, e.g.
   nearest 50 px).
3. Add a `go` step for it in the probe section.
4. Run, observe the miss, correct the coordinates, repeat. Two or three
   iterations typically gets a button dead-center.

---

## Quick troubleshooting reference

| Symptom | Most likely cause | Fix |
|---|---|---|
| Scroll doesn't happen at all | Wheel event sent while screen is still loading | Raise `screen_load_ms` |
| Click lands on wrong list item after scrolling | List still animating | Raise `scroll.settle_ms` |
| Click lands on wrong menu after entering a screen | Screen still loading | Raise `settle_ms` |
| Everything lands offset by the same amount | Wrong `units_per_mm` | Re-measure density (section 3) |
| Cursor doesn't reach the far side of the screen | `screen.width/height` too small | Fix resolution |
| Long moves overshoot | Acceleration | Lower `max_chunk_units` or raise `chunk_pause_ms` |
| Works warm, fails on cold boot | System slower when busy | Add margin to boot wait and timing values |
