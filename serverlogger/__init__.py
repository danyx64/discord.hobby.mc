from .serverlogger_v2 import ServerLogger


async def setup(bot):
    await bot.add_cog(ServerLogger(bot))
