"""Static info about each supported gateway: official links, steps, and the credential fields we ask for.

All links point to the gateway's own official domains. The merchant creates their API keys THERE,
then pastes them into PayGate. Money always settles directly into the merchant's own gateway account.
"""

PROVIDERS = {
    "razorpay": {
        "name": "Razorpay",
        "tagline": "UPI, cards, netbanking & wallets",
        "accent": "#3395ff",
        "has_env": False,  # test/live is detected from the key prefix (rzp_test_ / rzp_live_)
        "links": {
            "signup": ("Create Razorpay account", "https://accounts.razorpay.com/auth/?x-country-code=IN"),
            "api_keys": ("Open API Keys page", "https://dashboard.razorpay.com/app/keys"),
            "docs": ("Razorpay docs", "https://razorpay.com/docs/"),
        },
        "steps": [
            "Sign up on Razorpay. Test mode works right after you verify your email, no documents needed.",
            "Open Dashboard → Account & Settings → API Keys and click Generate Key.",
            "Copy the Key ID and Key Secret (the secret is shown only once) and paste them below.",
        ],
        "fields": [
            {"key": "key_id", "label": "Key ID", "placeholder": "rzp_test_xxxxxxxxxxxxxx", "secret": False},
            {"key": "key_secret", "label": "Key Secret", "placeholder": "Your key secret", "secret": True},
        ],
        "webhook_help": "Optional, for instant confirmation: Dashboard → Webhooks → add the URL below and enable the "
                        "payment_link.paid event. Without it we still confirm payments automatically within seconds.",
    },
    "cashfree": {
        "name": "Cashfree",
        "tagline": "UPI, cards, netbanking & wallets",
        "accent": "#7c5cff",
        "has_env": True,
        "links": {
            "signup": ("Create Cashfree account", "https://merchant.cashfree.com/merchants/signup"),
            "api_keys": ("Open API Keys page", "https://merchant.cashfree.com/merchants/pg/developers/api-keys"),
            "docs": ("Cashfree docs", "https://www.cashfree.com/docs/"),
        },
        "steps": [
            "Sign up on Cashfree and open the Payment Gateway dashboard (use Test mode first).",
            "Go to Developers → API Keys and generate your App ID (Client ID) and Secret Key.",
            "Paste them below and pick Sandbox for test keys or Production for live keys.",
        ],
        "fields": [
            {"key": "client_id", "label": "App ID / Client ID", "placeholder": "Your Cashfree App ID", "secret": False},
            {"key": "client_secret", "label": "Secret Key", "placeholder": "Your Cashfree secret key", "secret": True},
        ],
        "webhook_help": "Nothing to configure. We attach the notification URL to each order automatically.",
    },
    "phonepe": {
        "name": "PhonePe PG",
        "tagline": "PhonePe Payment Gateway (Standard Checkout)",
        "accent": "#5f259f",
        "has_env": True,
        "links": {
            "signup": ("PhonePe Business onboarding", "https://business.phonepe.com/"),
            "api_keys": ("Developer docs & sandbox credentials",
                     "https://developer.phonepe.com/payment-gateway/uat-testing-go-live/uat-sandbox"),
            "docs": ("PhonePe PG docs", "https://developer.phonepe.com/payment-gateway"),
        },
        "steps": [
            "Register as a merchant on PhonePe Business and complete their onboarding (KYC is done by PhonePe).",
            "From your PhonePe PG dashboard / onboarding email, get the Client ID, Client Secret and Client Version. "
            "For testing, use the UAT sandbox credentials from the developer docs.",
            "Paste them below and pick Sandbox for UAT credentials or Production for live ones.",
        ],
        "fields": [
            {"key": "client_id", "label": "Client ID", "placeholder": "Your PhonePe Client ID", "secret": False},
            {"key": "client_secret", "label": "Client Secret", "placeholder": "Your PhonePe Client Secret", "secret": True},
            {"key": "client_version", "label": "Client Version", "placeholder": "1", "secret": False, "default": "1"},
        ],
        "webhook_help": "Optional. You can also point PhonePe's callback to the URL below for instant confirmation. "
                        "Payments are verified with PhonePe's status API either way.",
    },
}

CRYPTO_LINKS = {
    "binance": ("Binance: get your USDT deposit address",
                "https://www.binance.com/en/my/wallet/account/main/deposit/crypto"),
    "trust": ("Trust Wallet (create a wallet)", "https://trustwallet.com/"),
}
