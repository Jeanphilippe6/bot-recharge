import os
import logging
import threading
import html
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
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

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    server.serve_forever()

# ---------------------------------------------------------
# BASE DE DONNÉES SQLITE
# ---------------------------------------------------------
DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Utilisateurs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            username TEXT,
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER,
            is_blocked INTEGER DEFAULT 0
        )
    """)
    
    # Transactions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            produit TEXT,
            montant_eur INTEGER,
            montant_xof INTEGER,
            code TEXT,
            statut TEXT,
            date_creation DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Paramètres système (Maintenance)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', '0')")
    
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_FILE)

# ---------------------------------------------------------
# CONFIGURATION ET VARIABLES D'ENVIRONNEMENT
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))
BONUS_PARRAINAGE = 500  # 500 XOF offert au parrain

GRILLES_TARIFS = {
    "PCS": {20: 7000, 30: 10000, 40: 15000, 50: 23000, 100: 53000, 150: 83000, 250: 143000},
    "Transcash": {20: 8000, 50: 28000, 100: 58000, 150: 88000, 200: 118000, 250: 148000, 300: 300000},
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ---------------------------------------------------------
# MENU PRINCIPAL
# ---------------------------------------------------------
def main_keyboard():
    keyboard = [
        [InlineKeyboardButton("💳 PCS", callback_data="prod_PCS"), InlineKeyboardButton("💳 Transcash", callback_data="prod_Transcash")],
        [InlineKeyboardButton("💼 Mon Solde & Retrait", callback_data="menu_solde"), InlineKeyboardButton("📜 Mes Transactions", callback_data="menu_history")],
        [InlineKeyboardButton("👥 Parrainage (+500 XOF)", callback_data="menu_parrainage"), InlineKeyboardButton("💬 Support Client", callback_data="menu_support")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------------------------------------------------
# COMMANDES UTILISATEUR
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Vérification maintenance
    cursor.execute("SELECT value FROM settings WHERE key='maintenance'")
    maint = cursor.fetchone()
    if maint and maint[0] == "1" and user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("🛠 **Le bot est actuellement en maintenance.** Veuillez recharger ultérieurement.")
        conn.close()
        return

    # Gestion du parrainage via argument /start <referrer_id>
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

    await update.message.reply_text(
        f"Bienvenue {html.escape(user.first_name)} ! 👋\n\n"
        "Plateforme professionnelle d'échange de recharges (PCS, Transcash).\n"
        "Sélectionnez une option ci-dessous pour démarrer :",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

# ---------------------------------------------------------
# GESTION DES BOUTONS DE NAVIGATION
# ---------------------------------------------------------
async def gerer_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    conn = get_db()
    cursor = conn.cursor()

    if data == "menu_main":
        await query.edit_message_text("Sélectionnez une option :", reply_markup=main_keyboard())

    elif data == "menu_solde":
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
        row = cursor.fetchone()
        solde = row[0] if row else 0
        keyboard = [
            [InlineKeyboardButton("💸 Demander un Retrait", callback_data="action_retrait")],
            [InlineKeyboardButton("🔙 Retour Menu", callback_data="menu_main")]
        ]
        await query.edit_message_text(
            f"💼 <b>VOTRE PORTEFEUILLE</b>\n\n"
            f"💰 Solde disponible : <b>{solde:,} XOF</b>\n\n"
            f"<i>Le solde est accumulé grâce aux commissions de parrainage.</i>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "action_retrait":
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user.id,))
        solde = cursor.fetchone()[0]
        if solde < 2000:
            await query.edit_message_text(
                "❌ **Solde insuffisant.** Le montant minimum pour effectuer un retrait est de 2 000 XOF.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="menu_solde")]]),
                parse_mode="Markdown"
            )
        else:
            context.user_data["etape"] = "ATTENTE_RETRAIT"
            await query.edit_message_text(
                f"💸 **DEMANDE DE RETRAIT** ({solde:,} XOF)\n\n"
                "Veuillez indiquer votre numéro de téléphone (Wave, Orange, MTN, Moov) ainsi que le nom du compte pour recevoir le paiement :"
            )

    elif data == "menu_history":
        cursor.execute(
            "SELECT produit, montant_eur, montant_xof, statut, date_creation FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 5",
            (user.id,)
        )
        rows = cursor.fetchall()
        if not rows:
            txt = "📜 Vous n'avez encore effectué aucune transaction."
        else:
            txt = "📜 <b>HISTORIQUE DE VOS 5 DERNIÈRES TRANSACTIONS :</b>\n\n"
            for r in rows:
                txt += f"• <b>{html.escape(r[0])}</b> {r[1]}€ ➡️ {r[2]:,} XOF | Statut : <i>{r[3]}</i> ({r[4][:10]})\n"

        keyboard = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu_main")]]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_parrainage":
        cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user.id,))
        nb_filleuls = cursor.fetchone()[0]
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start={user.id}"

        keyboard = [[InlineKeyboardButton("🔙 Retour Menu", callback_data="menu_main")]]
        await query.edit_message_text(
            f"👥 <b>PROGRAMME DE PARRAINAGE</b>\n\n"
            f"Gagnez <b>{BONUS_PARRAINAGE} XOF</b> pour chaque ami invité qui effectue une transaction validée !\n\n"
            f"🔗 <b>Votre lien d'invitation :</b>\n<code>{link}</code>\n\n"
            f"📊 Filleuls inscrits : <b>{nb_filleuls}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "menu_support":
        context.user_data["etape"] = "ATTENTE_SUPPORT"
        keyboard = [[InlineKeyboardButton("❌ Annuler", callback_data="menu_main")]]
        await query.edit_message_text(
            "💬 <b>SUPPORT CLIENT</b>\n\nPosez votre question ou détaillez votre problème ci-dessous. Un administrateur vous répondra directement :",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    conn.close()

# ---------------------------------------------------------
# SÉLECTION DU PRODUIT ET DU MONTANT
# ---------------------------------------------------------
async def gerer_choix_produit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    produit = query.data.split("_")[1]
    context.user_data["produit"] = produit

    tarifs = GRILLES_TARIFS.get(produit, {})
    keyboard = [[InlineKeyboardButton(f"{eur}€ ➡️ {xof:,} XOF", callback_data=f"montant_{eur}_{xof}")] for eur, xof in tarifs.items()]
    keyboard.append([InlineKeyboardButton("🔙 Retour", callback_data="menu_main")])

    await query.edit_message_text(
        text=f"Vous avez choisi : <b>{html.escape(produit)}</b>\n\nChoisissez le montant de votre recharge :",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )

async def gerer_choix_montant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    montant_eur, montant_xof = int(data[1]), int(data[2])

    context.user_data["montant_eur"] = montant_eur
    context.user_data["montant_xof"] = montant_xof
    context.user_data["etape"] = "ATTENTE_CODE"

    produit = context.user_data.get("produit")

    await query.edit_message_text(
        text=f"📊 <b>Récapitulatif de la commande :</b>\n"
             f"• Service : <b>{html.escape(produit)}</b>\n"
             f"• Montant du coupon : <b>{montant_eur} €</b>\n"
             f"• Vous recevrez : <b>{montant_xof:,} XOF</b>\n\n"
             f"👉 Veuillez écrire et envoyer votre <b>code de recharge {html.escape(produit)}</b> dans ce chat :",
        parse_mode="HTML",
    )

# ---------------------------------------------------------
# TRAITEMENT DES MESSAGES TEXTE UTILISATEUR
# ---------------------------------------------------------
async def gerer_messages_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etape = context.user_data.get("etape")
    texte = update.message.text.strip()
    user = update.effective_user

    if etape == "ATTENTE_CODE":
        produit = context.user_data.get("produit")
        montant_eur = context.user_data.get("montant_eur")
        montant_xof = context.user_data.get("montant_xof")
        context.user_data["etape"] = None

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transactions (user_id, produit, montant_eur, montant_xof, code, statut) VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, produit, montant_eur, montant_xof, texte, "En attente")
        )
        tx_id = cursor.lastrowid
        conn.commit()
        conn.close()

        await update.message.reply_text("⏳ Code(s) reçu(s) ! Nous vérifions et rechargeons le coupon. Veuillez patienter un instant...")

        keyboard = [
            [
                InlineKeyboardButton("✅ Valider Code", callback_data=f"admin_valide_{tx_id}"),
                InlineKeyboardButton("❌ Rejeter Code", callback_data=f"admin_invalide_{tx_id}"),
            ]
        ]

        message_admin = (
            f"📥 <b>TRANSACTION N°{tx_id}</b>\n\n"
            f"👤 <b>Client :</b> {html.escape(user.full_name)} (@{html.escape(user.username or 'aucun')})\n"
            f"🆔 <b>ID Client :</b> <code>{user.id}</code>\n"
            f"🏷 <b>Produit :</b> {html.escape(produit)}\n"
            f"💶 <b>Montant Coupon :</b> {montant_eur} €\n"
            f"💰 <b>À Payer :</b> <code>{montant_xof:,} XOF</code>\n\n"
            f"🔑 <b>Code Soumis :</b>\n<code>{html.escape(texte)}</code>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=message_admin, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif etape == "ATTENTE_NUMERO":
        context.user_data["etape"] = None
        await update.message.reply_text("Merci ! Votre numéro de dépôt a été transmis à l'administrateur. Le paiement est en cours de traitement.")

        keyboard = [[InlineKeyboardButton("💳 Confirmer Paiement Effectué", callback_data=f"admin_paye_{user.id}")]]

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📱 <b>NUMÉRO DE DÉPÔT REÇU</b>\n\n"
                 f"👤 <b>Client :</b> {html.escape(user.full_name)}\n"
                 f"🆔 <b>ID Client :</b> <code>{user.id}</code>\n"
                 f"📞 <b>Coordonnées :</b> <code>{html.escape(texte)}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
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
            text=f"💸 <b>DEMANDE DE RETRAIT DE SOLDE</b>\n\n"
                 f"👤 <b>Client :</b> {html.escape(user.full_name)}\n"
                 f"🆔 <b>ID Client :</b> <code>{user.id}</code>\n"
                 f"💰 <b>Montant :</b> {solde:,} XOF\n"
                 f"📞 <b>Compte Dépôt :</b> <code>{html.escape(texte)}</code>",
            parse_mode="HTML"
        )

    elif etape == "ATTENTE_SUPPORT":
        context.user_data["etape"] = None
        await update.message.reply_text("Votre message a été transmis au support. Nous vous répondrons dans les plus brefs délais.")
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"💬 <b>MESSAGE SUPPORT</b>\n\n"
                 f"👤 <b>Client :</b> {html.escape(user.full_name)} (ID: <code>{user.id}</code>)\n"
                 f"📝 <b>Message :</b>\n{html.escape(texte)}",
            parse_mode="HTML"
        )

# ---------------------------------------------------------
# ACTIONS ADMINISTRATEUR
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
        cursor.execute("SELECT user_id, produit, montant_eur FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        
        if tx:
            client_id = tx[0]
            cursor.execute("UPDATE transactions SET statut = 'Validé' WHERE id = ?", (tx_id,))
            
            # Application de la commission parrain si premier achat
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
                            text=f"🎉 **Bonus Parrainage !** Votre filleul a effectué sa première transaction. **+{BONUS_PARRAINAGE} XOF** ont été ajoutés à votre solde."
                        )
                    except Exception:
                        pass

            conn.commit()

            await query.edit_message_text(text=f"{query.message.text}\n\n✅ <b>STATUT : CODE VALIDE</b>", parse_mode="HTML")
            await context.bot.send_message(
                chat_id=client_id,
                text="✅ <b>Votre code est valide et accepté !</b>\n\n"
                     "Veuillez répondre en envoyant votre **Numéro de dépôt** (Wave, Orange, MTN, Moov) avec le nom du compte pour recevoir votre paiement :",
                parse_mode="Markdown"
            )
            context.application.user_data[client_id]["etape"] = "ATTENTE_NUMERO"

    elif action == "invalide":
        tx_id = int(data[2])
        cursor.execute("SELECT user_id FROM transactions WHERE id = ?", (tx_id,))
        tx = cursor.fetchone()
        if tx:
            client_id = tx[0]
            cursor.execute("UPDATE transactions SET statut = 'Refusé' WHERE id = ?", (tx_id,))
            conn.commit()

            await query.edit_message_text(text=f"{query.message.text}\n\n❌ <b>STATUT : CODE REFUSÉ</b>", parse_mode="HTML")
            await context.bot.send_message(
                chat_id=client_id,
                text="❌ <b>Code invalide ou déjà utilisé.</b> Veuillez vérifier le coupon et relancer la procédure via le menu.",
                parse_mode="Markdown"
            )

    elif action == "paye":
        client_id = int(data[2])
        await query.edit_message_text(text=f"{query.message.text}\n\n💳 <b>STATUT : PAIEMENT CONFIRMÉ</b>", parse_mode="HTML")
        await context.bot.send_message(
            chat_id=client_id,
            text="🎉 <b>Paiement effectué avec succès !</b> Le transfert a été envoyé sur votre compte. Merci pour votre confiance !",
            parse_mode="HTML"
        )

    conn.close()

# ---------------------------------------------------------
# COMMANDES PANNEAU ADMINISTRATEUR
# ---------------------------------------------------------
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    nb_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*), SUM(montant_xof) FROM transactions WHERE statut = 'Validé'")
    tx_stats = cursor.fetchone()
    conn.close()

    total_tx = tx_stats[0] or 0
    total_vol = tx_stats[1] or 0

    await update.message.reply_text(
        f"📊 <b>STATISTIQUES DU BOT</b>\n\n"
        f"👥 Utilisateurs totaux : <b>{nb_users}</b>\n"
        f"✅ Transactions validées : <b>{total_tx}</b>\n"
        f"💰 Volume d'échange total : <b>{total_vol:,} XOF</b>",
        parse_mode="HTML"
    )

async def admin_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key='maintenance'")
    curr = cursor.fetchone()[0]
    new_val = "0" if curr == "1" else "1"
    cursor.execute("UPDATE settings SET value = ? WHERE key='maintenance'", (new_val,))
    conn.commit()
    conn.close()

    etat = "ACTIVÉ" if new_val == "1" else "DÉSACTIVÉ"
    await update.message.reply_text(f"🛠 Mode Maintenance : <b>{etat}</b>", parse_mode="HTML")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Usage: `/broadcast Votre message annonce ici`", parse_mode="Markdown")
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    count = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u[0], text=f"📢 <b>ANNOUNCE</b>\n\n{html.escape(msg)}", parse_mode="HTML")
            count += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ Message diffusé à {count} utilisateurs.")

# ---------------------------------------------------------
# DÉMARRAGE DE L'APPLICATION
# ---------------------------------------------------------
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("maintenance", admin_maintenance))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))

    # Handlers Callbacks & Messages
    app.add_handler(CallbackQueryHandler(gerer_choix_produit, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(gerer_choix_montant, pattern="^montant_"))
    app.add_handler(CallbackQueryHandler(gerer_actions_admin, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(gerer_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gerer_messages_texte))

    print("Démarrage du serveur web secondaire...")
    threading.Thread(target=run_dummy_server, daemon=True).start()

    print("Bot démarré...")
    app.run_polling()

if __name__ == "__main__":
    main()
