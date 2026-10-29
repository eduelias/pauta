"""The app on a free port, with a chosen OneDrive (files off, or on the fake Graph)."""

import threading
from http.server import ThreadingHTTPServer

from pauta.server import make_handler


def serve(store, auth, drive):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store, auth, drive=drive))
    # a short poll so shutdown() doesn't wait half a second per test
    threading.Thread(target=httpd.serve_forever, args=(0.02,), daemon=True).start()
    return httpd
