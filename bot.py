import os
import logging
from flask import Flask, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Configuration du Logging
logging.basicConfig(level=logging.INFO)

# Initialisation de Flask (pour le déploiement sur Render)
app = Flask(__name__)

# Récupération des variables d'environnement
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

# --- INTERFACE WEB D'ACCUEIL ---
HTML_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Bot Telegram de Confirmation de Paiement</title>
  <style>
    body { font-family: Arial, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f0f2f5; }
    .card { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; max-width: 400px; }
    h1 { color: #0088cc; font-size: 22px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🤖 Bot Telegram Actif</h1>
    <p>Le serveur fonctionne parfaitement sur Render.</p>
  </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

@app.route('/health')
def health():
    return "OK", 200


# --- LOGIQUE BOT TELEGRAM ---

# Command /start pour le client
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Bonjour {user_name} ! 👋\n\n"
        "Veuillez envoyer la **capture d'écran (photo)** comme preuve de votre paiement Mobile Money pour valider votre commande."
    )

# Gestion de la preuve de paiement (Photo envoyée par le client)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_file = update.message.photo[-1].file_id

    # Notification au client
    await update.message.reply_text(
        "⏳ **Preuve envoyée !**\n"
        "L'administrateur va vérifier votre paiement sous peu."
    )

    # ÉTAPE 1 ADMIN : Bouton unique "Lancer la vérification"
    keyboard = [
        [
            InlineKeyboardButton(
                "🔍 Lancer la vérification", 
                callback_data=f"start_verify_{user.id}"
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Envoi de la photo à l'admin avec le bouton initial
    if ADMIN_CHAT_ID:
        await context.bot.send_photo(
            chat_id=int(ADMIN_CHAT_ID),
            photo=photo_file,
            caption=(
                f"📥 **NOUVELLE PREUVE DE PAIEMENT**\n\n"
                f"👤 **Client :** {user.full_name} (@{user.username or 'Sans pseudo'})\n"
                f"🆔 **ID Client :** `{user.id}`\n\n"
                f"Cliquez sur le bouton ci-dessous pour démarrer le contrôle."
            ),
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

# Gestion des actions des boutons pour l'administrateur
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    # ÉTAPE 2 ADMIN : Quand l'admin clique sur "Lancer la vérification"
    if data.startswith("start_verify_"):
        client_id = data.split("_")[2]

        # Déblocage des deux boutons "Valider" et "Rejeter"
        new_keyboard = [
            [
                InlineKeyboardButton("✅ Valider la commande", callback_data=f"confirm_{client_id}"),
                InlineKeyboardButton("❌ Rejeter la commande", callback_data=f"reject_{client_id}")
            ]
        ]
        new_reply_markup = InlineKeyboardMarkup(new_keyboard)

        # Mise à jour du message côté Admin
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=query.message.caption + "\n\n⚙️ **Vérification en cours...**",
            reply_markup=new_reply_markup,
            parse_mode="Markdown"
        )

        # Informer le client que l'admin est en train d'examiner la preuve
        try:
            await context.bot.send_message(
                chat_id=int(client_id),
                text="🔍 **Vérification en cours...**\nL'administrateur examine actuellement votre preuve de paiement."
            )
        except Exception as e:
            logging.error(f"Erreur notification client: {e}")

    # ÉTAPE 3A ADMIN : Validation de la commande
    elif data.startswith("confirm_"):
        client_id = data.split("_")[1]

        # Mise à jour du message admin (suppression des boutons)
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=query.message.caption + "\n\n✅ **STATUT : Commande Validée**",
            reply_markup=None,
            parse_mode="Markdown"
        )

        # Confirmation au client
        try:
            await context.bot.send_message(
                chat_id=int(client_id),
                text="🎉 **Commande Validée !**\nVotre paiement a été confirmé avec succès. La livraison sera effectuée sous peu."
            )
        except Exception as e:
            logging.error(f"Erreur notification client: {e}")

    # ÉTAPE 3B ADMIN : Rejet de la commande
    elif data.startswith("reject_"):
        client_id = data.split("_")[1]

        # Mise à jour du message admin (suppression des boutons)
        await context.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=query.message.caption + "\n\n❌ **STATUT : Commande Rejetée**",
            reply_markup=None,
            parse_mode="Markdown"
        )

        # Notification de rejet au client
        try:
            await context.bot.send_message(
                chat_id=int(client_id),
                text="❌ **Commande Rejetée**\nLa preuve de paiement est invalide ou non reçue. Veuillez renvoyer une nouvelle capture d'écran."
            )
        except Exception as e:
            logging.error(f"Erreur notification client: {e}")


# --- INITIALISATION ET DÉMARRAGE DU BOT ---
def main():
    if BOT_TOKEN:
        application = ApplicationBuilder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        application.add_handler(CallbackQueryHandler(handle_callback))

        # Démarrage du bot Telegram en mode non-bloquant
        application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    import threading
    
    # Exécution du Bot dans un thread séparé
    bot_thread = threading.Thread(target=main)
    bot_thread.daemon = True
    bot_thread.start()

    # Démarrage du serveur Web Flask sur le port de Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
