from .tempvoice import TempVoice, TempVoicePanel


async def setup(bot):
    # Red 3.5.24/discord.py 2.7 registra automaticamente gli app_commands del Cog
    # durante add_cog(). Manteniamo il pannello persistente e lasciamo a Red
    # una sola registrazione del gruppo /voice.
    cog = TempVoice(bot)

    async def safe_cog_load():
        bot.add_view(TempVoicePanel(cog))

    cog.cog_load = safe_cog_load

    # Se esiste gia' un /voice nell'albero locale, lo sostituiamo senza fallire.
    await bot.add_cog(cog, override=True)

    # Sync globale.
    await bot.tree.sync()

    # Sync immediata per ogni server in cui il bot e' presente. Questo evita di
    # dipendere dalla propagazione dei comandi globali e rende /voice visibile
    # subito nel server. copy_global_to copia i comandi globali nell'albero guild
    # prima della sync specifica del server.
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        except Exception:
            # La sync globale e' gia' stata eseguita; non bloccare il caricamento
            # del Cog se un singolo server rifiuta la sync guild-specific.
            pass
