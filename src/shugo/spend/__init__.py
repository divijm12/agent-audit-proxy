"""Spend proxy: sits in front of the Anthropic API, prices every call, and
blocks an agent once it has spent its budget. Shares shugo's kill switch and
audit log with the tool guard."""
