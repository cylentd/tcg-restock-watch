"""tcg-restock-watch: poll retailers for TCG restocks, alert phone, cart the item."""

import subprocess

__version__ = "0.1.0"

# Windows gives a child its own console window whenever the parent has none. That is
# invisible while the watcher runs from a terminal you opened, and obvious the moment
# it runs detached -- as pythonw under Task Scheduler, which is how it survives a
# reboot. Every retailer check shells out to the agent-browser .cmd shim, Target every
# 90 seconds, so without this the desktop fills with terminals.
#
# 0 on other platforms, and subprocess accepts creationflags=0 everywhere, so this
# needs no branch at the call sites. Pass it to every subprocess call in this package.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
