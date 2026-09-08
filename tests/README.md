# Moderation regression checks

Run from the repository root:

```sh
python3 tests/check-member-block.py
python3 tests/check-block-store.py
```

These compile the production parser/request flow and store declarations with isolated transport/persistence adapters. They do not use a real account or change a website blacklist. Coverage includes missing user profiles (404), distinguishing failures from an empty list, confirmation before changing state, ignoring legacy local rules, login requirements, account-specific caches, and late responses after an account switch.

## Simulator response replay

Debug simulator builds support `-moderationReplay /absolute/path/scenario.json`. This opens the moderation screen and runs the normal list-reading flow against captured HTTP response bodies. It supplies an in-memory test session, does not write Keychain credentials, and intercepts all V2EX client requests. Requests without captured responses fail with 503, so no block/unblock request reaches the real website. This code is excluded from device and Release builds.

The scenario format is:

```json
{
  "account": "fixture-account",
  "responses": [
    {"path": "/", "status": 200, "body": "<script>const blocked = [7,42];</script>"},
    {"path": "/api/members/show.json?id=7", "status": 200, "body": "{\"id\":7,\"username\":\"example\"}"},
    {"path": "/api/members/show.json?id=42", "status": 404, "body": "{\"status\":\"error\",\"message\":\"Object Not Found\"}"}
  ]
}
```

Keep personal captures outside the repository and omit credentials. The homepage fixture can retain only the `blocked` script needed by the parser. Response replay verifies UI and parsing; it is not a live authenticated website test.

## Feed pagination

```sh
python3 tests/check-feed-pagination.py
python3 tests/check-topic-pages.py
```

Checks cover append/deduplication, retrying the same page after failure, refresh, cached cursors, stale responses after switching feeds, exhausted followed nodes, public recent/node HTML templates, and end-of-list detection. The parser check optionally accepts paths to public page-2 HTML captures (include `node` in node capture filenames); captures stay outside the repository.
