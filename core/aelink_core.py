"""
AE Link core - shared by the Resolve menu scripts and the startup watcher.
Installed to ~/Library/Application Support/AE Link/aelink_core.py
"""
import glob, hashlib, json, os, re, shutil, subprocess, time

# ================= config =================
APP_SUPPORT = os.path.expanduser("~/Library/Application Support/AE Link")
SYNC_DIR_NAME = "AE Link Sync"         # created inside the project root you pick
AE_APP = None                          # e.g. "Adobe After Effects 2026"; None = newest
OM_TEMPLATE = "High Quality with Alpha"  # AE output module (ProRes 4444 + alpha)
BIN_NAME = "AE Link"
HANDLE_SECONDS = 2                     # handles on baked plates (each side)
RAW_TAIL_MAX_SECONDS = 600             # raw plates expose up to this much tail
KEEP_OLD_VERSIONS = 0                  # 0 = delete every superseded AE render
TRANSFORM_KEYS = ["Pan", "Tilt", "ZoomX", "ZoomY", "ZoomGang", "RotationAngle",
                  "AnchorPointX", "AnchorPointY", "Pitch", "Yaw", "FlipX", "FlipY",
                  "CropLeft", "CropRight", "CropTop", "CropBottom",
                  "CropSoftness", "CropRetain", "Opacity", "Distortion"]
# ==========================================

REGISTRY = os.path.join(APP_SUPPORT, "projects.json")
LOG_FILE = os.path.join(APP_SUPPORT, "aelink.log")


