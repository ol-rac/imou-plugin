# Imou Integration for Home Assistant

[![HACS Validation](https://github.com/ol-rac/imou-plugin/actions/workflows/validate.yml/badge.svg)](https://github.com/ol-rac/imou-plugin/actions/workflows/validate.yml)
[![hassfest Validation](https://github.com/ol-rac/imou-plugin/actions/workflows/hassfest.yml/badge.svg)](https://github.com/ol-rac/imou-plugin/actions/workflows/hassfest.yml)
[![Lint and Test](https://github.com/ol-rac/imou-plugin/actions/workflows/lint-and-test.yml/badge.svg)](https://github.com/ol-rac/imou-plugin/actions/workflows/lint-and-test.yml)

A Home Assistant custom integration for [Imou](https://www.imou.com/) cameras via the Imou cloud API.

## Features

- Camera live streaming (HLS, HD and SD)
- Privacy switch (enable/disable camera)
- Motion and human detection binary sensors
- Sleep-aware polling (skips sleeping devices, conserves API quota)
- API budget management (tracks daily usage, auto-throttles near limits)
- Webhook event detection (optional push-based event delivery)
- PTZ control (pan, tilt, zoom for supported cameras)

## Installation via HACS

1. Open HACS in Home Assistant
2. Go to **Integrations** > three-dot menu > **Custom repositories**
3. Add `https://github.com/ol-rac/imou-plugin` with category **Integration**
4. Search for "Imou" in HACS and click **Install**
5. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for "Imou"
3. Enter your **AppId** and **AppSecret** from the [Imou Open Platform](https://open.imoulife.com/)
4. Select your **region** (Singapore, Frankfurt, Oregon, or China)
5. All cameras bound to your account are automatically discovered

## License

MIT
