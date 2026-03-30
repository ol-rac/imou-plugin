"""Constants for the Imou integration."""

DOMAIN = "imou_ha"

# Config keys
CONF_APP_ID = "app_id"
CONF_APP_SECRET = "app_secret"
CONF_API_URL = "api_url"

# Options keys
OPT_SCAN_INTERVAL = "scan_interval"

# Regional API base URLs (per D-04)
API_BASE_URLS: dict[str, str] = {
    "api_sg": "openapi-sg.easy4ip.com",
    "api_fk": "openapi-fk.easy4ip.com",
    "api_or": "openapi-or.easy4ip.com",
    "api_cn": "openapi.easy4ip.com",
}

# Friendly labels for config flow dropdown (per D-04)
REGIONAL_ENDPOINTS: dict[str, str] = {
    "api_sg": "Asia Pacific (Singapore)",
    "api_fk": "Europe (Frankfurt)",
    "api_or": "North America (Oregon)",
    "api_cn": "China",
}

# Default region (per D-05)
DEFAULT_API_URL = "api_fk"

# Polling interval (per D-08)
DEFAULT_SCAN_INTERVAL = 60
MIN_SCAN_INTERVAL = 30

# Platforms to forward (empty for Phase 1, expanded in later phases)
PLATFORMS: list[str] = []

# Imou error codes (from pyimouapi/const.py)
ERROR_CODE_TOKEN_EXPIRED = "TK1002"
ERROR_CODE_DEVICE_OFFLINE = "DV1007"
ERROR_CODE_DEVICE_SLEEPING = "DV1030"
ERROR_CODE_LICENSE_LIMIT = "FL1001"
ERROR_CODE_RATE_LIMIT = "OP1011"

# Capability strings (case-sensitive, from pyimouapi/const.py)
CAPABILITY_DORMANT = "Dormant"
CAPABILITY_MOTION_DETECT = "MobileDetect"
CAPABILITY_ALARM_MD = "AlarmMD"
CAPABILITY_PRIVACY = "closedCamera"
CAPABILITY_ELECTRIC = "Electric"
