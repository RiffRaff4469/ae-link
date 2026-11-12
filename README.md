# AE Link

**Send a clip from DaVinci Resolve to After Effects and get the render back on your timeline.**

AE Link is two Resolve menu scripts, a small Python core and a background watcher. You run "Send to After Effects" on a clip and After Effects opens with a comp already set up for it: same resolution and frame rate, with handles. Save in After Effects, run "Sync Now" in Resolve, and the rendered result drops onto the track above the original clip. Every later save replaces it with a new version.

## What it does

- Sends the clip under the playhead to a new After Effects project. You get a `_PLATE` precomp with handles and a main comp that matches the clip's length, the timeline resolution and the frame rate.
- Lets you bake the Resolve color grade, the Fusion effects or both into a ProRes 4444 plate with alpha before sending. Leave both unticked and After Effects uses the original source file, with no copy made.
- Pre-ticks the color bake on color-managed projects and the Fusion bake on clips that have Fusion comps.
- Syncs both ways with "Sync Now":
  - Resolve to AE: if the grade, Fusion comp or transforms changed since the plate was made, it renders the plate again and reloads it in After Effects (if AE is open).
  - AE to Resolve: if the `.aep` was saved since the last sync, or the plate changed, it renders the comp with `aerender` and swaps the new version into the timeline.
- Handles changes to the comp's length. If you make the comp longer or shorter in After Effects, the timeline clip is rebuilt at the new length and keeps its grade and transforms.
- Puts the first return on the first free track above the original. For raw sends the original clip gets disabled. For baked sends it stays enabled, because it is still the source of the grade or Fusion work.
- Bakes the clip's Inspector transforms (pan, tilt, zoom, rotation, anchor point, pitch/yaw, flip, crop, opacity, distortion) into baked plates as well, and re-renders the plate when they change.
- Runs a background watcher through launchd every 30 seconds. The first time it sees a project open in a Resolve session, it runs one sync. Anything you saved in After Effects while Resolve was closed comes back when you reopen the project.
- On a clip that's already linked, "Send to After Effects" gives you three options instead: open the comp, sync just that clip, or unlink it (the files stay).

## Install

Requirements: macOS, DaVinci Resolve, After Effects installed in `/Applications` (it uses the bundled `aerender`), and Python 3.

```sh
git clone https://github.com/RiffRaff4469/ae-link.git
cd ae-link
./install.sh
```

`install.sh` installs for your user only and doesn't need sudo. It copies:

| From | To |
| --- | --- |
| `core/aelink_core.py`, `core/aelink_watch.py` | `~/Library/Application Support/AE Link/` |
| `resolve_scripts/*.py` | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| generated LaunchAgent | `~/Library/LaunchAgents/com.riffraff4469.aelink.plist` |

Then it loads the LaunchAgent. If an installed file is different from the new one, the old copy is kept as `<name>.bak`.

After installing:

1. In Resolve, open Preferences > System > General and set **External scripting using** to **Local**. The watcher needs this.
2. Restart Resolve. The two scripts show up under **Workspace > Scripts**.

The first time a script controls After Effects, macOS may ask you to allow it.

Settings are at the top of `aelink_core.py`: which After Effects version to use (default: the newest one in `/Applications`), the output module template, handle length, how much tail raw sends expose, and how many old renders to keep. Running `install.sh` again overwrites that file (the old copy is kept as `.bak`).

To uninstall:

```sh
launchctl bootout gui/$(id -u)/com.riffraff4469.aelink
rm ~/Library/LaunchAgents/com.riffraff4469.aelink.plist
rm -r ~/Library/Application\ Support/AE\ Link
rm ~/Library/Application\ Support/Blackmagic\ Design/DaVinci\ Resolve/Fusion/Scripts/Utility/AE\ Link\ -\ *.py
```

## Using it

1. Put the playhead over a clip. If clips are stacked, the top enabled track is used. Run **Workspace > Scripts > AE Link - Send to After Effects**.
2. The first time you do this in a project, pick a project root, usually the drive your footage is on. AE Link creates an `AE Link Sync` folder there and remembers it for that project.
3. Choose what to bake (grade, Fusion, both or neither). After Effects opens with the comp ready.
4. Work in the main comp and change its length if you need to. Save.
5. Back in Resolve, run **AE Link - Sync Now**. The render lands on the timeline. Each later save and sync replaces it with a new version.

Every send gets its own folder inside `AE Link Sync`:

```
AE Link Sync/
  links.json                     manifest of every link in this project
  <clip>_<MMDD_HHMMSS>/
    <clip>_<MMDD_HHMMSS>.aep
    plate/                       baked plate (if you baked)
    renders/                     <comp>_v001.mov, _v002.mov ...
```

Returned clips go in an `AE Link` bin in the media pool. The log is at `~/Library/Application Support/AE Link/aelink.log`.

## How it's built

- Plain Python standard library, no dependencies. It uses Resolve's scripting API on one side and generated ExtendScript plus `aerender` on the other. The JSX is written to the link folder and run with AppleScript's `DoScriptFile` in a separate process, so Resolve doesn't freeze while After Effects works.
- Dialogs, folder pickers and notifications are AppleScript through `osascript`, so the scripts don't need a GUI toolkit inside Resolve.
- To render a plate, it drops a temporary copy of the clip, with handles, on a scratch track past the end of the timeline. It copies the grade, Fusion comp and transforms onto that copy, renders it as a single ProRes 4444 clip with alpha, then deletes the copy and the track and restores your render settings. The finished plate replaces the old file in one atomic step, so After Effects can reload it in place.
- To spot changes on the Resolve side, it hashes (SHA-1) an exported 33-point LUT, the node count, the exported Fusion comps and the transform values.
- Fusion bakes get no head handle, because Fusion keyframes are timed from the start of the clip.
- When the comp's length changes, a temporary holder clip keeps the grade while the timeline clip is deleted and placed again.
- State lives in a `links.json` manifest per sync folder. Writes are atomic and the manifest is saved after each link, so an error halfway through a sync doesn't undo the links already done. A lock file (treated as stale after 30 minutes) stops two syncs from running at once.

## Limitations

- macOS only. It depends on `osascript`, launchd and the standard `/Applications` install paths for Resolve and After Effects.
- Only works on clips with a source file on disk. Titles, generators and compound clips can't be sent.
- Video only. No audio goes to After Effects.
- Syncing isn't live. It runs when you click Sync Now, or once per project each time Resolve launches.
- By default old After Effects renders get deleted when a new version comes in (`KEEP_OLD_VERSIONS = 0`).
- The watcher only works if Resolve's external scripting is set to Local.

Tested with After Effects 2026 and DaVinci Resolve Studio on macOS 26.

Made by RiffRaff4469 (JMV Productions). MIT licensed.
