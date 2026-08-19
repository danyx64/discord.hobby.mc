from .leavefeed import LeaveFeed


async def setup(bot):
    await bot.add_cog(LeaveFeed(bot))
