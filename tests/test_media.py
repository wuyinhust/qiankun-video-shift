"""Real FFmpeg integration checks on original synthetic media, no user assets."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from media_tools import resolve_binary


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg = resolve_binary("ffmpeg", "FFMPEG_BIN")
        cls.ffprobe = resolve_binary("ffprobe", "FFPROBE_BIN")
        if not cls.ffmpeg or not cls.ffprobe:
            raise unittest.SkipTest("FFmpeg/FFprobe required for actual media verification")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        cls.video = cls.work / "synthetic.mp4"
        subprocess.run([cls.ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=red:s=160x120:r=25:d=2", "-f", "lavfi", "-i", "color=blue:s=160x120:r=10:d=2", "-f", "lavfi", "-i", "color=black:s=160x120:r=25:d=0.4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4.4", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-c:a", "aac", "-fps_mode", "vfr", str(cls.video)], check=True, capture_output=True)
        t = time.perf_counter()
        cls.run_script("segment_video.py", str(cls.video), "--output-dir", str(cls.work / "deconstruction"), "--scene-threshold", "0.05", "--no-audio")
        cls.cold_s = time.perf_counter() - t
        cls.manifest = json.loads((cls.work / "deconstruction" / "shot_manifest.json").read_text())

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    @classmethod
    def run_script(cls, name, *args, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / name), *args], capture_output=True, text=True)
        if success and result.returncode:
            raise AssertionError(result.stderr)
        return result

    def test_actual_pts_and_tail(self):
        manifest = self.manifest
        self.assertEqual("2.0", manifest["pipeline_version"])
        actual = json.loads(subprocess.check_output([self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(self.video)], text=True))["frames"]
        timestamps = {float(f["best_effort_timestamp_time"]) for f in actual}
        frames = [f for s in manifest["shots"] for f in s["keyframes"]]
        self.assertTrue(all(f["pts_s"] in timestamps for f in frames))
        self.assertEqual(max(timestamps), max(f["pts_s"] for f in frames))
        self.assertEqual(min(timestamps), min(f["pts_s"] for f in frames))
        self.assertGreaterEqual(manifest["shot_count"], 3)
        tail = max(frames, key=lambda f: f["pts_s"])
        pixels = subprocess.check_output([self.ffmpeg, "-v", "error", "-i", tail["path"], "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
        self.assertLess(max(pixels), 5)

    def test_reuse_identical_artifacts(self):
        path = self.work / "deconstruction" / "shot_manifest.json"
        before = path.read_bytes()
        t = time.perf_counter()
        self.run_script("segment_video.py", str(self.video), "--output-dir", str(path.parent), "--scene-threshold", "0.05", "--no-audio", "--reuse")
        warm = time.perf_counter() - t
        self.assertEqual(before, path.read_bytes())
        self.assertLess(warm, self.cold_s)

    def test_changed_settings_not_reused(self):
        result = self.run_script("segment_video.py", str(self.video), "--output-dir", str(self.work / "deconstruction"), "--scene-threshold", "0.7", "--no-audio", "--reuse", success=False)
        self.assertEqual(4, result.returncode)

    def test_seed_no_invented_observations(self):
        target = self.work / "analysis.json"
        self.run_script("seed_analysis.py", str(self.work / "deconstruction" / "shot_manifest.json"), "--output", str(target))
        data = json.loads(target.read_text())
        self.assertEqual([], data["facts"])
        self.assertEqual("unreviewed", data["review"]["status"])
        self.assertTrue(data["evidence"])
        second = self.run_script("seed_analysis.py", str(self.work / "deconstruction" / "shot_manifest.json"), "--output", str(target), success=False)
        self.assertNotEqual(0, second.returncode)

    def test_focused_review_unreviewed(self):
        target = self.work / "review"
        self.run_script("review_evidence.py", str(self.video), "--start", "1.8", "--end", "2.3", "--every", "0.1", "--question", "Which color changes at the cut?", "--output-dir", str(target))
        receipt = json.loads((target / "review.json").read_text())
        self.assertFalse(receipt["reviewed"])
        self.assertTrue(all(1.8 <= f["time_s"] < 2.3 for f in receipt["frames"]))
        self.assertTrue((target / "index.html").is_file())

    def test_audio_metadata(self):
        self.assertTrue(self.manifest["audio_streams"])
        self.assertIsInstance(self.manifest["audio_streams"][0]["start_pts_s"], float)


if __name__ == "__main__":
    unittest.main()
