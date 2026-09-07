import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Configuration via variables d'environnement sur Render
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 0))

# --- GRILLES TARIFAIRES (EUR : XOF) ---
GRILLES_TARIFS = {
    "PCS": {
        20: 7000,
        30: 10000,
        40: 15000,
        50: 23000,
        100: 53000,
        150: 83000,
        250: 143000,
    },
    "Transcash": {
        20: 8000,
        50: 28000,
        100: 58000,
        150: 88000,
        200: 118000,
        250: 148000,
        300: 300000,
    },
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- ETAPE 1: /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("💳 PCS", callback_data="prod_PCS"),
            InlineKeyboardButton("💳 Transcash", callback_data="prod_Transcash"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Bienvenue ! 👋\n\nVeuillez sélectionner le type de recharge que vous souhaitez échanger :",
        reply_markup=reply_markup,
    )

# --- ETAPE 2: Choix du Produit -> Affichage des Boutons de Montants ---
async def gerer_choix_produit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    produit = query.data.split("_")[1]
    context.user_data["produit"] = produit

    tarifs = GRILLES_TARIFS.get(produit, {})

    keyboard = []
    for eur, xof in tarifs.items():
        texte_bouton = f"{eur}€ ➡️ {xof:,} XOF"
        keyboard.append([InlineKeyboardButton(texte_bouton, callback_data=f"montant_{eur}_{xof}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=f"Vous avez choisi : **{produit}**\n\nChoisissez le montant de votre recharge :",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

# --- ETAPE 3: Sélection du Montant -> Demande du Code ---
async def gerer_choix_montant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    montant_eur = int(data[1])
    montant_xof = int(data[2])

    context.user_data["montant_eur"] = montant_eur
    context.user_data["montant_xof"] = montant_xof
    context.user_data["etape"] = "ATTENTE_CODE"

    produit = context.user_data.get("produit")

    await query.edit_message_text(
        text=f"📊 **Récapitulatif de la commande :**\n"
             f"• Service : **{produit}**\n"
             f"• Montant du coupon : **{montant_eur} €**\n"
             f"• Vous recevrez : **{montant_xof:,} XOF**\n\n"
             f"👉 Veuillez maintenant écrire et envoyer votre **code de recharge {produit}** dans ce chat :",
        parse_mode="Markdown",
    )

# --- ETAPE 4: Traitement des messages texte (Code & Numéro de Dépôt) ---
async def gerer_messages_texte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    etape = context.user_data.get("etape")
    texte = update.message.text.strip()

    # Réception du code de recharge (supporte les sauts de ligne)
    if etape == "ATTENTE_CODE":
        code_soumis = texte
        client_id = update.effective_user.id
        client_name = update.effective_user.full_name
        username = update.effective_user.username or "Pas de username"

        produit = context.user_data.get("produit")
        montant_eur = context.user_data.get("montant_eur")
        montant_xof = context.user_data.get("montant_xof")

        context.user_data["etape"] = None

        await update.message.reply_text(
            "⏳ Code(s) reçu(s) ! Nous vérifions et rechargeons le coupon. Veuillez patienter un instant..."
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Code Valide", callback_data=f"valide_{client_id}"),
                InlineKeyboardButton("❌ Code Invalide", callback_data=f"invalide_{client_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_admin = (
            f"📥 **NOUVELLE TRANSACTION**\n\n"
            f"👤 **Client :** {client_name} (@{username})\n"
            f"🆔 **ID Client :** `{client_id}`\n"
            f"🏷 **Produit :** {produit}\n"
            f"💶 **Montant Coupon :** {montant_eur} €\n"
            f"💰 **Montant A Payer :** `{montant_xof:,} XOF`\n\n"
            f"🔑 **Code(s) Soumis :**\n`{code_soumis}`"
        )

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID, text=message_admin, parse_mode="Markdown", reply_markup=reply_markup
        )

    # Réception du numéro de dépôt Mobile Money
    elif etape == "ATTENTE_NUMERO":
        numero_depot = texte
        client_id = update.effective_user.id
        client_name = update.effective_user.full_name
        montant_xof = context.user_data.get("montant_xof")

        context.user_data["etape"] = None

        await update.message.reply_text(
            "Merci ! Votre numéro de dépôt a été transmis. Vous recevrez la confirmation dès que le transfert sera fait."
        )

        keyboard = [
            [InlineKeyboardButton("💳 Paiement Effectué", callback_data=f"paye_{client_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📱 **NUMÉRO DE DÉPÔT REÇU**\n\n"
                 f"👤 **Client :** {client_name}\n"
                 f"🆔 **ID Client :** `{client_id}`\n"
                 f"📞 **Numéro / Réseau :** `{numero_depot}`\n"
                 f"💵 **Montant à transférer :** `{montant_xof:,} XOF`",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

# --- ETAPE 5: Actions Administrateur ---
async def gerer_actions_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[0]
    client_id = int(data[1])

    if action == "valide":
        await query.edit_message_text(text=f"{query.message.text}\n\n✅ **STATUT : CODE CHARGÉ AVEC SUCCÈS**")

        await context.bot.send_message(
            chat_id=client_id,
            text="✅ **Votre code est valide et accepté !**\n\n"
                 "Veuillez répondre en envoyant votre **Numéro de dépôt** (Wave, Orange, MTN, Moov, etc.) avec le nom du compte pour recevoir votre paiement :"
        )
        context.application.user_data[client_id]["etape"] = "ATTENTE_NUMERO"

    elif action == "invalide":
        await query.edit_message_text(text=f"{query.message.text}\n\n❌ **STATUT : CODE REFUSÉ / INVALIDE**")
        await context.bot.send_message(
            chat_id=client_id,
            text="❌ **Code invalide ou déjà utilisé.** Veuillez vérifier la recharge et relancer la procédure avec la commande /start."
        )

    elif action == "paye":
        await query.edit_message_text(text=f"{query.message.text}\n\n💳 **STATUT : PAIEMENT EFFECTUÉ ET CONFIRMÉ**")
        await context.bot.send_message(
            chat_id=client_id,
            text="🎉 **Paiement effectué avec succès !** Le transfert a été envoyé sur votre numéro. Merci pour votre confiance !"
        )

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(gerer_choix_produit, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(gerer_choix_montant, pattern="^montant_"))
    app.add_handler(CallbackQueryHandler(gerer_actions_admin, pattern="^(valide|invalide|paye)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gerer_messages_texte))

    print("Bot démarré...")
    app.run_polling()

if __name__ == "__main__":
    main()
