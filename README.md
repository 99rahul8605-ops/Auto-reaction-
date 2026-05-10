# 🤖 Telegram Auto Reaction Bot

Har group ya channel message pe automatically emoji reaction deta hai.

---

## 📁 File Structure

```
telegram-reaction-bot/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker build file
├── .dockerignore       # Docker ignore rules
├── .env.example        # Environment variable template
├── .gitignore
└── README.md
```

---

## ⚙️ Environment Variables

| Variable    | Description                              |
|-------------|------------------------------------------|
| `API_ID`    | Telegram App ID (my.telegram.org/apps)   |
| `API_HASH`  | Telegram App Hash (my.telegram.org/apps) |
| `BOT_TOKEN` | Bot token from @BotFather                |
| `PORT`      | Health server port (default: 8080)       |

---

## 🚀 Render pe Deploy Karna

### Step 1 — Credentials Lena

1. **API_ID & API_HASH** → https://my.telegram.org/apps pe jao → App create karo
2. **BOT_TOKEN** → Telegram pe `@BotFather` se `/newbot` karo

### Step 2 — GitHub pe Push Karo

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### Step 3 — Render Setup

1. https://render.com pe jao → **New → Web Service**
2. GitHub repo connect karo
3. Settings:
   - **Environment:** Docker
   - **Dockerfile Path:** `./Dockerfile`
4. **Environment Variables** add karo:
   - `API_ID` = your api id
   - `API_HASH` = your api hash
   - `BOT_TOKEN` = your bot token
5. **Deploy** karo!

### Step 4 — Bot ko Group/Channel me Add Karo

- Bot ko group/channel me add karo
- Admin banao (reactions ke liye permission chahiye)
- Done! Bot automatically react karega 🎉

---

## 🏥 Health Check

Render health check ke liye ye endpoints available hain:

- `GET /` → `200 OK`
- `GET /health` → `200 OK`

---

## 🐳 Local Docker Test

```bash
# Build
docker build -t reaction-bot .

# Run
docker run -e API_ID=xxx -e API_HASH=xxx -e BOT_TOKEN=xxx -p 8080:8080 reaction-bot
```

---

## 😄 Reactions Pool

Bot in emojis mein se random ek select karta hai:

`👍 ❤️ 🔥 🎉 😍 👏 🤩 💯 😂 🥰`
