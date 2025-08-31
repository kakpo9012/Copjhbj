# -*- coding: utf-8 -*-
import html
import re
from typing import Dict, Any, List, Optional

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)

# ================== États de la conversation (ACHAT + RETRAIT) ==================
CHOIX_PRODUIT, CHOIX_PLATEFORME, SAISIE_QTE, SAISIE_LIEN, CHOIX_PAIEMENT, ENVOI_TRANSACTION = range(6)
# --- retrait: on ajoute un nouvel état pour choisir la plateforme
RETRAIT_PLATEFORME, RETRAIT_QTE, RETRAIT_LIEN = range(6, 9)

# ================== Prix par 1000 unités ==================
PRIX = {
    "TikTok": {"Abonnés": 2000, "Likes": 800, "Vues": 500},
    "Facebook": {"Abonnés": 2500, "Likes": 700, "Vues": 700},
    "Instagram": {"Abonnés": 3500, "Likes": 1200, "Vues": 700},
    "Telegram": {"Followers": 2500, "Likes": 500, "Vues": 500},
    "WhatsApp": {"Followers": 4500},
}

# ================== Canaux ==================
ADMIN_CHANNEL_ID = -1003076956244    # <- change si besoin
SUIVI_CHANNEL_ID = -1002379469108    # <- change si besoin

# ✅ Canaux que les utilisateurs DOIVENT rejoindre
REQUIRED_CHANNELS = [
    -1002379469108,
    -1002834854293,
]
REQUIRED_CHANNEL_LINKS = [
    "https://t.me/flashboost1",
    "https://t.me/flashboost03",
]

# Admins autorisés
ADMINS = [7827581652, 6114819292]

# ================== Infos paiement ==================
PAIEMENT_METHODES = {
    "MTN": "+2290159152677",
    "Moov": "+2290160731390",
    "Crypto": "Contactez @boosts_services"
}

# ================== Paramètres retrait ==================
MIN_RETRAIT = 100
MAX_RETRAIT = 10_000

# ================== “Base de données” en mémoire ==================
DB: Dict[int, Dict[str, Any]] = {}
# DB[user_id] = {
#   "balance": int,
#   "orders": [ {code, produit, ...} ],
#   "referrer": Optional[int],
#   "ref_bonus_given": set(),
#   "pending_retraits": { rid: {plateforme, qte, lien} }
# }

# ================== Helpers ==================
def ensure_user(user_id: int):
    if user_id not in DB:
        DB[user_id] = {
            "balance": 0,
            "orders": [],
            "referrer": None,
            "ref_bonus_given": set(),
            "pending_retraits": {}
        }

def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🛒 Achat", "📜 Historique de mes commandes"],
            ["🔗 Lien de parrainage", "💰 Solde Like"],
            ["💸 Retrait Like"],
        ],
        resize_keyboard=True
    )

def parse_start_payload(text: str) -> Optional[int]:
    # /start ref_12345
    m = re.search(r"ref_(\d+)", text or "")
    return int(m.group(1)) if m else None

def channels_required_configured() -> bool:
    return (
        bool(REQUIRED_CHANNELS)
        and bool(REQUIRED_CHANNEL_LINKS)
        and len(REQUIRED_CHANNELS) == len(REQUIRED_CHANNEL_LINKS)
    )

async def check_all_memberships(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not channels_required_configured():
        return True
    try:
        for chat_id in REQUIRED_CHANNELS:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        return True
    except Exception:
        # Si le bot n’a pas les droits, on considère non-vérifié
        return False

async def prompt_join_channels(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les liens + bouton 'J'ai rejoint'."""
    if not channels_required_configured():
        return
    join_buttons = [[InlineKeyboardButton(f"🔗 Canal {i+1}", url=link)]
                    for i, link in enumerate(REQUIRED_CHANNEL_LINKS)]
    join_buttons.append([InlineKeyboardButton("✅ J'ai rejoint", callback_data="joined_ok")])

    text = (
        "👋 Bienvenue !\n\n"
        "🔒 Pour accéder au menu, rejoins d'abord nos canaux puis appuie sur « ✅ J'ai rejoint »."
    )
    msg = getattr(update_or_query, "message", None)
    if msg:
        await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(join_buttons))
    else:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(join_buttons))

