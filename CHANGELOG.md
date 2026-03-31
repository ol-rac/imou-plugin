# CHANGELOG

<!-- version list -->

## v0.5.0 (2026-03-31)

### Features

- **09-01**: Clean up API client and add wake constants to const.py
  ([`ce77180`](https://github.com/ol-rac/imou-plugin/commit/ce771804f2b43625853f28939d7c542a437314f7))

- **09-01**: Rework privacy switch wake flow and consolidate wake button
  ([`3c9a0e6`](https://github.com/ol-rac/imou-plugin/commit/3c9a0e6311b47ff407f49adf885b87d57e50f49f))

- **09-01**: Rework privacy switch with wake-then-verify for battery cameras
  ([`a769a17`](https://github.com/ol-rac/imou-plugin/commit/a769a170b24ae576181ef4e548471db2932ff315))

### Testing

- CloseDormant button retries 5 times with 5s delay
  ([`63ecbe9`](https://github.com/ol-rac/imou-plugin/commit/63ecbe953f9d6256aa42b126e81d0c979e7fc17f))

- **09-01**: Add failing tests for wake-and-verify flow (TDD red phase)
  ([`1f93682`](https://github.com/ol-rac/imou-plugin/commit/1f93682bb2e99af02849c3fdada4f286f6e91842))


## v0.4.3 (2026-03-31)

### Bug Fixes

- Add channelId to closeDormant call (matches imou_life)
  ([`768f931`](https://github.com/ol-rac/imou-plugin/commit/768f9312f738703c0843b06e0b08b352b93e4710))


## v0.4.2 (2026-03-31)

### Bug Fixes

- Log device capabilities in wake-up test button
  ([`c65d9a7`](https://github.com/ol-rac/imou-plugin/commit/c65d9a7704dffb588656a2f3980eba0499ba07d6))


## v0.4.1 (2026-03-31)

### Bug Fixes

- Call closeDormant API directly without channel_id
  ([`b2022ab`](https://github.com/ol-rac/imou-plugin/commit/b2022abc2cbd5b3709f4d81925aa20a2d0055fd1))


## v0.4.0 (2026-03-31)

### Features

- Add two wake-up test buttons (closeDormant vs wakeUpDevice)
  ([`a74bca4`](https://github.com/ol-rac/imou-plugin/commit/a74bca4c9d18f9b3a3ab098fe9d736227ae6f8f0))


## v0.3.0 (2026-03-31)

### Features

- Add Wake Up button for battery cameras
  ([`750edd3`](https://github.com/ol-rac/imou-plugin/commit/750edd3cdea42d9dffb009164b5846faedc96a82))


## v0.2.0 (2026-03-31)

### Features

- Wake up battery cameras before privacy command
  ([`07a3a4e`](https://github.com/ol-rac/imou-plugin/commit/07a3a4eb27f2f4d707fe73a208c4aecf044f0d17))

### Testing

- Fix switch tests for battery vs powered camera distinction
  ([`06e061a`](https://github.com/ol-rac/imou-plugin/commit/06e061a2bb6e87016a3b6983c0b56888f3f2fb13))


## v0.1.3 (2026-03-31)

### Bug Fixes

- Check Dormant capability at runtime instead of __init__
  ([`af20da2`](https://github.com/ol-rac/imou-plugin/commit/af20da2d06ae7f5c36631eabdb81278ef22830e7))


## v0.1.2 (2026-03-31)

### Bug Fixes

- Trust privacy command for battery cameras, skip verification poll
  ([`3bd56c0`](https://github.com/ol-rac/imou-plugin/commit/3bd56c08b6cd9d0d9beec6ac60a558a1c0942494))


## v0.1.1 (2026-03-31)

### Bug Fixes

- Handle DV1026 (unsupported function) for battery cameras
  ([`2543d47`](https://github.com/ol-rac/imou-plugin/commit/2543d47f04f458e8024df525d268ac898c9fdc22))


## v1.0.0 (2026-03-31)

- Initial Release

## v1.0.0 (2026-03-31)

- Initial Release
