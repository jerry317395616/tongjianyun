"""Download only public OpenCV Zoo weights; verify pinned SHA256 and keep licenses."""
import hashlib
from pathlib import Path
import sys
import urllib.request

MODELS = [
    ("face_detection_yunet", "face_detection_yunet_2023mar.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    ("face_recognition_sface", "face_recognition_sface_2021dec.onnx", "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
]
target = Path(sys.argv[1]).resolve()
target.mkdir(parents=True, exist_ok=True, mode=0o700)
for folder, filename, digest in MODELS:
    url = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{filename}"
    path = target / filename
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        with urllib.request.urlopen(url, timeout=90) as response:
            raw = response.read(40 * 1024**2)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError("Model integrity verification failed")
        path.write_bytes(raw)
        path.chmod(0o600)
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/{folder}/LICENSE", timeout=30) as response:
        (target / (folder + "-LICENSE.txt")).write_bytes(response.read(100000))
    print(filename + " SHA256 verified")
