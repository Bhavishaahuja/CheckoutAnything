# A review token is in the URL, and a live one can approve an order, so it can't sit in the logs.
# This rewrites /review/<token> to /review/[redacted] in uvicorn's access log, which stays on.

import logging
import re

REVIEW_PATH = re.compile(r"/review/[^/?#\s\"]+")
REDACTED_PATH = "/review/[redacted]"


class RedactReviewTokens(logging.Filter):
    def filter(self, record):
        # uvicorn logs the path as one of the format arguments, not in the message itself
        if isinstance(record.msg, str):
            record.msg = REVIEW_PATH.sub(REDACTED_PATH, record.msg)

        if isinstance(record.args, tuple):
            cleaned = []
            for value in record.args:
                if isinstance(value, str):
                    value = REVIEW_PATH.sub(REDACTED_PATH, value)
                cleaned.append(value)
            record.args = tuple(cleaned)

        # never drops a line, it only rewrites them
        return True


redact_review_tokens = RedactReviewTokens()


def install_log_redaction():
    # uvicorn sets up its loggers before it imports the app, so this runs after that and sticks.
    # one shared filter object, so importing twice can't add it twice
    logging.getLogger("uvicorn.access").addFilter(redact_review_tokens)
