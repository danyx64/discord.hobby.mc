from .autoreactions import AutoReactions


async def setup(bot):
    await bot.add_cog(AutoReactions(bot))
