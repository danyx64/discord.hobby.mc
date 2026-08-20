from .serverlogger_v4 import ServerLogger


async def setup(bot):
    await bot.add_cog(ServerLogger(bot))
