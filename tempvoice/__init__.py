from .tempvoice import TempVoice, TempVoicePanel


async def setup(bot):
    cog = TempVoice(bot)

    async def safe_cog_load():
        bot.add_view(TempVoicePanel(cog))

    cog.cog_load = safe_cog_load

    # Registra il Cog senza duplicare manualmente /voice.
    await bot.add_cog(cog, override=True)

    # Red 3.5.x tiene gli application commands disabilitati finche' non vengono
    # esplicitamente abilitati. Abilitiamo /voice e ricostruiamo il RedTree.
    await bot.enable_app_command("voice")
    await bot.tree.red_check_enabled()

    # Pubblica subito i comandi su Discord.
    await bot.tree.sync()
