"""Per-race extraction in a child process; the live I/O worker never waits for it."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import uuid


def validate_scene(path, ram_hash):
    value = json.loads(path.read_text())
    if value.get("schema") != "screamer-scene/v1" or value["provenance"]["ram_sha256"] != ram_hash:
        raise ValueError("Extracted asset provenance does not match this race capture")
    for key, stride in (("vertices", 36), ("indices", 4)):
        item = value[key]
        file = path.parent / item["file"]
        if file.stat().st_size != item["count"]*stride:
            raise ValueError("Extracted mesh buffer length does not match its descriptor")
    return value


def terminate_group(process):
    if process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass


class AssetJobs:
    def __init__(self, root, extractor, game_root=None):
        self.root, self.extractor = Path(root), Path(extractor)
        self.root.mkdir(parents=True, exist_ok=True)
        self.game_root = Path(game_root) if game_root else None
        self.current = None
        self.ready = None
        self.error = None
        self.retired = []

    def start(self, epoch, data, metadata):
        if self.current and self.current["epoch"] == epoch:
            return
        if self.current and self.current["process"].poll() is None:
            terminate_group(self.current["process"])
            self.retired.append(self.current["process"])
        self.ready, self.error = None, None
        directory = self.root / ("race-" + uuid.uuid4().hex)
        directory.mkdir()
        (directory / "ram.bin").write_bytes(data)
        (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        log = (directory / "extraction.log").open("wb")
        command = [sys.executable, str(Path(__file__).resolve()), "--job", str(directory),
                   "--extractor", str(self.extractor)]
        if self.game_root:command += ["--game-root",str(self.game_root)]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,start_new_session=True,
                                   env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"))
        log.close()
        self.current = {"epoch":epoch,"directory":directory,"process":process,"ram_hash":metadata["ram_sha256"]}

    def poll(self, epoch):
        self.retired = [process for process in self.retired if process.poll() is None]
        if not self.current or self.current["epoch"] != epoch:
            return None
        result = self.current["process"].poll()
        if result is None:
            return None
        if result != 0:
            self.error = f"Asset extraction exited{result}; see {self.current['directory'] / 'extraction.log'}"
            return None
        if self.ready is None:
            directory = self.current["directory"]
            scene, cars = directory / "world/scene.json", directory / "cars/scene.json"
            scene_data=validate_scene(scene, self.current["ram_hash"])
            car_data = validate_scene(cars, self.current["ram_hash"])
            if len(car_data.get("dynamic_instances", [])) != 6:
                raise ValueError("Captured race asset set does not contain six cars")
            self.ready = {"epoch":epoch,"scene":str(scene),"cars":str(cars),
                          "world_scene":str(scene),"cars_scene":str(cars),"ram_sha256":self.current["ram_hash"]}
            if scene_data.get("sky"):self.ready["sky_texture"]=str(scene.parent/scene_data["sky"]["path"])
            variants = directory / "condition-variants.json"
            if variants.is_file():
                self.ready["condition_variants"] = validate_conditions(
                    directory, json.loads(variants.read_text()), self.current["ram_hash"], car_data)
        return self.ready

    def stop(self):
        processes = self.retired + ([self.current["process"]] if self.current else [])
        for process in processes:
            terminate_group(process)


def validate_conditions(directory, value, ram_hash, base_cars):
    """Optional alternate visuals must belong to this exact captured car cohort."""
    original = value.get("original", "day")
    try:
        if value.get("schema") != "screamer-original-conditions/v1" or original not in ("day", "night"):
            raise ValueError("Original condition descriptor is invalid")
        night = value.get("night", {})
        if not night.get("available"):
            return value
        for name in ("world_scene", "cars_scene", "sky_texture"):
            target = Path(night[name])
            if not target.is_absolute() or not target.resolve().is_relative_to(directory.resolve()) or not target.is_file():
                raise ValueError("Original Night assets must stay inside this captured race cache")
        validate_scene(Path(night["world_scene"]), ram_hash)
        cars = validate_scene(Path(night["cars_scene"]), ram_hash)
        identity = lambda scene: [(item["id"], item["model"]) for item in scene.get("dynamic_instances", [])]
        if identity(cars) != identity(base_cars):
            raise ValueError("Original Night car identities differ from the captured race")
    except (KeyError, TypeError, ValueError, OSError) as error:
        return {"schema": "screamer-original-conditions/v1", "original": original if original in ("day", "night") else "day",
                "night": {"available": False, "reason": str(error)}}
    return value


def export_conditions(directory, game_root):
    result = {"schema": "screamer-original-conditions/v1", "original": "day",
              "night": {"available": False, "reason": "Original game assets are unavailable."}}
    if game_root is not None:
        try:
            from guest_memory import Snapshot
            capture = Snapshot.load(directory / "ram.bin", directory / "metadata.json")
            track = capture.rd32(capture.link(0x1435c0, 4))
            result["original"] = "night" if capture.rd32(capture.link(0x1435c4, 4)) & 1 else "day"
            conditions = Path(__file__).resolve().parents[1] / "Conditions"
            if not (conditions / "rally.py").is_file():
                raise ValueError("Original condition decoder is unavailable")
            sys.path.insert(0, str(conditions))
            from rally import export_night
            result = export_night(game_root, track, directory / "world/scene.json", directory / "cars/scene.json",
                                  directory / "night", capture=capture)
        except Exception as error:
            # Optional authored Night artwork cannot prevent the independent
            # baseline race assets from loading if an archive is unavailable.
            result["night"] = {"available": False, "reason": str(error)[:500]}
            print("Original Rally Night assets unavailable:", error, flush=True)
    (directory / "condition-variants.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def run_job(directory, extractor, game_root=None):
    # Lower the extraction worker's CPU priority without affecting the emulator
    # or the live input/frame worker. User data is never an output target.
    try:
        os.nice(10)
    except OSError:
        pass
    common = ["--ram",str(directory/"ram.bin"),"--metadata",str(directory/"metadata.json")]
    subprocess.run([sys.executable,str(extractor/"extract_track.py"),*common,"--textures",
                    "--output",str(directory/"world")],check=True)
    if game_root:
        sys.path.insert(0,str(extractor))
        from sky_assets import export_capture_sky
        from guest_memory import Snapshot
        scene_path=directory/"world/scene.json";scene=json.loads(scene_path.read_text())
        scene["sky"]=export_capture_sky(Snapshot((directory/"ram.bin").read_bytes(),json.loads((directory/"metadata.json").read_text())),game_root,scene_path.parent)
        scene_path.write_text(json.dumps(scene,indent=2)+"\n")
    subprocess.run([sys.executable,str(extractor/"extract_cars.py"),*common,
                    "--output",str(directory/"cars")],check=True)
    export_conditions(directory, game_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job",type=Path,required=True)
    parser.add_argument("--extractor",type=Path,required=True)
    parser.add_argument("--game-root",type=Path)
    args = parser.parse_args()
    run_job(args.job,args.extractor,args.game_root)
