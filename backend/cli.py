"""birbTrack maintenance, run inside the container:

  docker exec birbtrack python3 cli.py weekly [--week 2026-W43] [--send]
      print the weekly report message (Components V2 JSON), or post it now (--send ignores "already sent")
  docker exec birbtrack python3 cli.py test-post
      post a one-line test message to the Discord webhook
  docker exec birbtrack python3 cli.py lifer <detection id> [--send]
      print (or post, with its call video) the new-yard-bird message for a detection, to check how it looks
"""

import asyncio
import json
import sys

from app import db, images, notify


def main(argv):
    if not argv:
        sys.exit(__doc__)
    db.init()
    images.AVI = images._read()   # the photo index the server keeps
    cmd, args = argv[0], argv[1:]
    send = "--send" in args
    if cmd == "weekly":
        key = args[args.index("--week") + 1] if "--week" in args else notify.due_week(
            __import__("datetime").datetime.now(notify.config.TZ))[0]
        if send:
            print("sent" if asyncio.run(notify.send_weekly(key, force=True)) else "FAILED")
        else:
            print(json.dumps(notify.weekly_message(key), indent=1, ensure_ascii=False))
    elif cmd == "test-post":
        ok = asyncio.run(notify.post([notify.text("birbTrack test post: the webhook works.")]))
        print("sent" if ok else "FAILED")
    elif cmd == "lifer" and args:
        row = dict(db.conn().execute("SELECT * FROM detections WHERE id = ?", (int(args[0]),)).fetchone())
        if send:
            print("sent" if asyncio.run(notify.detection_post(row, "lifer")) else "FAILED")
        else:
            print(json.dumps(notify.detection_message(row, "lifer"), indent=1, ensure_ascii=False))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
