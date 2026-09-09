import os
import logging
import threading
import html
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

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))

GRILLES_TARIFS = {
    "PCS": {20: 7000, 30: 10000, 40: 15000, 50: 23000, 100: 53000, 150: 83000, 250: 143000},
    "Transcash": {20: 8000, 50: 28000, 100: 58000, 150: 88000, 200: 118000, 250: 148000, 300: 300000},
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [
            InlineKeyboardButton("💳 PCS", callback_data="prod_PCS"),
            InlineKeyboardButton("💳 Transcash", callback_data="prod_Transcash"),
        ]
    ]
    await update.message.reply_text(
        "Bienvenue ! 👋\n\nVeuillez sélectionner le type de recharge que vous souhaitez échanger :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def gerer_choix_produit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    produit = query.data.split("_")[1]
    context.user_data["produit"] = produit

    tarifs = GRILLES_TARIFS.get(produit, {})
    keyboard = [[InlineKeyboardButton(f"{eur}€ ➡️ {xof:,} XOF", callback_data=f"montant_{eur}_{xof}")] for eur, xof in tarifs.items()]

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
             f"👉 Veuillez maintenant écrire et envoyer votre <b>code de recharge {html.escape(produit)}</b> dans ce chat :",
        parse_mode="HTML",
    )

async def gerer_messages_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etape = context.user_data.get("etape")
    texte = update.message.text.strip()

    if etape == "ATTENTE_CODE":
        client_id = update.effective_user.id
        client_name = html.escape(update.effective_user.full_name)
        username = html.escape(update.effective_user.username or "Pas de username")
        produit = context.user_data.get("produit")
        montant_eur = context.user_data.get("montant_eur")
        montant_xof = context.user_data.get("montant_xof")

        context.user_data["etape"] = None

        await update.message.reply_text("⏳ Code(s) reçu(s) ! Nous vérifions et rechargeons le coupon. Veuillez patienter un instant...")

        keyboard = [
            [
                InlineKeyboardButton("✅ Code Valide", callback_data=f"valide_{client_id}"),
                InlineKeyboardButton("❌ Code Invalide", callback_data=f"invalide_{client_id}"),
            ]
        ]

        message_admin = (
            f"📥 <b>NOUVELLE TRANSACTION</b>\n\n"
            f"👤 <b>Client :</b> {client_name} (@{username})\n"
            f"🆔 <b>ID Client :</b> <code>{client_id}</code>\n"
            f"🏷 <b>Produit :</b> {html.escape(produit)}\n"
            f"💶 <b>Montant Coupon :</b> {montant_eur} €\n"
            f"💰 <b>Montant A Payer :</b> <code>{montant_xof:,} XOF</code>\n\n"
            f"🔑 <b>Code(s) Soumis :</b>\n<code>{html.escape(texte)}</code>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=message_admin, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif etape == "ATTENTE_NUMERO":
        client_id = update.effective_user.id
        client_name = html.escape(update.effective_user.full_name)
        montant_xof = context.user_data.get("montant_xof")

        context.user_data["etape"] = None

        await update.message.reply_text("Merci ! Votre numéro de dépôt a été transmis. Vous recevrez la confirmation dès que le transfert sera fait.")

        keyboard = [[InlineKeyboardButton("💳 Paiement Effectué", callback_data=f"paye_{client_id}")]]

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📱 <b>NUMÉRO DE DÉPÔT REÇU</b>\n\n"
                 f"👤 <b>Client :</b> {client_name}\n"
                 f"🆔 <b>ID Client :</b> <code>{client_id}</code>\n"
                 f"📞 <b>Numéro / Réseau :</b> <code>{html.escape(texte)}</code>\n"
                 f"💵 <b>Montant à transférer :</b> <code>{montant_xof:,} XOF</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

async def gerer_actions_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action, client_id = data[0], int(data[1])

    if action == "valide":
        await query.edit_message_text(text=f"{query.message.text}\n\n✅ STATUT : CODE CHARGÉ AVEC SUCCÈS")
        await context.bot.send_message(
            chat_id=client_id,
            text="✅ Votre code est valide et accepté !\n\nVeuillez répondre en envoyant votre Numéro de dépôt (Wave, Orange, MTN, Moov, etc.) avec le nom du compte pour recevoir votre paiement :"
        )
        context.application.user_data[client_id]["etape"] = "ATTENTE_NUMERO"

    elif action == "invalide":
        await query.edit_message_text(text=f"{query.message.text}\n\n❌ STATUT : CODE REFUSÉ / INVALIDE")
        await context.bot.send_message(
            chat_id=client_id,
            text="❌ Code invalide ou déjà utilisé. Veuillez vérifier la recharge et relancer la procédure avec la commande /start."
        )

    elif action == "paye":
        await query.edit_message_text(text=f"{query.message.text}\n\n💳 STATUT : PAIEMENT EFFECTUÉ ET CONFIRMÉ")
        await context.bot.send_message(
            chat_id=client_id,
            text="🎉 Paiement effectué avec succès ! Le transfert a été envoyé sur votre numéro. Merci pour votre confiance !"
        )

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(gerer_choix_produit, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(gerer_choix_montant, pattern="^montant_"))
    app.add_handler(CallbackQueryHandler(gerer_actions_admin, pattern="^(valide|invalide|paye)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gerer_messages_texte))

    print("Démarrage du serveur web secondaire...")
    threading.Thread(target=run_dummy_server, daemon=True).start()

    print("Bot démarré...")
    app.run_polling()

if __name__ == "__main__":
    main()
