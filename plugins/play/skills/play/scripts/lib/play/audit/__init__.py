"""Play deep inspection: a static, advisory, fail-safe audit of a Play package.

Public surface::

    from play.audit import safe_audit, card, author, report
    envelope = safe_audit(Path("~/.rote/flows/owner/name").expanduser())
    print(card(envelope))

``safe_audit`` never raises and always returns an envelope. See ``runner``.
"""

from __future__ import annotations

from .render import author, card, report
from .runner import safe_audit, unavailable

__all__ = ["safe_audit", "unavailable", "card", "author", "report"]
