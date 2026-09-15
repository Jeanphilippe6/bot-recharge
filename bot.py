import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import logging
import os
import re
import sqlite3
import threading
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------
# SERVEUR WEB SECONDAIRE (UPTIMEROBOT)
# ---------------------------------------------------------
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Telegram Actif")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), DummyHandler).serve_forever()

# ---------------------------------------------------------
# BASE DE DONNÉES SQLITE
# ---------------------------------------------------------
DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            balance INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'fr',
            referrer_id INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            produit TEXT,
            devise TEXT,
            montant_eur INTEGER,
            montant_crypto INTEGER,
            code TEXT,
            statut TEXT,
            date_creation TEXT,
            rating INTEGER DEFAULT 0,
            methode_paiement TEXT,
            numero_paiement TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('liquidite', '50000000')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', '0')")

    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_FILE)

# ---------------------------------------------------------
# CONFIGURATION ET TRADUCTIONS
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "TON_TOKEN_ICI")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))

BONUS_PARRAINAGE = 125
SEUIL_MIN_RETRAIT = 2000
TIMEOUT_SESSION = 600  # 10 minutes en secondes (600s)

TEXTS = {
    "fr": {
        "welcome": "Bienvenue {name} ! 👋\nPlateforme professionnelle d'échange.",
        "pcs": "💳 PCS",
        "transcash": "💳 Transcash",
        "cryptonow": "🪙 Cryptonow",
        "paysafecard": "🔒 Paysafecard",
        "solde": "💼 Mon Solde & Retrait",
        "history": "📜 Mes Transactions",
        "parrainage": "👥 Parrainage (+125 XOF)",
        "lang": "🌐 Langue / Language",
        "select_lang": "Choisissez votre langue :",
        "lang_updated": "✅ Langue mise à jour en Français !",
        "liquidite_disp": "💧 **Liquidité globale disponible :** {liq:,} XOF",
        "no_tx": "📜 Vous n'avez encore effectué aucune transaction.",
        "tx_title": "📜 **HISTORIQUE COMPLET DE VOS TRANSACTIONS :**\n\n",
        "ask_qty": "🔢 Combien de recharges **{produit}** de **{eur}€** avez-vous ?\n\n_Veuillez répondre par un chiffre (ex: 1, 2, 5...)_\n\n⏳ Temps restant : **{m:02d}:{s:02d}**",
        "ask_code": "👉 Veuillez envoyer vos **{qty} code(s) de recharge {produit}** (sous forme de texte ou de photo) ci-dessous :\n\n⏳ Temps restant : **{m:02d}:{s:02d}**",
        "ask_mixed_codes": "🔀 **RECHARGES MULTIPLES / DIFFÉRENTS MONTANTS**\n\nVeuillez envoyer tous vos codes ci-dessous (texte ou photo) en précisant le montant.\n\n**Exemple de format texte :**\n<code>100€ - ABCD1234EF\n50€ - XYZ987654\n20€ - QWER112233</code>\n\n⏳ Temps restant : **{m:02d}:{s:02d}**",
        "code_received": "⏳ Code/Photo reçu(e) ! Vérification en cours...",
        "success_recharge": "🎉 **FÉLICITATIONS !** 🥳👏\nVotre recharge {produit} a été validée avec succès !",
        "select_payment_method": "📲 **CHOIX DU MODE DE PAIEMENT**\n\nVotre recharge est validée ! Veuillez sélectionner le moyen par lequel vous souhaitez recevoir votre paiement ({montant:,} XOF) :",
        "ask_phone_number": "📱 Veuillez envoyer votre numéro de téléphone **{methode}** ci-dessous pour recevoir le paiement :",
        "phone_received": "✅ Numéro reçu ! L'administrateur procède à l'envoi du paiement...",
        "payment_sent": "💸 **PAIEMENT EFFECTUÉ !** 💸\n\nVotre paiement de **{montant:,} XOF** a été envoyé avec succès sur votre compte **{methode}** ({numero}). Merci pour votre confiance !",
        "phone_unreachable": "⚠️ **NUMÉRO INATTEIGNABLE OU INVALIDE** ⚠️\n\nL'administrateur signale que votre numéro **{numero}** est injoignable ou incorrect.\n\n👉 Veuillez renvoyer un **autre numéro de téléphone** pour recevoir votre paiement :",
        "code_refused": "❌ **Code invalide ou déjà utilisé.** Veuillez réessayer.",
        "completer_demande": "⚠️ **RECHARGE INCOMPLÈTE !** ⚠️\n\nL'administrateur signale qu'il manque un ou plusieurs codes pour votre recharge **{produit}**.\n\n👉 Veuillez répondre ci-dessous en envoyant les codes ou photos manquants :\n\n⏳ Temps restant : **{m:02d}:{s:02d}**",
        "retrait_insuffisant": "❌ **Solde insuffisant.** Le montant minimum pour effectuer un retrait est de {min_retrait:,} XOF.",
        "retrait_demande": "💸 **DEMANDE DE RETRAIT** ({solde:,} XOF)\n\nVeuillez envoyer votre numéro de dépôt (Wave, Orange, MTN, Moov) :",
        "rate_prompt": "⭐ **ÉVALUATION DE LA TRANSACTION** ⭐\nComment évaluez-vous ce service ? Notez sur 7 étoiles :",
        "thanks_rate": "🙏 **Merci pour votre note de {stars}/7 !** Votre avis nous aide à nous améliorer.",
        "liquidite_insuffisante": "⚠️ **TRANSACTION IMPOSSIBLE** ⚠️\n\nLa liquidité disponible actuellement ({liq:,} XOF) est insuffisante pour traiter cette transaction de {montant:,} XOF. Veuillez réessayer plus tard ou choisir un montant inférieur.",
        "qty_invalid": "❌ **Saisie invalide.** Veuillez taper un nombre entier.",
        "session_expired": "⏱ **SESSION EXPIRÉE !** ⚠️\n\nLe délai de 10 minutes est écoulé. La session a été fermée.\n\nVeuillez relancer une nouvelle demande dans le menu.",
        "back": "🔙 Retour"
    },
    "en": {
        "welcome": "Welcome {name}! 👋\nProfessional gift card exchange platform.",
        "pcs": "💳 PCS Card",
        "transcash": "💳 Transcash",
        "cryptonow": "🪙 Cryptonow",
        "paysafecard": "🔒 Paysafecard",
        "solde": "💼 My Balance & Withdrawal",
        "history": "📜 My Transactions",
        "parrainage": "👥 Referral (+125 XOF)",
        "lang": "🌐 Language / Langue",
        "select_lang": "Select your language:",
        "lang_updated": "✅ Language updated to English!",
        "liquidite_disp": "💧 **Available Global Liquidity:** {liq:,} XOF",
        "no_tx": "📜 You haven't made any transactions yet.",
        "tx_title": "📜 **FULL TRANSACTION HISTORY:**\n\n",
        "ask_qty": "🔢 How many **{produit}** top-up cards of **{eur}€** do you have?\n\n_Please enter a number (e.g., 1, 2, 5...)_\n\n⏳ Time remaining: **{m:02d}:{s:02d}**",
        "ask_code": "👉 Please send your **{qty} {produit} top-up code(s)** (text or photo) below:\n\n⏳ Time remaining: **{m:02d}:{s:02d}**",
        "ask_mixed_codes": "🔀 **MULTIPLE CARDS / DIFFERENT AMOUNTS**\n\nPlease send all your codes below (text or photo), specifying the amount.\n\n**Example text format:**\n<code>100€ - ABCD1234EF\n50€ - XYZ987654\n20€ - QWER112233</code>\n\n⏳ Time remaining: **{m:02d}:{s:02d}**",
        "code_received": "⏳ Code/Photo received! Verification in progress...",
        "success_recharge": "🎉 **CONGRATULATIONS!** 🥳👏\nYour {produit} top-up has been successfully validated!",
        "select_payment_method": "📲 **SELECT PAYMENT METHOD**\n\nYour top-up is validated! Please select how you want to receive your payment ({montant:,} XOF):",
        "ask_phone_number": "📱 Please enter your **{methode}** phone number below to receive payment:",
        "phone_received": "✅ Number received! The administrator is processing your payment...",
        "payment_sent": "💸 **PAYMENT SENT!** 💸\n\nYour payment of **{montant:,} XOF** was sent successfully to your **{methode}** account ({numero}). Thank you for your trust!",
        "phone_unreachable": "⚠️ **UNREACHABLE OR INVALID NUMBER** ⚠️\n\nThe administrator reported that your number **{numero}** is unreachable or incorrect.\n\n👉 Please send a **different phone number** to receive your payment:",
        "code_refused": "❌ **Invalid code or already used.** Please try again.",
        "completer_demande": "⚠️ **INCOMPLETE TOP-UP!** ⚠️\n\nThe administrator reported missing code(s) for your **{produit}** recharge.\n\n👉 Please reply below with the missing code(s) or photo(s):\n\n⏳ Time remaining: **{m:02d}:{s:02d}**",
        "retrait_insuffisant": "❌ **Insufficient balance.** The minimum withdrawal amount is {min_retrait:,} XOF.",
        "retrait_demande": "💸 **WITHDRAWAL REQUEST** ({solde:,} XOF)\n\nPlease send your payment account details:",
        "rate_prompt": "⭐ **TRANSACTION RATING** ⭐\nHow would you rate our service? Please give a rating out of 7 stars:",
        "thanks_rate": "🙏 **Thank you for your {stars}/7 rating!** Your feedback is appreciated.",
        "liquidite_insuffisante": "⚠️ **TRANSACTION NOT POSSIBLE** ⚠️\n\nThe current available liquidity ({liq:,} XOF) is insufficient to process this transaction of {montant:,} XOF. Please try again later or select a smaller amount.",
        "qty_invalid": "❌ **Invalid input.** Please type a valid number.",
        "session_expired": "⏱ **SESSION EXPIRED!** ⚠️\n\n10 minutes have passed without activity. Your session has been closed.\n\nPlease start a new request from the main menu.",
        "back": "🔙 Back"
    }
}

