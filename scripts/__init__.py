"""Developer scripts.

The modules here are standalone CLIs. Reusable logic lives in the application
packages so coverage measures it and the server does not import from this
package: `server.pairing_audit` owns the pairing measurement and
`server.deeplink_verifier` owns the deep-link verifier, while
`scripts/pairing_audit.py` and `scripts/verify_deeplinks.py` keep their command
lines and re-export the names their callers already used.
"""
