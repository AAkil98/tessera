# Migration Guide: Tessera 0.1.0-alpha -> 1.0.0

## Prerequisites

Upgrade `pymfp` to >= 1.0.0 **before** upgrading Tessera:

```bash
pip install "pymfp>=1.0.0"
pip install "tessera>=1.0.0"
```

## Tessera API Changes

**None.** The `TesseraNode` and `TesseraConfig` public API is unchanged. Existing
code using Tessera 0.1.0-alpha will work without modification.

## Wire Protocol Compatibility

No wire-breaking changes. Tessera 1.0.0 peers can communicate with 0.1.0-alpha
peers — the wire protocol version remains `0x0001`, the manifest format version
remains `0x0001`, and state files remain at version `1`.

## MFP 1.0.0 Breaking Changes (for users who configure MFP directly)

If you configure `pymfp.RuntimeConfig` directly alongside Tessera, be aware of
these MFP 1.0.0 defaults:

| MFP Setting | 0.1.0 Default | 1.0.0 Default | Impact |
|---|---|---|---|
| `max_message_rate` | 0 (unlimited) | 1000 msg/s | Rate limiting now enforced (sliding 1s window) |
| `max_payload_size` | 0 (unlimited) | 1 MB | Payloads > 1 MB rejected |
| `StorageConfig.encrypt_at_rest` | `False` | `True` | Requires 32-byte `master_key` |

### Tessera alignment

- Tessera's `max_payload_size` default is already 1 MB — no change needed.
- Tessera's default concurrency (`max_requests_per_peer=5`,
  `max_requests_per_swarm=20`) operates well within the 1000 msg/s rate limit.
- Tessera uses its own storage layer (`tessera/storage/`), not MFP's
  `StorageConfig`. No `master_key` is required by Tessera.

## MFP Rate Limiting Behavior Change

MFP 1.0.0 switched from a cumulative counter (permanent quarantine after
threshold) to a sliding 1-second window (agents recover automatically after the
window passes). This is a behavioral improvement that requires no Tessera
configuration changes.

## Specifications

All 13 specification documents have been finalized from `status: draft` to
`status: stable`. No spec content was changed — only YAML header metadata.