async def ensure_access_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Vérifie l'accès. Si non, renvoie False et affiche les liens."""
    user = update.effective_user
    ensure_user(user.id)
    if not channels_required_configured():
        return True
    if await check_all_memberships(context, user.id):
        return True
    await prompt_join_channels(update, context)
    return False

# ================== START & PARRAINAGE ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    # Gérer le parrainage si /start ref_<id>
    payload = update.message.text if update.message else ""
    ref_id = parse_start_payload(payload)
    if ref_id and ref_id != user.id:
        DB[user.id]["referrer"] = ref_id  # on mémorise le parrain potentiel

    if channels_required_configured():
        if await check_all_memberships(context, user.id):
            # Créditer le parrain si pas déjà crédité
            ref = DB[user.id].get("referrer")
            if ref and ref != user.id:
                ensure_user(ref)
                if user.id not in DB[ref]["ref_bonus_given"]:
                    DB[ref]["balance"] += 10
                    DB[ref]["ref_bonus_given"].add(user.id)
                    try:
                        await context.bot.send_message(
                            ref, f"🎁 Bonus parrainage : +10 Likes (filleul : {user.full_name})"
                        )
                    except Exception:
                        pass
            await update.message.reply_text("✅ Accès débloqué.", reply_markup=main_menu_keyboard())
            return
        await prompt_join_channels(update, context)
        return
    else:
        # Aucun canal requis -> accès direct + crédit parrain immédiatement (une fois)
        ref = DB[user.id].get("referrer")
        if ref and ref != user.id:
            ensure_user(ref)
            if user.id not in DB[ref]["ref_bonus_given"]:
                DB[ref]["balance"] += 10
                DB[ref]["ref_bonus_given"].add(user.id)
                try:
                    await context.bot.send_message(
                        ref, f"🎁 Bonus parrainage : +10 Likes (filleul : {user.full_name})"
                    )
                except Exception:
                    pass
        await update.message.reply_text("👋 Bienvenue !", reply_markup=main_menu_keyboard())

async def after_joined_ok(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ensure_user(user.id)

    if not channels_required_configured():
        await query.edit_message_text("✅ Accès déjà disponible.", parse_mode=ParseMode.HTML)
        await context.bot.send_message(chat_id=user.id, text="🏠 Menu principal", reply_markup=main_menu_keyboard())
        return

    joined = await check_all_memberships(context, user.id)
    if not joined:
        await query.edit_message_text("❌ Abonnement non détecté. Rejoins tous les canaux puis réessaie.")
        return

    # Créditer le parrain (10 Likes) seulement une fois
    ref_id = DB[user.id].get("referrer")
    if ref_id and ref_id != user.id:
        ensure_user(ref_id)
        if user.id not in DB[ref_id]["ref_bonus_given"]:
            DB[ref_id]["balance"] += 10
            DB[ref_id]["ref_bonus_given"].add(user.id)
            try:
                await context.bot.send_message(
                    ref_id, f"🎁 Bonus parrainage : +10 Likes (filleul : {user.full_name})"
                )
            except Exception:
                pass

    await query.edit_message_text("✅ Merci ! Accès débloqué.")
    await context.bot.send_message(chat_id=user.id, text="🏠 Menu principal", reply_markup=main_menu_keyboard())

# ================== MENU PRINCIPAL (hors conversations) ==================
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)
    txt = (update.message.text or "").strip()

    # Anti-contournement : si canaux requis et pas membre -> on bloque tout le menu
    if not await ensure_access_or_prompt(update, context):
        return

    if txt == "📜 Historique de mes commandes":
        orders: List[Dict[str, Any]] = DB[user.id]["orders"]
        if not orders:
            await update.message.reply_text("📭 Aucun historique pour le moment.", reply_markup=main_menu_keyboard())
        else:
            lines = []
            for o in orders[-10:]:
                lines.append(
                    f"• {o['code']} • {o['produit']} - {o['plateforme']} • {o['quantite']} • {o['prix']} F CFA • {o['etat']}"
                )
            await update.message.reply_text(
                "📜 *Dernières commandes*\n" + "\n".join(lines),
                parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_keyboard()
            )

    elif txt == "🔗 Lien de parrainage":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"
        await update.message.reply_text(f"🔗 Ton lien de parrainage :\n{link}", reply_markup=main_menu_keyboard())

    elif txt == "💰 Solde Like":
        bal = DB[user.id]["balance"]
        await update.message.reply_text(f"💰 Solde Likes : {bal}", reply_markup=main_menu_keyboard())

    elif txt == "🛒 Achat":
        pass  # capté par le ConversationHandler achat

    elif txt == "💸 Retrait Like":
        pass  # capté par le ConversationHandler retrait

    else:
        await update.message.reply_text("❓ Choix inconnu. Utilise le menu ci-dessous.", reply_markup=main_menu_keyboard())