GRILLES_TARIFS = {
    "PCS": {
        20: 7000,
        50: 23000,
        100: 53000,
        150: 83000,
        200: 108000,
        250: 143000,
    },
    "Transcash": {
        20: 8000,
        50: 28000,
        100: 58000,
        150: 88000,
        200: 118000,
        250: 148000,
        500: 300000,
    },
    "Cryptonow": {
        20: 8000,
        50: 24000,
        100: 54000,
        150: 83000,
        200: 110000,
        250: 143000,
        500: 285000,
    },
    "Paysafecard": {
        20: 6000,
        50: 20000,
        100: 45000,
    }
}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

def get_user_lang(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else "fr"

def client_keyboard(lang):
    t = TEXTS[lang]
    keyboard = [
        [InlineKeyboardButton(t["pcs"], callback_data="prod_PCS"), InlineKeyboardButton(t["transcash"], callback_data="prod_Transcash")],
        [InlineKeyboardButton(t["cryptonow"], callback_data="prod_Cryptonow"), InlineKeyboardButton(t["paysafecard"], callback_data="prod_Paysafecard")],
        [InlineKeyboardButton(t["solde"], callback_data="menu_solde"), InlineKeyboardButton(t["history"], callback_data="menu_history")],
        [InlineKeyboardButton(t["parrainage"], callback_data="menu_parrainage"), InlineKeyboardButton(t["lang"], callback_data="menu_lang")]
    ]
    return InlineKeyboardMarkup(keyboard)

def rating_keyboard(tx_id):
    keyboard = [[InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{tx_id}_{i}") for i in range(1, 8)]]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# FONCTION DU COMPTE À REBOURS EN DIRECT
# ---------------------------------------------------------
async def demarrer_compte_a_rebours(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, text_template: str, kwargs: dict):
    if "timer_task" in context.user_data and context.user_data["timer_task"]:
        context.user_data["timer_task"].cancel()

    async def _timer():
        time_left = TIMEOUT_SESSION
        while time_left > 0:
            if context.user_data.get("etape") is None:
                break

            m, s = divmod(time_left, 60)
            text_mis_a_jour = text_template.format(m=m, s=s, **kwargs)

            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text_mis_a_jour,
                    parse_mode="Markdown" if "<code>" not in text_mis_a_jour else "HTML"
                )
            except Exception:
                pass

            await asyncio.sleep(2)
            time_left -= 2

        if time_left <= 0 and context.user_data.get("etape") is not None:
            context.user_data["etape"] = None
            lang = get_user_lang(chat_id)
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=TEXTS[lang]["session_expired"],
                    reply_markup=client_keyboard(lang)
                )
            except Exception:
                pass

    context.user_data["timer_task"] = asyncio.create_task(_timer())

# ---------------------------------------------------------
# COMMANDES CLIENT & ADMIN
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if "timer_task" in context.user_data and context.user_data["timer_task"]:
        context.user_data["timer_task"].cancel()
    context.user_data["etape"] = None

    conn = get_db()
    cursor = conn.cursor()

    referrer_id = None
    if context.args and context.args[0].isdigit():
        ref_candidate = int(context.args[0])
        if ref_candidate != user.id:
            referrer_id = ref_candidate

    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users (user_id, full_name, username, referrer_id) VALUES (?, ?, ?, ?)",
            (user.id, user.full_name, user.username or "", referrer_id)
        )
        conn.commit()
    conn.close()

    lang = get_user_lang(user.id)
    await update.message.reply_text(
        TEXTS[lang]["welcome"].format(name=html.escape(user.first_name)),
        reply_markup=client_keyboard(lang)
    )

