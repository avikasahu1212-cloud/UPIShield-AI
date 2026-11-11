"""Worker runner - allows running workers as separate processes."""

from __future__ import annotations

import logging
import threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import INGEST_MODE

logger = logging.getLogger(__name__)


def run_workers(stop_event: threading.Event | None = None) -> None:
    """Start all background workers."""
    from app.workers.detector_worker import DetectorWorker

    workers = []

    if INGEST_MODE == "kafka":
        logger.info("Starting workers in Kafka mode")
        detector = DetectorWorker()
        detector.initialize()
        t = threading.Thread(target=detector.run, args=(stop_event,), daemon=True, name="detector")
        t.start()
        workers.append(t)
    else:
        logger.info("Running in file mode (no background workers needed)")

    logger.info("Started %d worker threads", len(workers))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_workers()
    # Keep running
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down workers")
