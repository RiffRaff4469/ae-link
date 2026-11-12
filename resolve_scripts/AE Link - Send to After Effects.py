#!/usr/bin/env python3
"""Workspace > Scripts > AE Link - Send to After Effects
Clip under the playhead -> After Effects. On a clip that's already linked,
offers Open / Sync / Unlink instead."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/Library/Application Support/AE Link"))
import aelink_core as core

COLOR = "Bake color grade (renders a copy)"
FUSION = "Bake Fusion effects (renders a copy)"

def get_resolve():
    try:
        return resolve  # noqa: F821
    except NameError:
        pass
    try:
        return app.GetResolve()  # noqa: F821
    except NameError:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")

def main():
    r = get_resolve()
    project = r.GetProjectManager().GetCurrentProject()
    tl = project.GetCurrentTimeline() if project else None
    if not tl:
        return core.alert("Open a timeline first.")
    item = tl.GetCurrentVideoItem()
    if not item or not item.GetMediaPoolItem():
        return core.alert("Put the playhead over a video clip (top enabled track wins).")

    sync_dir = core.get_sync_dir(project, interactive=True)
    if not sync_dir:
        return
    mp = core.manifest_path(sync_dir)
    manifest = core.load_json(mp, {"links": {}})

    key, link = core.find_link_for_item(manifest, item, sync_dir)
    if link:
        pick = core.choose(["Open comp in After Effects", "Sync this clip now",
                            "Unlink (keeps files)"],
                           "This clip is linked to %s" % link["comp"],
                           defaults=["Open comp in After Effects"])
        if not pick:
            return
        if pick[0].startswith("Open"):
            core.subprocess.Popen(["open", "-a", core.find_ae_app(), link["aep"]])
        elif pick[0].startswith("Sync"):
            core.sync(r, project, interactive=True, only=key)
        else:
            del manifest["links"][key]
            core.save_json(mp, manifest)
            core.notify("Unlinked %s" % link["comp"])
        return

    defaults = []
    if core.is_color_managed(project):
        defaults.append(COLOR)
    if (item.GetFusionCompCount() or 0) > 0:
        defaults.append(FUSION)
    pick = core.choose([COLOR, FUSION],
                       "What should come over from Resolve?\n(Nothing ticked = original "
                       "source file, no copy.)", multiple=True, defaults=defaults)
    if pick is None:
        return
    mode = {"color": COLOR in pick, "fusion": FUSION in pick}
    core.send(r, project, tl, item, mode, sync_dir)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        core.alert("Error: %s" % e)
        raise
