"""Runtime event publication.

Responsibility
    Publishes the ``RuntimeEvent`` vocabulary defined in the SDK at each
    lifecycle boundary.

Why it exists now
    The initial publisher is in-process. Because the runtime already publishes
    through this seam, adding Azure Service Bus, Event Grid or Kafka later is a
    new publisher implementation rather than a re-instrumentation of the runtime
    (``CLAUDE.md``, "Event Bus (Future)").

Filled in from Milestone 03.
"""
