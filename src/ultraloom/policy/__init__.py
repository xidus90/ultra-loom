"""Rules about what a tool call may touch.

Below the check chain and below the harness: the policy runs before every tool
call, so what it imports is its price and not a detail. test_module_boundary
holds that promise.

Named `policy` and not `guard`: `flows/verify_until_green.py` already has a
`guard` node, and it answers a different question -- what a repairer touched,
not what anyone may touch.
"""
