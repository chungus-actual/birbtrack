#!/usr/bin/env python3
"""birdmic-rtsp: serve the USB mic as rtsp://<pi>:8554/birdmic (L16, 48 kHz mono).

Debian packages only (python3-gi, gir1.2-gst-rtsp-server-1.0, gstreamer1.0-alsa,
gstreamer1.0-plugins-good). One shared capture for every client; the mic is
opened on the first client and released after the last one leaves.

Who may connect is nftables' job (/etc/nftables.conf, table inet birdmic): an
in-process ACL via the pre-*-request signals corrupted the heap (PyGObject and
the stack-allocated GstRTSPContext), so this only logs.

Env (from /etc/default/birdmic):
  BIRDMIC_DEVICE  ALSA device       default plughw:CARD=Device,DEV=0
  BIRDMIC_PORT    RTSP port         default 8554
  BIRDMIC_MOUNT   path              default /birdmic
  BIRDMIC_RATE    sample rate       default 48000
"""
import os
import sys

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import GLib, Gst, GstRtspServer  # noqa: E402

DEVICE = os.environ.get("BIRDMIC_DEVICE", "plughw:CARD=Device,DEV=0")
PORT = os.environ.get("BIRDMIC_PORT", "8554")
MOUNT = os.environ.get("BIRDMIC_MOUNT", "/birdmic")
RATE = int(os.environ.get("BIRDMIC_RATE", "48000"))


def log(msg):
    print(msg, flush=True)


def on_client(server, client):
    ip = client.get_connection().get_ip()
    log(f"client {ip} connected")
    client.connect("closed", lambda c: log(f"client {ip} closed"))


def main():
    Gst.init(None)
    launch = (
        f"( alsasrc device={DEVICE} do-timestamp=true buffer-time=200000 "
        f"! audioconvert ! audioresample "
        f"! audio/x-raw,format=S16BE,rate={RATE},channels=1 "
        f"! rtpL16pay name=pay0 pt=96 )"
    )
    factory = GstRtspServer.RTSPMediaFactory()
    factory.set_launch(launch)
    factory.set_shared(True)

    server = GstRtspServer.RTSPServer()
    server.set_service(PORT)
    server.get_mount_points().add_factory(MOUNT, factory)
    server.connect("client-connected", on_client)
    if server.attach(None) == 0:
        log(f"could not bind port {PORT}")
        sys.exit(1)
    log(f"serving rtsp://0.0.0.0:{PORT}{MOUNT} from {DEVICE} @ {RATE} Hz mono")
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
