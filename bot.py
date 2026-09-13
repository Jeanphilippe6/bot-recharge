import asyncio
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import html
import logging
import os
import re
import sqlite3
import threading

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
            rating INTEGER DEFAULT 0
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

TEXTS = {
    "fr": {
        "welcome": "Bienvenue {name} ! 👋\nPlateforme professionnelle d'échange.",
        "pcs": "💳 PCS",
        "transcash": "💳 Transcash",
        "solde": "💼 Mon Solde & Retrait",
        "history": "📜 Mes Transactions",
        "parrainage": "👥 Parrainage (+125 XOF)",
        "lang": "🌐 Langue / Language",
        "select_lang": "Choisissez votre langue :",
        "lang_updated": "✅ Langue mise à jour en Français !",
        "liquidite_disp": "💧 **Liquidité globale disponible :** {liq:,} XOF",
        "no_tx": "📜 Vous n'avez encore effectué aucune transaction.",
        "tx_title": "📜 **HISTORIQUE COMPLET DE VOS TRANSACTIONS :**\n\n",
        "ask_qty": "🔢 Combien de recharges **{produit}** de **{eur}€** avez-vous ?\n\n_Veuillez répondre par un chiffre (ex: 1, 2, 5...)_",
        "ask_code": "👉 Veuillez envoyer vos **{qty} code(s) de recharge {produit}** ci-dessous (un par ligne ou séparés par des espaces) :",
        "ask_mixed_codes": "🔀 **RECHARGES MULTIPLES / DIFFÉRENTS MONTANTS**\n\nVeuillez envoyer tous vos codes ci-dessous en précisant le montant pour chacun.\n\n**Exemple de format :**\n<code>100€ - ABCD1234EF\n50€ - XYZ987654\n20€ - QWER112233</code>",
        "code_received": "⏳ Code(s) reçu(s) ! Vérification en cours...",
        "success_recharge": "🎉 **FÉLICITATIONS !** 🥳👏\nVotre recharge {produit} a été validée avec succès !",
        "code_refused": "❌ **Code invalide ou déjà utilisé.** Veuillez réessayer.",
        "completer_demande": "⚠️ **RECHARGE INCOMPLÈTE !** ⚠️\n\nL'administrateur signale qu'il manque un ou plusieurs codes pour votre recharge **{produit}**.\n\n👉 Veuillez répondre ci-dessous en envoyant les codes manquants :",
        "retrait_insuffisant": "❌ **Solde insuffisant.** Le montant minimum pour effectuer un retrait est de {min_retrait:,} XOF.",
        "retrait_demande": "💸 **DEMANDE DE RETRAIT** ({solde:,} XOF)\n\nVeuillez envoyer votre numéro de dépôt (Wave, Orange, MTN, Moov) :",
        "rate_prompt": "⭐ **ÉVALUATION DE LA TRANSACTION** ⭐\nComment évaluez-vous ce service ? Notez sur 7 étoiles :",
        "thanks_rate": "🙏 **Merci pour votre note de {stars}/7 !** Votre avis nous aide à nous améliorer.",
        "liquidite_insuffisante": "⚠️ **TRANSACTION IMPOSSIBLE** ⚠️\n\nLa liquidité disponible actuellement ({liq:,} XOF) est insuffisante pour traiter cette transaction de {montant:,} XOF. Veuillez réessayer plus tard ou choisir un montant inférieur.",
        "qty_invalid": "❌ **Saisie invalide.** Veuillez taper un nombre entier.",
        "back": "🔙 Retour"
    },
    "en": {
        "welcome": "Welcome {name}! 👋\nProfessional gift card exchange platform.",
        "pcs": "💳 PCS Card",
        "transcash": "💳 Transcash",
        "solde": "💼 My Balance & Withdrawal",
        "history": "📜 My Transactions",
        "parrainage": "👥 Referral (+125 XOF)",
        "lang": "🌐 Language / Langue",
        "select_lang": "Select your language:",
        "lang_updated": "✅ Language updated to English!",
        "liquidite_disp": "💧 **Available Global Liquidity:** {liq:,} XOF",
        "no_tx": "📜 You haven't made any transactions yet.",
        "tx_title": "📜 **FULL TRANSACTION HISTORY:**\n\n",
        "ask_qty": "🔢 How many **{produit}** top-up cards of **{eur}€** do you have?\n\n_Please enter a number (e.g., 1, 2, 5...)_",
        "ask_code": "👉 Please send your **{qty} {produit} top-up code(s)** below:",
        "ask_mixed_codes": "🔀 **MULTIPLE CARDS / DIFFERENT AMOUNTS**\n\nPlease send all your codes below, specifying the amount for each card.\n\n**Example format:**\n<code>100€ - ABCD1234EF\n50€ - XYZ987654\n20€ - QWER112233</code>",
        "code_received": "⏳ Code(s) received! Verification in progress...",
        "success_recharge": "🎉 **CONGRATULATIONS!** 🥳👏\nYour {produit} top-up has been successfully validated!",
        "code_refused": "❌ **Invalid code or already used.** Please try again.",
        "completer_demande": "⚠️ **INCOMPLETE TOP-UP!** ⚠️\n\nThe administrator reported missing code(s) for your **{produit}** recharge.\n\n👉 Please reply below with the missing code(s):",
        "retrait_insuffisant": "❌ **Insufficient balance.** The minimum withdrawal amount is {min_retrait:,} XOF.",
        "retrait_demande": "💸 **WITHDRAWAL REQUEST** ({solde:,} XOF)\n\nPlease send your payment account details:",
        "rate_prompt": "⭐ **TRANSACTION RATING** ⭐\nHow would you rate our service? Please give a rating out of 7 stars:",
        "thanks_rate": "🙏 **Thank you for your {stars}/7 rating!** Your feedback is appreciated.",
        "liquidite_insuffisante": "⚠️ **TRANSACTION NOT POSSIBLE** ⚠️\n\nThe current available liquidity ({liq:,} XOF) is insufficient to process this transaction of {montant:,} XOF. Please try again later or select a smaller amount.",
        "qty_invalid": "❌ **Invalid input.** Please type a valid number.",
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
        [InlineKeyboardButton(t["solde"], callback_data="menu_solde"), InlineKeyboardButton(t["history"], callback_data="menu_history")],
        [InlineKeyboardButton(t["parrainage"], callback_data="menu_parrainage"), InlineKeyboardButton(t["lang"], callback_data="menu_lang")]
    ]
    return InlineKeyboardMarkup(keyboard)

def rating_keyboard(tx_id):
    keyboard = [[InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{tx_id}_{i}") for i in range(1, 8)]]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# COMMANDES CLIENT & ADMIN
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
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
# CALLBACKS CLIENT
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
        # Bouton pour montants multiples / coupons différents
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
        await query.edit_message_text(t["ask_mixed_codes"], parse_mode="HTML")

    elif data.startswith("montant_"):
        parts = data.split("_")
        montant_eur = int(parts[1])
        montant_crypto_unitaire = int(parts[2])

        context.user_data["is_mixte"] = False
        context.user_data["montant_eur"] = montant_eur
        context.user_data["montant_crypto_unitaire"] = montant_crypto_unitaire
        context.user_data["etape"] = "ATTENTE_QUANTITE"

        produit = context.user_data.get("produit")
        await query.edit_message_text(
            t["ask_qty"].format(produit=produit, eur=montant_eur),
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
# TRAITEMENT DES MESSAGES TEXTE
# ---------------------------------------------------------
async def gerer_messages_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    texte = update.message.text.strip()
    
    # 1. MESSAGE REÇU DE L'ADMIN EN TRAIN D'ÉCRIRE À UN CLIENT
    if user.id == ADMIN_CHAT_ID and context.user_data.get("admin_dest_id"):
        dest_id = context.user_data.pop("admin_dest_id")
        try:
            await context.bot.send_message(
                chat_id=dest_id,
                text=f"💬 **Message de l'administrateur :**\n\n{texte}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ **Message envoyé avec succès au client !**")
        except Exception as e:
            await update.message.reply_text(f"❌ Impossible d'envoyer le message : {e}")
        return

    # 2. MESSAGE RÉPONSE OU COMMANDE DU CLIENT
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
        await update.message.reply_text(
            t["ask_code"].format(qty=quantite, produit=produit),
            parse_mode="Markdown"
        )

    elif etape in ["ATTENTE_CODE", "ATTENTE_CODE_MIXTE"]:
        produit = context.user_data.get("produit")
        tx_id_origine = context.user_data.get("tx_id_completer")
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

        if etape == "ATTENTE_CODE_MIXTE":
            # Extraire dynamiquement les montants en EUR spécifiés par le client (ex: "100€", "50 euros", etc.)
            valeurs_trouvees = [int(v) for v in re.findall(r'(\d+)\s*(?:€|eur|euros)', texte, re.IGNORECASE)]
            montant_eur = sum(valeurs_trouvees) if valeurs_trouvees else 0
            
            # Calcul du montant XOF équivalent selon la grille tarifaire
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
            nouveau_code = f"{ancien_code}\n--- COMPLÉMENT DU {now_str} ---\n{texte}"
            
            cursor.execute("UPDATE transactions SET code = ?, statut = 'En attente' WHERE id = ?", (nouveau_code, tx_id_origine))
            tx_id = tx_id_origine
            context.user_data["tx_id_completer"] = None
        else:
            cursor.execute(
                "INSERT INTO transactions (user_id, produit, devise, montant_eur, montant_crypto, code, statut, date_creation) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user.id, f"{produit} (Multiples x{quantite})" if etape == "ATTENTE_CODE_MIXTE" else f"{produit} (x{quantite})", "XOF", montant_eur, montant_crypto, texte, "En attente", now_str)
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
                InlineKeyboardButton("📩 Écrire au client", callback_data=f"admin_message_{user.id}")
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
            f"🔑 <b>Code(s) Soumis :</b>\n<code>{html.escape(texte)}</code>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=message_admin,
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

            await query.edit_message_text(f"{query.message.text}\n\n✅ **CODE VALIDÉ PAR L'ADMIN**")

            # ANIMATION EMOJIS
            msg_anim = await context.bot.send_message(chat_id=client_id, text="✨ 🟢 ⏳ Payment Validation...")
            await asyncio.sleep(0.7)
            await msg_anim.edit_text("🎉 🥳 💫 <b>PAYMENT CONFIRMED !</b>", parse_mode="HTML")
            await asyncio.sleep(0.7)
            await msg_anim.edit_text("💥 🎈 ✨ 🍾 <b>CONGRATULATIONS !</b> 🎉 🥳 👏", parse_mode="HTML")

            msg_success = t_client["success_recharge"].format(produit=produit)
            await context.bot.send_message(chat_id=client_id, text=msg_success, parse_mode="Markdown")

            await context.bot.send_message(
                chat_id=client_id,
                text=t_client["rate_prompt"],
                reply_markup=rating_keyboard(tx_id),
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

            await query.edit_message_text(f"{query.message.text}\n\n❌ **CODE REFUSÉ PAR L'ADMIN**")
            await context.bot.send_message(chat_id=client_id, text=msg_refused, parse_mode="Markdown")

    elif action == "completer":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id, produit FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            client_id, produit = tx[0], tx[1]
            client_lang = get_user_lang(client_id)

            context.application.user_data[client_id]["etape"] = "ATTENTE_CODE"
            context.application.user_data[client_id]["tx_id_completer"] = tx_id
            context.application.user_data[client_id]["produit"] = produit

            await query.edit_message_text(f"{query.message.text}\n\n⚠️ **DEMANDE DE COMPLÉMENT ENVOYÉE AU CLIENT**")
            await context.bot.send_message(
                chat_id=client_id,
                text=TEXTS[client_lang]["completer_demande"].format(produit=produit),
                parse_mode="Markdown"
            )

    elif action == "message":
        client_id = int(data[2])
        context.user_data["admin_dest_id"] = client_id
        await query.message.reply_text(
            f"✏️ **Mode écriture activé !**\n\nTapez votre message ci-dessous, il sera envoyé directement au client (`ID: {client_id}`).",
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gerer_messages_texte))

    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    print("🤖 Bot démarré avec succès !")
    app.run_polling()

if __name__ == "__main__":
    main()
