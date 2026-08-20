from .leavefeed_v5 import LeaveFeed


async def setup(bot):
    await bot.add_cog(LeaveFeed(bot))
