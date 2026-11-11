# The live event log for connect runs. The run happens in a background thread and emits events
# here, the SSE endpoint reads them. Events are kept in memory per store, so a browser that
# connects late (or reconnects) gets the whole run from the start.
#
# Each event: {seq, type, store_id, item_id, message, data}. message is one human sentence.

import json
import threading

EVENT_TYPES = {
    "fetch.started", "fetch.done", "extract.started", "extract.done", "extract.rejected",
    "item.checking", "item.verified", "item.failed", "item.repairing",
    "store.ready", "error",
}
# after one of these nothing else is coming, the stream closes
FINAL_TYPES = {"store.ready", "error"}

# how long a stream waits for the next event before sending a keep-alive comment
KEEPALIVE_SECONDS = 15


class EventBus:
    def __init__(self):
        self.events = {}
        self.changed = threading.Condition()

    def emit(self, store_id, event_type, message, item_id=None, data=None):
        if event_type not in EVENT_TYPES:
            raise ValueError("Unknown event type " + event_type)
        with self.changed:
            log = self.events.setdefault(store_id, [])
            event = {
                "seq": len(log),
                "type": event_type,
                "store_id": store_id,
                "item_id": item_id,
                "message": message,
                "data": data or {},
            }
            log.append(event)
            self.changed.notify_all()
        return event

    def history(self, store_id):
        with self.changed:
            return list(self.events.get(store_id, []))

    def clear(self, store_id=None):
        with self.changed:
            if store_id is None:
                self.events = {}
            else:
                self.events.pop(store_id, None)
            self.changed.notify_all()

    def stream(self, store_id, start=0):
        # yields events from `start` on, then None every KEEPALIVE_SECONDS while it waits.
        # stops after a final event
        position = start
        while True:
            with self.changed:
                log = self.events.get(store_id, [])
                if position >= len(log):
                    self.changed.wait(timeout=KEEPALIVE_SECONDS)
                    log = self.events.get(store_id, [])
                waiting = list(log[position:])
            if not waiting:
                yield None
                continue
            for event in waiting:
                position += 1
                yield event
                if event["type"] in FINAL_TYPES:
                    return


def sse_format(event):
    # one Server-Sent Event. None is a keep-alive comment, proxies drop quiet connections
    if event is None:
        return ": keep-alive\n\n"
    return (
        "id: " + str(event["seq"]) + "\n"
        + "event: " + event["type"] + "\n"
        + "data: " + json.dumps(event) + "\n\n"
    )


bus = EventBus()
