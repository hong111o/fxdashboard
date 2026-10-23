# WhatsApp bot setup

Chat with FX Watch on WhatsApp: send `check`, `target GBP/HKD 10.05` and so
on, and get the answer in about a minute.

```
You (WhatsApp) ──► Meta WhatsApp Cloud API ──► Cloudflare Worker (whatsapp-bot/worker.js)
                                                     │ checks it's really Meta and really you,
                                                     │ then starts the "FX Watch" GitHub workflow
                                                     ▼
You (WhatsApp) ◄────────────── reply ◄────── GitHub Actions (applies the command, checks rates)
```

**Time:** about 45–60 minutes, once. **Cost:** free (see [Costs](#costs)).
You'll collect a few values as you go. Keep them in a note while you work:

| Value | From step |
|---|---|
| `WA_PHONE_NUMBER_ID` | 2 |
| `APP_SECRET` | 3 |
| `WA_TOKEN` (permanent) | 4 |
| `GITHUB_TOKEN` | 5 |
| `VERIFY_TOKEN` | 6 (you make this up) |

> Before you start: the code must be on your **main** branch (merge the pull
> request), because the bot runs the workflow from `main`.

---

## Part A: Meta (WhatsApp)

Meta renames menus fairly often. If a screen doesn't match, look for the
closest wording, or send me a screenshot.

### 1. Create a Meta app
1. Go to <https://developers.facebook.com>, log in with Facebook, and click
   **Get started** to register as a developer if asked.
2. Click **My Apps → Create app**.
3. For the use case, choose **Connect with customers through WhatsApp**. If
   asked for an app type instead, choose **Business**.
4. Give it a name, e.g. `FX Watch`. When asked for a **business portfolio**,
   create one with your own name. No verification is needed for personal use.

### 2. Get the test number and add your phone
1. In the app's left menu, open **WhatsApp → API Setup**.
2. Under **From**, Meta gives you a free **test phone number**. This is the
   bot. Copy the **Phone number ID** shown under it → `WA_PHONE_NUMBER_ID`.
3. Under **To**, click **Manage phone number list**, add **your** WhatsApp
   number, and enter the code WhatsApp sends you.
4. Click **Send message** to send the `hello_world` test. You should receive
   it on WhatsApp. **Save the sender as a contact**, e.g. "FX Watch".

### 3. Copy the app secret
**App settings → Basic → App secret → Show**. Copy it → `APP_SECRET`.

### 4. Create a permanent access token (the fiddly step)
The token on the API Setup page **expires after 24 hours**, so don't use it.
Create a permanent one instead:

1. Go to <https://business.facebook.com/settings> and pick your business
   portfolio.
2. **Users → System users → Add**. Name it `fxwatch` and set the role to
   **Admin**.
3. With the system user selected, click **Assign assets**:
   - **Apps** → your FX Watch app → **Full control**
   - **WhatsApp accounts** → your test WhatsApp account → **Full control**
4. Click **Generate new token**, choose your app, set the expiry to
   **Never**, and tick the permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Copy the token → `WA_TOKEN`. **It's only shown once.**

---

## Part B: GitHub token

### 5. Create a token the Worker can use to start the workflow
1. On GitHub, go to **your profile picture → Settings → Developer settings →
   Personal access tokens → Fine-grained tokens → Generate new token**.
2. Name: `fxwatch-whatsapp`. Expiration: the longest available. Add a
   calendar reminder to renew it.
3. **Repository access → Only select repositories → `fxdashboard`**.
4. **Permissions → Repository permissions → Actions → Read and write**.
   Leave everything else as it is.
5. Generate it and copy it → `GITHUB_TOKEN`.

---

## Part C: Cloudflare Worker (the relay)

### 6. Create the Worker
1. Sign up for free at <https://dash.cloudflare.com>.
2. **Workers & Pages → Create → Create Worker** (the "Hello World" one). Name
   it `fxwatch-whatsapp` and click **Deploy**.
3. Click **Edit code**, delete everything, paste in the whole of
   [`whatsapp-bot/worker.js`](../whatsapp-bot/worker.js), and click **Deploy**.
4. Note the Worker's address, e.g.
   `https://fxwatch-whatsapp.<your-name>.workers.dev`.
5. In the Worker, open **Settings → Variables and Secrets** and add these as
   **Secret** (encrypted) values:

   | Name | Value |
   |---|---|
   | `VERIFY_TOKEN` | make up a long password, e.g. `fx-verify-8f3k2...` |
   | `APP_SECRET` | from step 3 |
   | `OWNER_PHONE` | your number, digits only with country code: `447700900123` |
   | `WA_TOKEN` | from step 4 |
   | `WA_PHONE_NUMBER_ID` | from step 2 |
   | `GITHUB_TOKEN` | from step 5 |

   and these as plain **Text** values:

   | Name | Value |
   |---|---|
   | `GITHUB_REPO` | `hong111o/fxdashboard` |
   | `GITHUB_REF` | `main` |

<details>
<summary>Alternative: deploy from the command line</summary>

```bash
cd whatsapp-bot
npx wrangler login
npx wrangler deploy
for s in VERIFY_TOKEN APP_SECRET OWNER_PHONE WA_TOKEN WA_PHONE_NUMBER_ID GITHUB_TOKEN; do
  npx wrangler secret put $s
done
```
`GITHUB_REPO` and `GITHUB_REF` are already in `wrangler.toml`.
</details>

### 7. Connect Meta to the Worker
1. Back in the Meta app: **WhatsApp → Configuration → Webhook → Edit**.
2. **Callback URL:** your Worker address from step 6.
   **Verify token:** the `VERIFY_TOKEN` you made up.
3. Click **Verify and save**. If it fails, recheck `VERIFY_TOKEN` in
   Cloudflare.
4. Under **Webhook fields**, click **Manage** and **Subscribe** to
   **messages**.

---

## Part D: GitHub secrets for replies

### 8. Let the workflow reply on WhatsApp
In the repo, go to **Settings → Secrets and variables → Actions → New
repository secret** and add:

| Secret | Value |
|---|---|
| `WA_TOKEN` | from step 4 |
| `WA_PHONE_NUMBER_ID` | from step 2 |
| `WHATSAPP_PHONE` | your number, e.g. `+447700900123` (you may already have this from CallMeBot) |

### 9. Test it 🎉
Send **`help`** to your FX Watch contact on WhatsApp. You should get:
1. `⏳ Got it - working on it...` within a few seconds (from the Worker), then
2. the command list, about a minute later (from GitHub Actions).

Then try `check`, or `target GBP/HKD 10.05`.

---

## Commands

```
check                         current rates vs your targets
rate GBP/HKD                  latest mid-market rate for any pair
list                          show current targets and levels
target GBP/HKD 10.05          set a conversion alert's target
above AUD/USD 0.68            set a watch's upper level
below AUD/USD 0.64            set a watch's lower level
clear AUD/USD [above|below]   remove a watch's level(s)
pause GBP/JPY / resume GBP/JPY
help
```

To make several changes, **put them in one message**, one per line. GitHub
queues at most one waiting run, so commands sent seconds apart in separate
messages can be dropped. Wait for each reply before sending the next message.

## Costs

| Part | Free allowance | Your use |
|---|---|---|
| WhatsApp Cloud API | Replies within 24h of your message are free | Every command reply is inside that window |
| Alerts | FX Watch only uses the bot for alerts within 24h of your last message; otherwise it uses CallMeBot (free) or Telegram | No paid template messages are ever sent |
| Cloudflare Workers | 100,000 requests/day | A handful a day |
| GitHub Actions | Unlimited for public repos; 2,000 min/month for private | ~720 min for hourly checks + ~1 min per command |

Pricing rules belong to Meta, Cloudflare and GitHub and can change, so check
their pricing pages if anything looks different.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No "⏳ Got it" reply | Webhook not subscribed to **messages** (step 7.4), wrong `OWNER_PHONE` (digits only, with country code), or wrong `APP_SECRET`. Check the Worker's **Logs** tab in Cloudflare. |
| "Couldn't start FX Watch (GitHub said 404)" | `GITHUB_REPO` is wrong, or the workflow isn't on `main` yet |
| "... (GitHub said 401/403)" | `GITHUB_TOKEN` expired or lacks **Actions: Read and write** |
| "Got it" arrives but no answer | Check **Actions → FX Watch** for the run's log, and the `WA_TOKEN` / `WA_PHONE_NUMBER_ID` GitHub secrets |
| Everything stopped after a day | You used the 24-hour token from the API Setup page; make the permanent one (step 4) |
| Meta API errors mentioning the version | Set `GRAPH_VERSION` (Worker text variable and GitHub secret) to a current version, e.g. `v24.0` |
