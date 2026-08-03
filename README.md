![](logo.png)

**Genshin Impact Fishing Automata — Python**

Automates Genshin Impact fishing at 1920x1080: it reads the fishing point's
fish, picks the matching bait, aims the cast at a fish, hooks the bite and
plays the tension-bar minigame.

This is a Python rewrite of [Nigh/Genshin-fishing](https://github.com/Nigh/Genshin-fishing)
(originally AutoHotkey). The AutoHotkey implementation has been removed — see
the git history if you need it.

## Requirements

- Windows, Python 3.10+
- `pip install -r requirements.txt` (numpy, opencv-python, mss)
- Genshin Impact running at **1920x1080**

Or grab a build (see [Building](#building)) and skip Python entirely.

## Usage

```
python genshin_fishing.py
```

Accept the UAC prompt: the game runs elevated and ignores input from a
non-elevated process. Press **F5** to quit.

Walk to a fishing point and press **F** to open *Prepare to Fish* — the bot
takes over from there:

1. reads the equipped bait and the **Fish Present** icons, and picks the bait
   most of them want
2. selects that bait if it differs, then clicks **Start Fishing**
3. scans the water, turns the camera until a fish is under the cast, casts
4. hooks the bite and plays the tension-bar minigame
5. recasts, and swaps bait if the fish it targets are fished out

Fish the game draws as plain silhouettes — species you have not caught yet —
carry no colour to identify, so they are ignored rather than guessed at. If
nothing is identified confidently the equipped bait is simply kept.

Everything happens inside fishing mode; changing bait uses the in-game
right-click *change bait* button, so the bot never has to leave.

### How aiming works

The landing ring sits a fixed distance ahead of the camera and cannot be
steered across the screen, so `aim=1` turns the camera until the fish reaches
`aim_x_px` instead. The camera response is measured live by phase-correlating
successive frames — about 2 screen px per mouse unit — so no manual
calibration is needed.

Steps are deliberately small. An injected move still drags the OS cursor, and
once that is pinned against a screen edge every further move in the same
direction is clamped to nothing; the bot recentres the cursor inside the game
window when it drifts too far. If the camera genuinely does not respond it
logs `aim camera not responding` and casts straight ahead.

### Offline check

```
python genshin_fishing.py --test-frames <dir-of-1920x1080-pngs>
```

Runs state and tension-bar detection over saved frames (e.g. extracted from a
recording) and prints what it would have done. Handy for diagnosing a bad run
without the game open.

`--selftest` checks that the templates, bait art, fish icons and config all
load, and prints where they were found — the quickest way to tell whether a
build is intact.

To check where a cast actually lands — the number behind `aim_x_px` — take a
screenshot while the trajectory preview is up and run:

```
python -m tools.aim_cast shot.png
```

It prints the landing ring's screen position. Daylight only; at night the
ring is too dim to find reliably.

## setting.ini

Copy `setting.ini.example` next to the bot (or the exe) and edit it. UTF-8 and
UTF-16 both read fine, and every key is optional — defaults shown.

| Section | Key | Default | Meaning |
| --- | --- | --- | --- |
| `[update]` | `log` | `1` | 0 quiet, 1 actions, 2 per-tick detail → `genshinfishing.log` |
| `[autocast]` | `autostart` | `1` | click **Start Fishing** in the panel |
| | `autobait` | `1` | select bait from the fish present |
| | `enabled` | `1` | cast automatically |
| | `aim` | `1` | turn the camera onto a fish before casting |
| | `rebait` | `1` | swap bait when the targeted fish are gone |
| | `rebait_min_fish` | `2` | fish of another kind needed before swapping |
| | `cast_hold_ms` | `600` | how long the cast is charged — this sets the distance |
| | `cast_cooldown_s` | `5` | minimum gap between casts |
| | `bite_timeout_s` | `35` | reel in and recast if nothing bites |
| | `aim_x_px` | `995` | screen x the cast lands on; aiming turns until the fish reaches it |
| | `aim_tolerance_px` | `45` | close enough, stop turning |
| | `aim_timeout_s` | `6` | give up aiming and cast anyway |

## Building

```
.\build.ps1
```

Installs PyInstaller if needed and produces `dist\GenshinFishing.exe` (~58 MB,
one file, no Python required), plus a `dist\setting.ini` copied from the
example. `assets/` is bundled inside the exe; `setting.ini` and
`genshinfishing.log` live beside it, so the config survives a rebuild and you
can drop the exe anywhere.

The exe carries a `requireAdministrator` manifest, so Windows raises the UAC
prompt on launch. Verify a build with `GenshinFishing.exe --selftest`.

Two things worth knowing:

- **Defender often quarantines freshly built PyInstaller exes.** The build is
  not UPX-packed (which makes it much worse), but you may still need an
  exclusion for the folder.
- A one-file build unpacks to `%TEMP%` on every launch, costing about a second
  of startup. For a faster build, set `onefile=False` — edit the spec to pass
  `a.binaries, a.datas` to a `COLLECT()` instead of into `EXE()`.

## Scope

Bait selection and the panel/dialog interactions are **1920x1080 only** —
their templates and screen positions are cut for that resolution. State
detection and the tension-bar minigame scale to other resolutions, but are
untested there.

## Credits

Fork of [Nigh/Genshin-fishing](https://github.com/Nigh/Genshin-fishing).
Fish and bait reference icons come from game8.co. See LICENSE.
