import discord
from redbot.core import commands
from redbot.core.bot import Red


class SwearJarResetStats(commands.Cog):
    """Comandi amministrativi per azzerare le statistiche di SwearJar."""

    __author__ = "danyx64"
    __version__ = "1.0.0"

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.command(name="swearreset", aliases=["swearjarreset", "resetbestemmie"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def swear_reset_member(self, ctx: commands.Context, member: discord.Member):
        """Azzera le statistiche SwearJar di un membro nel server corrente.

        Esempio: [p]swearreset @utente
        """
        swearjar = self.bot.get_cog("SwearJar")
        if swearjar is None:
            return await ctx.send("Il cog SwearJar non risulta caricato.")

        member_group = swearjar.config.member(member)
        previous_count = await member_group.count()
        await member_group.count.set(0)

        await ctx.send(
            f"Statistiche SwearJar di {member.mention} azzerate. "
            f"Conteggio precedente: **{previous_count}** → **0**."
        )
