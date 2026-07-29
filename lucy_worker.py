"""
LucyLive worker — streams Max viewport frames to Decart Lucy 2.5 via WebRTC.
Runs as a subprocess from 3ds Max (Python 3.11 venv).
"""

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
import threading

CANVAS_WIDTH  = 1280
CANVAS_HEIGHT = 720
VIDEO_FPS     = 30


def read_control(state_dir: pathlib.Path) -> dict:
    try:
        val = json.loads((state_dir / "control.json").read_text(encoding="utf-8"))
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def process_is_alive(pid: int) -> bool:
    """Check the owning process without adding a psutil dependency."""
    if not pid:
        return True
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259   # STILL_ACTIVE
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Frame source — reads latest JPEG from state dir and pushes to VideoSource
# ─────────────────────────────────────────────────────────────────────────────

class ViewportFrameSource:
    def __init__(self, state_dir: pathlib.Path):
        self._state = state_dir
        self._last_mtime: float = 0.0
        self._last_rgb: bytes | None = None

    def read_rgb24(self) -> bytes | None:
        """Returns raw RGB24 bytes (1280*720*3) or None if no new frame."""
        path = self._state / "latest_frame.jpg"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        if mtime <= self._last_mtime and self._last_rgb is not None:
            return self._last_rgb  # repeat last frame

        try:
            from PIL import Image
            import io
            data = path.read_bytes()
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img = img.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.LANCZOS)
            self._last_rgb = img.tobytes()
            self._last_mtime = mtime
            return self._last_rgb
        except Exception:
            return self._last_rgb


# ─────────────────────────────────────────────────────────────────────────────
# Output writer — saves received AI frames to state dir as JPEG
# ─────────────────────────────────────────────────────────────────────────────

