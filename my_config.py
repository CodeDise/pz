# =====================================================================================
#  my_config.py  -  YOUR SETTINGS. Fill the values below, save, and upload this file
#                   to the ROOT folder of your GitHub repo (next to requirements.txt).
#
#  Rules:
#   * Keep every value inside quotes, like  BOT_TOKEN = "123456:ABC..."
#   * Do not delete a line. If you don't need a setting, leave it as it is.
#   * IMPORTANT: this file contains secrets. Your GitHub repo MUST be PRIVATE.
#     (If a bot token is ever public, anyone can take over your bot.)
#   * Render "Environment" variables still work and win over this file, but you
#     do not need to add anything there.
# =====================================================================================


# ---------- 1. Telegram bot  (REQUIRED) ----------
# Create the bot in Telegram with @BotFather (/newbot). It gives you the token.
BOT_TOKEN = "9235632896:AAHuHQ4MamW5NhqyXQgcU_aLerqHHHane4s"                 # example: "123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
BOT_USERNAME = "payzubot"      # the bot's username WITHOUT the @. Change it if yours is different.
APP_NAME = "Payzu"             # brand name shown on the website and dashboard


# ---------- 2. Database  (REQUIRED on Render) ----------
# Without this, your data is DELETED every time Render restarts or redeploys.
# How to get it: Render -> New -> PostgreSQL -> create -> open it -> copy the
# "Internal Database URL" and paste it here. It looks like: postgresql://user:password@host/dbname
DATABASE_URL = "mongodb+srv://itsyudo0_db_user:CR4HGDttw9JkMqYT@cluster0.lgu6ocy.mongodb.net/?compressors=zlib"


# ---------- 3. Owner panel password  (REQUIRED to approve merchants) ----------
# This is the password for  https://YOUR-APP.onrender.com/admin
# Make up your own long one: at least 16 characters, letters and numbers.
# If it is empty or shorter than 16 characters, the /admin page stays switched off.
ADMIN_TOKEN = "Kx9mP2vQ7rT4wZ8nB5cL1hJ6dF3sA0yE"


# ---------- 4. Security key  (optional) ----------
# Used to encrypt your merchants' gateway keys. Leave it empty and the app makes one
# from your BOT_TOKEN automatically. If you fill it, use 40+ random characters.
# NEVER change either of them after merchants have added keys, or those keys stop working.
SECRET_KEY = "7c2_example_encrypted_key_placeholder_to_replace_with_real_one"


# ---------- 5. Force-subscribe  (optional) ----------
# Users must join this channel before using the bot. Example: "@payzuupdates"
# Make your bot an ADMIN of that channel first. Leave empty to switch this off.
FSUB_CHANNEL = "@payzuupdates"


# ---------- 6. Crypto  (optional) ----------
TRONGRID_API_KEY = ""          # free key from trongrid.io, gives higher limits for TRC20 detection
BSC_RPC_URL = "https://bsc-dataseed.binance.org"   # BEP20 detection, the public default is fine


# ---------- 7. Advanced  (normally leave as it is) ----------
BASE_URL = ""                  # your public https address. Leave empty on Render, it is detected automatically.
REQUIRE_KYC = True             # True = you must approve a merchant before live payments. False = skip approval.
POLL_INTERVAL = 15             # how often (seconds) payments are re-checked
BSC_CONFIRMATIONS = 12
DEV_LOGIN = False              # keep False when live
ALLOW_PRIVATE_WEBHOOKS = False # keep False when live
