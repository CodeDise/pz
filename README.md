# PayGate: Telegram payment gateway bot (non-custodial)

यह प्रोजेक्ट merchants को **अपने ही Razorpay / Cashfree / PhonePe अकाउंट** या **अपने USDT wallet** से पेमेंट लेने देता है।
पैसा कभी आपके पास नहीं आता। आप सिर्फ टेक्नोलॉजी लेयर हैं: Telegram बॉट, डैशबोर्ड, API, hosted checkout, signed webhooks।

## क्या-क्या बना हुआ है

- **Telegram बॉट**: `/start`, `/dashboard`, `/orders`, `/verify` (Telegram से mobile number verify), हर पेमेंट पर नोटिफिकेशन
- **Merchant डैशबोर्ड** (ब्राउज़र + Telegram Mini App): Overview, Payments, Integrations, Developers, Settings
- **Integrations पेज**: हर गेटवे के ऊपर **ऑफिशियल लिंक** (साइन-अप, API keys पेज, docs), नीचे **"Add your API keys"** फ़ॉर्म। Keys encrypt होकर स्टोर होती हैं और सेव करते समय गेटवे से verify होती हैं
- **UPI/Cards**: Razorpay (Payment Links), Cashfree (Orders + JS checkout), PhonePe PG (Standard Checkout v2), सब merchant की अपनी keys से
- **Crypto**: USDT TRC20 (TronGrid) और BEP20 (BSC RPC), merchant के अपने wallet address पर, हर ऑर्डर का unique amount
- **API** `/api/v1`: orders बनाना/देखना/cancel, API keys (test + live), idempotency, rate limit
- **Webhooks**: HMAC-SHA256 signed, 8 बार retry, SSRF protection
- **Docs पेज** `/docs`: curl, Python, Node.js, PHP के कोड सैंपल के साथ। Swagger: `/api/swagger`
- **Test mode**: "Simulate payment" बटन, बिना असली पैसे के पूरा flow चेक करो
- **Admin पैनल** `/admin`: merchants को approve/reject करो (live payments के लिए approval ज़रूरी)

## Render पर deploy (step by step)

1. **Telegram बॉट बनाओ**: Telegram में `@BotFather` खोलो, `/newbot`, नाम और username दो। `BOT_TOKEN` और `BOT_USERNAME` कॉपी कर लो।
2. **GitHub पर पुश करो**: इस फोल्डर के सारे फाइल्स एक नई repo में अपलोड करो (ZIP को extract करके)।
3. **Render**: Dashboard → **New → Blueprint** → अपनी repo चुनो। `render.yaml` से web service और Postgres अपने-आप बन जाएंगे।
   (मैन्युअल करना हो तो New → Web Service: Build `pip install -r requirements.txt`, Start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`)
4. **सारी वैल्यू `my_config.py` में भरो** (रूट फोल्डर की फाइल), तब Render के Environment में कुछ नहीं डालना पड़ता। **रिपो Private रखना**, क्योंकि फाइल में secrets हैं।
   नीचे की लिस्ट सिर्फ़ तब काम की है जब तुम Render के Environment से सेट करना चाहो (वो फाइल पर भारी पड़ता है):
   - `BOT_TOKEN`, `BOT_USERNAME` (बिना @)
   - `ADMIN_TOKEN` = कोई लंबा random टेक्स्ट (आपका admin पासवर्ड)
   - `SECRET_KEY` Render अपने-आप बना देता है। **इसे बाद में मत बदलना**, वरना सेव की हुई merchant keys पढ़ी नहीं जाएंगी
5. Deploy होते ही बॉट का webhook अपने-आप सेट हो जाता है। बॉट में `/start` भेजो।
6. अपने आप को approve करो: `https://आपका-app.onrender.com/admin` → `ADMIN_TOKEN` डालो → अपना merchant Approve करो।

> **Free plan की सीमा:** Render का free web service 15 मिनट idle रहने पर सो जाता है। तब क्रिप्टो/वेबहुक का बैकग्राउंड वर्कर भी रुक जाता है। असली इस्तेमाल के लिए paid instance लो। Free Postgres भी 30 दिन बाद expire होता है।

## पहली बार चेक करने का तरीका

1. बॉट में `/start` → **Open dashboard**
2. **Developers** → "Create key" (Test) → key कॉपी करो
3. **Payments** → test payment link बनाओ → खोलकर **Simulate successful payment** दबाओ → Telegram में नोटिफिकेशन आएगा
4. **Integrations** → Razorpay का "Open API Keys page" लिंक → वहाँ test keys बनाओ → वापस आकर "Add your API keys" में डालो
5. Live mode में (अपने approve होने के बाद) INR का payment link बनाओ। Razorpay/Cashfree sandbox keys से असली पैसे के बिना पूरा gateway flow चेक हो जाता है

## लोकल में चलाना

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # SECRET_KEY भरो, DEV_LOGIN=1 रखो
export $(grep -v '^#' .env | xargs)
uvicorn app.main:app --reload
```
`http://localhost:8000/login` पर "Developer login" से बिना Telegram के डैशबोर्ड खुल जाएगा।

## ज़रूरी बातें (कृपया पढ़ें)

- **यह कोड मैंने लाइव Razorpay/Cashfree/PhonePe/Telegram के सामने टेस्ट नहीं किया है** (मेरे वातावरण में नेटवर्क नहीं था)। गेटवे के API format उनके ऑफिशियल docs के हिसाब से लिखे हैं, पर पहली बार sandbox keys से ज़रूर चेक करो। कुछ टूटे तो Render का log और error मुझे भेज दो।
- **KYC**: अभी बेसिक है: नाम, बिज़नेस, email, Telegram से verified mobile, और आपका manual approval। असली identity verification के लिए बाद में कोई KYC provider जोड़ना होगा। PAN/Aadhaar जैसे documents इसमें स्टोर नहीं होते।
- **कानूनी**: Non-custodial मॉडल में आप पैसा नहीं रखते, इसलिए लाइसेंस का रिस्क कम है। फिर भी बिज़नेस शुरू करने से पहले CA/वकील से पूछ लो, ख़ासकर क्रिप्टो वाले हिस्से के लिए।
- **UPI**: UPI ID + password/email से पेमेंट confirm करने वाला कोई तरीका इसमें जानबूझकर नहीं है। सिर्फ़ गेटवे की ऑफिशियल API इस्तेमाल होती है।
- **Crypto**: ग्राहक को ठीक वही amount भेजना होता है जो पेज पर दिखे (आख़िरी digits से हम पेमेंट पहचानते हैं)। गलत amount/नेटवर्क का पेमेंट अपने-आप match नहीं होगा।
- **Multi-instance**: बैकग्राउंड वर्कर वेब प्रोसेस के अंदर चलता है। एक ही instance (1 worker) रखो।

## फोल्डर

```
app/
  main.py            FastAPI ऐप + startup
  config.py          environment variables
  models.py          database tables
  security.py        encryption, signed tokens, API keys
  worker.py          background loop
  routers/           api, checkout, dashboard, admin, hooks, pages
  services/          orders, crypto, webhooks, telegram, gateways/{razorpay,cashfree,phonepe}
  templates/         HTML (dashboard, checkout, docs)
  static/            CSS + JS
```