class OutputWriter:
    def __init__(self, state_dir: pathlib.Path):
        self._state = state_dir

    def write(self, frame_bgra: bytes, width: int, height: int):
        try:
            from PIL import Image
            import io
            img = Image.frombytes("RGBA", (width, height), frame_bgra, "raw", "BGRA")
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            tmp = self._state / "_out_tmp.jpg"
            tgt = self._state / "output_latest.jpg"
            tmp.write_bytes(buf.getvalue())
            import os as _os, time as _time
            for _i in range(8):
                try:
                    _os.replace(str(tmp), str(tgt))
                    break
                except OSError:
                    _time.sleep(0.015)
        except Exception as e:
            print(f"[worker] output write error: {e}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Recording (optional MP4)
# ─────────────────────────────────────────────────────────────────────────────

class Mp4Recorder:
    def __init__(self, output_path: pathlib.Path, width: int, height: int, fps: int):
        self._path = output_path
        self._width = width
        self._height = height
        self._fps = fps
        self._container = None
        self._stream = None
        self._pts = 0

    def open(self):
        try:
            import av
            self._container = av.open(str(self._path), mode="w")
            self._stream = self._container.add_stream("libx264", rate=self._fps)
            if not self._stream:
                self._stream = self._container.add_stream("mpeg4", rate=self._fps)
            self._stream.width = self._width
            self._stream.height = self._height
            self._stream.pix_fmt = "yuv420p"
            try:
                self._stream.options = {"crf": "18", "preset": "veryfast"}
            except Exception:
                pass
            print(f"[worker] recorder opened: {self._path} ({self._stream.codec.name})", flush=True)
        except Exception as e:
            print(f"[worker] recorder open error: {e}", flush=True)

    def write_bgra(self, bgra_bytes: bytes, width: int, height: int):
        if not self._container or not self._stream:
            return
        try:
            import av
            from fractions import Fraction
            from PIL import Image
            img = Image.frombytes("RGBA", (width, height), bgra_bytes, "raw", "BGRA")
            img = img.convert("RGB")
            if img.width != self._width or img.height != self._height:
                img = img.resize((self._width, self._height), Image.LANCZOS)
            frame = av.VideoFrame.from_image(img)
            frame.pts = self._pts
            frame.time_base = Fraction(1, self._fps)
            self._pts += 1
            for pkt in self._stream.encode(frame):
                self._container.mux(pkt)
        except Exception as e:
            print(f"[worker] recorder write error: {e}", flush=True)

    def close(self):
        try:
            if self._stream:
                for pkt in self._stream.encode():
                    self._container.mux(pkt)
            if self._container:
                self._container.close()
        except Exception:
            pass
        self._container = None
        self._stream = None


# ─────────────────────────────────────────────────────────────────────────────
# Main async loop
# ─────────────────────────────────────────────────────────────────────────────

async def main(state_dir: pathlib.Path, parent_pid: int | None):
    try:
        from decart import RealtimeClient, models
        from decart.types import ModelState, Prompt
        from decart.realtime.types import RealtimeConnectOptions
        from livekit import rtc
        from livekit.rtc._proto.video_frame_pb2 import VideoBufferType
    except ImportError as e:
        print(f"[worker] import error: {e}", flush=True)
        print("[worker] Run install.bat to install dependencies.", flush=True)
        return 1

    api_key = (os.environ.get("DECART_API_KEY")
               or os.environ.get("DECART_KEY")
               or "")
    if not api_key:
        try:
            cfg = json.loads((state_dir.parent / "config.json").read_text(encoding="utf-8"))
            api_key = cfg.get("decart_key", "")
        except Exception:
            pass

    if not api_key:
        print("[worker] No API key found. Set DECART_KEY env or add decart_key to config.json", flush=True)
        return 1

    frame_source = ViewportFrameSource(state_dir)
    output_writer = OutputWriter(state_dir)
    recorder: Mp4Recorder | None = None
    recording_active = False

    # ── VideoSource + LocalVideoTrack ────────────────────────────────────────
    video_source = rtc.VideoSource(CANVAS_WIDTH, CANVAS_HEIGHT)
    local_track  = rtc.LocalVideoTrack.create_video_track("viewport", video_source)

    # ── Read initial control ─────────────────────────────────────────────────
    ctrl = read_control(state_dir)
    prompt_text   = ctrl.get("prompt", "")
    reference_path = ctrl.get("reference_image")

    initial_state: ModelState | None = None
    if prompt_text:
        initial_prompt = Prompt(text=prompt_text, enhance=True)
        initial_state  = ModelState(prompt=initial_prompt)

    print(f"[worker] Connecting to Decart Lucy 2.5...", flush=True)
    print(f"[worker] Prompt: {prompt_text!r}", flush=True)

    # ── Remote frame handler ─────────────────────────────────────────────────
    remote_stream_ref: list = []

    def on_remote_stream(track):
        remote_stream_ref.append(track)
        print("[worker] AI video stream connected.", flush=True)

    REALTIME_BASE_URL = "wss://api3.decart.ai"

    try:
        model_def = models.realtime("lucy-2.5")
        options   = RealtimeConnectOptions(
            model=model_def,
            on_remote_stream=on_remote_stream,
            initial_state=initial_state,
            preferred_video_codec="vp9",
        )
        realtime = await RealtimeClient.connect(
            base_url=REALTIME_BASE_URL,
            api_key=api_key,
            local_track=local_track,
            options=options,
        )

        try:

            realtime.on("connection_change",
                        lambda state: print(f"[worker] state: {state}", flush=True))
            realtime.on("generation_tick",
                        lambda msg: print(f"[worker] usage: {msg}s", flush=True))
            realtime.on("error",
                        lambda err: print(f"[worker] error: {err}", flush=True))

            print("[worker] Connected. Starting frame loop.", flush=True)

            # ── Start receiving remote frames ────────────────────────────────
            async def receive_remote():
                # wait until stream arrives (up to 30s)
                for _ in range(120):
                    if remote_stream_ref:
                        break
                    await asyncio.sleep(0.25)
                if not remote_stream_ref:
                    print("[worker] remote stream never arrived", flush=True)
                    return
                stream = rtc.VideoStream(remote_stream_ref[0], format=VideoBufferType.BGRA)
                async for event in stream:
                    frame = event.frame
                    bgra = bytes(frame.data)
                    output_writer.write(bgra, frame.width, frame.height)
                    if recorder and recording_active:
                        if isinstance(recorder, Mp4Recorder):
                            recorder.write_bgra(bgra, frame.width, frame.height)
                        elif isinstance(recorder, dict):
                            try:
                                from PIL import Image
                                img = Image.frombytes("RGBA", (frame.width, frame.height),
                                                      bgra, "raw", "BGRA").convert("RGB")
                                n = recorder["frame"]
                                img.save(str(recorder["dir"] / f"frame_{n:06d}.jpg"),
                                         quality=92)
                                recorder["frame"] = n + 1
                            except Exception as e:
                                print(f"[worker] seq write error: {e}", flush=True)

            asyncio.ensure_future(receive_remote())

            # ── Frame push + control poll loop ───────────────────────────────
            interval = 1.0 / VIDEO_FPS
            last_ctrl_read = 0.0
            last_prompt = prompt_text
            last_reference = reference_path

            while True:
                t0 = time.monotonic()

                # push viewport frame
                rgb = frame_source.read_rgb24()
                if rgb:
                    frame = rtc.VideoFrame(
                        CANVAS_WIDTH, CANVAS_HEIGHT,
                        VideoBufferType.RGB24, rgb
                    )
                    video_source.capture_frame(frame)
                else:
                    if int(time.monotonic()) % 5 == 0:
                        print("[worker] waiting for viewport frame...", flush=True)

                # poll control.json every 0.25s
                now = time.monotonic()
                if now - last_ctrl_read > 0.25:
                    last_ctrl_read = now
                    ctrl = read_control(state_dir)
                    new_prompt    = ctrl.get("prompt", "")
                    new_reference = ctrl.get("reference_image")
                    new_recording = ctrl.get("recording", False)

                    # update prompt / reference if changed
                    if new_prompt != last_prompt or new_reference != last_reference:
                        last_prompt    = new_prompt
                        last_reference = new_reference
                        try:
                            img_bytes = None
                            if new_reference and pathlib.Path(new_reference).is_file():
                                img_bytes = pathlib.Path(new_reference).read_bytes()
                            await realtime.set_image(
                                img_bytes,
                                prompt=new_prompt or None,
                                enhance=True,
                            )
                        except Exception as e:
                            print(f"[worker] set error: {e}", flush=True)

                    # recording toggle
                    if new_recording and not recording_active:
                        raw_path = ctrl.get("rec_path", "")
                        rec_fmt  = ctrl.get("rec_fmt", "JPEG Seq")
                        if rec_fmt == "MP4":
                            rec_path = pathlib.Path(raw_path) if raw_path else \
                                state_dir / f"recording_{int(time.time())}.mp4"
                            recorder = Mp4Recorder(rec_path, CANVAS_WIDTH, CANVAS_HEIGHT, VIDEO_FPS)
                            recorder.open()
                        else:
                            # JPEG sequence — save to folder
                            seq_dir = pathlib.Path(raw_path) if raw_path else \
                                state_dir / f"seq_{int(time.time())}"
                            seq_dir.mkdir(parents=True, exist_ok=True)
                            recorder = {"type": "seq", "dir": seq_dir, "frame": 0}
                            rec_path = seq_dir
                        recording_active = True
                        print(f"[worker] Recording started: {rec_path}", flush=True)
                    elif not new_recording and recording_active:
                        if isinstance(recorder, Mp4Recorder):
                            recorder.close()
                        elif isinstance(recorder, dict):
                            print(f"[worker] Sequence saved: {recorder['frame']} frames → {recorder['dir']}", flush=True)
                        recorder = None
                        recording_active = False
                        print("[worker] Recording stopped.", flush=True)

                # check parent alive
                if parent_pid and not process_is_alive(parent_pid):
                    print("[worker] 3ds Max exited; the realtime session was closed", flush=True)
                    break

                elapsed = time.monotonic() - t0
                sleep_time = interval - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except Exception as e:
            print(f"[worker] session error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            await realtime.disconnect()

    except Exception as e:
        print(f"[worker] fatal error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if recorder and recording_active:
            if isinstance(recorder, Mp4Recorder):
                recorder.close()

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=pathlib.Path, required=True)
    parser.add_argument("--parent-pid", type=int, default=None)
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True)
    raise SystemExit(asyncio.run(main(args.state, args.parent_pid)))
