# OnlineForge — 24/7 Discord Token Online Keeper

## Local (PC on)
```
pip install -r requirements.txt
# add tokens to tokens.txt
python keeper.py
```

## Railway (PC off — free cloud)
1. Push this folder to a GitHub repo (tokens.txt is gitignored)
2. Go to railway.app → New Project → Deploy from GitHub
3. In Railway dashboard → Variables → add:
   DISCORD_TOKENS = tok1,tok2,tok3
4. Deploy. Done. Stays online 24/7.

## VPS (Hetzner €4/mo or Oracle Free Tier)
```bash
git clone <your-repo> && cd OnlineForge
pip install -r requirements.txt
export DISCORD_TOKENS="tok1,tok2,tok3"
# run in background, survives SSH disconnect:
screen -S onlineforge python keeper.py
# detach: Ctrl+A then D
# reattach: screen -r onlineforge
```

## Token format
Supports raw token OR email:pass:user:TOKEN (last field used automatically).
DISCORD_TOKENS env var: comma-separated raw tokens only.
