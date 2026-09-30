import time, json
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_hid.mouse import Mouse

kbd = Keyboard(usb_hid.devices)
mouse = Mouse(usb_hid.devices)

# ============================================================
# Low-level helpers
# ============================================================
def log(msg):
    print(f"[{time.monotonic():.2f}] {msg}")

def yes_no(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower().replace("í", "i")
    return s in ("si", "s", "yes", "y", "true", "1", "on")

def alt_esc():
    kbd.press(Keycode.LEFT_ALT, Keycode.ESCAPE)
    time.sleep(0.05)
    kbd.release_all()

def home_key(times=1):
    for _ in range(max(0, int(times))):
        alt_esc()
        time.sleep(0.25)

# ============================================================
# Load the UI map (ALL movement/scroll tuning lives here)
# ============================================================
with open("ui_map.json", "r") as f:
    ui_map = json.load(f)

SCREEN_W = int(ui_map["screen"]["width"])
SCREEN_H = int(ui_map["screen"]["height"])

MOVEMENT = ui_map.get("movement", {})
MAX_MOVE_UNITS = int(MOVEMENT.get("max_chunk_units", 100))
CHUNK_PAUSE_S = float(MOVEMENT.get("chunk_pause_ms", 50)) / 1000.0
SETTLE_MS = max(200, int(MOVEMENT.get("settle_ms", 200)))
SCREEN_LOAD_S = max(SETTLE_MS, int(MOVEMENT.get("screen_load_ms", 600))) / 1000.0

SCROLL_CFG = ui_map.get("scroll", {})
SCROLL_TICKS = int(SCROLL_CFG.get("ticks", 800))
SCROLL_SETTLE_S = max(SETTLE_MS, int(SCROLL_CFG.get("settle_ms", 500))) / 1000.0

SCREENS = ui_map["screens"]

def move_rel(dx, dy, delay_ms=SETTLE_MS):
    """Chunked relative move: big moves split into <=MAX_MOVE_UNITS
    sub-moves with CHUNK_PAUSE_S between them so the target's mouse
    acceleration cannot distort them."""
    dx, dy = int(dx), int(dy)
    remaining_x, remaining_y = dx, dy
    while remaining_x != 0 or remaining_y != 0:
        step_x = max(-MAX_MOVE_UNITS, min(MAX_MOVE_UNITS, remaining_x))
        step_y = max(-MAX_MOVE_UNITS, min(MAX_MOVE_UNITS, remaining_y))
        mouse.move(step_x, step_y)
        remaining_x -= step_x
        remaining_y -= step_y
        time.sleep(CHUNK_PAUSE_S)
    time.sleep(max(delay_ms, 200) / 1000.0)

def scroll(direction, ticks):
    ticks = int(ticks)
    direction = (direction or "").strip().lower()
    if direction in ("arriba", "up"):
        mouse.move(wheel=-abs(ticks))
    else:  # "abajo" / "down"
        mouse.move(wheel=abs(ticks))
    time.sleep(SCROLL_SETTLE_S)

# ============================================================
# Virtual cursor + navigation state
# ============================================================
class Cursor:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.x, self.y = 0, 0

    def reset(self):
        move_rel(-self.width, -self.height, delay_ms=SETTLE_MS)
        self.x, self.y = 0, 0

    def go_to(self, x, y, delay_ms=SETTLE_MS):
        move_rel(x - self.x, y - self.y, delay_ms)
        self.x, self.y = x, y

    def click_abs(self, x, y):
        self.go_to(x, y)
        mouse.click(Mouse.LEFT_BUTTON)
        time.sleep(0.2)

cursor = Cursor(SCREEN_W, SCREEN_H)

state = {"screen": "main", "view": None, "known": True}

# Index: target name -> (screen, view or None, target dict)
TARGET_INDEX = {}
for scr_name, scr in SCREENS.items():
    for tgt_name, tgt in scr.get("targets", {}).items():
        TARGET_INDEX[tgt_name] = (scr_name, None, tgt)
    for view_name, view in scr.get("views", {}).items():
        for tgt_name, tgt in view.get("targets", {}).items():
            TARGET_INDEX[tgt_name] = (scr_name, view_name, tgt)

# Index: target name -> screen it opens
OPENS_SCREEN = {}
for scr_name, scr in SCREENS.items():
    entry = scr.get("enter")
    if entry:
        OPENS_SCREEN[entry["target"]] = scr_name

# Observed behavior: scroll "up" 800 -> bottom view; "down" 800 -> top view.
VIEW_SCROLL = {"bottom": "up", "top": "down"}

def enter_path(screen_name):
    """Return the chain of screens from 'main' down to screen_name."""
    chain = []
    name = screen_name
    while name != "main":
        scr = SCREENS.get(name)
        if scr is None or "enter" not in scr:
            log(f"ERROR: no 'enter' defined for screen '{name}'")
            return None
        chain.insert(0, name)
        name = scr["enter"]["parent"]
    return chain

def ensure_view(screen_name, view_name):
    """Ensure screen_name is showing the needed view. Scrollable
    screens switch views by scrolling; tabbed screens by clicking
    the tab target named in the view's 'switch'."""
    if state["screen"] != screen_name:
        navigate_to_screen(screen_name)
    if state.get("view") == view_name:
        return
    scr = SCREENS[screen_name]
    if scr.get("scrollable"):
        direction = VIEW_SCROLL.get(view_name)
        if direction is None:
            log(f"WARN: unknown view '{view_name}', skipping scroll")
            return
        time.sleep(SCREEN_LOAD_S)   # let the screen finish loading first
        log(f"Scroll {direction} {SCROLL_TICKS} for view '{view_name}'")
        scroll(direction, SCROLL_TICKS)
        state["view"] = view_name
    else:
        view = scr.get("views", {}).get(view_name)
        if not view or "switch" not in view:
            log(f"WARN: no way to reach view '{view_name}' on '{screen_name}'")
            return
        log(f"Switch to view '{view_name}' via tab '{view['switch']}'")
        tgt = TARGET_INDEX[view["switch"]][2]
        cursor.click_abs(int(tgt["x"]), int(tgt["y"]))
        state["view"] = view_name

def navigate_to_screen(screen_name):
    """Click our way from the current screen to screen_name."""
    if not state["known"]:
        log("State unknown -> zero reset before navigating")
        cursor.reset()
        state["screen"], state["view"], state["known"] = "main", None, True

    if state["screen"] == screen_name:
        return

    chain = enter_path(screen_name)
    if chain is None:
        return

    # --- Ascent: if we're on a screen not on the destination path,
    # return to main via the persistent Home button first. ---
    path_screens = set(chain) | {"main"}
    if state["screen"] not in path_screens:
        home_tgt = TARGET_INDEX.get("home")
        if home_tgt:
            log(f"Ascending to main via Home button from '{state['screen']}'")
            cursor.click_abs(int(home_tgt[2]["x"]), int(home_tgt[2]["y"]))
        else:
            log("No 'home' target defined -> using Alt+Esc")
            home_key(1)
        state["screen"], state["view"] = "main", None

    # --- Descent: walk the enter chain top-down. ---
    for name in chain:
        scr = SCREENS[name]
        entry = scr["enter"]
        parent = entry["parent"]
        if state["screen"] != parent:
            navigate_to_screen(parent)
        parent_view = entry.get("parent_view")
        if parent_view and (SCREENS[parent].get("scrollable")
                            or SCREENS[parent].get("views")):
            ensure_view(parent, parent_view)
        log(f"Enter screen '{name}' via target '{entry['target']}'")
        tgt = TARGET_INDEX[entry["target"]][2]
        cursor.click_abs(int(tgt["x"]), int(tgt["y"]))
        state["screen"], state["view"] = name, None

def go(target_name):
    """Named action: navigate to the target's screen/view, then click it."""
    if target_name not in TARGET_INDEX:
        log(f"ERROR: unknown target '{target_name}'")
        return
    screen_name, view_name, tgt = TARGET_INDEX[target_name]

    if state["screen"] != screen_name or not state["known"]:
        navigate_to_screen(screen_name)

    if view_name and SCREENS[screen_name].get("views"):
        ensure_view(screen_name, view_name)

    if "wait_before" in tgt:
        log(f"Waiting {tgt['wait_before']}s before '{target_name}'")
        time.sleep(float(tgt["wait_before"]))

    log(f"Click '{target_name}' at ({tgt['x']},{tgt['y']})")
    cursor.click_abs(int(tgt["x"]), int(tgt["y"]))

    # Update state from this click's effects.
    if tgt.get("terminal"):
        log(f"Terminal target '{target_name}' -> state unknown, zero reset")
        cursor.reset()
        state["screen"], state["view"], state["known"] = "unknown", None, False
    elif "sets_view" in tgt:
        state["view"] = tgt["sets_view"]
    elif target_name in OPENS_SCREEN:
        state["screen"] = OPENS_SCREEN[target_name]
        state["view"] = None

# ============================================================
# Macro runner (new English + legacy Spanish step types)
# ============================================================
LEGACY_TYPES = ("esperar", "ir_a_home", "mover", "click", "clicks", "scroll")

def run_step(step, delay_ms):
    delay_ms = max(delay_ms, 200)   # floor: never below 200 ms

    typ = (step.get("type") or "").strip().lower()
    legacy = (step.get("tipo") or "").strip().lower()

    if typ == "wait":
        time.sleep(float(step.get("seconds", 0)))

    elif typ == "go":
        go(step.get("target"))

    elif typ == "home_key":
        home_key(step.get("times", 1))
        state["screen"], state["view"], state["known"] = "main", None, True

    elif typ == "zero":
        cursor.reset()
        state["screen"], state["view"], state["known"] = "main", None, True

    elif legacy in LEGACY_TYPES:
        if legacy == "esperar":
            time.sleep(float(step.get("segundos", 0)))
        elif legacy == "ir_a_home":
            home_key(step.get("veces", 1))
            state["screen"], state["view"], state["known"] = "main", None, True
        elif legacy == "mover":
            move_rel(step.get("dx", 0), step.get("dy", 0), delay_ms)
        elif legacy == "click":
            cursor.go_to(cursor.x + int(step.get("dx", 0)),
                        cursor.y + int(step.get("dy", 0)))
            mouse.click(Mouse.LEFT_BUTTON)
            time.sleep(0.2)
        elif legacy == "clicks":
            for c in step.get("lista", []):
                cursor.go_to(cursor.x + int(c.get("dx", 0)),
                            cursor.y + int(c.get("dy", 0)))
                mouse.click(Mouse.LEFT_BUTTON)
                time.sleep(0.2)
        elif legacy == "scroll":
            scroll(step.get("direccion", "arriba"), step.get("ticks", SCROLL_TICKS))

    else:
        log(f"Unknown step: {step} (ignored)")

    time.sleep(delay_ms / 1000.0)

# ============================================================
# Main
# ============================================================
with open("macro.json", "r") as f:
    cfg = json.load(f)

conf = cfg.get("config") or cfg.get("configuracion") or {}
reset_at_start = yes_no(
    conf.get("reset_pointer_at_start", conf.get("reiniciar_puntero_al_inicio")), True)
delay_ms = max(200, int(conf.get("delay_between_steps_ms",
                                 conf.get("delay_entre_pasos_ms", 200))))

if reset_at_start:
    cursor.reset()

sections = cfg.get("sections", cfg.get("secciones", []))
log(f"Sections: {len(sections)} | Targets: {len(TARGET_INDEX)} | "
    f"chunks <= {MAX_MOVE_UNITS}u / {CHUNK_PAUSE_S*1000:.0f}ms pause / "
    f"settle {SETTLE_MS}ms / screen load {SCREEN_LOAD_S*1000:.0f}ms / "
    f"scroll settle {SCROLL_SETTLE_S*1000:.0f}ms")

for sec in sections:
    desc = sec.get("description", sec.get("descripcion", "(untitled)"))
    if not yes_no(sec.get("active", sec.get("activo")), True):
        log(f"Skipping (inactive): {desc}")
        continue
    log(f"Running: {desc}")
    for step in sec.get("steps", sec.get("pasos", [])):
        run_step(step, delay_ms)

log("Macro finished.")
while True:
    time.sleep(1)
