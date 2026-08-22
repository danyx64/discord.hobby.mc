from .tempvoice import TempVoice, TempVoicePanel


# Etichette leggibili per la pulsantiera TempVoice.
# La patch e' idempotente: su reload non si avvolge mai su se stessa.
_BASE_PANEL_INIT = getattr(TempVoicePanel.__init__, "__wrapped__", TempVoicePanel.__init__)


def _labeled_panel_init(self, cog):
    _BASE_PANEL_INIT(self, cog)
    labels = {
        "tempvoice:rename": "Rinomina",
        "tempvoice:limit": "Limite",
        "tempvoice:privacy": "Privacy",
        "tempvoice:trust": "Fidati",
        "tempvoice:block": "Blocca",
        "tempvoice:invite": "Invita",
        "tempvoice:kick": "Espelli",
        "tempvoice:claim": "Rivendica",
        "tempvoice:transfer": "Trasferisci",
        "tempvoice:delete": "Elimina",
    }
    for item in self.children:
        custom_id = getattr(item, "custom_id", None)
        if custom_id in labels:
            item.label = labels[custom_id]


_labeled_panel_init.__wrapped__ = _BASE_PANEL_INIT
TempVoicePanel.__init__ = _labeled_panel_init


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
