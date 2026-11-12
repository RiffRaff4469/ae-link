#!/usr/bin/env python3
"""Workspace > Scripts > AE Link - Sync Now
Both directions, every linked clip in this project:
  Resolve grade/Fusion changed -> re-render plate -> AE picks it up
  .aep saved (or plate changed) -> aerender -> swap into the timeline"""
import os, sys
sys.path.insert(0, os.path.expanduser("~/Library/Application Support/AE Link"))
import aelink_core as core

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

if __name__ == "__main__":
    try:
        r = get_resolve()
        project = r.GetProjectManager().GetCurrentProject()
        if project:
            core.sync(r, project, interactive=True)
    except Exception as e:
        core.alert("Error: %s" % e)
        raise
