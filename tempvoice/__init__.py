import discord

from .tempvoice import TempVoice


async def setup(bot):
    # Red/discord.py registra automaticamente gli app_commands dichiarati nel Cog
    # durante add_cog(). Se /voice e' rimasto nell'albero da un precedente load
    # o da una vecchia versione del cog, rimuovilo prima dell'iniezione per evitare
    # CommandAlreadyRegistered.
    existing = bot.tree.get_command("voice", type=discord.AppCommandType.chat_input)
    if existing is not None:
        bot.tree.remove_command("voice", type=discord.AppCommandType.chat_input)

    await bot.add_cog(TempVoice(bot))
