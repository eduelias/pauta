"""The app on a free port, with a chosen OneDrive and Meta (off, or on the fakes)."""

import threading
from http.server import ThreadingHTTPServer

from pauta.server import make_handler


def serve(store, auth, drive, meta=None, ig=None):
    handler = make_handler(store, auth, drive=drive, meta=meta, ig=ig)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    # a short poll so shutdown() doesn't wait half a second per test
    threading.Thread(target=httpd.serve_forever, args=(0.02,), daemon=True).start()
    return httpd
