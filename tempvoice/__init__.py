from .tempvoice import TempVoice, TempVoicePanel


async def setup(bot):
    # Red 3.5.24/discord.py 2.7 registra automaticamente gli app_commands del Cog
    # durante add_cog(). La vecchia cog_load di TempVoice tentava poi di registrare
    # /voice una seconda volta. Manteniamo solo il pannello persistente.
    cog = TempVoice(bot)

    async def safe_cog_load():
        bot.add_view(TempVoicePanel(cog))

    cog.cog_load = safe_cog_load

    # Se un altro /voice o una registrazione rimasta in memoria esiste gia', Red
    # riceve override=True e sostituisce il comando invece di sollevare
    # CommandAlreadyRegistered durante l'iniezione del Cog.
    await bot.add_cog(cog, override=True)