# ---------------- utilities ----------------
def log(msg):
    os.makedirs(APP_SUPPORT, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")

def osa(script):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return p.stdout.strip()

def q(s):  # AppleScript string literal
    return json.dumps(str(s))

def notify(msg):
    log(msg)
    osa("display notification %s with title \"AE Link\"" % q(msg))

def alert(msg):
    log("ALERT: " + msg)
    osa("display alert \"AE Link\" message %s" % q(msg))

def choose(items, prompt, multiple=False, defaults=None):
    """Returns list of chosen items, or None if cancelled."""
    lst = "{%s}" % ", ".join(q(i) for i in items)
    s = "choose from list %s with title \"AE Link\" with prompt %s" % (lst, q(prompt))
    if defaults:
        s += " default items {%s}" % ", ".join(q(d) for d in defaults)
    if multiple:
        s += " with multiple selections allowed and empty selection allowed"
    s = "set r to (%s)\nif r is false then return \"__CANCEL__\"\n" \
        "set AppleScript's text item delimiters to \"|\"\nreturn r as text" % s
    out = osa(s)
    if out == "__CANCEL__":
        return None
    return [x for x in out.split("|") if x]

def choose_folder(prompt, default=None):
    loc = " default location (POSIX file %s)" % q(default) if default and os.path.isdir(default) else ""
    out = osa("try\nreturn POSIX path of (choose folder with prompt %s%s)\n"
              "on error\nreturn \"\"\nend try" % (q(prompt), loc))
    return out.rstrip("/") or None

def safe(name):
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "clip"

def load_json(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

def is_running(pattern):
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0

def find_ae_app():
    if AE_APP:
        return AE_APP
    apps = sorted(glob.glob("/Applications/Adobe After Effects *"))
    if not apps:
        raise RuntimeError("Couldn't find After Effects in /Applications.")
    return os.path.basename(apps[-1])

def find_aerender():
    p = os.path.join("/Applications", find_ae_app(), "aerender")
    if not os.path.exists(p):
        raise RuntimeError("aerender not found at " + p)
    return p

def run_jsx(jsx_text, path, launch=True):
    """Run ExtendScript in After Effects without blocking Resolve."""
    if not launch and not is_running("After Effects"):
        return False
    with open(path, "w") as f:
        f.write(jsx_text)
    subprocess.Popen(["osascript", "-e",
                      "tell application %s to DoScriptFile %s" % (q(find_ae_app()), q(path))])
    return True


# ---------------- project / sync folder ----------------
def guess_root(project):
    tl = project.GetCurrentTimeline()
    paths = []
    if tl:
        for t in range(1, tl.GetTrackCount("video") + 1):
            for it in tl.GetItemListInTrack("video", t) or []:
                mpi = it.GetMediaPoolItem()
                p = mpi.GetClipProperty("File Path") if mpi else ""
                if p:
                    paths.append(os.path.dirname(p))
    if not paths:
        return os.path.expanduser("~/Movies")
    try:
        return os.path.commonpath(paths)
    except ValueError:
        return paths[0]

def get_sync_dir(project, interactive):
    reg = load_json(REGISTRY, {})
    key = project.GetUniqueId()
    entry = reg.get(key)
    if entry and os.path.isdir(entry["root"]):
        d = os.path.join(entry["root"], SYNC_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        return d
    if not interactive:
        return None
    root = choose_folder("Pick the project root for \"%s\" (AE Link puts its sync "
                         "folder here - usually your footage SSD)" % project.GetName(),
                         guess_root(project))
    if not root:
        return None
    reg[key] = {"name": project.GetName(), "root": root}
    os.makedirs(APP_SUPPORT, exist_ok=True)
    save_json(REGISTRY, reg)
    d = os.path.join(root, SYNC_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d

def manifest_path(sync_dir):
    return os.path.join(sync_dir, "links.json")

class Lock:
    def __init__(self, sync_dir):
        self.path = os.path.join(sync_dir, ".lock")
    def __enter__(self):
        if os.path.exists(self.path) and time.time() - os.path.getmtime(self.path) > 1800:
            os.remove(self.path)  # stale
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            raise RuntimeError("Another AE Link sync is already running.")
        return self
    def __exit__(self, *a):
        os.close(self.fd)
        os.remove(self.path)


# ---------------- Resolve helpers ----------------
def is_color_managed(project):
    mode = (project.GetSetting("colorScienceMode") or "").lower()
    return mode not in ("", "davinciyrgb")

def timeline_by_id(project, tl_id):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t and t.GetUniqueId() == tl_id:
            return t
    return None

def all_video_items(tl):
    for t in range(1, tl.GetTrackCount("video") + 1):
        for it in tl.GetItemListInTrack("video", t) or []:
            yield t, it

def find_item_by_id(tl, uid):
    for _, it in all_video_items(tl):
        if it.GetUniqueId() == uid:
            return it
    return None

def find_item_by_mpi(tl, mpi_id):
    for _, it in all_video_items(tl):
        m = it.GetMediaPoolItem()
        if m and m.GetUniqueId() == mpi_id:
            return it
    return None

def track_is_free(tl, track, start, end):
    for it in tl.GetItemListInTrack("video", track) or []:
        if it.GetStart() < end and it.GetEnd() > start:
            return False
    return True

def free_track_above(tl, track, start, end):
    t = track + 1
    while t <= tl.GetTrackCount("video"):
        if track_is_free(tl, t, start, end):
            return t
        t += 1
    tl.AddTrack("video")
    return tl.GetTrackCount("video")

def get_bin(media_pool):
    root = media_pool.GetRootFolder()
    for f in root.GetSubFolderList():
        if f.GetName() == BIN_NAME:
            return f
    return media_pool.AddSubFolder(root, BIN_NAME)

def find_mpi(folder, uid):
    for c in folder.GetClipList() or []:
        if c.GetUniqueId() == uid:
            return c
    return None

def get_transforms(item):
    out = {}
    for k in TRANSFORM_KEYS:
        v = item.GetProperty(k)
        if v is not None:
            out[k] = v
    return out

def set_transforms(item, props):
    for k, v in props.items():
        item.SetProperty(k, v)

def append(media_pool, info):
    res = media_pool.AppendToTimeline([info])
    if not res:
        raise RuntimeError("Resolve couldn't place a clip on the timeline.")
    return res[0]

def scratch_spot(tl):
    """A new top track and a frame past the end of everything - for temp clips."""
    tl.AddTrack("video")
    track = tl.GetTrackCount("video")
    fps = float(tl.GetSetting("timelineFrameRate"))
    return track, tl.GetEndFrame() + int(fps * 2)


# ---------------- fingerprint of Resolve-side changes ----------------
def fingerprint(resolve, item, mode, scratch):
    h = hashlib.sha1()
    os.makedirs(scratch, exist_ok=True)
    if mode["color"]:
        lut = os.path.join(scratch, "fp.cube")
        exp = getattr(resolve, "EXPORT_LUT_33PTCUBE", 2)
        if item.ExportLUT(exp, lut) and os.path.exists(lut):
            with open(lut, "rb") as f:
                h.update(f.read())
            os.remove(lut)
        h.update(str(item.GetNumNodes()).encode())
    if mode["fusion"]:
        for i in range(1, (item.GetFusionCompCount() or 0) + 1):
            p = os.path.join(scratch, "fp%d.comp" % i)
            if item.ExportFusionComp(p, i) and os.path.exists(p):
                with open(p, "rb") as f:
                    h.update(f.read())
                os.remove(p)
    if mode["color"] or mode["fusion"]:
        h.update(json.dumps(get_transforms(item), sort_keys=True).encode())
    return h.hexdigest()


# ---------------- Resolve -> plate render ----------------
def render_plate(project, tl, item, mode, handles, out_path):
    """Renders the clip (with grade and/or Fusion) plus handles to out_path.
    Returns the plate length in frames."""
    media_pool = project.GetMediaPool()
    mpi = item.GetMediaPoolItem()
    tl_fps = float(tl.GetSetting("timelineFrameRate"))
    clip_fps = float(mpi.GetClipProperty("FPS") or tl_fps)
    ratio = clip_fps / tl_fps
    hl, hr = handles
    src_in = item.GetSourceStartFrame()
    src_len = round(item.GetDuration() * ratio)

    scratch = os.path.join(os.path.dirname(out_path), "_tmp")
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)

    track, rec = scratch_spot(tl)
    tmp = None
    saved_mode = project.GetCurrentRenderMode()
    saved_fmt = project.GetCurrentRenderFormatAndCodec()
    try:
        tmp = append(media_pool, {
            "mediaPoolItem": mpi, "trackIndex": track, "recordFrame": rec, "mediaType": 1,
            "startFrame": src_in - round(hl * ratio),
            "endFrame": src_in + src_len + round(hr * ratio),
        })
        if mode["color"]:
            item.CopyGrades([tmp])
        if mode["fusion"] and (item.GetFusionCompCount() or 0) > 0:
            comp_file = os.path.join(scratch, "fx.comp")
            item.ExportFusionComp(comp_file, 1)
            tmp.ImportFusionComp(comp_file)
        set_transforms(tmp, get_transforms(item))

        project.SetCurrentRenderMode(1)  # single clip
        project.SetCurrentRenderFormatAndCodec("mov", "ProRes4444")
        project.SetRenderSettings({
            "SelectAllFrames": False,
            "MarkIn": tmp.GetStart(), "MarkOut": tmp.GetEnd() - 1,
            "TargetDir": scratch, "CustomName": "plate",
            "ExportVideo": True, "ExportAudio": False, "ExportAlpha": True,
            "FormatWidth": int(tl.GetSetting("timelineResolutionWidth")),
            "FormatHeight": int(tl.GetSetting("timelineResolutionHeight")),
        })
        job = project.AddRenderJob()
        if not job:
            raise RuntimeError("Resolve wouldn't create the plate render job.")
        project.StartRendering(job)
        while project.IsRenderingInProgress():
            time.sleep(0.5)
        status = project.GetRenderJobStatus(job) or {}
        project.DeleteRenderJob(job)
        if status.get("JobStatus") not in (None, "Complete"):
            raise RuntimeError("Plate render failed: %s" % status)
        frames = tmp.GetDuration()
    finally:
        if tmp:
            tl.DeleteClips([tmp], False)
        tl.DeleteTrack("video", track)
        project.SetCurrentRenderMode(saved_mode)
        if saved_fmt:
            project.SetCurrentRenderFormatAndCodec(saved_fmt.get("format"), saved_fmt.get("codec"))

    movs = sorted(glob.glob(os.path.join(scratch, "*.mov")), key=os.path.getmtime)
    if not movs:
        raise RuntimeError("Plate render produced no file.")
    os.replace(movs[-1], out_path)  # same folder/volume -> atomic overwrite
    shutil.rmtree(scratch, ignore_errors=True)
    return frames


# ---------------- send ----------------
BUILD_JSX = r"""
(function () {
    var c = __CFG__;
    if (app.project.numItems > 0 || app.project.file) {
        if (!app.newProject()) { return; }
    }
    var bin = app.project.items.addFolder("AE Link Plate");
    var footage = app.project.importFile(new ImportOptions(new File(c.footage)));
    footage.parentFolder = bin;

    // Plate precomp: Resolve footage (raw or baked) with handles both sides.
    var plate = app.project.items.addComp(c.comp + "_PLATE", c.w, c.h, 1, c.plateDur, c.fps);
    plate.parentFolder = bin;
    var fl = plate.layers.add(footage);
    fl.startTime = c.footStart;
    if (footage.width && footage.height) {
        var s = Math.min(c.w / footage.width, c.h / footage.height) * 100;
        fl.property("Scale").setValue([s, s]);
    }

    // Main comp: this is what comes back to Resolve. Change its length freely.
    var comp = app.project.items.addComp(c.comp, c.w, c.h, 1, c.dur, c.fps);
    var pl = comp.layers.add(plate);
    pl.startTime = -c.headSec;
    comp.workAreaStart = 0;
    comp.workAreaDuration = comp.duration;

    app.project.save(new File(c.aep));
    comp.openInViewer();
})();
"""

RELOAD_JSX = r"""
(function () {
    var p = new File(__PATH__).fsName;
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FootageItem && it.file && it.file.fsName === p) {
            it.mainSource.reload();
        }
    }
})();
"""

def send(resolve, project, tl, item, mode, sync_dir):
    mpi = item.GetMediaPoolItem()
    src = mpi.GetClipProperty("File Path")
    if not src or not os.path.exists(src):
        raise RuntimeError("This clip has no source file on disk (title, generator, compound?).")

    tl_fps = float(tl.GetSetting("timelineFrameRate"))
    w = int(tl.GetSetting("timelineResolutionWidth"))
    h = int(tl.GetSetting("timelineResolutionHeight"))
    clip_fps = float(mpi.GetClipProperty("FPS") or tl_fps)
    dur = item.GetDuration()
    left = int(item.GetLeftOffset() or 0)
    right = int(item.GetRightOffset() or 0)
    bake = mode["color"] or mode["fusion"]
    hf = int(HANDLE_SECONDS * tl_fps)

    if mode["fusion"]:          # Fusion keyframes are clip-start relative: no head handle
        hl, hr = 0, min(hf, right)
    elif bake:
        hl, hr = min(hf, left), min(hf, right)
    else:
        hl, hr = min(hf, left), min(int(RAW_TAIL_MAX_SECONDS * tl_fps), right)

    comp = "%s_%s" % (safe(os.path.splitext(os.path.basename(src))[0]),
                      time.strftime("%m%d_%H%M%S"))
    folder = os.path.join(sync_dir, comp)
    os.makedirs(os.path.join(folder, "renders"), exist_ok=True)
    os.makedirs(os.path.join(folder, "plate"), exist_ok=True)
    aep = os.path.join(folder, comp + ".aep")

    link = {
        "comp": comp, "folder": folder, "aep": aep, "src": src, "mode": mode,
        "timeline_id": tl.GetUniqueId(), "orig_item_id": item.GetUniqueId(),
        "orig_track": item.GetTrackTypeAndIndex()[1], "record": item.GetStart(),
        "handles": [hl, hr], "plate": None, "fingerprint": None,
        "mpi_id": None, "versions": [], "vcount": 0, "last_aep_mtime": 0,
    }

    if bake:
        notify("Rendering %s plate from Resolve..." % ("graded" if mode["color"] else "Fusion"))
        plate = os.path.join(folder, "plate", comp + "_plate.mov")
        frames = render_plate(project, tl, item, mode, (hl, hr), plate)
        link["plate"] = plate
        link["fingerprint"] = fingerprint(resolve, item, mode, os.path.join(folder, "plate", "_fp"))
        footage, foot_start, plate_frames = plate, 0.0, frames
    else:
        src_in_sec = item.GetSourceStartFrame() / clip_fps
        footage = src
        foot_start = -(src_in_sec - hl / tl_fps)
        plate_frames = hl + dur + hr

    cfg = {"footage": footage, "aep": aep, "comp": comp, "w": w, "h": h, "fps": tl_fps,
           "dur": dur / tl_fps, "plateDur": plate_frames / tl_fps,
           "footStart": foot_start, "headSec": hl / tl_fps}

    mp = manifest_path(sync_dir)
    manifest = load_json(mp, {"links": {}})
    manifest["links"][comp] = link
    save_json(mp, manifest)

    run_jsx(BUILD_JSX.replace("__CFG__", json.dumps(cfg)), os.path.join(folder, "build.jsx"))
    notify("Sent %s to After Effects" % comp)
    return link

def find_link_for_item(manifest, item, sync_dir):
    mpi = item.GetMediaPoolItem()
    mid = mpi.GetUniqueId() if mpi else None
    path = mpi.GetClipProperty("File Path") if mpi else ""
    uid = item.GetUniqueId()
    for key, link in manifest["links"].items():
        if link.get("mpi_id") == mid or link.get("orig_item_id") == uid \
                or (path and path.startswith(link["folder"] + os.sep)):
            return key, link
    return None, None


# ---------------- AE -> Resolve ----------------
def aerender(link):
    link["vcount"] += 1
    out = os.path.join(link["folder"], "renders", "%s_v%03d.mov" % (link["comp"], link["vcount"]))
    cmd = [find_aerender(), "-project", link["aep"], "-comp", link["comp"],
           "-OMtemplate", OM_TEMPLATE, "-output", out]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("aerender failed for %s:\n%s" % (link["comp"], (p.stdout + p.stderr)[-600:]))
    return out

def resize_in_place(project, tl, ae_item, mpi, new_len):
    """Rebuild the timeline clip at the new length, keeping grade + transforms."""
    media_pool = project.GetMediaPool()
    start = ae_item.GetStart()
    track = ae_item.GetTrackTypeAndIndex()[1]
    props = get_transforms(ae_item)
    htrack, hrec = scratch_spot(tl)
    holder = append(media_pool, {"mediaPoolItem": mpi, "trackIndex": htrack,
                                 "recordFrame": hrec, "startFrame": 0, "endFrame": 1,
                                 "mediaType": 1})
    try:
        ae_item.CopyGrades([holder])
        tl.DeleteClips([ae_item], False)
        if not track_is_free(tl, track, start, start + new_len):
            track = free_track_above(tl, track, start, start + new_len)
        new = append(media_pool, {"mediaPoolItem": mpi, "trackIndex": track,
                                  "recordFrame": start, "mediaType": 1})
        holder.CopyGrades([new])
        set_transforms(new, props)
    finally:
        tl.DeleteClips([holder], False)
        tl.DeleteTrack("video", htrack)

def bring_back(project, tl, link, out):
    media_pool = project.GetMediaPool()
    ae_bin = get_bin(media_pool)
    mpi = find_mpi(ae_bin, link["mpi_id"]) if link["mpi_id"] else None
    ae_item = find_item_by_mpi(tl, link["mpi_id"]) if mpi else None

    if mpi and ae_item:
        old_len = ae_item.GetDuration()
        if not mpi.ReplaceClip(out):
            raise RuntimeError("Resolve refused to swap in " + out)
        new_len = int(float(mpi.GetClipProperty("Frames") or old_len))
        if new_len != old_len:
            resize_in_place(project, tl, ae_item, mpi, new_len)
        return

    # First return (or the AE clip was deleted from the timeline): place it fresh.
    if mpi:
        mpi.ReplaceClip(out)
    else:
        media_pool.SetCurrentFolder(ae_bin)
        imported = media_pool.ImportMedia([out])
        if not imported:
            raise RuntimeError("Couldn't import " + out)
        mpi = imported[0]
        link["mpi_id"] = mpi.GetUniqueId()
    orig = find_item_by_id(tl, link["orig_item_id"])
    start = orig.GetStart() if orig else link["record"]
    otrack = orig.GetTrackTypeAndIndex()[1] if orig else link["orig_track"]
    length = int(float(mpi.GetClipProperty("Frames") or 1))
    track = free_track_above(tl, otrack, start, start + length)
    append(media_pool, {"mediaPoolItem": mpi, "trackIndex": track,
                        "recordFrame": start, "mediaType": 1})
    # Keep the original live when it's the grade/Fusion source, so you can still edit it.
    if orig and not (link["mode"]["color"] or link["mode"]["fusion"]):
        orig.SetClipEnabled(False)

def prune_versions(link):
    keep = link["versions"][-(KEEP_OLD_VERSIONS + 1):]
    renders_dir = os.path.join(link["folder"], "renders") + os.sep
    for v in link["versions"]:
        if v not in keep and v.startswith(renders_dir) and os.path.exists(v):
            os.remove(v)
    link["versions"] = keep


# ---------------- sync (both directions) ----------------
def sync(resolve, project, interactive=False, only=None):
    sync_dir = get_sync_dir(project, interactive=False)
    if not sync_dir or not os.path.exists(manifest_path(sync_dir)):
        if interactive:
            notify("No AE Link comps in this project yet.")
        return []
    with Lock(sync_dir):
        mp = manifest_path(sync_dir)
        manifest = load_json(mp, {"links": {}})
        start_tl = project.GetCurrentTimeline()
        done = []
        try:
            for key, link in manifest["links"].items():
                if only and key != only:
                    continue
                if not os.path.exists(link["aep"]):
                    continue
                tl = timeline_by_id(project, link["timeline_id"])
                if not tl:
                    continue
                project.SetCurrentTimeline(tl)
                plate_changed = False

                # Resolve -> AE: re-render the plate if grade / Fusion changed.
                orig = find_item_by_id(tl, link["orig_item_id"])
                if link["plate"] and orig:
                    fp = fingerprint(resolve, orig, link["mode"],
                                     os.path.join(link["folder"], "plate", "_fp"))
                    if fp != link["fingerprint"]:
                        notify("Resolve changes on %s - re-rendering plate" % link["comp"])
                        render_plate(project, tl, orig, link["mode"], link["handles"], link["plate"])
                        link["fingerprint"] = fp
                        plate_changed = True
                        run_jsx(RELOAD_JSX.replace("__PATH__", json.dumps(link["plate"])),
                                os.path.join(link["folder"], "reload.jsx"), launch=False)

                # AE -> Resolve: render if the .aep was saved or the plate changed.
                aep_m = os.path.getmtime(link["aep"])
                if plate_changed or aep_m > link["last_aep_mtime"]:
                    notify("Rendering %s from After Effects..." % link["comp"])
                    out = aerender(link)
                    bring_back(project, tl, link, out)
                    link["versions"].append(out)
                    link["last_aep_mtime"] = aep_m
                    prune_versions(link)
                    done.append(link["comp"])
                save_json(mp, manifest)  # save after each link so progress survives errors
        finally:
            if start_tl:
                project.SetCurrentTimeline(start_tl)
    if done:
        notify("Synced %d comp(s): %s" % (len(done), ", ".join(done)))
    elif interactive:
        notify("Everything is up to date (did you save in After Effects?)")
    return done
