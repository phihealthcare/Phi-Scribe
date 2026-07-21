import threading
import time

from app.services import transcribe


def test_concurrent_get_model_only_constructs_once(monkeypatch):
    transcribe._reset_model()

    construct_count = {"n": 0}
    start_barrier = threading.Barrier(8)

    class _FakeWhisperModel:
        def __init__(self, model_id, device, compute_type):
            construct_count["n"] += 1
            time.sleep(0.05)  # widen the race window
            self.model_id = model_id

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", _FakeWhisperModel)

    results = []

    def worker():
        start_barrier.wait()
        model, _ = transcribe._get_model("small", "cpu", "int8")
        results.append(model)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert construct_count["n"] == 1
    assert len({id(m) for m in results}) == 1

    transcribe._reset_model()