# ================== FLOW ACHAT ==================
async def achat_entry_from_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_access_or_prompt(update, context):
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📈 Acheter Vues", callback_data="Vues")],
        [InlineKeyboardButton("❤️ Acheter Likes", callback_data="Likes")],
        [InlineKeyboardButton("👥 Acheter Abonnés/Followers", callback_data="Abonnés")],
    ]
    await update.message.reply_text(
        "Quelle commande lancez-vous ? 🤔👉",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOIX_PRODUIT

async def start_old_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_access_or_prompt(update, context):
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📈 Acheter Vues", callback_data="Vues")],
        [InlineKeyboardButton("❤️ Acheter Likes", callback_data="Likes")],
        [InlineKeyboardButton("👥 Acheter Abonnés/Followers", callback_data="Abonnés")],
    ]
    if update.message:
        await update.message.reply_text(
            "Bienvenue chez ⚡ Flash Boost 🚀, votre service de visibilité 👀.\n\n"
            "Quelle commande lancez-vous ? 🤔👉",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.callback_query.message.reply_text(
            "Retour au menu principal 👇\n\nChoisissez une option :",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    return CHOIX_PRODUIT

async def choix_produit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    ensure_user(user_id)

    if channels_required_configured() and not await check_all_memberships(context, user_id):
        await prompt_join_channels(query, context)
        return ConversationHandler.END

    produit = query.data
    context.user_data["produit"] = produit

    plateformes = ["TikTok", "Facebook", "Instagram", "Telegram"]
    if produit == "Abonnés":
        plateformes.append("WhatsApp")

    buttons = [[InlineKeyboardButton(p, callback_data=p)] for p in plateformes]
    buttons.append([InlineKeyboardButton("🔙 Retour au menu", callback_data="menu")])

    await query.edit_message_text(
        f"✅ Produit choisi : <b>{produit}</b>\n\nChoisissez une plateforme :",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )
    return CHOIX_PLATEFORME

async def choix_plateforme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu":
        await query.edit_message_text("🏠 Retour au menu principal.")
        await context.bot.send_message(query.from_user.id, "Menu :", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    plateforme = query.data
    context.user_data["plateforme"] = plateforme
    produit = context.user_data["produit"]

    cle_produit = produit if not (produit == "Abonnés" and plateforme in ["Telegram", "WhatsApp"]) else "Followers"

    if plateforme not in PRIX or cle_produit not in PRIX[plateforme]:
        await query.edit_message_text("❌ Option non disponible pour cette plateforme.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"🌐 Plateforme : <b>{plateforme}</b>\n"
        f"📱 Produit : <b>{produit}</b>\n\n"
        "➡️ Entrez la quantité souhaitée (minimum 1000) :",
        parse_mode=ParseMode.HTML,
    )
    return SAISIE_QTE

async def saisie_quantite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texte = (update.message.text or "").strip()

    if not texte.isdigit():
        await update.message.reply_text("⚠️ Veuillez saisir un nombre entier valide.")
        return SAISIE_QTE

    qte = int(texte)
    if qte < 1000:
        await update.message.reply_text("⚠️ Minimum 1000. Réessayez.")
        return SAISIE_QTE

    context.user_data["quantite"] = qte
    produit = context.user_data["produit"]
    plateforme = context.user_data["plateforme"]

    cle_produit = produit if not (produit == "Abonnés" and plateforme in ["Telegram", "WhatsApp"]) else "Followers"
    prix_1k = PRIX[plateforme][cle_produit]

    prix_total = int((qte / 1000) * prix_1k)
    context.user_data["prix_total"] = prix_total

    await update.message.reply_text(
        f"📋 Récapitulatif commande :\n"
        f"- Produit : <b>{produit}</b>\n"
        f"- Plateforme : <b>{plateforme}</b>\n"
        f"- Quantité : {qte}\n"
        f"- Prix total : <b>{prix_total} F CFA</b>\n\n"
        "➡️ Envoyez maintenant le lien du compte / post / vidéo :",
        parse_mode=ParseMode.HTML,
    )
    return SAISIE_LIEN

async def saisie_lien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lien = (update.message.text or "").strip()
    safe_lien = html.escape(lien)

    context.user_data["lien"] = lien

    buttons = [
        [InlineKeyboardButton("💛 MTN", callback_data="MTN")],
        [InlineKeyboardButton("💙 Moov", callback_data="Moov")],
        [InlineKeyboardButton("🪙 Crypto", callback_data="Crypto")],
        [InlineKeyboardButton("🔙 Retour au menu", callback_data="menu")],
    ]

    await update.message.reply_text(
        f"🔗 Lien reçu ✅\n<code>{safe_lien}</code>\n\n"
        "👉 Choisissez maintenant votre méthode de paiement :",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML,
    )
    return CHOIX_PAIEMENT

async def choix_paiement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "menu":
        await query.edit_message_text("🏠 Retour au menu principal.")
        await context.bot.send_message(query.from_user.id, "Menu :", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    methode = query.data
    context.user_data["paiement"] = methode
    numero = PAIEMENT_METHODES[methode]

    await query.edit_message_text(
        f"✅ Méthode choisie : <b>{methode}</b>\n\n"
        f"➡️ Payez sur ce numéro / contact : <code>{numero}</code>\n\n"
        "Ensuite, envoyez l'ID de transaction ci-dessous 👇",
        parse_mode=ParseMode.HTML,
    )
    return ENVOI_TRANSACTION

async def reception_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id = html.escape((update.message.text or "").strip())
    user = update.message.from_user

    produit = context.user_data.get("produit", "N/A")
    plateforme = context.user_data.get("plateforme", "N/A")
    qte = context.user_data.get("quantite", "N/A")
    prix = context.user_data.get("prix_total", "N/A")
    lien = html.escape(context.user_data.get("lien", "N/A"))
    paiement = context.user_data.get("paiement", "N/A")

    username = f"@{user.username}" if user.username else "Aucun"

    ensure_user(user.id)
    code_cmd = f"CMD{user.id}-{len(DB[user.id]['orders'])+1}"
    commande = {
        "code": code_cmd,
        "nom": user.full_name,
        "username": username,
        "produit": produit,
        "plateforme": plateforme,
        "quantite": qte,
        "prix": prix,
        "lien": lien,
        "paiement": paiement,
        "transaction": tx_id,
        "etat": "En attente",
    }
    DB[user.id]["orders"].append(commande)

    message_admin = (
        f"📥 <b>Nouvelle commande</b>\n\n"
        f"👤 Nom : {user.full_name}\n"
        f"🔗 Username : {username}\n"
        f"🆔 ID : <code>{user.id}</code>\n"
        f"🧾 Code : <b>{code_cmd}</b>\n\n"
        f"📱 Produit : {produit}\n"
        f"🌐 Plateforme : {plateforme}\n"
        f"🔢 Quantité : {qte}\n"
        f"🔗 Lien : <code>{lien}</code>\n"
        f"💰 Prix : {prix} F CFA\n"
        f"💳 Méthode paiement : {paiement}\n"
        f"🧾 Transaction ID : <code>{tx_id}</code>"
    )

    buttons = [[
        InlineKeyboardButton("✅ Confirmer", callback_data=f"confirmer_cmd_{user.id}_{code_cmd}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"rejeter_cmd_{user.id}_{code_cmd}")
    ]]

    await context.bot.send_message(
        ADMIN_CHANNEL_ID, message_admin,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    await update.message.reply_text("✅ Transaction reçue ! Merci. Vous serez contacté pour validation.",
                                    reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ================== FLOW RETRAIT LIKE (MODIFIÉ) ==================
async def retrait_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_access_or_prompt(update, context):
        return ConversationHandler.END

    # 1) Choix plateforme (Telegram / Facebook)
    kb = [
        [InlineKeyboardButton("Telegram", callback_data="ret_pf_Telegram")],
        [InlineKeyboardButton("Facebook", callback_data="ret_pf_Facebook")],
        [InlineKeyboardButton("🔙 Retour au menu", callback_data="ret_pf_menu")],
    ]
    await update.message.reply_text(
        "💸 Retrait de Likes\n\nChoisissez une plateforme :",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return RETRAIT_PLATEFORME

async def retrait_choix_plateforme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data == "ret_pf_menu":
        await query.edit_message_text("🏠 Retour au menu principal.")
        await context.bot.send_message(query.from_user.id, "Menu :", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    # data = ret_pf_Telegram / ret_pf_Facebook
    plateforme = data.split("_", 2)[-1]
    context.user_data["ret_plateforme"] = plateforme

    await query.edit_message_text(
        f"🌐 Plateforme : <b>{plateforme}</b>\n\n"
        f"➡️ Entrez le nombre de Likes à retirer (min {MIN_RETRAIT}, max {MAX_RETRAIT}) :",
        parse_mode=ParseMode.HTML
    )
    return RETRAIT_QTE

async def retrait_qte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    if "ret_plateforme" not in context.user_data:
        # Sécurité: si l'utilisateur a sauté l'étape
        kb = [
            [InlineKeyboardButton("Telegram", callback_data="ret_pf_Telegram")],
            [InlineKeyboardButton("Facebook", callback_data="ret_pf_Facebook")],
        ]
        await update.message.reply_text(
            "⚠️ Choisissez d'abord une plateforme.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return RETRAIT_PLATEFORME

    txt = (update.message.text or "").strip()
    if not txt.isdigit():
        await update.message.reply_text("⚠️ Entrez un nombre valide.")
        return RETRAIT_QTE

    qte = int(txt)
    if qte < MIN_RETRAIT:
        await update.message.reply_text(
            f"❌ Le minimum de retrait est {MIN_RETRAIT} Likes.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    if qte > MAX_RETRAIT:
        await update.message.reply_text(
            f"❌ Le maximum de retrait est {MAX_RETRAIT} Likes.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    # Vérifier le solde dès maintenant
    bal = DB[user.id]["balance"]
    if bal < MIN_RETRAIT or bal < qte:
        await update.message.reply_text(
            f"❌ Solde insuffisant. Minimum requis: {MIN_RETRAIT} Likes. Solde actuel: {bal}.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    context.user_data["ret_qte"] = qte
    await update.message.reply_text("🔗 Maintenant, envoyez le lien / username où livrer les Likes :", reply_markup=ReplyKeyboardRemove())
    return RETRAIT_LIEN

async def retrait_lien(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user.id)

    lien_raw = (update.message.text or "").strip()
    lien = html.escape(lien_raw)
    qte = int(context.user_data.get("ret_qte", 0))
    plateforme = context.user_data.get("ret_plateforme", "N/A")

    # ID de retrait
    rid = f"RET{user.id}-{len(DB[user.id]['pending_retraits'])+1}"
    DB[user.id]["pending_retraits"][rid] = {"plateforme": plateforme, "qte": qte, "lien": lien_raw}

    msg = (
        f"💸 <b>Demande de Retrait Likes</b>\n\n"
        f"🆔 User: <code>{user.id}</code>\n"
        f"👤 {user.full_name} ({'@'+user.username if user.username else 'aucun'})\n"
        f"🌐 Plateforme : <b>{plateforme}</b>\n"
        f"🔢 Quantité : {qte}\n"
        f"🔗 Lien : <code>{lien}</code>\n"
        f"🧾 ID demande : <b>{rid}</b>"
    )
    buttons = [[
        InlineKeyboardButton("✅ Confirmer", callback_data=f"confirmer_ret_{user.id}_{rid}"),
        InlineKeyboardButton("❌ Rejeter", callback_data=f"rejeter_ret_{user.id}_{rid}")
    ]]
    await context.bot.send_message(
        ADMIN_CHANNEL_ID, msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(buttons)
    )

    await update.message.reply_text(
        f"✅ Demande de retrait envoyée.\nID: {rid}\nEn attente de validation.",
        reply_markup=main_menu_keyboard()
    )
    return ConversationHandler.END

# ================== VALIDATION ADMIN (achats + retraits) ==================
async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    admin_id = query.from_user.id

    if admin_id not in ADMINS:
        await query.answer("⛔ Tu n'es pas autorisé à valider.", show_alert=True)
        return

    data = (query.data or "")
    parts = data.split("_", 3)  # ex: confirmer_cmd_<user_id>_<code>  /  rejeter_ret_<user_id>_<rid>
    if len(parts) < 4:
        await query.edit_message_text("⚠️ Données incomplètes.")
        return

    action, kind, user_id_s, ident = parts
    user_id = int(user_id_s)
    ensure_user(user_id)

    # ======== ACHAT ========
    if kind == "cmd":
        target = None
        for o in DB[user_id]["orders"]:
            if o["code"] == ident:
                target = o
                break

        if not target:
            await query.edit_message_text("⚠️ Commande introuvable.")
            return

        if action == "confirmer":
            target["etat"] = "Confirmée"
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Félicitations ! Votre commande {ident} a été confirmée ✅"
            )
            await query.edit_message_text(f"✅ Commande {ident} confirmée et client notifié.")

            # Suivi automatique
            message_suivi = (
                f"📦 <b>Commande Confirmée</b>\n\n"
                f"👤 Nom : {target['nom']}\n"
                f"🔗 Username : {target['username']}\n"
                f"🧾 Code : <b>{target['code']}</b>\n"
                f"📱 Produit : {target['produit']}\n"
                f"🌐 Plateforme : {target['plateforme']}\n"
                f"🔢 Quantité : {target['quantite']}\n"
                f"🔗 Lien : <code>{target['lien']}</code>\n"
                f"💰 Prix : {target['prix']} F CFA\n"
                f"💳 Paiement : {target['paiement']}\n"
                f"🧾 Transaction : <code>{target['transaction']}</code>"
            )
            await context.bot.send_message(SUIVI_CHANNEL_ID, message_suivi, parse_mode=ParseMode.HTML)

        else:  # rejeter
            target["etat"] = "Rejetée"
            await context.bot.send_message(chat_id=user_id, text=f"❌ Désolé, votre commande {ident} a été rejetée.")
            await query.edit_message_text(f"🚫 Commande {ident} rejetée et client notifié.")

    # ======== RETRAIT ========
    elif kind == "ret":
        pend = DB[user_id]["pending_retraits"].get(ident)
        if not pend:
            await query.edit_message_text("⚠️ Demande introuvable ou déjà traitée.")
            return

        if action == "confirmer":
            qty = int(pend["qte"])
            # Débiter le solde à la confirmation
            if DB[user_id]["balance"] >= qty:
                DB[user_id]["balance"] -= qty
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Retrait {ident} refusé (solde insuffisant)."
                )
                await query.edit_message_text("🚫 Retrait refusé (solde insuffisant au moment de la validation).")
                DB[user_id]["pending_retraits"].pop(ident, None)
                return

            await context.bot.send_message(
                user_id,
                f"✅ Retrait confirmé : {qty} Likes seront livrés sur ({pend.get('plateforme','N/A')}) :\n{pend['lien']}"
            )
            await query.edit_message_text("✅ Retrait confirmé et utilisateur notifié.")

            # Suivi auto
            await context.bot.send_message(
                SUIVI_CHANNEL_ID,
                f"💸 Retrait confirmé • User {user_id} • {qty} Likes • Plateforme: {pend.get('plateforme','N/A')} • Lien: {pend['lien']}"
            )
        else:
            await context.bot.send_message(user_id, f"❌ Retrait rejeté (ID: {ident}).")
            await query.edit_message_text("🚫 Retrait rejeté et utilisateur notifié.")

        DB[user_id]["pending_retraits"].pop(ident, None)

# ================== Annulation générique ==================
async def annuler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Opération annulée.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ================== MAIN ==================
def main():
    # ⚠️ Ne publie jamais ton token en clair. Mets-le dans une variable d'environnement.
    TOKEN = "7912783785:AAGy39S9SfPIfQt5KCRb8l-Gqpv1QIJoRLg"

    app = ApplicationBuilder().token(TOKEN).build()

    # Bouton "J'ai rejoint" (parrainage)
    app.add_handler(CallbackQueryHandler(after_joined_ok, pattern=r"^joined_ok$"))

    # ===== Conversation ACHAT =====
    achat_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^🛒 Achat$"), achat_entry_from_menu),
            CommandHandler("achat", start_old_purchase),
        ],
        states={
            CHOIX_PRODUIT: [CallbackQueryHandler(choix_produit)],
            CHOIX_PLATEFORME: [CallbackQueryHandler(choix_plateforme)],
            SAISIE_QTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, saisie_quantite)],
            SAISIE_LIEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, saisie_lien)],
            CHOIX_PAIEMENT: [CallbackQueryHandler(choix_paiement)],
            ENVOI_TRANSACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, reception_transaction)],
        },
        fallbacks=[CommandHandler("cancel", annuler)],
        allow_reentry=True,
    )
    app.add_handler(achat_conv)

    # ===== Conversation RETRAIT (MODIFIÉE) =====
    retrait_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"^💸 Retrait Like$"), retrait_entry),
            CommandHandler("retrait", retrait_entry),
        ],
        states={
            RETRAIT_PLATEFORME: [CallbackQueryHandler(retrait_choix_plateforme, pattern=r"^ret_pf_(Telegram|Facebook|menu)$")],
            RETRAIT_QTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, retrait_qte)],
            RETRAIT_LIEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, retrait_lien)],
        },
        fallbacks=[CommandHandler("cancel", annuler)],
        allow_reentry=True,
        per_chat=True,
        per_user=True,
    )
    app.add_handler(retrait_conv)

    # ===== Admin (achats + retraits) =====
    app.add_handler(CallbackQueryHandler(handle_admin_action, pattern=r"^(confirmer|rejeter)_(cmd|ret)_"))

    # ===== /start -> déblocage + menu =====
    app.add_handler(CommandHandler("start", start))

    # ===== Handler du menu (après les ConversationHandlers) =====
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    print("🤖 Bot démarré...")
    app.run_polling()


if __name__ == "__main__":
    main()