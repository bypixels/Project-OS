"""project-os — control plane for a Claude Code environment.

Principle: project-os measures, warns and blocks. It never repairs, deletes or
edits anything on its own. Every write goes through a confirmation and a guard.
"""
__version__ = "0.1.0"
