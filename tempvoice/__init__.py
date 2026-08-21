import discord

from .tempvoice import TempVoice


async def setup(bot):
    # Pulisce eventuali residui di una precedente registrazione del cog/comando.
    old_cog = bot.get_cog("TempVoice")
    if old_cog is not None:
        try:
            await bot.remove_cog("TempVoice")
        except Exception:
            pass

    # Rimuove qualunque vecchio /voice rimasto nell'albero prima che Red inietti
    # automaticamente gli app_commands dichiarati nel nuovo cog.
    try:
        while bot.tree.get_command("voice", type=discord.AppCommandType.chat_input) is not None:
            bot.tree.remove_command("voice", type=discord.AppCommandType.chat_input)
    except Exception:
        pass

    await bot.add_cog(TempVoice(bot))
