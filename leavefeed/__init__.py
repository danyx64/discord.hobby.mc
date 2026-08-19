from .leavefeed_v4 import LeaveFeed


async def setup(bot):
    await bot.add_cog(LeaveFeed(bot))
