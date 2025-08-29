# --- Saisie de la quantité ---
async def quantite_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantite = int(update.message.text)
        context.user_data['quantite'] = quantite

        plateforme = context.user_data['plateforme']
        service = context.user_data['service']
        prix_unitaire = tarifs[plateforme][service]
        total = prix_unitaire * quantite

        await update.message.reply_text(
            f"✅ Récapitulatif de votre commande :\n"
            f"Plateforme : {plateforme}\n"
            f"Service : {service}\n"
            f"Quantité : {quantite}K\n"
            f"Total : {total} F\n\n"
            "💳 Paiement : via MoMo / Flooz ou contactez WhatsApp pour finaliser."
        )
    except ValueError:
        await update.message.reply_text("❌ Veuillez entrer un nombre valide.")
        return QUANTITE

    return ConversationHandler.END

# --- Annulation ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Commande annulée.")
    return ConversationHandler.END

# --- Lancement du bot ---
def main():
    TOKEN = "7912783785:AAGy39S9SfPIfQt5KCRb8l-Gqpv1QIJoRLg"
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('commande', commande)],
        states={
            PLATEFORME: [CallbackQueryHandler(plateforme_choice)],
            SERVICE: [CallbackQueryHandler(service_choice)],
            QUANTITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, quantite_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('infos', infos))
    app.add_handler(CommandHandler('parrainage', parrainage))
    app.add_handler(conv_handler)

    print("🤖 Bot en ligne...")
    app.run_polling()

if __name__ == '__main__':
    main()