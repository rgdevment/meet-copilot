import json
import logging
import os
import time

logger = logging.getLogger(__name__)


class RawRecorder:
    """Append-only black box of every UIA caption read, written before dedup.

    One JSONL line per observation with the decision the manager took, so a
    "lost words" report can be traced back to either the source (never read) or
    the dedup rule that discarded it.
    """

    def __init__(self, diag_dir: str):
        self.path = None
        self._fh = None
        try:
            os.makedirs(diag_dir, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            self.path = os.path.join(diag_dir, f"raw_uia_{stamp}.jsonl")
            self._fh = open(self.path, "a", encoding="utf-8")
        except Exception:
            logger.warning("RawRecorder disabled: could not open diag file", exc_info=True)
            self._fh = None

    def log(self, speaker: str | None, text: str | None, decision: str):
        if not self._fh:
            return
        try:
            self._fh.write(
                json.dumps(
                    {
                        "t": round(time.time(), 3),
                        "speaker": speaker or "",
                        "text": text or "",
                        "decision": decision,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self._fh.flush()
        except Exception:
            logger.debug("RawRecorder write failed", exc_info=True)

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
