"""The task broker: dramatiq's Redis broker, minus two ways a dropped connection strands delayed messages.

A worker holds each delayed message in memory until it is due, while Redis files
it as fetched by that worker. Redis hands a worker's fetched messages back only
once its heartbeat is a minute stale, and a live worker heartbeats with every
command. So a message the worker loses without handing it back waits for the
worker process to exit, which in practice is the next deploy.

Dramatiq loses them in two places, up to at least 2.2.1:

* On a connection error, the consumer thread discards its delayed messages
  before it closes, so there is nothing left to hand back.
* When a due message fails to enqueue, the consumer closes and tries to hand the
  rest back. That requeue raises Redis's own error, which ``close()`` does not
  catch, and the error kills the consumer thread for that queue.
"""

from __future__ import annotations

from typing import cast

import redis
from dramatiq.broker import Consumer
from dramatiq.brokers.redis import RedisBroker as DramatiqRedisBroker
from dramatiq.errors import ConnectionClosed


class RedisBroker(DramatiqRedisBroker):
    def consume(self, queue_name: str, prefetch: int = 1, timeout: int = 5000) -> Consumer:
        """Hand back what this worker lost from a delay queue, then consume it.

        Dramatiq starts a delay queue's consumer with nothing held in memory: at
        boot, after a connection error has discarded what it held, and after
        ``close()`` has emptied it into a requeue, whether or not the requeue
        got through. So nobody holds what Redis still files as fetched by this
        worker from that queue, and requeueing all of it is safe. Redis's
        requeue only moves messages still filed under this worker, so it cannot
        duplicate one that ``close()`` already handed back.

        If a later dramatiq keeps delayed messages across a reconnect, this would
        requeue messages it still holds and run them twice. The tests for this
        module fail if that happens.
        """
        if queue_name in self.delay_queues:
            fetched = f"{self.namespace}:__acks__.{self.broker_id}.{queue_name}"
            try:
                if message_ids := cast(set[bytes], self.client.smembers(fetched)):
                    self.do_requeue(queue_name, *message_ids)
            except redis.ConnectionError as e:
                raise ConnectionClosed(e) from None  # type: ignore[no-untyped-call]
        return super().consume(queue_name, prefetch, timeout)

    def do_requeue(self, queue_name: str, *message_ids: str | bytes) -> None:
        """Requeue, raising the connection error dramatiq's callers expect.

        Dramatiq's Redis consumer turns a lost connection into ``ConnectionClosed``
        on fetch, ack and nack, but not on requeue. So a requeue during an outage
        raised Redis's own error, which neither the consumer's ``close()`` nor
        the worker's shutdown catches.
        """
        try:
            self._dispatch("requeue")(queue_name, *message_ids)  # type: ignore[no-untyped-call]
        except redis.ConnectionError as e:
            raise ConnectionClosed(e) from None  # type: ignore[no-untyped-call]
