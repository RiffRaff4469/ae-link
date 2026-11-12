#!/usr/bin/env python3
"""Runs every 30s via launchd. The first time it sees a project open in a
Resolve session, it runs a full AE Link sync once. Does nothing otherwise."""
import json, os, subprocess, sys, time

SUP = os.path.expanduser("~/Library/Application Support/AE Link")
STATE = os.path.join(SUP, "watch_state.json")
API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"

def main():
    p = subprocess.run(["pgrep", "-x", "Resolve"], capture_output=True, text=True)
    if p.returncode != 0:
        if os.path.exists(STATE):
            os.remove(STATE)  # Resolve closed: next launch syncs again
        return
    pid = p.stdout.split()[0]

    os.environ.setdefault("RESOLVE_SCRIPT_API", API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", LIB)
    sys.path.insert(0, os.path.join(API, "Modules"))
    sys.path.insert(0, SUP)
    import DaVinciResolveScript as dvr
    import aelink_core as core

    r = dvr.scriptapp("Resolve")
    if not r:
        return  # still launching, or External scripting isn't set to Local
    pm = r.GetProjectManager()
    project = pm.GetCurrentProject() if pm else None
    if not project:
        return

    state = core.load_json(STATE, {"pid": pid, "synced": []})
    if state.get("pid") != pid:
        state = {"pid": pid, "synced": []}
    key = project.GetUniqueId()
    if key in state["synced"]:
        return
    time.sleep(5)  # let the project finish loading
    state["synced"].append(key)
    core.save_json(STATE, state)
    core.sync(r, project, interactive=False)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.path.insert(0, SUP)
        import aelink_core as core
        core.log("watcher error: %s" % e)
