import os

from dotenv import load_dotenv

from app import create_app

load_dotenv()

app = create_app(os.environ.get("FLASK_ENV", "default"))

if __name__ == "__main__":
    # threaded=True: a live realtime WebSocket session (app/routes/realtime.py)
    # holds its connection open for the whole consultation — without this,
    # it would block every other request (REST uploads, other users) on the
    # dev server's single request-handling thread for its entire lifetime.
    # Safe with the batch endpoints too: app/services/transcribe.py's model
    # cache has its own lock (see _model_lock) for exactly this concurrency.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)