async def admin_set_liquidite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    try:
        montant = int(context.args[0])
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET value = ? WHERE key='liquidite'", (str(montant),))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"💧 **Liquidité mise à jour :** {montant:,} XOF", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Usage: `/liquidite 50000000`", parse_mode="Markdown")

# ---------------------------------------------------------
# CALLBACKS CLIENT & ADMIN
# ---------------------------------------------------------
async def gerer_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    lang = get_user_lang(user.id)
    t = TEXTS[lang]

    conn = get_db()
    cursor = conn.cursor()

    if data == "menu_main":
        if "timer_task" in context.user_data and context.user_data["timer_task"]:
            context.user_data["timer_task"].cancel()
        context.user_data["etape"] = None
        await query.edit_message_text("Menu :", reply_markup=client_keyboard(lang))

    elif data == "menu_lang":
        keyboard = [
            [InlineKeyboardButton("🇫🇷 Français", callback_data="setlang_fr"), InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en")],
            [InlineKeyboardButton(t["back"], callback_data="menu_main")]
        ]
        await query.edit_message_text(t["select_lang"], reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("setlang_"):
        new_lang = data.split("_")[1]
        cursor.execute("UPDATE users SET lang = ? WHERE user_id = ?", (new_lang, user.id))
        conn.commit()
        await query.edit_message_text(TEXTS[new_lang]["lang_updated"], reply_markup=client_keyboard(new_lang))

    elif data == "menu_solde":
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
        solde = cursor.fetchone()[0]
        cursor.execute("SELECT value FROM settings WHERE key='liquidite'")
        liquidite = int(cursor.fetchone()[0])

        txt = (
            f"💼 <b>PORTEFEUILLE / WALLET</b>\n\n"
            f"💰 Solde : <b>{solde:,} XOF</b>\n"
            f"{t['liquidite_disp'].format(liq=liquidite)}\n"
        )
        keyboard = [
            [InlineKeyboardButton("💸 Demander un Retrait", callback_data="action_retrait")],
            [InlineKeyboardButton(t["back"], callback_data="menu_main")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "action_retrait":
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
        solde = cursor.fetchone()[0]

        if solde < SEUIL_MIN_RETRAIT:
            keyboard = [[InlineKeyboardButton(t["back"], callback_data="menu_solde")]]
            await query.edit_message_text(
                t["retrait_insuffisant"].format(min_retrait=SEUIL_MIN_RETRAIT),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            context.user_data["etape"] = "ATTENTE_RETRAIT"
            await query.edit_message_text(t["retrait_demande"].format(solde=solde), parse_mode="Markdown")

    elif data == "menu_parrainage":
        cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user.id,))
        nb_filleuls = cursor.fetchone()[0]
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user.id}"

        keyboard = [[InlineKeyboardButton(t["back"], callback_data="menu_main")]]
        await query.edit_message_text(
            f"👥 <b>PROGRAMME DE PARRAINAGE</b>\n\nGagnez <b>{BONUS_PARRAINAGE} XOF</b> pour chaque ami invité qui effectue sa première transaction validée !\n\n🔗 <b>Lien d'invitation :</b>\n<code>{link}</code>\n\n📊 Filleuls inscrits : <b>{nb_filleuls}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "menu_history":
        cursor.execute("SELECT produit, montant_eur, montant_crypto, statut, date_creation, rating FROM transactions WHERE user_id = ? ORDER BY id DESC", (user.id,))
        rows = cursor.fetchall()

        if not rows:
            txt = t["no_tx"]
        else:
            txt = t["tx_title"]
            for r in rows:
                date_heure = r[4] if r[4] else "N/A"
                note_str = f" | ⭐ {r[5]}/7" if r[5] > 0 else ""
                txt += f"• <b>[{date_heure}]</b> {html.escape(r[0])} {r[1]}€ ➡️ {r[2]:,} XOF ({r[3]}){note_str}\n"

        keyboard = [[InlineKeyboardButton(t["back"], callback_data="menu_main")]]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("prod_"):
        produit = data.split("_")[1]
        context.user_data["produit"] = produit
        tarifs = GRILLES_TARIFS.get(produit, {})

        keyboard = [[InlineKeyboardButton(f"{eur}€ ➡️ {xof:,} XOF", callback_data=f"montant_{eur}_{xof}")] for eur, xof in tarifs.items()]
        keyboard.append([InlineKeyboardButton("🔀 Montants multiples / Différents", callback_data="montant_mixte")])
        keyboard.append([InlineKeyboardButton(t["back"], callback_data="menu_main")])

        await query.edit_message_text(
            f"Service : <b>{html.escape(produit)}</b>\n_Sélectionnez un montant fixe ou choisissez 'Montants multiples' si vous avez plusieurs coupons différents._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "montant_mixte":
        context.user_data["is_mixte"] = True
        context.user_data["etape"] = "ATTENTE_CODE_MIXTE"
        
        await demarrer_compte_a_rebours(
            context, query.message.chat_id, query.message.message_id,
            t["ask_mixed_codes"], {}
        )

    elif data.startswith("montant_"):
        parts = data.split("_")
        montant_eur = int(parts[1])
        montant_crypto_unitaire = int(parts[2])

        context.user_data["is_mixte"] = False
        context.user_data["montant_eur"] = montant_eur
        context.user_data["montant_crypto_unitaire"] = montant_crypto_unitaire
        context.user_data["etape"] = "ATTENTE_QUANTITE"

        produit = context.user_data.get("produit")

        await demarrer_compte_a_rebours(
            context, query.message.chat_id, query.message.message_id,
            t["ask_qty"], {"produit": produit, "eur": montant_eur}
        )

    elif data.startswith("paymethod_"):
        parts = data.split("_")
        methode = parts[1]
        tx_id = int(parts[2])

        context.user_data["etape"] = "ATTENTE_NUMERO_PAIEMENT"
        context.user_data["methode_paiement"] = methode
        context.user_data["tx_id_paiement"] = tx_id

        await query.edit_message_text(
            t["ask_phone_number"].format(methode=methode),
            parse_mode="Markdown"
        )

    elif data.startswith("rate_"):
        parts = data.split("_")
        tx_id = int(parts[1])
        stars = int(parts[2])

        cursor.execute("UPDATE transactions SET rating = ? WHERE id = ?", (stars, tx_id))
        conn.commit()

        await query.edit_message_text(t["thanks_rate"].format(stars=stars), parse_mode="Markdown")

    conn.close()

# ---------------------------------------------------------
# TRAITEMENT DU CONTENU (TEXTE & PHOTO DU CLIENT OU ADMIN)
# ---------------------------------------------------------
async def enregistrer_et_envoyer_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE, code_text: str, photo_file_id: str = None):
    user = update.effective_user
    etape = context.user_data.get("etape")
    lang = get_user_lang(user.id)
    t = TEXTS[lang]

    if "timer_task" in context.user_data and context.user_data["timer_task"]:
        context.user_data["timer_task"].cancel()

    produit = context.user_data.get("produit")
    tx_id_origine = context.user_data.get("tx_id_completer")
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    contenu_code = code_text if code_text else "[PHOTO REÇUE]"

    if etape == "ATTENTE_CODE_MIXTE":
        valeurs_trouvees = [int(v) for v in re.findall(r'(\d+)\s*(?:€|eur|euros)', code_text, re.IGNORECASE)] if code_text else []
        montant_eur = sum(valeurs_trouvees) if valeurs_trouvees else 0
        grille = GRILLES_TARIFS.get(produit, {})
        montant_crypto = sum(grille.get(val, val * 500) for val in valeurs_trouvees) if valeurs_trouvees else 0
        quantite = len(valeurs_trouvees) if valeurs_trouvees else 1
    else:
        montant_eur = context.user_data.get("montant_eur", 0)
        montant_crypto = context.user_data.get("montant_crypto", 0)
        quantite = context.user_data.get("quantite", 1)

    context.user_data["etape"] = None
    conn = get_db()
    cursor = conn.cursor()

    if tx_id_origine:
        cursor.execute("SELECT code FROM transactions WHERE id = ?", (tx_id_origine,))
        ancien_code = cursor.fetchone()[0]
        nouveau_code = f"{ancien_code}\n--- COMPLÉMENT DU {now_str} ---\n{contenu_code}"
        cursor.execute("UPDATE transactions SET code = ?, statut = 'En attente' WHERE id = ?", (nouveau_code, tx_id_origine))
        tx_id = tx_id_origine
        context.user_data["tx_id_completer"] = None
    else:
        cursor.execute(
            "INSERT INTO transactions (user_id, produit, devise, montant_eur, montant_crypto, code, statut, date_creation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user.id, f"{produit} (Multiples x{quantite})" if etape == "ATTENTE_CODE_MIXTE" else f"{produit} (x{quantite})", "XOF", montant_eur, montant_crypto, contenu_code, "En attente", now_str)
        )
        tx_id = cursor.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(t["code_received"])

    # BOUTONS ADMINS
    keyboard = [
        [
            InlineKeyboardButton("✅ Valider Code", callback_data=f"admin_valide_{tx_id}"),
            InlineKeyboardButton("❌ Rejeter Code", callback_data=f"admin_invalide_{tx_id}")
        ],
        [
            InlineKeyboardButton("➕ Demander de compléter", callback_data=f"admin_completer_{tx_id}"),
            InlineKeyboardButton("💬 Écrire Texte", callback_data=f"admin_message_{user.id}")
        ],
        [
            InlineKeyboardButton("🖼️ Envoyer Photo au client", callback_data=f"admin_sendphoto_{user.id}")
        ]
    ]

    message_admin = (
        f"📥 <b>TRANSACTION N°{tx_id}</b> ({now_str})\n\n"
        f"👤 <b>Client :</b> {html.escape(user.full_name)} (@{html.escape(user.username or 'aucun')})\n"
        f"🌐 <b>Langue client :</b> {lang.upper()}\n"
        f"🆔 <b>ID Client :</b> <code>{user.id}</code>\n"
        f"🏷 <b>Produit :</b> {html.escape(produit or 'PCS')} (x{quantite})\n"
        f"💶 <b>Montant Total Estimé :</b> {montant_eur} €\n"
        f"💰 <b>À Payer Estimé :</b> <code>{montant_crypto:,} XOF</code>\n\n"
        f"🔑 <b>Code(s) / Détails Soumis :</b>\n<code>{html.escape(contenu_code)}</code>"
    )

    if photo_file_id:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id,
            caption=message_admin,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=message_admin,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def gerer_messages_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    texte = update.message.text.strip() if update.message.text else ""
    
    # Message Admin Texte -> Client
    if user.id == ADMIN_CHAT_ID and context.user_data.get("admin_dest_id"):
        dest_id = context.user_data.pop("admin_dest_id")
        try:
            await context.bot.send_message(
                chat_id=dest_id,
                text=f"💬 **Message de l'administrateur :**\n\n{texte}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ **Message texte envoyé avec succès au client !**")
        except Exception as e:
            await update.message.reply_text(f"❌ Impossible d'envoyer le message : {e}")
        return

    etape = context.user_data.get("etape")
    lang = get_user_lang(user.id)
    t = TEXTS[lang]

    if etape == "ATTENTE_QUANTITE":
        if not texte.isdigit() or int(texte) <= 0:
            await update.message.reply_text(t["qty_invalid"])
            return

        quantite = int(texte)
        montant_eur_unitaire = context.user_data.get("montant_eur")
        montant_crypto_unitaire = context.user_data.get("montant_crypto_unitaire")

        montant_eur_total = montant_eur_unitaire * quantite
        montant_crypto_total = montant_crypto_unitaire * quantite

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key='liquidite'")
        liquidite = int(cursor.fetchone()[0])
        conn.close()

        if liquidite <= 0 or montant_crypto_total > liquidite:
            if "timer_task" in context.user_data and context.user_data["timer_task"]:
                context.user_data["timer_task"].cancel()

            keyboard = [[InlineKeyboardButton(t["back"], callback_data="menu_main")]]
            await update.message.reply_text(
                t["liquidite_insuffisante"].format(liq=liquidite, montant=montant_crypto_total),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            context.user_data["etape"] = None
            return

        context.user_data["quantite"] = quantite
        context.user_data["montant_eur"] = montant_eur_total
        context.user_data["montant_crypto"] = montant_crypto_total
        context.user_data["etape"] = "ATTENTE_CODE"

        produit = context.user_data.get("produit")

        msg = await update.message.reply_text(
            t["ask_code"].format(qty=quantite, produit=produit, m=10, s=0),
            parse_mode="Markdown"
        )
        await demarrer_compte_a_rebours(
            context, update.message.chat_id, msg.message_id,
            t["ask_code"], {"qty": quantite, "produit": produit}
        )

    elif etape in ["ATTENTE_CODE", "ATTENTE_CODE_MIXTE"]:
        await enregistrer_et_envoyer_transaction(update, context, code_text=texte, photo_file_id=None)

    elif etape == "ATTENTE_NUMERO_PAIEMENT":
        context.user_data["etape"] = None
        methode = context.user_data.get("methode_paiement", "Wave / Orange Money")
        tx_id = context.user_data.get("tx_id_paiement")

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE transactions SET methode_paiement = ?, numero_paiement = ? WHERE id = ?", (methode, texte, tx_id))
        cursor.execute("SELECT montant_crypto FROM transactions WHERE id = ?", (tx_id,))
        row = cursor.fetchone()
        montant_crypto = row[0] if row else 0
        conn.commit()
        conn.close()

        await update.message.reply_text(t["phone_received"])

        # Notifications avec actions pour l'admin (Paiement effectué OU Numéro inatteignable)
        keyboard = [
            [InlineKeyboardButton("✅ Valider & Confirmer Paiement", callback_data=f"admin_payconfirm_{tx_id}")],
            [InlineKeyboardButton("📞 Numéro inatteignable (Demander autre)", callback_data=f"admin_payunreachable_{tx_id}")]
        ]
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"📱 <b>NUMÉRO DE PAIEMENT REÇU !</b>\n\n"
                f"🆔 <b>Transaction N° :</b> {tx_id}\n"
                f"👤 <b>Client :</b> {html.escape(user.full_name)} (@{html.escape(user.username or 'aucun')})\n"
                f"💳 <b>Méthode :</b> {methode}\n"
                f"📞 <b>Numéro client :</b> <code>{html.escape(texte)}</code>\n"
                f"💰 <b>Montant à envoyer :</b> <code>{montant_crypto:,} XOF</code>"
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif etape == "ATTENTE_RETRAIT":
        context.user_data["etape"] = None
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
        solde = cursor.fetchone()[0]
        conn.close()

        await update.message.reply_text("Votre demande de retrait a été transmise à l'administrateur.")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"💸 <b>DEMANDE DE RETRAIT</b>\n\n"
                f"👤 <b>Client :</b> {html.escape(user.full_name)}\n"
                f"🆔 <b>ID Client :</b> <code>{user.id}</code>\n"
                f"💰 <b>Montant :</b> {solde:,} XOF\n"
                f"📞 <b>Compte Réception :</b> <code>{html.escape(texte)}</code>"
            ),
            parse_mode="HTML"
        )

async def gerer_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo = update.message.photo[-1]  # Meilleure résolution
    caption = update.message.caption or ""

    # Mode Envoi de Photo par Admin au Client
    if user.id == ADMIN_CHAT_ID and context.user_data.get("admin_dest_photo_id"):
        dest_id = context.user_data.pop("admin_dest_photo_id")
        try:
            caption_text = f"🖼️ **Image reçue de l'administrateur :**\n\n{caption}" if caption else "🖼️ **Image / Pièce jointe reçue de l'administrateur**"
            await context.bot.send_photo(
                chat_id=dest_id,
                photo=photo.file_id,
                caption=caption_text,
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ **Photo envoyée avec succès au client !**")
        except Exception as e:
            await update.message.reply_text(f"❌ Impossible d'envoyer la photo : {e}")
        return

    # Client envoyant une photo
    etape = context.user_data.get("etape")
    if etape in ["ATTENTE_CODE", "ATTENTE_CODE_MIXTE"]:
        await enregistrer_et_envoyer_transaction(update, context, code_text=caption, photo_file_id=photo.file_id)

# ---------------------------------------------------------
# VALIDATION ADMIN & ACTIONS COMPLÉMENTAIRES
# ---------------------------------------------------------
async def gerer_actions_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[1]

    conn = get_db()
    cursor = conn.cursor()

    if action == "valide":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id, produit, montant_crypto FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()

        if tx:
            client_id, produit, montant = tx[0], tx[1], tx[2]
            cursor.execute("UPDATE transactions SET statut = 'Validé' WHERE id = ?", (tx_id,))
            cursor.execute("UPDATE settings SET value = value - ? WHERE key='liquidite'", (montant,))

            cursor.execute("SELECT referrer_id FROM users WHERE user_id = ?", (client_id,))
            ref_row = cursor.fetchone()
            if ref_row and ref_row[0]:
                referrer_id = ref_row[0]
                cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND statut = 'Validé'", (client_id,))
                if cursor.fetchone()[0] == 1:
                    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (BONUS_PARRAINAGE, referrer_id))
                    try:
                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text=f"🎉 **Bonus Parrainage !** Votre filleul a effectué sa première transaction. **+{BONUS_PARRAINAGE} XOF** crédités sur votre solde."
                        )
                    except Exception:
                        pass

            conn.commit()

            client_lang = get_user_lang(client_id)
            t_client = TEXTS[client_lang]

            if query.message.caption:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ **CODE VALIDÉ PAR L'ADMIN**")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n✅ **CODE VALIDÉ PAR L'ADMIN**")

            # ANIMATION EMOJIS
            msg_anim = await context.bot.send_message(chat_id=client_id, text="✨ 🟢 ⏳ Payment Validation...")
            await asyncio.sleep(0.7)
            await msg_anim.edit_text("🎉 🥳 💫 <b>PAYMENT CONFIRMED !</b>", parse_mode="HTML")
            await asyncio.sleep(0.7)
            await msg_anim.edit_text("💥 🎈 ✨ 🍾 <b>CONGRATULATIONS !</b> 🎉 🥳 👏", parse_mode="HTML")

            msg_success = t_client["success_recharge"].format(produit=produit)
            await context.bot.send_message(chat_id=client_id, text=msg_success, parse_mode="Markdown")

            # DEMANDE DE SÉLECTION DU MODE DE PAIEMENT (WAVE OU ORANGE MONEY)
            pay_keyboard = [
                [
                    InlineKeyboardButton("🌊 Wave", callback_data=f"paymethod_Wave_{tx_id}"),
                    InlineKeyboardButton("🍊 Orange Money", callback_data=f"paymethod_OrangeMoney_{tx_id}")
                ]
            ]
            await context.bot.send_message(
                chat_id=client_id,
                text=t_client["select_payment_method"].format(montant=montant),
                reply_markup=InlineKeyboardMarkup(pay_keyboard),
                parse_mode="Markdown"
            )

    elif action == "payconfirm":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id, montant_crypto, methode_paiement, numero_paiement FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()

        if tx:
            client_id, montant, methode, numero = tx[0], tx[1], tx[2], tx[3]
            client_lang = get_user_lang(client_id)
            t_client = TEXTS[client_lang]

            if query.message.caption:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n✅ **CONFIRMATION DE PAIEMENT ENVOYÉE AU CLIENT**")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n✅ **CONFIRMATION DE PAIEMENT ENVOYÉE AU CLIENT**")

            # Information du paiement au client
            txt_sent = t_client["payment_sent"].format(montant=montant, methode=methode, numero=numero)
            await context.bot.send_message(
                chat_id=client_id,
                text=txt_sent,
                parse_mode="Markdown"
            )

            # Évaluation après confirmation du paiement
            await context.bot.send_message(
                chat_id=client_id,
                text=t_client["rate_prompt"],
                reply_markup=rating_keyboard(tx_id),
                parse_mode="Markdown"
            )

    elif action == "payunreachable":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id, methode_paiement, numero_paiement FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()

        if tx:
            client_id, methode, numero = tx[0], tx[1], tx[2]
            client_lang = get_user_lang(client_id)
            t_client = TEXTS[client_lang]

            # Remettre le client en attente de numéro
            context.application.user_data[client_id]["etape"] = "ATTENTE_NUMERO_PAIEMENT"
            context.application.user_data[client_id]["methode_paiement"] = methode
            context.application.user_data[client_id]["tx_id_paiement"] = tx_id

            if query.message.caption:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n📞 **NOTIFICATION NUMÉRO INATTEIGNABLE ENVOYÉE**")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n📞 **NOTIFICATION NUMÉRO INATTEIGNABLE ENVOYÉE**")

            txt_unreachable = t_client["phone_unreachable"].format(numero=numero)
            await context.bot.send_message(
                chat_id=client_id,
                text=txt_unreachable,
                parse_mode="Markdown"
            )

    elif action == "invalide":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            client_id = tx[0]
            cursor.execute("UPDATE transactions SET statut = 'Refusé' WHERE id = ?", (tx_id,))
            conn.commit()

            client_lang = get_user_lang(client_id)
            msg_refused = TEXTS[client_lang]["code_refused"]

            if query.message.caption:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n❌ **CODE REFUSÉ PAR L'ADMIN**")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n❌ **CODE REFUSÉ PAR L'ADMIN**")

            await context.bot.send_message(chat_id=client_id, text=msg_refused, parse_mode="Markdown")

    elif action == "completer":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id, produit FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            client_id, produit = tx[0], tx[1]
            client_lang = get_user_lang(client_id)
            t_client = TEXTS[client_lang]

            context.application.user_data[client_id]["etape"] = "ATTENTE_CODE"
            context.application.user_data[client_id]["tx_id_completer"] = tx_id
            context.application.user_data[client_id]["produit"] = produit

            if query.message.caption:
                await query.edit_message_caption(caption=f"{query.message.caption}\n\n⚠️ **DEMANDE DE COMPLÉMENT ENVOYÉE AU CLIENT**")
            else:
                await query.edit_message_text(f"{query.message.text}\n\n⚠️ **DEMANDE DE COMPLÉMENT ENVOYÉE AU CLIENT**")
            
            msg = await context.bot.send_message(
                chat_id=client_id,
                text=t_client["completer_demande"].format(produit=produit, m=10, s=0),
                parse_mode="Markdown"
            )

            fake_context = type('Context', (), {'bot': context.bot, 'user_data': context.application.user_data[client_id]})()
            await demarrer_compte_a_rebours(
                fake_context, client_id, msg.message_id,
                t_client["completer_demande"], {"produit": produit}
            )

    elif action == "message":
        client_id = int(data[2])
        context.user_data["admin_dest_id"] = client_id
        await query.message.reply_text(
            f"✏️ **Mode écriture texte activé !**\n\nTapez votre message ci-dessous, il sera envoyé au client (`ID: {client_id}`).",
            parse_mode="Markdown"
        )

    elif action == "sendphoto":
        client_id = int(data[2])
        context.user_data["admin_dest_photo_id"] = client_id
        await query.message.reply_text(
            f"🖼️ **Mode envoi de photo activé !**\n\nEnvoyez la photo/capture ci-dessous, elle sera transmise au client (`ID: {client_id}`).",
            parse_mode="Markdown"
        )

    conn.close()

# ---------------------------------------------------------
# LANCEMENT DU BOT
# ---------------------------------------------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("liquidite", admin_set_liquidite))
    app.add_handler(CallbackQueryHandler(gerer_actions_admin, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(gerer_callbacks))
    
    # Handlers Texte & Photo
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gerer_messages_texte))
    app.add_handler(MessageHandler(filters.PHOTO, gerer_photos))

    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    print("🤖 Bot démarré avec succès !")
    app.run_polling()

if __name__ == "__main__":
    main()
